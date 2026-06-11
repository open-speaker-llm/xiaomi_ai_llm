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
  → Mac 服务端：LLM 流式生成 → 逐句 EdgeTTS
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
| `native` | **主线** | 音箱 shell 自己直连 LLM 拿回答 → 整段发 `/api/v1/tts/stream` → EdgeTTS 流式返回；微服务不可用时降级原生 `mibrain` TTS | 只出 TTS（可换成路由器/NAS/云函数上的迷你服务，甚至不需要） |
| `server` | 辅助 / 回退 | 音箱把文本 POST 给 `/api/v1/stream/text_chat`，Mac 调 LLM + EdgeTTS 流式返回 | 调 LLM + TTS |

`native` 作为主线的理由：音箱脱离开发 Mac 独立运行——唤醒、ASR、NLP 全是小米原生，LLM 由音箱直连，TTS 优先用 EdgeTTS 微服务（好音色、和小爱区分）、离线退回原生 TTS（不哑）。`server` 保留用于：开发联调时方便、或音箱侧不便放 key 时的回退。

> 配置说明：默认 `LLM_PIPELINE=native`（主线）。native 模式必须在 `/data/native_first.env` 填 `DEEPSEEK_API_KEY`，否则无法直连 LLM。要回退到经 Mac 调 LLM，设 `LLM_PIPELINE=server`。

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
