# boot1 处理后 PCM 连续追问

> 后续已实现并安装 [原生 ASR 连续追问](../native_asr/README.md)，无需 Mac 识别程序。本文保留 PCM + Mac 路线的实现和历史验证，供回退参考。

适配范围：S12A / MDZ-25-DA，system1，ROM 1.76.54。这里只包含自己的采样代码，不包含小米固件二进制或现场录音。

## 已验证与待验证

2026-09-06 已验证：`mipns-xiaomi` 空闲时仍持续调用 `xaudio_wrapper_dnn`，在原函数调用结束后复制输出，可在**没有原生唤醒事件**时取得用户语音。30 秒对照录音包含用户说的“明天早上七点我们去爬山”，Whisper small 能识别到主体内容，同时也识别了背景人声，不能当作安静环境下的准确率测试。

2026-09-06 完整链路已首次实测通过：“介绍杭州西湖” → 免唤醒说“那什么时候适合去呢” → 同 session 回答西湖适合春秋季。用户确认接着回答，期间没有新的原生唤醒事件；随后无有效语音时退出，原生报时正常。独立 8 秒安静采样也返回空结果。安装后已重启设备并确认自动加载；重启后的用户语音复测见 [实测记录](../../docs/history/2026-09-06-boot1-pcm-followup.md)。

## 为什么这条路径与旧实验不同

旧的 `speech.usock` 音频上传流受原生会话状态控制。这里复制的是前端 DNN 处理函数的输出，位置在上传门控之前。原函数仍按原参数调用，其返回值与输出均不改动；不打开 ALSA，不暂停或重启原生进程来抢麦克风。

实测 ABI：`int xaudio_wrapper_dnn(void*, void*, int, void*, int*)`。正常输入/输出各 640 字节，每秒约 100 次；输出是两段各 160 个 S16 样本。本采样使用第一段，拼成 16 kHz 单声道。不能按交错双声道或 32 kHz 单声道解释。

已验证固件 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `/usr/bin/mipns-xiaomi` | `a02071a39f3509d3a90dac638e323039a24de784a907f076a0a91f81cd5fbb9d` |
| `/usr/lib/libxaudio_engine.so` | `79f1a33d9683cd6940c8d23e3dd4e992f1958fe220c0dfff8d230f9f8a1b5e73` |
| 原始 `/etc/init.d/pns` | `d9544da4c47bebce556eb656ff5679a6eb90b49255d51f5f740c74706e25a1d7` |

其他型号/固件需要重新验证 ABI，不能直接注入。

## 构建与数据格式

```sh
sh device/pcm_tap/build.sh /tmp/boot1-pcm-build
```

本次使用 Zig 0.16.0。`xaudio_pcm_tap.so` 是 ARM32 glibc 2.25 共享库；`capture_pcm` 是 ARM64 musl 静态程序。虽然内核是 ARM64，原生音频进程是 ARM32，不能用同一个编译目标。

采样库只在 `/usr/bin/mipns-xiaomi` 内初始化。通过该服务的 `LD_PRELOAD` 加载；初始化后取消该环境变量，避免传给它启动的子进程。`native_pcm_tap.sh` 先校验上述固件哈希，再通过临时 bind mount 注入 PNS 的 procd 环境。客户端在开机时调用它重新建立挂载，组件保存在 `/data`，不改写根文件系统。加载健康检查失败会恢复原生服务，并关闭本次客户端的追问，保留首轮 LLM；不接管来源不明的 PNS 挂载。

`/tmp/native_followup_pcm.ring` 是 0600、82,976 字节的内存文件，保存约 2.56 秒循环音频。序号发布与前后复查防止读取半帧/覆盖帧。录音程序从调用时的最新位置开始，只取后续音频；不带入刚播放的历史帧。生产者更换、停滞超过 2 秒、消费者落后、帧校验失败均退出，完整采样前不写 WAV。检测到原生麦克风静音标记时中止录音。`capture_pcm --check` 只检查新帧是否流动，不输出录音文件。

```sh
/data/capture_pcm /tmp/voice.wav 8
```

目前是固定 8 秒窗口，不是说完即停的 VAD，也不支持播放中打断。

## 接入客户端与 ASR

Mac 可以只启动追问 ASR，LLM/TTS 保留音箱已有链路：

```sh
python -m server.followup_asr --host MAC_LAN_IP --port 8080 --model small --threads 4
```

`--model` 也可指定已下载的 Whisper `.pt` 文件。运行前安装项目 Python 依赖。模型初始化结束后，`GET /` 返回 ready。复用 `/api/v1/route/asr` 的质量过滤，独立服务的最低 logprob 为 -0.75（旧通用 ASR 保留 -1.0），以过滤现场观察到的低置信度误识别；背景电视人声也可能通过过滤，因此需要安静对照验证，不等于能自动区分用户和电视。

安装器会为 boot1 添加以下配置；通用示例默认仍关闭，需要按已验证固件选择启用：

```sh
SYSTEM1_FOLLOWUP_ENABLED=1
SYSTEM1_FOLLOWUP_RECORD_MODE=native_pcm
SYSTEM1_FOLLOWUP_ASR_ENGINE=mac
PCM_CAPTURE_BIN=/data/capture_pcm
PCM_TAP_MANAGER=/data/native_pcm_tap.sh
PCM_CAPTURE_SECONDS=8
FOLLOWUP_ASR_TIMEOUT=30
PAUSE_NATIVE_ASR_DURING_LLM=0
```

`SERVER` 指向实际 ASR 地址。该配置不会替换 boot0 的录音方式。Mac 必须在线并运行 ASR；当前 LLM 与 TTS 仍由音箱直连。“退下”“不要再讲了”等结束语按用户要求继续交给 LLM 自然回应，不做特殊拦截。空语音正常退出，不闪错误灯。boot1 恢复原生播放器时短暂静音清理残留队列，再恢复原音量与声音；本轮残留轻声与原生报时对照已由用户确认正常。

## 安装与回退

先在 Mac 准备项目 Python 环境和官方 Whisper small 模型，再运行：

```sh
python3 tools/speaker-maintenance/install_followup_asr_macos.py \
  --python /absolute/path/to/.venv/bin/python \
  --model-file /absolute/path/to/small.pt --host MAC_LAN_IP
```

安装器会核对模型 SHA-256，把服务源代码、模型和无密钥配置复制到 `~/Library/Application Support/xiaomi-ai-llm/followup-asr`，并生成 `~/Library/LaunchAgents/org.open-speaker-llm.followup-asr.plist`。Python 环境本身仍使用指定的固定路径，需要保留。首次加载：

```sh
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/org.open-speaker-llm.followup-asr.plist"
```

这是**用户登录时**启动的 LaunchAgent；已验证由 launchd 重启服务，未通过重启 Mac 验证登录流程。ASR 地址返回 ready 后，在音箱空闲时安装：

```sh
python3 tools/speaker-maintenance/install_boot1_pcm_followup.py \
  --host SPEAKER_IP --build-dir /tmp/boot1-pcm-build \
  --asr-server http://MAC_LAN_IP:8080
```

音箱须已具备 `/data/init.sh` 的开机入口。安装器检查 boot1 和固件、校验传输哈希、私有备份已有文件，再原子替换并检查启动；失败会恢复备份。输出 `BACKUP=/data/native-pcm-backup-...`。回退整个改动：

```sh
sh /data/native-pcm-backup-<安装时间>/restore.sh
```

只卸载采样挂载：`sh /data/native_pcm_tap.sh stop`。如要持久关闭，同时将配置里的 `SYSTEM1_FOLLOWUP_ENABLED=0`；否则下次客户端启动会重新加载。

Mac 服务停用：

```sh
launchctl bootout gui/$(id -u) "$HOME/Library/LaunchAgents/org.open-speaker-llm.followup-asr.plist"
```

安装器不会覆盖已有 Mac 安装；更新前需停止服务、备份并移走原运行目录及 plist。
