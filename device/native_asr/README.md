# boot1 原生 ASR 连续追问

适用：S12A / MDZ-25-DA，boot1/system1，ROM 1.76.54。功能已接入 `native_first_client.sh` 并安装到实机，验证进度见 [实测记录](../../docs/history/2026-09-06-boot1-native-followup.md)。

LLM 播报结束后，音箱主动创建新的小米原生识别会话；识别文本进入当前 LLM session，再播报并打开下一轮。无需 Mac Whisper 或其他外部识别程序。识别仍通过小米云服务完成；音箱端直连 LLM 和 EdgeTTS 也需要网络。

## 使用

先正常唤醒并说“呼叫 DeepSeek，用一句话介绍杭州西湖”。回答完、绿灯续听时直接问“那什么时候适合去呢”，无需再次喊“小爱同学”。保持安静会退出追问，之后正常唤醒又由小爱处理。

绿灯续听时如果再次真实唤醒“小爱同学”，退出当前 LLM 追问并交还小爱原生会话，可以接着操作家居。组件记录 `physical wake handoff`，控制程序以 125 返回且不输出旧追问文本。音频清理和音量恢复在开启追问前完成；交接后不再静音、清队列或关闭原生灯效。旧追问迟到的停止收音、结束和动作指令不能影响新会话。

收听与句末判定由原生 VAD 控制；空闲收听约 6 秒。`NATIVE_ASR_LISTEN_TIMEOUT=20` 是整轮识别的保护超时，并非等待开口 20 秒。没有播放中打断；“退下”“不要再讲了”等结束语仍按普通追问交给 LLM，不作特殊处理。

boot1 的 `native_live` LLM 对话另有输入补全（`NATIVE_DIALOG_INPUT_GUARD=1`）：

- 没有触发真实唤醒事件、仅 ASR 文本为“小爱同学”时，播放固定短提示“我在，请说。”，提示播完后重新收听；这四个字和固定提示均不进入 LLM 历史。真实唤醒优先走上述原生交接。
- 对“帮我查一下”“呼叫 DeepSeek 帮我查一下”等明确缺少查询对象的独立短句，先提示“请继续说，要查什么？”，再把原句与下一段内容合成一轮问题，继续使用同一 session。
- 完整问题、带问题的唤醒词、“为什么”“那它呢”等上下文追问直接走原流程。该规则只匹配明确的独立短句，不修改 ASR 字词，也不改变原生家电路由和云端收音参数。
- 提示期间不收听，绿灯续听时再补充。静默退出，每轮最多提示两次（`NATIVE_DIALOG_INPUT_MAX_REPROMPTS=2`，范围 1–3）；提示播报失败则结束本轮。设 `NATIVE_DIALOG_INPUT_GUARD=0` 可恢复旧的直接提交行为。

这是收音结果提交前的补全，不能保证接住云端停录瞬间仍在说的后半句；句中停顿容忍度和中间识别候选纠错须另行验证。

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

管理器在原生麦克风采集启动前启用 `Loopback Enable`，使播放音频进入 AEC 参考通道；PNS 服务单独重启时也会先设置该项。仅在采集已经运行后切换开关不能替代重新初始化。原值保存在 `/tmp/native_followup/loopback.before`，停止管理器或安装失败时先恢复原值，再启动原生服务。该处理同样受 boot1 固件哈希校验限制，不改写固件或替换麦克风音频。

完全不依赖 Mac 还要求沿用音箱端链路：`LLM_PIPELINE=native`、`TTS_ENGINE=device`。`native_live` 不调用旧的录音、`asr_audio` 或 Mac ASR 路由。原 PCM + Mac 组件可保留以供回退，但与本管理器的 PNS 覆盖不同时加载。

## 实现和隔离

1. 只在 LLM 实际播放完成后，由客户端发起有所有者 PID、序号和单调时钟期限的识别请求。进程间及线程间访问使用文件锁，一次只接受一个请求。
2. 从运行时注册中取得原生回调和上下文，发起程序唤醒；只改写本次上行 prepare 的 `activate_mode=NONWAKEUP`。使用 protobuf 对象副本，不写原生对象，也不替换真实麦克风音频。
3. `mico_aivs_lab` 以 prepare 包摘要、长度及处理线程作用域关联本次 Recognize，再绑定准确的 `dialog_id`。每轮清空旧文本，取消、超时和旧 dialog 的结果不能进入后续会话。
4. 在该 Recognize 的 `Execution.RequestControl` 中设置 `disabled=["NLP","TTS"]`。这是小米协议规定的 ASR-only 模式；该请求不会走通常的语义理解和回答流程。匹配本轮 dialog 的非 ASR 动作/播报指令另在解析入口隔离，普通原生 dialog 保持原样。[小米 Execution 协议](https://cnbj1.fds.api.xiaomi.com/instruction/Execution.pdf?Expires=9223372036854775807&GalaxyAccessKeyId=5151729087601&Signature=tvKms0qd313PPuyQgKK9VtEevP8%3D)
5. 本地唤醒词缓存通过零长度 IVW 完成通知放行；实际上传的始终是原生麦克风流。最终 ASR 文本以数据交给 shell，绝不作为 shell 配置执行。
6. `wakeup.sh` hook 跳过续听期间的原生灯效和脚本提示音，客户端继续显示绿灯。真实唤醒先撤销追问归属和 busy 标记，再调用原生回调，恢复原生提示与处理。此固件另有 `wakeup_tone_raw` 线程直接向 ALSA 播放“欸”等本地 WAV，绕过脚本：组件在线程创建时记录本次续听的归属，仅在该线程读取五个已知唤醒音文件时将 PCM 缓冲区置零，保留 80 字节文件头、长度及播放结束时序。普通唤醒、其他线程和其他文件不受影响；原始音频文件不改写。线程归属保留到结束，避免识别完成或取消后延迟响起。静音清理旧原生队列及恢复音量在开启追问收听前完成。

播放期间的原生回调只在自有续听 phase 1–6 且 busy 时屏蔽；IDLE、FAILED、交接或状态不可用时透传。LLM 保持连续播报。追问开麦前恢复原生音量，同时保留本轮 LLM 的音量目标，避免下一段重新计算后变响。2026-09-09 已修复 AEC 参考通道的初始化时机，参考电平及串音对照见[验证记录](../../docs/history/2026-09-09-parallel-wake-reference.md)。参考信号存在不等于每次家居命令都能成功，仍需分别核对真实唤醒、最终 ASR 和家居动作。

首轮失败文案拦截仍由 `device/aivs_guard/` 负责，和本组件的追问 ASR-only 隔离是两件事。

正常完成的同一追问 `Dialog.Finish` 允许 SDK 重复解析，包括 CLI 已将 phase 置回 IDLE 的间隙。它负责清除 SDK 的会话/TTS 超时等待，不能当作旧动作拦截；否则会在 ASR final 约十秒后误报 `50010005 / TTS timeout`，并触发本地“网络异常”语音。该例外不适用于交接、取消或被新会话替代的 dialog，也不放行旧 StopCapture 或家居动作。

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
zig cc -target arm-linux-gnueabihf.2.25 -Os -Wall -Wextra -Werror device/native_asr/test_native_asr_wake.c -ldl -lpthread -o /tmp/test_native_asr_wake
# 将二进制复制到音箱 /tmp 后运行；测试状态分别使用
# /tmp/native_followup_unit 与 /tmp/native_followup_wake_unit，目录已存在时拒绝运行。
```

安装器输出 `BACKUP=/data/native-asr-backup-时间`。待音箱空闲后，在设备执行该目录的 `restore.sh`，会恢复对应安装前的客户端、配置、组件和原生服务。第一次从 PCM 路线切换前的备份可恢复 PCM + Mac ASR；后续安装备份则恢复上一版原生组件。不要混淆这两种回退点。
