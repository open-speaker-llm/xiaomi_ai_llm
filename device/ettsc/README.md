# ettsc — 音箱端直连 EdgeTTS 客户端

音箱自己 wss 连微软 EdgeTTS、Sec-MS-GEC 鉴权、拿 MP3，交原生 `miplayer` 播。
**不需要 Mac、不需要任何 TTS 微服务。** 作为 `native_first_client.sh` 的端侧 TTS 一档（`TTS_ENGINE=device`），
与 Mac Server TTS（`TTS_ENGINE=server`）通过配置开关二选一。

## 为什么是这个实现

踩坑后定下的一条硬约束（细节见 memory `edgetts-device-side-wss`）：

**纯阻塞 IO，不用 tokio。** tokio 的 epoll 异步 reactor 在这台音箱（musl 静态 / kernel 4.9 / zig 构建）上不工作：
TCP 内核层能连上但 `connect().await` 永不返回、握手永不发出（早期以为是路由器代理/TLS 库的问题，实为此）。
换 `std::net::TcpStream`（阻塞）+ 同步 `tungstenite` 后一切正常。本工作负载是"一次连接、收完即退"，
也根本不需要异步——阻塞既是唯一能跑的，也是架构上最贴合的。

TLS 用 **rustls + 内置 webpki 根证书**：纯 Rust、无需系统 CA / `SSL_CERT_FILE`，二进制 ~0.95MB。
（早期那版换成 vendored OpenSSL 把体积顶到 3.6MB，后证实 rustls 本身没问题、卡的是 tokio，故回退 rustls。）

产物：ELF 32-bit ARM 全静态 musl，无运行时依赖，~0.95MB。

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
# 合成并落盘（rustls 自带根证书，无需 SSL_CERT_FILE）
/data/ettsc "你好" /tmp/out.mp3 zh-CN-YunjianNeural
miplayer --file /tmp/out.mp3 2>/dev/null

# 自检：只测 wss 握手（看 101 / 错误）
/data/ettsc probe
```

## 维护：版本过期（403）怎么办

EdgeTTS 的 `Sec-MS-GEC-Version` 跟着 Chromium 版本走，微软会不定期抬高最低版本，旧值会 `403 Forbidden`。
**这与 Mac 端 edge-tts 是同一个问题**——Mac 端靠 `pip install -U edge-tts` 白嫖维护者的更新。

本客户端把相关值做成**环境变量，过期时只改配置、无需重编**：

| env | 默认 | 说明 |
|---|---|---|
| `ETTSC_GEC_VERSION` | `1-143.0.3650.75` | 对照最新 edge-tts `constants.py` 的 `SEC_MS_GEC_VERSION` |
| `ETTSC_UA` | Chrome/143 UA | 同上的 `BASE_HEADERS["User-Agent"]` |
| `ETTSC_ORIGIN` | `chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold` | 同上的 `WSS_HEADERS["Origin"]` |

`native_first_client.sh` 通过 `DEVICE_TTS_GEC_VERSION` / `DEVICE_TTS_UA` / `DEVICE_TTS_ORIGIN`
把这些喂给 ettsc，所以**线上过期 = 改 `/data/native_first.env` 一行**。

拿最新值：
```sh
pip download edge-tts -d /tmp/ett --no-deps && cd /tmp/ett && unzip -o edge_tts-*.whl >/dev/null
grep -E "CHROMIUM_FULL_VERSION|jdiccldimp" edge_tts/constants.py
```
