# 同一原生进程内多次唤醒：唯一标识与现场验证

接续 [首轮实际判停](native-first-endpoint-20260919.md)。本轮解决“每次试验必须重启原生服务”的限制，并增加有界自动重新就绪入口；仍未替换日常客户端或开机启动。

后续进展见 [完成状态约束与自动接续](native-route-20260919.md)：自动 LLM/追问/新唤醒现场验证已完成两轮，失败 final 的客户端约束已临时联调。下文保留本阶段的验证边界。

## 为什么不能直接取消首次请求限制

同一固件两轮 prepare 可以都是相同的 10 字节。时间新鲜、字节匹配或累计次数相近均不能区分迟到旧包。旧模式 1/2 继续保留首次限制；新模式 3 `native_wake_watch endpoint-tagged` 为每轮生成 128-bit `/dev/urandom` 标识。

已核对当前固件：mipns 的 prepare 在 0x14988 调用 pack，再同步进入 0x14498 的发送函数，0x145f4 调用 sendto，发送长度使用 pack 返回值。AIVS 在 0x34728 将接收缓冲配置为 65536 字节，0x34bdc recvfrom 的实际长度传给 0x34d14 的 unpack。服务使用本机 Unix 数据报。反汇编及固件 SHA256 保存于私有 `repeat-build/transport-evidence.txt`，安装增加 message-util 库哈希校验。

发送钩子只有在同线程、同一输出缓冲指针、长度、完整报文内容、当前租约/随机标识和精确目标 `/tmp/mico_aivs_lab/usock/speech.usock` 全匹配时，才把原报文复制到自己的定长缓冲并追加 28 字节。**不扩写原调用者的缓冲区**。成功发送后仍向原生调用者返回原始 10 字节长度。

追加部分是合法 protobuf 未知字段 51000：版本魔数加 16 字节标识。接收钩子先剥离扩展，原解析器仍收到原始报文；也用真实 protobuf-c 库验证了没有接收钩子时未知字段可正常解析。该标识只在设备本机 IPC 出现，不进入云端 JSON、音频或 LLM。

接收端检查当前随机标识、原始报文、500 ms 时限及尚未认领，才允许原生 Wakeup.id → Recognize.id 绑定。旧标识、无标识、重复 prepare 均撤销当前判停权限，并照常交给原生处理，不再猜测归属。新正常唤醒仍先撤销旧音频/提议映射；0x101 不被当成新轮。没有改动 ASR-only 追问的协议语义。

## 独立设备与主机验证

设备 `test_first_endpoint` 在私有测试目录，用真实 message-util/SDK、模拟音频回调和私有 Unix socket 完成：

- 不重启测试进程，连续两轮相同 prepare 配不同标识，各自绑定成功。
- pack 输出后的哨兵字节保持不变；实际发送 38 字节，原生发送调用返回 10。
- 真实 protobuf-c 能解析带扩展报文；hook 去扩展后正常解析并清除 TLS scope。
- 把第一轮报文延迟交给新一轮，不能认领；无标识/重复报文撤销控制。
- 旧有原样 PCM、过期/积压提议、新唤醒撤销、helper 故障、ASR-only 冲突、final、硬上限、owner 撤销测试继续通过。

主机状态测试补了模式 3 的认领/随机标识门槛，以及短包、截断、损坏、容量不足、全零标识拒绝。基础 136 项回归及 shell 语法通过。自动 session 另有六项测试：成功连续就绪、配置失败立即退出、两次失败停止、到时清理子进程、保留其他实例锁、拒绝无界参数。设备 BusyBox 用假 watcher 验证连续三轮、到时清理和配置失败，未访问麦克风或云服务。

最终合并运行全部 **142 项测试**与 shell 语法通过（46.626 秒）。最终重新构建的 probe/watch 哈希与下面实际现场产物一致。

## 20:11–20:12 两轮真实唤醒

实际 probe SHA256 `22dd23773f3f7c599cc5ec06180d66be217815a5e749f302fb1e0560df31778f`，watch `f9211fc0dc2c2efea6fe21c498e15665eb9389d7dc292a7269e468c77a7f0eda`。模型 runtime manifest 仍为 `df6c3bdab10da6df96ff28b623739ea57af71b9fbbe2c7a677061f6a5d64a82c`。两轮之间**没有重新 setup 或重启服务**，一直为 mipns 3245 / aivs 3182。

| 项目 | A | B |
| --- | --- | --- |
| 口令 | 现在 / 停约 1.5 秒 / 几点了 | 七乘以 / 停约 1.5 秒 / 八等于几 |
| dialog | 692f40fae1d3781d374e18b3b8b5fba5 | abc5f0f1bd009969d3939e789d29f689 |
| owner / helper | 3432 / 3433 | 590 / 591 |
| 接收 prepare | 38 字节，mode=3 | 38 字节，mode=3 |
| 实际本地 quiet 结束 | 音频 5640 ms | 音频 6480 ms |
| 完整 final | 现在几点了 | 7×8等于几 |
| 原生回答 | 现在是晚上8点11分 | 答案是五十六 |
| StopCapture | 无 | 无 |
| final、Finish、helper/CLI 返回 0 | 全部满足 | 全部满足 |

用户分别确认按要求完成、正常，无报错或干扰；B 没有混入 A。两个审计都核对本地结束早于 final、接收带标识报文、mode=3、完整 final/Finish、进程未变。helper init 约 1.93–1.96 秒，RSS 25544/26056 KiB，CPU 1401.114/1269.060 ms；最大积压分别 10/20 帧。当前只证明这两轮和离线故障用例，不能宣称所有连续唤醒都已验收。

私有证据：`tmp/asr-shadow-20260918/repeat-build/live-a/`、`live-b/`、`device-unit.txt`、`session-device-unit.txt`。每轮现场均等 FIRST_ENDPOINT_READY 才提示说话。

## 有界自动重新就绪入口

`sh run_native_wake_session.sh 4 180` 在已经 setup 的试验环境运行，最多四轮、180 秒；参数最多允许二十轮、240 秒。需明确提供已核验的 runtime manifest。它保持原生服务不重启，每轮启动独立 watcher/helper，随机身份与音频映射不复用。

忙碌/静音时等待，不软件唤醒；每个 watcher 仍独立检查 native ASR、进程和模型。配置失败立即停止，连续两轮失败停止；退出或到时终止自己的 watcher、等待其清理 helper，只移除自己的 session.lock。这个脚本不安装模型、不自行 setup、不修改 `/data`，也不撤销别人持有的安装。外层 300 秒自动恢复和显式 restore 仍负责卸载试验库。

**本轮现场测试是两次手动运行 tagged watcher；自动入口只通过主机和设备假 worker 测试，尚未进行自动连续现场验收。** 每轮仍重新加载模型约两秒，这段时间没有武装时由原生照常处理。首个 READY 不等于后台永远就绪，也不能称作零冷启动的常驻 VAD。

## 恢复与剩余发布条件

两轮后已 restore，核验 client/init 哈希不变、native_asr healthy、原生进程不再加载实验库、watch/helper/state/armed/busy 无残留。按 manifest 校验后删除本轮运行包和测试可执行文件；BusyBox 测试目录也自行清理。

仍需完成自动多轮与 LLM 播放/免唤醒追问交接的实际验收、静音与抢占、模型/owner 退出和网络超时的现场异常路径。故障或硬上限导致的结果应与正常 quiet 区分，并在正式路由中防止把被迫结束的残句写进 LLM 历史；目前 CLI 已标失败，生产路由尚未接入这个失败状态。已有 final-only 修正仍在 worktree，不能单独解决云端判停或硬上限残句。

日常版应复用现有设备启动/恢复管理，明确预加载的内存/CPU预算及未就绪时回原生的行为，不能把本实验脚本直接设成开机常驻。TTS 停顿是另一项已定位到合成重试的工作，本轮未修改其参数。
