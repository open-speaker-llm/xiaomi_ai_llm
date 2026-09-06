# boot1 原生 ASR 连续追问

适用：S12A / MDZ-25-DA，boot1/system1，ROM 1.76.54。功能已接入 `native_first_client.sh` 并安装到实机，验证进度见 [实测记录](../../docs/history/2026-09-06-boot1-native-followup.md)。

LLM 播报结束后，音箱主动创建新的小米原生识别会话；识别文本进入当前 LLM session，再播报并打开下一轮。无需 Mac Whisper 或其他外部识别程序。识别仍通过小米云服务完成；音箱端直连 LLM 和 EdgeTTS 也需要网络。

## 使用

先正常唤醒并说“呼叫 DeepSeek，用一句话介绍杭州西湖”。回答完、绿灯续听时直接问“那什么时候适合去呢”，无需再次喊“小爱同学”。保持安静会退出追问，之后正常唤醒又由小爱处理。

收听与句末判定由原生 VAD 控制；空闲收听约 6 秒。`NATIVE_ASR_LISTEN_TIMEOUT=20` 是整轮识别的保护超时，并非等待开口 20 秒。没有播放中打断；“退下”“不要再讲了”等结束语仍按普通追问交给 LLM，不作特殊处理。

## 构建与安装

在仓库根目录执行，需 Zig 和设备 SSH 权限：

```sh
sh device/native_asr/build.sh /tmp/native-asr-build
python3 tools/speaker-maintenance/install_boot1_native_followup.py --host 192.168.8.152 --build-dir /tmp/native-asr-build
```

安装器校验当前分区、原生二进制 ABI 和传输文件摘要，备份原文件与私有配置，然后安装：

- `/data/native_asr.so`：加载进 ARM32 `mipns-xiaomi` 和 `mico_aivs_lab`。
- `/data/native_asr_ctl`：ARM64 的请求、结果和取消控制程序。
- `/data/native_asr.sh`：以可恢复的 bind mount 配置两个原生 procd 服务。
- `/data/native_first_client.sh`：实际 LLM 会话集成。

安装器追加的 boot1 设置如下；boot0 保留原来的录音和文件 ASR 路径：

```sh
SYSTEM1_FOLLOWUP_ENABLED=1
SYSTEM1_FOLLOWUP_RECORD_MODE=native_live
SYSTEM1_FOLLOWUP_ASR_ENGINE=native_live
NATIVE_ASR_MANAGER=/data/native_asr.sh
NATIVE_ASR_CTL=/data/native_asr_ctl
NATIVE_ASR_LISTEN_TIMEOUT=20
PAUSE_NATIVE_ASR_DURING_LLM=0
```

已有 `/data/init.sh` 启动客户端，客户端重建 `/tmp` 中的状态文件和服务覆盖；无需每次重启手动操作。不复制或修改固件分区的原生可执行文件。ABI 不匹配或启动检查失败时恢复原生服务并关闭追问，首轮 LLM 路径仍可用。

完全不依赖 Mac 还要求沿用音箱端链路：`LLM_PIPELINE=native`、`TTS_ENGINE=device`。`native_live` 不调用旧的录音、`asr_audio` 或 Mac ASR 路由。原 PCM + Mac 组件可保留以供回退，但与本管理器的 PNS 覆盖不同时加载。

## 实现和隔离

1. 只在 LLM 实际播放完成后，由客户端发起有所有者 PID、序号和单调时钟期限的识别请求。进程间及线程间访问使用文件锁，一次只接受一个请求。
2. 从运行时注册中取得原生回调和上下文，发起程序唤醒；只改写本次上行 prepare 的 `activate_mode=NONWAKEUP`。使用 protobuf 对象副本，不写原生对象，也不替换真实麦克风音频。
3. `mico_aivs_lab` 以 prepare 包摘要、长度及处理线程作用域关联本次 Recognize，再绑定准确的 `dialog_id`。每轮清空旧文本，取消、超时和旧 dialog 的结果不能进入后续会话。
4. 在该 Recognize 的 `Execution.RequestControl` 中设置 `disabled=["NLP","TTS"]`。这是小米协议规定的 ASR-only 模式；该请求不会走通常的语义理解和回答流程。匹配本轮 dialog 的非 ASR 动作/播报指令另在解析入口隔离，普通原生 dialog 保持原样。[小米 Execution 协议](https://cnbj1.fds.api.xiaomi.com/instruction/Execution.pdf?Expires=9223372036854775807&GalaxyAccessKeyId=5151729087601&Signature=tvKms0qd313PPuyQgKK9VtEevP8%3D)
5. 本地唤醒词缓存通过零长度 IVW 完成通知放行；实际上传的始终是原生麦克风流。最终 ASR 文本以数据交给 shell，绝不作为 shell 配置执行。
6. `wakeup.sh` hook 跳过续听期间的原生灯效和脚本提示音，客户端继续显示绿灯。此固件另有 `wakeup_tone_raw` 线程直接向 ALSA 播放“欸”等本地 WAV，绕过脚本：组件在线程创建时记录本次续听的归属，仅在该线程读取五个已知唤醒音文件时将 PCM 缓冲区置零，保留 80 字节文件头、长度及播放结束时序。普通唤醒、其他线程和其他文件不受影响；原始音频文件不改写。线程归属保留到结束，避免识别完成或取消后延迟响起。退出沿用已验证的静音清理原生队列、恢复音量和待机流程。

首轮失败文案拦截仍由 `device/aivs_guard/` 负责，和本组件的追问 ASR-only 隔离是两件事。

## 状态、测试与回退

```sh
sh /data/native_asr.sh status
/data/native_asr_ctl status
tail /tmp/native_followup/events.log
tail /tmp/native_first_client.log
```

正常状态能看到两个存活进程、序号和本轮 dialog。`events.log` 记录创建、ASR-only、final 字节数和结束，不记录原始音频；`cue silenced seq=… bytes=…` 表示该轮直接播放的唤醒提示音已被置为静音。`state` 位于受限权限的 `/tmp/native_followup/`，仅保留当前轮文本。

本地自动测试覆盖控制程序的并发、取消、空结果、旧文本、参数校验，以及 shell 的同一会话、boot0 兼容与 LLM 错误退出。另有 `test_native_asr.c`，在独立设备进程中验证实际 JsonCpp ABI、ASR-only 上下文和动作/结果隔离，并用固件的真实 WAV 进行 15 项提示音隔离测试：五种提示音、普通唤醒透传、其他线程/文件/进程透传，以及完成或取消后的延迟读取。测试不调用麦克风或云服务、不播放音频：

```sh
zig cc -target arm-linux-gnueabihf.2.25 -Os -Wall -Wextra -Werror device/native_asr/test_native_asr.c -ldl -lpthread -o /tmp/test_native_asr
# 将二进制复制到音箱 /tmp 后运行；临时测试状态使用 /tmp/native_followup_unit。
```

安装器输出 `BACKUP=/data/native-asr-backup-时间`。待音箱空闲后，在设备执行该目录的 `restore.sh`，会恢复对应安装前的客户端、配置、组件和原生服务。第一次从 PCM 路线切换前的备份可恢复 PCM + Mac ASR；后续安装备份则恢复上一版原生组件。不要混淆这两种回退点。
