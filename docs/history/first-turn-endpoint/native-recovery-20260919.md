# 控制器异常退出后的资源回收

接续 [自动接续与路由完成状态](native-route-20260919.md)。本轮没有挂载实验库、没有录音或发送云请求，也没有重启日常服务。验证使用主机和音箱上的独立测试进程；模拟音频回调与结束回调不操作原生麦克风。

后续 [预加载与外层管理进程恢复](native-lifecycle-20260919.md) 已补齐下文留下的两个生命周期缺口，仍未部署常驻版。

## 复现的问题

对已经 READY 的真实 watcher 发送 SIGKILL，它没有机会执行退出清理，`native-wake.state` 留下。旧代码下一次启动因文件已存在而退出，不能自动重新就绪。主机实际进程测试先得到 `WAKE_OBSERVER_READY not found` 失败，证据为私有 `tmp/asr-shadow-20260918/recovery-before.txt`。

失败记录仍会阻止残句进入 LLM；这里修复的是下一轮可恢复性，不改变识别或判停参数。

## 回收规则

新增 `native_wake_recovery.h`，watcher 全生命周期持有私有 `watch.lock` 的非阻塞 flock。锁文件保留，不按路径删除，以免两个实例分别持有不同 inode 的锁。锁 FD 设置 CLOEXEC，helper exec 后不继承；watcher 被杀时内核释放锁。

新 watcher 在加载模型前检查旧状态：

- 旧 owner 仍存活时拒绝接管，即使租约过期。PID 被复用也保守拒绝。
- owner 已退出但 helper 尚存活时返回可重试 busy（3），让自动 session 等待。
- 两者都已退出时，校验私有普通文件、大小、协议、owner/nonce/observer，并先验证两份映射，再回收该代音频/提议映射和状态。
- 删除前再次比对 inode。身份不符、损坏、符号链接或不安全权限均保留并报错。
- 路由 journal 完全不删除。旧 pending/failed 仍拒绝迟到的 final；新 dialog 独立处理。

## 验证结果

全部 **148 项主机回归**及 shell 语法通过（52.525 秒），ARM32 严格编译通过。

1. 主机使用实际 watcher：等待 READY、SIGKILL、启动新 watcher；新实例回收旧状态并再次 READY，竞争实例不能夺取状态；TERM 后正常清理。旧路由 pending 仍在。
2. 主机与音箱运行同一独立 C 测试：创建实际 owner/helper 子进程，杀掉 owner 后活 helper 阻止回收；helper 退出后才回收。测试同时覆盖存活但过期 owner、错代提议、符号链接、损坏状态、重复回收和保留 pending；新 dialog 能发布 quiet。
3. 音箱现有 `test_first_endpoint` 增加真实 helper 子进程死亡用例：使用模拟 PCM/结束回调执行实际 `first_end_step`，得到 helper-failed EOF；即使随后补 final/Finish，也不能晋升 quiet。紧接着同一测试进程内的新代正常 quiet 完成。
4. 音箱运行实际 ARM watcher 的观察模式，状态目录编译到私有 `/tmp/native_recovery_watch_unit`：SIGKILL 后新实例输出 `FIRST_RECOVERED` 和 `WAKE_OBSERVER_READY`，竞争实例拒绝，正常退出清理。未安装到原生服务，不会打开麦克风。

第 2/3 项 helper 是测试子进程，不是运行 Silero 推理的模型；本轮不能称作真实麦克风故障验收。第 4 项是真实 watcher 的设备进程生命周期验证，模式为只观察。

私有证据目录：`tmp/asr-shadow-20260918/recovery-build/`，含 `regression.txt`、`device-unit.txt`、`device-watch.txt` 和构建产物。设备测试全部成功后已清除本轮测试可执行文件和私有目录，原生服务一直为 mipns 3070 / aivs 3009，最后核验 healthy。

构建 SHA256：

- probe 未改：`0ad8dab879cef56b4b1e59691cc12471c19dcd1796d3fee0ffd456fdc74d3138`
- watch：`61f55fabb5cc71199a46b5cadccacb0e94bef31130fedb9b0386f0fe231931cd`
- endpoint 测试：`b85fef13a74021581f895757af172e9b7b1839704501911e5d457bfa70212c19`
- recovery 测试：`1af59b2d5fd213af8c036d5fc83dd2b9f28eea909e529f7e7cd4aeda030e3286`

## 剩余边界

回收只处理已有有效状态文件的旧代。模型预加载阶段、尚未发布状态时被 SIGKILL，可能留下按旧 owner/nonce 命名的映射；本轮没有按通配符删除它们。外层 session 自身被 SIGKILL 的锁恢复、常驻预加载和 journal 保留策略仍需单独完成。

录音中 owner 死亡时，原生旧请求依赖之前设置的有界超时退出；回收器不冒充旧 owner 发送 EOF，也不杀未知进程。真实静音、抢占、断网与完整录音故障现场尚未验收。以上改动保留在 worktree，没有部署为日常常驻版本。
