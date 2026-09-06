# Native-first 架构说明

文档类型：当前主线架构
适用范围：理解为什么先走小米原生、什么时候转 LLM、boot0/boot1 如何兼容
当前结论：boot0 按原生 domain/action 路由；boot1 按 AIVS 文本规则路由，失败提示快速拦截已于 2026-09-06 实机验证

## 1. 目标

native-first 不是重写一个小爱，而是把小爱已经做得稳定的部分留下：

- 高质量唤醒："小爱同学"
- 小米原生 ASR/NLP
- 家电、音量、天气等原生能力
- 原生执行链路里的设备上下文

LLM 只接管小米原生不擅长的开放问答。

音箱端由 shell 状态机（`device/native_first_client.sh`）负责主流程，boot1 配合 C 快速拦截器（`device/aivs_guard/`）；可选 FastAPI 服务（`server/`）提供 LLM/TTS 辅助链路。

## 2. 主流程

```text
用户说"小爱同学"
  → /bin/wakeup.sh 被原生链路调用
  → native_first_client.sh 的 hook 记录 WuW/think/ready 事件
  → 小米原生 ASR/NLP 先处理
  → boot0：读取 domain/action 与 speak，按路由策略选择原生或 LLM
  → boot1：读取 RecognizeResult 与 Speak.text
       → 命中直接转 LLM 的提问或失败文案：转 LLM
       → guard 在匹配失败 Speak 后暂停播放器，shell 接手
       → 未命中：原生链路继续处理，不据此保证原生一定答对
  → 音箱直连 LLM 拿回答
  → TTS 播放：优先可选 EdgeTTS 服务；不可用时走原生 mibrain TTS
  → 音箱播放
```

hook 的实现方式是把 `/bin/wakeup.sh` 用 bind mount 替换为自己的脚本（`mounted /bin/wakeup.sh -> /tmp/wakeup.sh.native_first_client`），原生链路每次唤醒都会调用它，脚本借此拿到事件流，且不修改只读 rootfs。

## 3. 路由标准

### boot0：结构化结果与文本辅助

读取 `nlp_result_get` 中同一条最新结果的 `domain/action/query/to_speak`。现有代码先检查失败文案或 `michat/model`，再检查原生能力白名单；非白名单转 LLM。典型原生 domain 为 `smartMiot soundboxControl weather time music player alarm timer system volume`。

`domain` 表示能力类别，不是通用成功/失败状态；例如 `qabot/query` 可能有正常回答，也可能有失败提示。实际路由还需结合配置与文本，不能把非白名单都解释为小米明确报错。

### boot1：AIVS 文本规则与快速拦截

- `RecognizeResult` 给出用户提问；命中 `DIRECT_LLM_QUERY_PATTERNS`（默认 DeepSeek 的大小写写法）时直接转 LLM。
- 其余提问等待原生 `SpeechSynthesizer/Speak` 的 `payload.text`，命中 `UNSUPPORTED_PATTERNS` 后转 LLM。shell 与 guard 共用这份表达式。
- 适配器在匹配后填入的 `michat/model` 是客户端内部路由标记，**不是 boot1 固件返回的失败状态**。
- 未找到已验证可替代文本匹配的业务失败字段。`open_mic/valid_speech/valid_speak` 出现在历史追问实验中，尚无正常回答与失败提示的分类对照，且记录位于 finish 阶段。

2026-09-06 已在 S12A 的 boot1/system1（ROM 1.76.54）实测：匹配到的小爱失败提示可被拦截并转 LLM，修正版重启后用户确认正常转接、没有先播失败提示。判定仍依赖文本规则，未知文案可能漏判，正常回答含相似词也可能误判；不保证所有文案、时序或固件都无漏音。详见 [实测与历史字段复核](../history/2026-09-06-boot1-fallback-guard.md)。

### boot0 的 query 占位值

日志里可能出现：

```text
domain=weather action=query query=token speak=杭州上城今天...
```

这里 `query=token` 是小米内部字段，不代表用户真的说了 token。真正应该播报的是 `speak`，真正应该判断的是 `domain=weather`。

## 4. 播放控制

为了避免原生失败播报和 LLM 串台，脚本会：

- 在 `think` 阶段 freeze `mediaplayer`（boot0；boot1 见下文）。
- 拿到原生结果后判断路由。
- 原生成功：resume 播放器，并按需要 replay `speak`。
- 原生失败：保持拦截，按 `LLM_PIPELINE` 选择音箱直连 LLM 或经服务端调用。

LLM 请求与播报期间会设置 `/tmp/native_first_busy`，guard 在 busy 状态不执行拦截；LLM 回答文本本身不经过原生失败分类，包括降级原生 TTS 的正常流程。该保护不消除小爱原生回答的文本误判风险。

控制类短播报支持"下一次唤醒取消旧播报"，避免用户已经进入下一轮对话时又听到上一轮"开啦/关啦"。对应配置：

```sh
NATIVE_REPLAY_CANCEL_ON_WAKE=1
NATIVE_REPLAY_CANCEL_DOMAINS="smartMiot soundboxControl volume system"
```

天气这类纯语音回答不要放进取消列表，否则结果可能不播报。

## 5. boot0 与 boot1 兼容

同一份 `/data/native_first_client.sh` 会面对两套不同用户态（原因见 [boot-and-partitions.md](boot-and-partitions.md)）：

| 系统 | rootfs | 小米 ROM | 原生结果源 |
|---|---|---|---|
| boot0/system0 | `/dev/mtdblock4` | 1.54.8，2019 | `mibrain nlp_result_get` → `ubus_nlp_result` |
| boot1/system1 | `/dev/mtdblock5` | 1.76.54，2023 | `/tmp/mico_aivs_lab/instruction.log` → `aivs_lab_instruction` |

### 双系统能力对照（2026-09-06）

下表针对本项目 S12A 实测固件和已安装组件；通用模板仍须按安装说明启用相应能力。

| 能力 | boot0 / 1.54.8 | boot1 / 1.76.54 |
|---|---|---|
| 原生唤醒、报时、家电等功能 | 保留原生链路 | 保留原生链路 |
| 首轮转 LLM | domain/action 与失败文本辅助路由 | 提问触发词或失败 Speak 文案；没有已验证的通用失败状态字段 |
| 失败提示拦截 | think 阶段预冻结播放器 | C guard 发现匹配失败 Speak 后及时暂停；仍可能误判或漏判文案 |
| LLM 与 TTS 不依赖常驻 Mac | 可用音箱直连 LLM + 设备 TTS | 同样可用 |
| 免唤醒追问与同一上下文 | 原有录音方案 + 小米文件 ASR，仍标为实验方案 | 原生实时 ASR-only；有声上下文追问已实测 |
| 追问识别不依赖 Mac | 支持原生文件 ASR，Mac 回退可选 | native_live 不调用 Mac ASR，仍需小米云 |
| 收听窗口 | 由本地录音配置控制，默认 window 8 秒 | 原生 VAD 判定，空闲收听约 6 秒；20 秒是整轮保护超时 |
| SSH、自启动、原生 OTA 拦截 | 已配置验证 | 已配置验证，原生追问组件重启后自动加载 |
| 播放中语音打断 | 未实现 | 未实现 |

核心功能基本齐备不代表两边会对每个问题作相同路由，也不代表速度、识别准确率或长期稳定性相同。本轮未切回 boot0 重新进行完整对照。boot1 续听“欸”声补丁已部署并经设备检查确认命中，最终听觉复验仍待用户确认。证据见 [正式集成记录](../history/2026-09-06-boot1-native-followup.md)。

boot1/system1 上 `mibrain nlp_result_get` 可能不刷新；原生 ASR/TTS 指令会写进 `mico_aivs_lab` 的 `instruction.log`，例如：

```text
SpeechRecognizer/RecognizeResult
SpeechSynthesizer/Speak
Dialog/Finish
```

脚本通过检测当前 rootfs 自动选择结果源，对应配置：

```sh
NATIVE_RESULT_SOURCE=auto
NATIVE_AIVS_LAB_RESULT_SYSTEM1=1
```

boot1 还有三个实测得出的行为差异，`auto` 配置都已自动处理：

- **唤醒事件不同**：boot1 的 hook 事件可能只有 `think/ready`，没有 boot0 常见的 `WuW`。`WAKE_ON_THINK_SYSTEM1=1` 会在 boot1 上把 `think` 当作状态机触发源。
- **think 阶段不预冻结**：boot1 上 `think` 阶段提前 freeze `mediaplayer` 可能影响原生 ASR/NLP 继续产出结果，所以保留播放器运行到失败指令出现；安装 [AIVS 快速拦截器](../../device/aivs_guard/README.md) 后，由它监听新增失败 `Speak` 并提前暂停，shell 随后接手 fallback；缺少 helper 时仍按原轮询逻辑。boot0 保留 think 预冻结。
- **不接管音频采集**：`AUDIO_CAPTURE_SETUP=auto` 在检测到 boot1 时跳过 `dsnoop` 和 `libxaudio_engine.so` 覆盖，否则可能导致原生 `recorder` 崩溃——表现为能唤醒但开关灯、天气都不响应。

重要原则：**不要试图把两套系统"硬填平"**。不要复制 boot0 的 `mibrain_service`、`mipns-xiaomi`、`libxaudio_engine.so` 或 `wakeup.sh` 去覆盖 boot1。当前长期方案就是在脚本里保留两套结果源适配器。

## 6. 服务端

Mac 服务端（FastAPI）做三件事：

1. `POST /api/v1/stream/text_chat` 接收 fallback 文本，按 `BACKEND` 选择 LLM（DeepSeek/MiniMax/Claude/OpenAI）。
2. LLM 流式输出经 `sentence_splitter` 按中文句子边界切分，逐句送 EdgeTTS，先发 WAV 头再流式输出 PCM——首句合成完即可开播，不必等全文。
3. `POST /api/v1/tts/stream` 纯文本→流式 WAV（不含 LLM），供音箱直连模式使用，也是可移植迷你 TTS 服务的核心。
4. 保留 Whisper ASR 端点（`/api/v1/route/asr`、`/api/v1/stream/chat`）作为历史路线、测试和兜底。

## 7. 两种 LLM 链路：音箱直连（主线）vs 经 Mac（辅助）

fallback 到 LLM 时走哪条链路由 `LLM_PIPELINE` 决定。**当前主线是音箱直连 LLM（`native`），经 Mac 调 LLM（`server`）作为辅助 / 回退**：

| 模式 | 定位 | 链路 | Mac 角色 |
|---|---|---|---|
| `native` | **主线** | 音箱 shell 自己直连 LLM 拿回答 → 交给 TTS（见下 `TTS_ENGINE`）；失败降级原生 `mibrain` | 可选 TTS 服务；`TTS_ENGINE=device` 或原生兜底时不需要 Mac |
| `server` | 辅助 / 回退 | 音箱把文本 POST 给 `/api/v1/stream/text_chat`，Mac 调 LLM + EdgeTTS 流式返回 | 调 LLM + TTS |

`native` 作为主线的理由：音箱脱离开发 Mac 独立运行——唤醒、ASR、NLP 全是小米原生，LLM 由音箱直连。TTS 是可选增强：不部署 Mac 服务端时，可以用音箱端 EdgeTTS（`TTS_ENGINE=device`），失败再退回小爱原生 `mibrain` TTS；如果希望用 Mac/路由器/NAS 上的 TTS 微服务，则用 `/api/v1/tts/stream`（音色在 `config.yaml` 的 `tts.edgetts.voice` 配置）。`server` 保留用于：开发联调时方便、或音箱侧不便放 key 时的回退。

> 配置说明：默认 `LLM_PIPELINE=native`（主线）。native 模式必须在 `/data/native_first.env` 填 `DEEPSEEK_API_KEY`，否则无法直连 LLM。要回退到经 Mac 调 LLM，设 `LLM_PIPELINE=server`。

### TTS 引擎：Mac 微服务 vs 音箱端直连（与 LLM 链路正交）

"谁出声"是和 `LLM_PIPELINE` 独立的另一维度，由 `TTS_ENGINE` 决定。`native` LLM 链路下两种都能用：

| `TTS_ENGINE` | 链路 | 依赖 | 失败兜底 |
|---|---|---|---|
| `server`（默认） | 整段发 Mac `/api/v1/tts/stream`，端点 Python 切句、EdgeTTS 流式返回 WAV → `aplay` | 需要 Mac/迷你 TTS 微服务在线 | 微服务 ping 不通 → 原生 `mibrain` |
| `device` | 音箱端 `ettsc` 自己 wss 连微软 EdgeTTS、Sec-MS-GEC 鉴权、拿整段 MP3 → 原生 `miplayer` | **不需要任何 helper**，音箱独立完成 | ettsc 失败（如 403）→ 原生 `mibrain` |

`device` 档不需要常驻 Mac 或自建 TTS 微服务；音箱仍联网调用微软 EdgeTTS。实现见 [`device/ettsc/README.md`](../../device/ettsc/README.md)，两条实测定下的硬约束：

- **纯阻塞 IO，不用 tokio**：tokio 的 epoll 异步 reactor 在这台音箱（musl 静态 / kernel 4.9 / zig 构建）上不工作——TCP 内核层能连上但 `connect().await` 永不返回。换 `std::net::TcpStream` 阻塞 + 同步 `tungstenite` + `native-tls`（vendored OpenSSL 静态）后正常。
- **TLS 用 OpenSSL 而非 rustls**：ClientHello 同源于 curl，稳过本地网络。

> 维护点：EdgeTTS 的 `Sec-MS-GEC-Version` 跟着 Chromium 版本走，微软抬高最低版本会 `403`（和 Mac 端 edge-tts 同性质，Mac 靠 `pip -U` 白嫖更新）。端侧把版本号/UA/Origin 做成配置（`DEVICE_TTS_GEC_VERSION` 等），过期时改 `/data/native_first.env` 一行、不必重编。

关键设计点（都是实测踩坑后定的）：

- **中文切句放在端点 Python 做**，不在 busybox shell 里——shell 按字节处理 UTF-8 会把 `。！？` 切碎成乱码。音箱只管"整段发 + fifo 流式播放"。
- **思考型模型要关思考**：`deepseek-v4-flash` 默认输出 `reasoning_content`（思考链），首句要等 ~3s。`LLM_THINKING=disabled` 关掉后首句 ~2s，而且 shell 只取 `content` 字段天然把思考滤掉。
- **降级探测**：每次 fallback 前快速 ping TTS 微服务（`TTS_HEALTH_TIMEOUT`），在线走 EdgeTTS，离线走原生 `mibrain text_to_speech`（已验证能完整念几百字长文本）。
- **会话历史**保存在 `LLM_HISTORY_DIR`（默认 `/tmp/native_first_llm_hist`，重启清空，可自行配置持久目录），保留最近 `LLM_HISTORY_TURNS` 轮多轮上下文。

相关配置见 `device/native_first.env.example` 的"音箱端直连 LLM"段。回退随时可做：`LLM_PIPELINE=server` 即切回经 Mac 的老链路。

## 8. 连续追问状态

boot1 / S12A ROM 1.76.54 已实现并安装原生 ASR 连续追问：LLM 播报结束后主动创建 NONWAKEUP 会话，在 Recognize 上报中关闭 NLP/TTS，只把该 dialog 的最终识别文本送入当前 LLM session，随后继续播报和续听。无需 Mac Whisper 或外部录音识别程序，仍需小米云服务联网。

- 采集继续由原生音频前端负责，不抢占 ALSA、不暂停 mipns，也不生成临时 WAV。
- 脚本提示音在 `wakeup.sh` hook 处跳过；绕过脚本直接播放的本地“欸”等提示音，按本次续听的线程归属将 WAV 读取缓冲区置为静音。普通唤醒保留原样；静默结束后清理原生队列、恢复音量。
- 本次追问中的原生 NLP/设备动作被隔离；普通首轮唤醒仍走小爱的原生处理。
- 使用 `SYSTEM1_FOLLOWUP_RECORD_MODE=native_live`，需先安装匹配固件的组件。通用示例仍默认关闭。
- 原生 VAD 控制句末和静默窗口；20 秒配置是整体保护超时。尚未实现播放中打断，不特别处理结束语。
- boot0 保留原录音与文件 ASR 方式。此前 [PCM + Mac ASR](../../device/pcm_tap/README.md) 实现保留供回退；旧下行 reopen/文件识别失败结论不适用于新入口。

详见 [原生组件安装](../../device/native_asr/README.md)、[集成验证记录](../history/2026-09-06-boot1-native-followup.md)、[入口研究](../history/2026-09-06-boot1-native-asr-research.md)。

## 9. 状态灯反馈

灯效用颜色区分"现在是原生小爱还是 LLM 在处理"，让用户不看屏也能判断进度。由 `native_first_client.sh` 直接写 LED sysfs（`/sys/devices/i2c-1/1-003c/led_rgb`），设备不支持时静默跳过、不影响主流程；可用 `LED_FEEDBACK_ENABLED=0` 整体关闭。

| 阶段 | 灯效 | 含义 |
|---|---|---|
| 唤醒瞬间 | 蓝灯常亮（hook 按住 `LED_WAKE_HOLD_SECONDS`，默认 4s） | 听到"小爱同学"，已唤醒 |
| 原生处理中 | 蓝灯常亮 | 小米原生 ASR/NLP 在判定，可能原生直接答 |
| 转 LLM | 绿色快闪 3 下后转绿 | 原生答不了，已接管转大模型 |
| LLM 生成/播放 | 绿色转圈 | 大模型在生成 / 逐句播放回答 |
| 等待追问 | 绿灯常亮 | 回答播完可以继续追问；boot0 按录音配置计时，boot1 native_live 按原生 VAD 判定 |
| 追问识别成功 | 绿色快闪 3 下后转绿 | 追问录音 ASR 出文本，转下一轮 LLM |
| 出错/无文本 | 橙色快闪 3 下后灭 | LLM 调用失败 / 追问录音失败 / ASR 空，本轮结束 |
| 回到待机 | 灭灯 | 对话结束，交还原生小爱 |

颜色约定：蓝=原生小爱，绿=LLM（整个 LLM 链路统一绿色系），橙=出错。原生 `think` 转圈灯效在接管期间默认抑制（`SUPPRESS_NATIVE_THINK_LED=1`），避免"确认转 LLM"前出现一段语义不清的蓝色转圈。

闪烁/转圈节奏由 `LED_BLINK_ON_SECONDS`、`LED_CHASE_DELAY_SECONDS`、`LED_SOLID_REFRESH_SECONDS` 等参数控制，默认值见 [device/native_first.env.example](../../device/native_first.env.example)。
