# ettsc — 音箱端直连 EdgeTTS 客户端

音箱自己 wss 连微软 EdgeTTS、Sec-MS-GEC 鉴权、拿 MP3，交原生 `miplayer` 播。
**不需要 Mac、不需要任何 TTS 微服务。** 作为 `native_first_client.sh` 的端侧 TTS 一档（`TTS_ENGINE=device`），
与 Mac Server TTS（`TTS_ENGINE=server`）通过配置开关二选一。

## 为什么是这个实现

踩坑后定下的两条硬约束（细节见 memory `edgetts-device-side-wss`）：

1. **纯阻塞 IO，不用 tokio。** tokio 的 epoll 异步 reactor 在这台音箱（musl 静态 / kernel 4.9 / zig 构建）上不工作：
   TCP 内核层能连上但 `connect().await` 永不返回、握手永不发出。换 `std::net::TcpStream`（阻塞）+
   同步 `tungstenite` + `native-tls`（vendored OpenSSL 静态）后一切正常。
2. **TLS 用 OpenSSL（vendored 静态），不用 rustls。** 同源于 curl 的 ClientHello，稳过本地网络环境。

产物：ELF 32-bit ARM 全静态 musl，无运行时依赖。

## 构建与部署

```sh
# 一次性工具链
brew install rustup zig
rustup default stable && rustup target add arm-unknown-linux-musleabihf
cargo install cargo-zigbuild

./build.sh            # 交叉编译 -> dist/ettsc
./deploy.sh           # scp 到 192.168.8.152:/data/ettsc（可传 host 参数）
```

仓库已带一份预编译 `dist/ettsc`，多数情况下直接 `./deploy.sh` 即可，不必本地装工具链。

## 用法

```sh
# 合成并落盘
SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt /data/ettsc "你好" /tmp/out.mp3 zh-CN-YunyangNeural
miplayer --file /tmp/out.mp3 2>/dev/null

# 自检
/data/ettsc rawtcp host:port     # 纯阻塞 TCP 收发
SSL_CERT_FILE=... /data/ettsc probe   # 只测 wss 握手（看 101 / 403）
```

运行需 `SSL_CERT_FILE` 指向设备 CA bundle（`/etc/ssl/certs/ca-certificates.crt`），
vendored OpenSSL 靠它校验微软证书。

## 维护：版本过期（403）怎么办

EdgeTTS 的 `Sec-MS-GEC-Version` 跟着 Chromium 版本走，微软会不定期抬高最低版本，旧值会 `403 Forbidden`。
**这与 Mac 端 edge-tts 是同一个问题**——Mac 端靠 `pip install -U edge-tts` 白嫖维护者的更新。

本客户端把相关值做成**环境变量，过期时只改配置、无需重编**：

| env | 默认 | 说明 |
|---|---|---|
| `ETTSC_GEC_VERSION` | `1-143.0.3650.75` | 对照最新 edge-tts `constants.py` 的 `SEC_MS_GEC_VERSION` |
| `ETTSC_UA` | Chrome/143 UA | 同上的 `BASE_HEADERS["User-Agent"]` |
| `ETTSC_ORIGIN` | `chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold` | 同上的 `WSS_HEADERS["Origin"]` |
| `ETTSC_INSECURE` | 未设 | 设为任意值则跳过证书校验（仅调试） |

`native_first_client.sh` 通过 `DEVICE_TTS_GEC_VERSION` / `DEVICE_TTS_UA` / `DEVICE_TTS_ORIGIN`
把这些喂给 ettsc，所以**线上过期 = 改 `/data/native_first.env` 一行**。

拿最新值：
```sh
pip download edge-tts -d /tmp/ett --no-deps && cd /tmp/ett && unzip -o edge_tts-*.whl >/dev/null
grep -E "CHROMIUM_FULL_VERSION|jdiccldimp" edge_tts/constants.py
```
