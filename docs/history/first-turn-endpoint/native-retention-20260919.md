# 路由记录有界保留与恢复入口对齐

接续 [预加载/管理进程生命周期](native-lifecycle-20260919.md)。本轮处理长期成功请求累积到 journal 上限的问题，并把新版管理程序的停止流程接回临时原生恢复入口。仍未安装日常常驻版。

## 记录可以清理到什么程度

`quiet` 是已完成的放行证据：对应同一代正常判停、final、Finish 和 helper 正常结束。它不会再转为 pending/failed。删除旧 quiet，不会将一条拒绝记录变成允许；客户端仍要求非空 final，并使用原有 dialog 去重。新增回放验证 quiet 删除前后的 partial 均拒绝，完整 final 仍只提交一次。

watcher 启动时，在持有独占 watch.lock、回收旧代之后，清理验证通过的旧 quiet 记录，通常保留最近 32 条（同秒按文件名确定顺序），允许当前轮结束时临时多一条。处理在独立 watcher 中进行，不放进原生 PCM 或 JSON 回调。

只接受完整规范格式、私有普通文件，删除前复核内容与 inode。pending、failed、格式错误、内嵌 NUL、符号链接、临时文件等均保留。空间紧张时，成功记录的保留数可降至零，为新一轮留位置；**不能用删除失败证据换取空间**。

256 条容量规则仍在。如果剩余记录全受保护且已满，watcher 在加载模型、发布 READY、改写 Wakeup 之前返回配置失败，并记录 `FIRST_ROUTE_CAPACITY protected-full action=no-arm`。Recognize 写入处再次校验容量，防止检查后的变化。本轮没有为失败记录设随意过期时间；若真的累积到此上限，应先处理故障原因。

## 恢复流程不依赖残留 PID

管理程序新增私有 Unix 数据报停止入口，`run_native_wake_session.sh stop` 无需模型 manifest。请求到当前 `session.sock`，程序停止自己的工作进程并退出；调用者等待 `session.guard` 的内核锁释放，最多五秒。没有运行中的管理程序则幂等返回。

`session.guard` 中的 PID 仅用于诊断。测试故意把它改成测试调用者自身 PID，停止命令依然通过本机请求正确退出管理程序，没有向该 PID 发信号。无法确认的旧 shell `session.lock` 会使 stop 报错保留现场，不能假装空闲。

`run_native_wake.sh restore` 现在先调用新版 stop，再撤销原生覆盖；stop 失败则不继续卸载。私有临时客户端 runner 也已去掉旧管理器 PID 终止段，交由该入口处理；其 armed 标记改为完整恢复成功后才删除，失败时仍可重试。原客户端进程的既有身份核对与恢复逻辑保留。本轮仅验证了停止子链路，未在日常原生进程上重新挂载/卸载覆盖。

这是设备本机的控制消息，不是新建网络服务。正式运行需配套使用本轮构建的 session 二进制和恢复脚本。

## 验证结果

最终全部 **158 项回归及 shell 语法通过（59.215 秒）**，严格 ARM32 构建通过。

- 主机和音箱的 journal 压力测试连续生成 600 条成功模拟记录，保留数量有界；失败、pending、损坏、内嵌 NUL、符号链接和临时证据不被清除。满额时可回收最后一条 quiet；全为保护记录时拒绝新增。
- 主机真实 watcher/session 加假 helper 验证 256 条保护记录使流程在加载前拒绝，未调用 helper、未发布 READY。
- 音箱 ARM 管理器/控制器加假 helper 验证预加载中的 stop：管理程序退出，helper 已结束，映射、状态和 socket 清理。陈旧 PID 文本不引发信号；旧版锁保留并拒绝停止；全保护容量上限拒绝接管。
- 设备独立 endpoint/helper 故障与旧代回收测试继续通过。

上述压力请求只写模拟 journal，不是 600 次真实录音或 LLM 调用。helper 为测试进程，没有运行模型推理。本轮未触碰麦克风、云端或日常启动配置；音箱原生进程始终 mipns 3070 / aivs 3009，状态 healthy，客户端和两个 init 脚本哈希不变。测试目录和可执行文件已逐项清除。

私有证据目录：`tmp/asr-shadow-20260918/retention-build/`，包含 `regression-final.txt`、`device-final.txt`、`device-stop-final.txt`、测试脚本及构建产物。

最终 SHA256：

- probe：`11d16628f7a17b46f56bfddc79d03a06ecc077e24a4af9246ec73bf748966f29`
- watch：`52a4340e1fd029b40f0c89561613dcf0426f3004e3b4e12d2023b9d9b30c9d26`
- session：`7c3948bbdab2c213a7a7b2e28a2caf1e49e57ea689d254443ba28179b2631bf0`

## 仍未完成的日常运行条件

当前管理器仍是最多 240 秒的试验入口，不能直接当作开机常驻方案。需要结合已有约 25 MiB 模型 RSS、每轮约两秒预加载、未就绪时保留原生处理，确定空闲模型保留与长期运行策略，再做完整录音的静音、抢占、断网和故障恢复联调。TTS 重试造成的旧播放停顿仍属另一条工作，本轮未改变其超时或重试参数。
