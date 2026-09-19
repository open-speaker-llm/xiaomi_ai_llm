# 空闲模型保留与续期验证

接续 [有界记录保留](native-retention-20260919.md)。选择的方向是在音箱空闲时保留一个已加载的 VAD 模型，仅真实唤醒认领后传入原生 PCM。文本仍由小米识别，无 Mac 转写、外部服务或额外 LLM 判句调用。

## 本次实现

新增 `native_wake_session ready <seconds>`，仍限制在 1–240 秒内；它调用 `endpoint-ready` watcher 和 `first-ready` helper。普通的按轮数试验入口保持原语义。停止或到时取消均返回 1，不能把取消算成完成了一次语音请求。

空闲代最长 20 分钟；每份租约最多 90 秒，在剩余不足 60 秒且确认为未认领的 ARMED 状态时续期。owner、helper、原生进程身份、nonce、随机标识必须匹配且仍存活；发生 wake、prepare、音频、修改或完成后均不再续期。真实请求的 20 秒收音上限、28 秒 helper 上限和 30 秒 watcher 完成等待没有扩大。20 分钟上限是代码约束，尚无完整 20 分钟实测。

helper 空闲轮询从 2 ms 改为 20 ms，每 250 ms 检查精确租约。共享锁竞争不阻塞 helper，最多容忍两秒；明确失效立即退出。没有 PCM 时不调用 VAD 推理，不打开麦克风。每轮完成仍退出旧 helper，再为下一轮创建独立模型，避免跨轮状态残留；约两秒的轮间加载空窗仍存在。

watcher 的无人唤醒退出码为 4，supervisor 将它视为空闲等待，不消耗轮数或失败预算。修正了预加载后的清理分支：此前已判为忙碌的返回码 3，会因尚未发布 ARMED 被误改成 1。现在保留忙碌与配置失败的分类；只有原本判成功、最终复核不通过时才降为失败。

## 独立音箱测量

2026-09-19 21:19:36–21:21:16，真实 Silero 模型、真实 watcher/session，使用 `/tmp/native_idle_unit` 中的模拟控制状态。没有安装原生覆盖，没有输入麦克风或云请求。

- 同一 owner 332、helper 333、nonce 621314821 保持 100 秒；仅加载一次，init 1911 ms，续期三次，跨过原有 45 秒等待及初始 90 秒租约。
- 三次快照均为 `audio_bytes=0 proposals=0`，结束时 `audio_ms=0 segments=0 max_step_ms=0`。
- 模型 RSS 三次均为 24924 KiB（约 24.3 MiB），最大 RSS 25472 KiB；watcher/session 约 384/380 KiB。
- 100 秒内 `/proc/PID/stat` 的 CPU 增量：helper 0.28 秒、watcher 0.56 秒、session 0.23 秒，合计约单核 1.07%。helper 自报加载后 CPU 290.124 ms，计量区间略有不同。
- 除去传输用 tar 后，可用内存约 108720 KiB（106.2 MiB）；试验前约 148608 KiB（145.1 MiB）。当前运行文件放在 tmpfs，所以不能只用模型 RSS 估算总内存代价，也不能简单将文件大小与 RSS 相加。
- 通过本机 stop 请求结束，helper 返回 `reason=signal`，属于预期取消；没有把空等待记成成功识别。进程、流映射、租约和 socket 清理通过。

这只是短时空闲成本与续期验证，不证明全天稳定性、活动期间内存峰值或实际唤醒后的结果。

## 自动验证

163 项回归和 shell 语法通过（73.106 秒），严格 ARM32 构建通过。增加了续期只能发生在未认领状态、身份与存活检查、过期/权限/符号链接/锁竞争、实际 watcher 加载后遇忙保留返回码，以及连续两次空闲不消耗失败预算的验证。新增测试快照命令后，真实 watcher 生命周期六项复测通过。

音箱 ARM 租约测试通过；原生 endpoint 独立测试再次覆盖原样 PCM、候选时效、第二次唤醒、helper 死亡、强制 EOF 拒绝、下一代恢复和 20 秒上限。测试期间原生日常进程保持 mipns 3070 / aivs 3009，客户端和两个 init 文件哈希不变。

私有证据：`tmp/asr-shadow-20260918/idle-build/`，包含 `regression.txt`、`device-idle.txt`、`archive-removed.txt`、`device-units.txt`、测量脚本、运行包与构建产物。

本轮构建 SHA256：

- watcher：`b34cb4a7c472dfe4c782f38683cdbcf934c243e4fd44926ce83bb2e5959d1cac`
- session：`73edd9df6cbbdd3b78efbb629533863ece65baa817985599e14ee9de7df661e8`
- helper：`14e191bd296cb6ae064898259707fd06e06bb33505312c7a636bfb27f4ac2b0c`
- runtime manifest：`26962481db6dd25acedf632a8c563fef9f367f005c539100ad3965878518e6e9`
- probe 未变：`11d16628f7a17b46f56bfddc79d03a06ecc077e24a4af9246ec73bf748966f29`

## 静置后真实唤醒

用户现场确认可以配合后，在限时临时版完成一次 LLM 首轮。真实测试的原生进程始终 mipns 3400 / aivs 3338，客户端 3002，模型 owner 3568 / helper 3569。就绪之后先独立核查两条进程的 probe 映射，再静置整整 60 秒复查；模型续期两次、没有重载。preload 到实际 wake 的单调时间差为 81186 ms，其中包含初始加载时间，不能把全部 81 秒都算作就绪等待。

dialog `59e1692ebcecba861ebfe2c100efc5e7`：

- 同一 Wakeup 与 Recognize 正确关闭自然录音，Recognize 的云 VAD 关闭、本地 VAD 开启；原生 context/NLP/TTS 保留。
- 模型在音频 9290 ms 提议结束，原生于 9300 ms 正常 quiet EOF，比首个 final 早 152 ms；无 StopCapture，final、Finish、helper 和 route 均成功。
- 完整 final 为“问问DEEPSEEK为什么月亮有时候白天也能看见请用一句话回答”。同样的完整文本只提交一次 LLM，会话历史恰好一条 user、一条 assistant。
- 单段 TTS attempt=1，客户端记录首声 3.69 秒、TTFT 1.04 秒。用户确认“按要求完成，回答完整，无卡顿或干扰”，包含只说一次、约 1.5 秒停顿后的轻声补充。
- 下一代加载期间遇到播放占用，实际返回 rc=3、等待重试，没有误算识别失败；播放及静默追问结束后可再次 READY。停止时取消了这次尚未认领的下一代，所以 session 记录 `attempted=2 passed=1 consecutive_failed=0 interrupted=1`，并非做了两次语音输入。

原始云事件/指令在该 dialog Finish 后立即保存，未被后续 ASR-only 追问覆盖；`live/audit.json` 校验请求开关、文本、EOF 顺序、无 StopCapture、唯一 LLM/历史和重试分类。现场证据在同一私有目录的 `live/`、`live-session-valid.txt`、`live-minute.txt`。

### 本次发现并纠正的启动顺序问题

第一次准备时先安装 probe、再启动临时客户端。客户端初始化会调用 `native_asr.sh start`；该管理器只认可日常 preload，因而卸下上层 probe 并重启服务，还导致 native_live 初始化失败。这个阶段虽有模型 READY，却没有有效原生测试层，**没有提示用户说话，也不计为现场成功**。记录在 `live-setup.txt`、`live-session.txt`。

先恢复正常管理器，再采用 **临时客户端 setup → 确认 native_live 正常 → probe setup → watcher READY → 检查实际进程映射 → 静置 → 提示开始** 后完成上述有效试验。私有 `run_route_client.sh` 新增前置检查：probe 已安装时拒绝启动客户端，并在启动前要求日常 native_asr 健康；shell 语法通过。后续准备必须用更新后的 runner，不能只凭 READY 判断覆盖层仍在。

## 恢复与下一阶段边界

现场后通过本机停止入口结束 session，撤下 probe 并恢复 `/data/native_first_client.sh`。最终 mipns 1518 / aivs 1450、原客户端 1706，native_asr healthy；原客户端和两个 init 文件 SHA256 与试验前相同。runtime 逐项校验后清除，模型、映射、租约、socket、armed 和独立测试目录均清理；route 完成证据仍按既定保留规则保留。可用内存恢复到 147680 KiB。未改 `/data` 文件或开机配置，未提交、合并或推送。

本轮支持采用“空闲保留模型、实际收音才推理、完成后新建下一代”的方向。当前仍是最多 240 秒的验证入口，没有安装日常常驻版。下一步需完成真实静音/新唤醒抢占、长句上限和中途失败的端到端边界验证，再确定日常运行入口；不能以一次静置成功替代这些验收。每轮约两秒重载空窗仍需保留在产品预期中。

历史两次播放停顿的 TTS 失败重试问题未修改；本次播放顺畅不代表已修复。
