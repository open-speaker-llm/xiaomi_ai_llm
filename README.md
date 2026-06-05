# 小米 AI 音箱 LLM 助手

当前主线是 **native-first 原生优先路线**：音箱继续使用小米原生“小爱同学”唤醒、ASR、NLP 和家电控制；当小米原生判断无法处理时，再把小米识别出的文本转给 Mac 服务端的 LLM。

这个方向的目标不是替换小爱，而是复用小爱最稳定的部分：

- 唤醒词：继续使用“小爱同学”
- 家电控制、天气、音量等：优先走小米原生链路
- 原生不支持的问题：fallback 到 DeepSeek/MiniMax 等 LLM
- LLM 播放后：进入短暂连续追问窗口

详细调试命令见 [DEV_COMMANDS.md](DEV_COMMANDS.md)。

## 1. 当前主线

### 1.1 Mac 服务端

服务端负责：

- 接收音箱端 fallback 请求
- 调用 LLM
- 生成 TTS 音频流
- 保留 Mac Whisper ASR 接口，作为历史路线和追问兜底能力

启动方式：

```sh
cd /Users/mac-mini-wx/research/xiaomi_ai/xiaomi_ai_llm
./start_server.sh
```

后台启动：

```sh
nohup ./start_server.sh > /tmp/server.log 2>&1 &
tail -f /tmp/server.log | grep -E '📥|🎤|🌐|🔊|🤖|✅|⚠️'
```

健康检查：

```sh
curl http://127.0.0.1:8080/
```

### 1.2 音箱端主客户端

当前部署到音箱的主脚本是：

```text
/data/native_first_client.sh
```

推荐配置文件是：

```text
/data/native_first.env
```

首次部署配置：

```sh
cp /data/native_first.env.example /data/native_first.env
vi /data/native_first.env
```

启动：

```sh
SERVER=http://192.168.8.150:8080 BACKEND=deepseek \
sh /data/native_first_client.sh > /tmp/native_first_client.log 2>&1 &
```

查看日志：

```sh
tail -f /tmp/native_first_client.log /tmp/native_first_events.log
```

当前主线日志里应该能看到：

```text
[HOOK] mounted /bin/wakeup.sh -> /tmp/wakeup.sh.native_first_client
[HOOK] watchdog pid=...
[IDLE] 等待原生唤醒词：小爱同学
```

## 2. Native-first 工作流

```text
小爱同学
  -> 小米原生唤醒
  -> 小米原生 ASR/NLP
  -> 读取 mibrain nlp_result_get
       -> domain 在成功白名单：恢复播放器并 replay 原生 speak
       -> 原生不支持：停止/冻结原生播报，fallback 到 Mac LLM
  -> LLM 播放完成
  -> 8s 连续追问窗口
       -> 固定窗口录音 5s
       -> 小米原生 ai_service 做 ASR，但不执行原生 NLP/TTS
       -> ASR 有文本：文本直接进入 LLM
       -> ASR 空/录音无效：退出对话，回到待机
```

当前强约束：

- 路由优先看 `domain/action`，不要用关键词猜测是否家电控制。
- `query` 只作为 fallback LLM 的输入；原生成功场景里可能是 `token` 等内部值。
- 原生成功播报使用 `speak/to_speak` replay。
- `think` 阶段 freeze mediaplayer，用于完整拦截原生失败播报。
- 已验证 `/data/mibrain/mibrain_asr_nlp.rcd` 不比 `mibrain nlp_result_get` 更早，且中文字段会断行，不适合作为正式路由来源。
- 已验证 `ubus monitor` 未看到更早的结构化 ASR/NLP push 事件。

## 3. 推荐配置

配置模板在 [device/native_first.env.example](device/native_first.env.example)。

当前核心推荐值：

```sh
BACKEND=deepseek
NATIVE_REPLAY_SUCCESS_SPEAK=1
NATIVE_REPLAY_SUCCESS_DELAY=0
FREEZE_NATIVE_PLAYER_ON_THINK=1
FOLLOWUP_ASR_ENGINE=native
FOLLOWUP_RECORD_MODE=window
FOLLOWUP_WINDOW_SECONDS=5
FOLLOWUP_WINDOW_CAPTURE_DEV=Capture
FOLLOWUP_WINDOW_CAPTURE_FORMAT=S16_LE
FOLLOWUP_WINDOW_CAPTURE_RATE=16000
FOLLOWUP_WINDOW_CAPTURE_CHANNELS=1
FOLLOWUP_WINDOW_MIN_PEAK=300
FOLLOWUP_WINDOW_MIN_RMS_THRESHOLD=40
FOLLOWUP_WINDOW_MIN_ACTIVE_PERMILLE=5
FOLLOWUP_TIMEOUT=8
FOLLOWUP_ARM_DELAY=0.2
FOLLOWUP_THRESHOLD=180
FOLLOWUP_START_HITS=1
FOLLOWUP_END_THRESHOLD=100
FOLLOWUP_SILENCE_LIMIT=3
PAUSE_NATIVE_ASR_DURING_LLM=0
```

这些值对应当前折中：

- 原生成功问题尽量快播报。
- 原生失败问题优先完整拦截，再转 LLM。
- 连续追问默认复用小米原生 ASR 获取文本，避免 Mac Whisper 对多麦克风录音识别不稳定。
- 固定窗口录音先用 `peak/rms/active` 做轻量有效性判断；只有三个指标都低才认为没有有效语音。

## 4. Mac 服务端配置

复制 `.env.example` 为 `.env`，填入需要的 API Key：

```sh
cp .env.example .env
```

常用后端：

```sh
DEEPSEEK_API_KEY=
MINIMAX_API_KEY=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
```

当前常用模型配置在 [config.yaml](config.yaml)：

- DeepSeek: `deepseek-v4-flash`
- MiniMax: `MiniMax-M2.7`
- ASR: Whisper `medium`
- TTS: EdgeTTS `zh-CN-YunjianNeural`

## 5. API 接口

| 端点 | 方法 | 描述 |
|------|------|------|
| `/` | GET | 健康检查 |
| `/api/v1/chat` | POST | 文字对话 |
| `/api/v1/asr` | POST | 语音识别 |
| `/api/v1/tts` | POST | 语音合成 |
| `/api/v1/voice_chat` | POST | 端到端语音对话 |
| `/api/v1/stream/text_chat` | POST | native-first fallback 文本流式对话 |
| `/api/v1/stream/chat` | POST | 录音上传、ASR、LLM、TTS 流式返回 |
| `/api/v1/route/asr` | POST | Mac Whisper ASR 路由接口，当前主线仅作为历史路线和兜底兼容 |

## 6. 测试

自动化测试不依赖真实音箱和 API：

```sh
./scripts/run_tests.sh
```

人工音箱测试见 [tests/manual_native_first_cases.md](tests/manual_native_first_cases.md)。

更完整说明见 [TESTING.md](TESTING.md)。

## 7. 项目结构

```text
xiaomi_ai_llm/
├── server/
│   ├── main.py              # FastAPI 主服务
│   ├── llm/                 # DeepSeek / MiniMax / Claude / OpenAI
│   ├── asr/                 # Whisper ASR
│   ├── tts/                 # EdgeTTS / MiniMax / 其他 TTS
│   └── audio/               # 音频处理
├── device/
│   ├── native_first_client.sh       # 当前主线音箱客户端
│   ├── native_first.env.example     # 当前主线推荐配置
│   ├── vad_record.sh                # 音箱端 VAD 录音
│   ├── native_result_timing_probe.sh# 原生结果时序探针
│   ├── native_wake_asr_trace.sh     # 原生唤醒/ASR 跟踪工具
│   ├── stream_client.sh             # 历史 KWS/录音客户端
│   └── wake_monitor.sh              # 历史 KWS 唤醒监控
├── DEV_COMMANDS.md          # 设备调试命令手册
├── config.yaml              # 服务端模型配置
├── .env.example             # API Key 模板
└── requirements.txt         # Python 依赖
```

## 8. 历史路线

这些路线保留用于回溯和对照，不是当前推荐部署路径。

### 8.1 KWS + stream_client 路线

早期路线使用 `/data/open-xiaoai/kws` 做自定义唤醒词检测，例如“你好小智”，然后用 `stream_client.sh` 录音上传 Mac。

相关脚本：

```text
device/stream_client.sh
device/wake_monitor.sh
```

保留原因：

- 可作为自定义唤醒词实验参考。
- 可用于对比 KWS、VAD、录音链路。

不再作为主线的原因：

- 自定义 KWS 准确率不如小米原生“小爱同学”。
- 追问、家电控制、唤醒反馈都需要额外实现。

### 8.2 native_client 路线

`native_client.sh` 是原生唤醒实验阶段的旧客户端。

相关脚本：

```text
device/native_client.sh
```

保留原因：

- 可对照 native-first 前的原生唤醒实验逻辑。

不再作为主线的原因：

- 当前状态机、hook watchdog、原生失败拦截、连续追问等优化都集中在 `native_first_client.sh`。

### 8.3 audio_capture / WebSocket 路线

早期通用客户端入口：

```text
device/audio_capture.py
```

保留原因：

- 可用于普通 HTTP/WebSocket 音频测试。

不再作为主线的原因：

- 不接入小米原生唤醒、NLP、家电控制链路。

## 9. 术语说明

| 名称 | 全称 | 说明 |
|------|------|------|
| KWS | Keyword Spotting | 唤醒词检测，用来识别“小爱同学”“你好小智”等唤醒词。当前主线不使用自定义 KWS。 |
| Wake Word | 唤醒词 | 触发语音助手开始监听的固定短语。当前主线使用小米原生“小爱同学”。 |
| ASR | Automatic Speech Recognition | 语音转文字。首轮和当前连续追问都优先使用小米原生 ASR；Mac Whisper ASR 保留作兼容和兜底。 |
| `ai_service` | 小米原生服务接口 | `ubus call mibrain ai_service`，当前用于追问录音的原生 ASR：`asr=1,nlp=1,tts=0,nlp_execute=0`。 |
| TTS | Text To Speech | 文字转语音，把 LLM 回复合成为音频并在音箱播放。 |
| VAD | Voice Activity Detection | 语音活动检测，用来判断什么时候开始说话、什么时候静默结束录音。 |
| LLM | Large Language Model | 大语言模型，例如 DeepSeek、MiniMax、Claude、OpenAI 模型。 |
| NLP | Natural Language Processing | 自然语言处理。小米原生链路会对 ASR 文本做意图识别，例如天气、音量、家电控制。 |
| Native | 小米原生链路 | 音箱自带的小爱服务链路，负责原生唤醒、ASR、NLP、家电控制和部分问答。 |
| Native-first | 原生优先 | 当前主线：先让小米原生链路处理，原生无法处理时再 fallback 到 LLM。 |
| Fallback | 兜底处理 | 当小米原生返回不支持、不会、无法回答等结果时，把问题转给 LLM。 |
| PCM | Pulse-Code Modulation | 原始音频采样数据，常用于边生成边播放的音频流。 |
| WAV | Waveform Audio File | 带文件头的音频文件格式，常用于录音上传和测试。 |
| ALSA | Advanced Linux Sound Architecture | Linux 底层音频框架，负责声卡、录音、播放、混音和音量控制。 |
| `arecord` | ALSA 录音工具 | 音箱端用于从麦克风录音。 |
| `aplay` | ALSA 播放工具 | 音箱端用于播放服务端返回的音频。 |
| `amixer` | ALSA 混音控制工具 | 用于查看和设置音量、静音、声道开关等 mixer 参数。 |
| `asound.conf` | ALSA 配置文件 | 用于定义音频设备、虚拟设备、插件链路和默认输入输出。 |
| `dsnoop` | ALSA 录音共享插件 | 允许多个进程同时读取同一个麦克风输入，避免录音设备被独占。 |
| U-Boot | Bootloader | 设备启动加载器，可用于切换启动分区、进入 failsafe 等低层调试。 |
| failsafe | 安全模式 | 系统异常或需要修复配置时进入的最小恢复环境。 |
