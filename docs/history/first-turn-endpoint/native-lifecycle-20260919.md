# 预加载与外层管理进程的异常生命周期

接续 [READY 后的控制器恢复](native-recovery-20260919.md)，补齐该记录明确留下的两个生命周期缺口。本轮未录音、未调用云端，也未安装或重启日常服务。

后续 [有界记录保留与停止入口](native-retention-20260919.md) 已补齐 journal 成功记录回收和新版恢复器衔接，下文保留本阶段的集成边界。

## 原因与修正

旧 watcher 先加载模型、后发布状态。若在模型建好映射后、READY 前被强杀，下一轮找不到这些资源的归属。现在先发布不可接管录音的 `NW_CANCELLED` 暂存状态，再 fork helper；helper 等待管道握手，父进程写入 helper PID 后才放行。模型与控制条件全部通过后，才发布 `NW_ARMED` 和 READY。真实唤醒不能认领预加载状态。

若父进程在 fork/握手之前退出，没有被放行的 helper，不能产生映射；若退出在模型加载中，旧状态能定位该 owner/nonce 的文件。回收仍要求旧进程退出、文件私有且身份匹配，保留所有路由拒绝证据。错误格式或身份不明的文件继续拒绝自动删除。

旧 shell 管理器依赖 `mkdir session.lock`，SIGKILL 不执行 trap，目录永久留下。独立复现中，旧实例退出且原计时器结束后，再启动仍返回 2、报目录已存在。证据保存于私有 `lifecycle-build/session-before.txt`。

新增小型 ARM32 `native_wake_session` 替代 shell 内的进程管理，原 `run_native_wake_session.sh` 入口保留并 exec 它：

- 全生命周期持有 `session.guard` 的内核 flock，异常退出自动释放。文件不删除，避免产生两把锁；文件内 PID 仅用于诊断，锁本身才是所有权依据。
- 新版不再创建 `session.lock`，消除 mkdir 与写 owner 之间的空档。对于旧版遗留目录，只有确认 owner 已退出且没有其他文件才回收；含糊或存活的旧实例仍保留。
- 单个进程使用单调时钟管理总时限，没有独立 sleep 倒计时进程。仍限制最多 20 轮、240 秒；busy 重试不消费轮数，配置错误或连续两次失败停止。
- 只等待和终止自己尚未回收的直接子进程。到时先 TERM、最多等两秒，再 KILL，不能因子进程忽略 TERM 无限卡住。
- Linux 用 `PR_SET_PDEATHSIG` 绑定 session → watcher → helper，设置前后都检查父进程，覆盖启动竞态。watcher 另在加载和主循环检查父进程归属；Mac 测试使用这一检查。父进程消失时子链路停止，不因外层消失继续接管录音。

ARM 管理程序当前 7920 字节，沿用设备 libc，无新增外部服务、识别引擎或模型。此大小不等同于运行时 RSS；本轮没有重新测量常驻开销。

## 验证

全部 **153 项回归及 shell 语法通过（61.750 秒）**。随后补充“fork 握手前退出、observer 尚为零”的断言，相关主机回收测试和 ARM 设备回收测试再次通过。严格 ARM32 编译通过。

新主机联动测试直接运行 watcher 和新管理程序，使用独立假 helper、控制状态与完成事件，覆盖：

1. 模型建文件前强杀 watcher：下一实例回收并成功完成模拟请求。
2. 只写好音频映射、尚无提议映射时强杀 watcher：同样恢复，旧映射不残留。
3. 预加载时强杀管理程序：watcher/helper 退出清理，新管理实例可启动；并发实例不能夺锁。
4. 预加载时 TERM：不发布 READY，正常清理。
5. 已确认退出的旧 shell 管理器锁可迁移；身份不明的锁保留。
6. 工作进程不响应 TERM：总时限仍触发最终终止。

音箱上使用 ARM watcher、ARM 管理器、同一假 helper/控制工具，目录固定为独立的 `/tmp/native_lifecycle_unit`。前三项现场设备进程测试均通过，分别输出 `PASS_PRELOAD_KILL_STAGE=before`、`PASS_PRELOAD_KILL_STAGE=stream`、`PASS_SUPERVISOR_KILL_RESTART`。三个恢复后的模拟请求均为 `attempted=1 passed=1`。测试结束核验无状态/映射残留，并逐项清除测试程序、日志与目录。

这些是实际操作系统进程与文件生命周期测试，helper 没有运行 Silero，模拟请求没有使用小米云或真实麦克风，不能称作完整录音异常现场验收。

设备原生进程一直为 mipns 3070 / aivs 3009，最后仍 healthy；原客户端和两个 init 脚本哈希保持不变。私有证据在 `tmp/asr-shadow-20260918/lifecycle-build/`，包含复现、回归、设备脚本、设备输出和最终状态。

构建 SHA256：probe 仍为 `0ad8dab879cef56b4b1e59691cc12471c19dcd1796d3fee0ffd456fdc74d3138`；watch 为 `52b4c84f594a039020753f6ab8b1dd27edd9e557854c99c702b5037d555e85ec`；session 为 `30cedb92838fcb8255ebf3416c795f8047506ca19db29c21156e2f9eac85f5fe`。

## 后续集成要求

新入口必须同时放置同版本 `native_wake_session` 二进制。旧临时客户端恢复器通过 `session.lock/owner` 查找管理进程，新版使用 `session.guard`；下次临时联调须适配恢复器，或先结束本任务持有的管理进程、确认子链路退出，再恢复原生服务。不能仅凭旧 PID 文本发送信号。

剩余日常化工作包括 journal 消费/保留策略、预加载的内存与延迟预算，以及静音、抢占、断网等真实录音异常联调。当前改动仅在 worktree 与独立测试中，未设为开机常驻。[历史播放停顿](playback-stall-20260919.md)仍是另一个 TTS 合成重试问题，本轮没有修改超时或重试参数。
