# Native-first 架构说明

文档类型：当前主线架构
适用范围：理解为什么先走小米原生、什么时候转 LLM、boot0/boot1 如何兼容
当前结论：路由依据优先是小米原生结构化结果，不是文本关键词

## 1. 目标

native-first 不是重写一个小爱，而是把小爱已经做得稳定的部分留下：

- 高质量唤醒："小爱同学"
- 小米原生 ASR/NLP
- 家电、音量、天气等原生能力
- 原生执行链路里的设备上下文

LLM 只接管小米原生不擅长的开放问答。

实现上整条链路就两个东西：音箱端一个约 1700 行的 shell 状态机（`device/native_first_client.sh`），Mac 端一个 FastAPI 服务（`server/`）。

## 2. 主流程

```text
用户说"小爱同学"
  → /bin/wakeup.sh 被原生链路调用
  → native_first_client.sh 的 hook 记录 WuW/think/ready 事件
  → 小米原生 ASR/NLP 得到结构化结果
  → native_first_client.sh 读取结果
       → 成功 domain：交回原生/replay speak
       → 不支持 domain 或失败文案：拦截原生播报，转 LLM
  → 音箱直连 LLM 拿回答
  → TTS 播放：优先可选 EdgeTTS 服务；不可用时走原生 mibrain TTS
  → 音箱播放
```

hook 的实现方式是把 `/bin/wakeup.sh` 用 bind mount 替换为自己的脚本（`mounted /bin/wakeup.sh -> /tmp/wakeup.sh.native_first_client`），原生链路每次唤醒都会调用它，脚本借此拿到事件流，且不修改只读 rootfs。

## 3. 路由标准

优先级：

1. `domain/action`：判断原生是否支持。
2. `speak/to_speak`：原生成功播报内容。
3. `query`：只在 fallback 到 LLM 时作为文本输入。
4. 文本关键词：只作为最后兜底，不作为主判断依据。

典型成功 domain：

```text
smartMiot soundboxControl weather time music player alarm timer system volume
```

典型 fallback domain：

```text
michat qabot shopping nonsense
```

这些 domain 不一定永远失败，但当前实测里经常对应"还在学习中""正在搜索"等非目标能力，所以会进入 fallback 或继续观察。

### 为什么 query 不能作为主判断

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
- 原生失败：保持拦截，调用 Mac LLM。

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
- **think 阶段不预冻结**：boot1 上 `think` 阶段提前 freeze `mediaplayer` 可能影响原生 ASR/NLP 继续产出结果，所以只在拿到 fallback 判定后再拦截；boot0 保留 think 预冻结。
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

`device` 档让音箱连 TTS 微服务都不再需要——真正脱离任何外部服务独立出声。实现见 [`device/ettsc/README.md`](../../device/ettsc/README.md)，两条实测定下的硬约束：

- **纯阻塞 IO，不用 tokio**：tokio 的 epoll 异步 reactor 在这台音箱（musl 静态 / kernel 4.9 / zig 构建）上不工作——TCP 内核层能连上但 `connect().await` 永不返回。换 `std::net::TcpStream` 阻塞 + 同步 `tungstenite` + `native-tls`（vendored OpenSSL 静态）后正常。
- **TLS 用 OpenSSL 而非 rustls**：ClientHello 同源于 curl，稳过本地网络。

> 维护点：EdgeTTS 的 `Sec-MS-GEC-Version` 跟着 Chromium 版本走，微软抬高最低版本会 `403`（和 Mac 端 edge-tts 同性质，Mac 靠 `pip -U` 白嫖更新）。端侧把版本号/UA/Origin 做成配置（`DEVICE_TTS_GEC_VERSION` 等），过期时改 `/data/native_first.env` 一行、不必重编。

关键设计点（都是实测踩坑后定的）：

- **中文切句放在端点 Python 做**，不在 busybox shell 里——shell 按字节处理 UTF-8 会把 `。！？` 切碎成乱码。音箱只管"整段发 + fifo 流式播放"。
- **思考型模型要关思考**：`deepseek-v4-flash` 默认输出 `reasoning_content`（思考链），首句要等 ~3s。`LLM_THINKING=disabled` 关掉后首句 ~2s，而且 shell 只取 `content` 字段天然把思考滤掉。
- **降级探测**：每次 fallback 前快速 ping TTS 微服务（`TTS_HEALTH_TIMEOUT`），在线走 EdgeTTS，离线走原生 `mibrain text_to_speech`（已验证能完整念几百字长文本）。
- **会话历史**存音箱 `/data`（`LLM_HISTORY_DIR`），保留最近 `LLM_HISTORY_TURNS` 轮多轮上下文。

相关配置见 `device/native_first.env.example` 的"音箱端直连 LLM"段。回退随时可做：`LLM_PIPELINE=server` 即切回经 Mac 的老链路。

## 8. 连续追问状态

当前追问不是最终方案：

- boot0：本地录音追问可实验，但稳定性依赖录音链路。
- boot1：默认关闭追问（`SYSTEM1_FOLLOWUP_ENABLED=0`），保证主流程。
- 已验证 native multirounds/reopen 方向尚未走通。
- 更值得继续探索的是从小米链路获取处理后的干净音频。

完整探索记录见 [../history/followup-exploration.md](../history/followup-exploration.md)。

## 9. 状态灯反馈

灯效用颜色区分"现在是原生小爱还是 LLM 在处理"，让用户不看屏也能判断进度。由 `native_first_client.sh` 直接写 LED sysfs（`/sys/devices/i2c-1/1-003c/led_rgb`），设备不支持时静默跳过、不影响主流程；可用 `LED_FEEDBACK_ENABLED=0` 整体关闭。

| 阶段 | 灯效 | 含义 |
|---|---|---|
| 唤醒瞬间 | 蓝灯常亮（hook 按住 `LED_WAKE_HOLD_SECONDS`，默认 4s） | 听到"小爱同学"，已唤醒 |
| 原生处理中 | 蓝灯常亮 | 小米原生 ASR/NLP 在判定，可能原生直接答 |
| 转 LLM | 绿色快闪 3 下后转绿 | 原生答不了，已接管转大模型 |
| LLM 生成/播放 | 绿色转圈 | 大模型在生成 / 逐句播放回答 |
| 等待追问 | 绿灯常亮 | 回答播完，`FOLLOWUP_TIMEOUT` 内可继续追问 |
| 追问识别成功 | 绿色快闪 3 下后转绿 | 追问录音 ASR 出文本，转下一轮 LLM |
| 出错/无文本 | 橙色快闪 3 下后灭 | LLM 调用失败 / 追问录音失败 / ASR 空，本轮结束 |
| 回到待机 | 灭灯 | 对话结束，交还原生小爱 |

颜色约定：蓝=原生小爱，绿=LLM（整个 LLM 链路统一绿色系），橙=出错。原生 `think` 转圈灯效在接管期间默认抑制（`SUPPRESS_NATIVE_THINK_LED=1`），避免"确认转 LLM"前出现一段语义不清的蓝色转圈。

闪烁/转圈节奏由 `LED_BLINK_ON_SECONDS`、`LED_CHASE_DELAY_SECONDS`、`LED_SOLID_REFRESH_SECONDS` 等参数控制，默认值见 [device/native_first.env.example](../../device/native_first.env.example)。
