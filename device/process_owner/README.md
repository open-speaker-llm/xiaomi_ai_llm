# Native-first 进程隔离候选

此候选使用独立 Linux session 管理一次客户端及其子进程。停止时只向已校验 PID、启动时间、session、进程组及命令行的会话发信号；不按进程名终止系统的 curl、aplay 或 arecord。新进程由 helper 串行化启动和停止；旧客户端若只有 PID 文件而没有所有权记录，拒绝自动清理，避免误杀。原生 `mipns-xiaomi` 启动时另开 session。

**安装兼容性尚未完成：** 当前候选客户端缺少 `/data/native_process_owner` 将拒绝启动；现有整包、升级器、回退工具和单文件安装方式还没有同步提供该二进制，也尚未验收通用旧客户端迁移。不能将此候选直接替换其他正在使用的客户端，不能据隔离测试声称正式发布可用。历史 PID 文件、异常断电、安装回滚、锁竞争和原生服务启动失败均需进一步验收。

若 supervisor 被单独强制杀死，而同一 session 中还有存活进程，现有 helper 会因为无法校验原 leader 而拒绝向该会话发信号；此类孤儿不会自动回收。常规 stop、重复启动和忽略 TERM 的 worker 均有隔离测试，不能据此声称覆盖 supervisor 被 `SIGKILL`、内核异常或所有外部程序自行脱离 session 的情况。仅当旧客户端正在运行并有足够信息核验其身份时，才能另行规划迁移；不能通过修改 PID 文件绕过身份校验。

构建（需要 Zig）：`sh device/process_owner/build.sh /tmp/native-owner-build`。输出 ARM32 和 AArch64 静态 Linux 程序；机器的 `uname -m` 只能说明内核架构，不代表用户态 ABI。必须按照目标进程及固件核对二进制架构、来源和摘要。构建脚本不自动部署。

测试：`test_owner.sh` 用独立临时 session 检验停止、重启、未登记 PID 和忽略 TERM 的子进程；`test_real_commands.sh` 使用 ALSA null 设备及受控的长连接 HTTP 测试真实 arecord/aplay/curl；`make_test_client.py` 生成隔离客户端供 `test_client_lifecycle.sh` 检验停止与重启。测试仅使用临时文件；运行真实命令测试前需要提供一个受控、会保持连接的 HTTP 服务，且应确认音箱空闲。测试不打开物理麦克风。原生服务进程号不变不等同于完整语音功能通过。
