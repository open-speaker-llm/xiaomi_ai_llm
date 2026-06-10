# 名词解释

文档类型：概念速查  
适用范围：读日志、读脚本、理解系统启动和音频链路  
当前结论：先理解 KWS/ASR/TTS/VAD/ALSA，再看 native-first 状态机日志会顺很多

| 名词 | 全称/来源 | 解释 |
|---|---|---|
| KWS | Keyword Spotting | 唤醒词检测。早期路线用开源 KWS 检测“你好小智”，当前主线使用小米原生“小爱同学”。 |
| ASR | Automatic Speech Recognition | 语音转文字。当前首轮优先使用小米原生 ASR；Mac Whisper 保留为测试和兜底。 |
| TTS | Text To Speech | 文字转语音。Mac 服务端当前使用 EdgeTTS，默认音色 `zh-CN-YunjianNeural`。 |
| VAD | Voice Activity Detection | 语音活动检测，用于判断什么时候开始/停止录音。 |
| LLM | Large Language Model | 大语言模型，例如 DeepSeek、MiniMax、Claude、OpenAI。 |
| ALSA | Advanced Linux Sound Architecture | Linux 音频子系统，提供录音/播放设备接口，例如 `arecord`、`aplay`、`Capture`。 |
| PCM | Pulse-code Modulation | 原始数字音频格式，常见参数包括采样率、声道数、位深。 |
| WAV | Waveform Audio File Format | 常见音频文件容器，内部通常保存 PCM 音频。 |
| `arecord` | ALSA 工具 | 命令行录音工具。 |
| `aplay` | ALSA 工具 | 命令行播放工具。 |
| `mediaplayer` | 小米播放器进程 | 小米原生 TTS/媒体播放相关进程，native-first 会在关键阶段 freeze/resume。 |
| `mipns-xiaomi` | 小米原生语音链路进程 | 与唤醒、录音、ASR 上传等链路有关。随意暂停可能影响原生能力。 |
| `mibrain` | 小米大脑服务 | 通过 `ubus call mibrain ...` 暴露部分 ASR/NLP/TTS 能力。 |
| `ai_service` | 小米原生服务接口 | 可做 ASR/NLP/TTS 组合调用。当前主要用于探索和部分追问方案。 |
| `domain` | 小米 NLP 字段 | 表示原生识别到的能力域，例如 `weather`、`smartMiot`。 |
| `action` | 小米 NLP 字段 | 表示动作类型，例如 `query`、`operate`。 |
| `query` | 小米 NLP 字段 | 用户文本或内部字段。不能单独作为路由标准。 |
| `speak` / `to_speak` | 小米播报字段 | 小米原生准备说出的文字，原生成功 replay 主要使用它。 |
| boot0 / boot1 | 启动分区 | U-Boot 使用的启动槽位，通常决定启动哪套内核/系统组合。 |
| system0 / system1 | 系统分区 | rootfs 所在分区，当前 system0 是 2019 ROM，system1 是 2023 ROM。 |
| kernel | Linux 内核 | 硬件驱动、进程调度、文件系统挂载等由内核负责。 |
| initramfs | initial RAM filesystem | 内核早期启动用的临时根文件系统，用于加载驱动、决定挂载哪个真正 rootfs。 |
| rootfs | root filesystem | Linux 运行后的根文件系统 `/`，包含 `/bin`、`/etc`、`/usr` 等。 |
| mount | 挂载 | 把某个分区或文件系统接到目录树上，例如把 system1 挂成 `/`。 |
| OpenWrt/LEDE | 嵌入式 Linux 发行版 | 小米音箱底层系统基于 OpenWrt/LEDE 风格。 |
| U-Boot | Bootloader | 上电后负责选择 boot 分区并加载 kernel 的引导程序。 |
| failsafe | OpenWrt 救援模式 | 启动早期进入的救援环境，可用于修复配置、恢复 SSH 等。 |

