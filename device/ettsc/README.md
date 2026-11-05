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

`dist/ettsc` 是本地构建产物，不提交到仓库；首次使用端侧 EdgeTTS 前需要先运行 `./build.sh`，再运行 `./deploy.sh`。未来如果发布 GitHub Release，可把预编译二进制作为附件提供，但当前仓库只保存源码和构建脚本。

## MP3 解码依赖安全补丁

`ETTSC_PCM=1` 使用的 `minimp3` 已通过本地补丁改用标准库缓冲区，移除存在
`RUSTSEC-2025-0044` 双重释放漏洞的 `slice-ring-buffer`。来源、改动范围、测试和维护要求见
[vendor/minimp3/README.md](vendor/minimp3/README.md)。运行 `cargo test --locked` 验证解码回归。
已有设备需要重新构建并部署 `ettsc` 才能获得修复；部署前验证真机播放并保留旧二进制。

## 用法

```sh
# 合成并落盘（rustls 自带根证书，无需 SSL_CERT_FILE）
/data/ettsc "你好" /tmp/out.mp3 zh-CN-YunjianNeural
miplayer --file /tmp/out.mp3 2>/dev/null

# 自检：只测 wss 握手（看 101 / 错误）
/data/ettsc probe
```

## 首段预连接实验

客户端开关 `DEVICE_TTS_PREWARM=0` 默认关闭。启用后，客户端在 LLM 生成期间启动：

```sh
/data/ettsc prewarm /tmp/本轮私有任务目录 zh-CN-YunjianNeural
```

目录由客户端使用 `mktemp` 创建。程序先完成真实握手，写 `ready`，并保留同一连接；客户端将首段文本写入 `request.part` 后原子改名为 `request`。程序只处理一个合成 turn，收到 `turn.end` 且解码成功后发布 `audio.pcm`，计时日志完成后写 `done=0`；错误为 `done=1`，不发布残缺音频。始终输出裸 PCM。首段使用完即退出，不支持单连接多句复用。

没有文本时，握手成功后空闲 20 秒退出。`cancel` 文件可取消等待；客户端在轮末/中断时终止并回收自己启动的进程。候选握手采用 5 秒 TCP 建链预算和 socket 读写超时，首段整体等待还受客户端 `DEVICE_TTS_TIMEOUT` 限制。默认的一次性与 `probe` 模式保持原行为；`probe` 是握手后断开，不能供后续进程复用。

上线前需要构建匹配架构的新二进制，并按[实际测试说明](../../docs/testing/2026-11-05-tts-prewarm.md)核验。关闭客户端开关即可回到一次性链路。2026-11-05 的握手基线 P50 785 ms、P90 1165 ms（20 次成功）；这是握手数据，不能代替声学首声验收。

## 维护：版本过期（403）怎么办

当前实现支持 `Sec-MS-GEC` v2，输出 `16 位 CS64-64 位 SHA256` 十六进制组合，并按上游握手方式发送随机 MUID Cookie。算法与 [edge-tts 固定提交](https://github.com/rany2/edge-tts/tree/bd44c1d1aaebdc1db7f47456ee12431b42ec7cac) 核对；默认男声仍为 `zh-CN-YunjianNeural`，音频格式、MP3 解码与 PCM 增益行为保持。

旧版只生成 v1 SHA256 摘要。v1 → v2 必须重新构建并替换 `ettsc`，同时确认配置选择 v2；仅修改旧二进制收到的版本字符串不能升级算法。以后的 Chromium 版本字段变化仍可通过环境变量更新：

| env | 默认 | 说明 |
|---|---|---|
| `ETTSC_GEC_VERSION` | `2-143.0.3650.75` | `2-` 选择 v2；`1-` 保留旧算法兼容。其他前缀明确报错 |
| `ETTSC_UA` | Chrome/143 UA | 同上的 `BASE_HEADERS["User-Agent"]` |
| `ETTSC_ORIGIN` | `chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold` | 同上的 `WSS_HEADERS["Origin"]` |

`native_first_client.sh` 通过 `DEVICE_TTS_GEC_VERSION` / `DEVICE_TTS_UA` / `DEVICE_TTS_ORIGIN`
把这些喂给 ettsc。旧客户端可能仍显式传入 v1，因此替换二进制后还应在实际 `/data/native_first.env` 中确认 `DEVICE_TTS_GEC_VERSION=2-143.0.3650.75`。配置和二进制应一起备份、一起恢复。

`probe` 与实际合成都会打印 `Sec-MS-GEC v2 version=2-143.0.3650.75`；成功握手随后打印 `handshake OK, HTTP 101`。这些日志不输出完整鉴权 token。合成出非空音频及实际听到原男声仍需分别验证；403 也可能涉及时钟或服务端策略，算法测试不能代替实时握手结果。

离线回归与构建：

```sh
python3 tests/generate_gec_v2_vectors.py --check
cargo test --locked
./build.sh
```

向量由上游 Python 原始算法独立生成，Rust 测试读取固定结果，覆盖 17 个时间点和 12 组摘要边界。测试和构建不会调用微软 TTS；`probe`、文本合成才会联网。

`src/gec_v2.rs` 使用 LGPLv3，相关许可、原始源码和静态二进制分发所需材料说明见 [NOTICE.edge-tts.md](NOTICE.edge-tts.md)。其余文件的既有许可保持不变。

拿最新值：
```sh
pip download edge-tts -d /tmp/ett --no-deps && cd /tmp/ett && unzip -o edge_tts-*.whl >/dev/null
grep -E "CHROMIUM_FULL_VERSION|jdiccldimp" edge_tts/constants.py
```
