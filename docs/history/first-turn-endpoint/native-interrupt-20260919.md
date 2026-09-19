# 真实唤醒打断与取消分类

接续 [空闲后唤醒](native-idle-20260919.md)。本轮现场验证“旧问题尚未结束，再次唤醒改问时间”，并修正管理器把主动打断算作识别失败的问题。没有安装日常常驻版。

## 现场结果

2026-09-19 21:34，使用上一轮已验证的临时构建，先启动客户端，再装载 probe，检查实际进程映射后发布 READY。原生进程 mipns 3307 / aivs 3245，旧请求 owner 3467 / helper 3468。

用户说“问问 DeepSeek，为什么月亮会……”后，立即再次唤醒并问“现在几点了”。用户确认按要求完成，只正常报时，无异常或干扰。

| 项目 | 证据 |
| --- | --- |
| 旧请求 | `d54afd5fcb3f8086e49a53e155c35a2e`，Wakeup/Recognize 均进入本地判停模式 |
| 旧输入 | 原始指令快照包含 partial“问问DEEPSEEK为什么月亮会” |
| 第二次真实唤醒 | 单调时间 622204148 ms，正常事件码 1；旧状态转 CANCELLED、撤销模型输入 |
| 旧结束权限 | `ended=0 final=0 finished=0 frames=570`，没有发送旧请求的本地 quiet EOF；journal 保持 pending |
| 新请求 | `95b3e14adef3e67f4607709dca371bb5`，完整 final“现在几点了”、原生回答“现在是晚上9点34分”、正常 Finish |
| LLM / 历史 | 临时客户端没有 LLM direct 请求日志；历史文件列表前后相同，无新增历史文件 |

新请求发生在旧代取消及下一代模型加载期间，沿用小米原生处理；Wakeup 的自然录音为 true。**本次证明新问题可正常接回原生，并不证明打断后的新问题已经获得本地延长收音。** 每轮重载的约两秒空窗仍存在。

每秒保存变化后的云事件/指令快照，旧请求在已保存快照中只有 partial，没有 final。这种采样不能证明所有短暂事件都被捕获；防止残句提交的依据仍是取消后的 pending 拒绝记录，以及客户端最终没有触发 LLM。没有保存麦克风录音。

## 发现的问题与修改

现场 watcher 将这次主动打断返回为 rc=1，外层记录 `FIRST_SESSION_BYPASS`。原逻辑会消耗试验轮数，并在连续两次失败后停止；正常改口不应消耗故障预算。

在修改前新增真实 watcher/session 加模拟 helper 的用例，重现取消被返回为失败、后续 READY 丢失；失败记录为 `before-fix.txt` 和 `before-two-cancels.txt`。随后增加明确的 `NW_END_REPLACED` 终止原因，复用现有字段，不改变共享结构尺寸：

- 仅正常新唤醒撤销已有请求时写入这个原因。可疑附加回调 0x101、重复/不匹配 prepare 等仍按原路径处理。
- watcher 返回独立的 rc=5；管理器记录 `reason=replaced`，重试但不消耗轮数或失败预算。
- 取消不代表成功，不发布 quiet，不发送旧 EOF，也不删除旧 pending 记录。
- 没有明确新唤醒原因的协议撤销仍返回失败；原有两次真正故障停止的保护不变。

## 修正后的验证

**166 项主机回归和 shell 语法通过（79.102 秒）**，ARM32 严格构建通过。

实际 watcher/session 连续取消两次后，可继续完成后续三轮，最终 `attempted=3 passed=3 consecutive_failed=0`。两条旧 journal 仍为 pending，三条完成记录为 quiet；协议撤销仍返回 rc=1。该序列在主机和音箱独立 ARM 进程均通过，未使用麦克风或云请求。

音箱独立原生回调测试也验证：有新鲜 quiet 候选时收到新唤醒，不发送旧 EOF；随后人为送入旧 final/Finish，仍不能改变取消状态或放行旧记录。已有 helper 死亡强制 EOF 拒绝、下一代恢复和 20 秒上限测试继续通过。

上述新的取消分类尚未重新做真人现场试验。现场样本验证的是修正前已有的中断与原生恢复行为，并提供此次修正的失败证据，不能混写成新构建已完成现场验收。

构建 SHA256：

- probe：`daf9c554dc5db8aab4281acd9c318f29de043180dea068f749dc369d21a84bbe`
- watcher：`d0297bdfdc26949f11420196f7bd49c632cc65fce0dba955f4f8b7e87e5a0d69`
- session：`380d1c09cb5937028808ea05cf81a0fb6298117fda45561fec156f95462cffb7`
- 模型运行包未改变，manifest 仍为 `26962481db6dd25acedf632a8c563fef9f367f005c539100ad3965878518e6e9`。

## 恢复与边界

现场后恢复日常客户端，独立测试期间没有再次重启日常服务。最终 native_asr healthy，mipns 1097 / aivs 1028、原客户端 1266，原客户端和两个 init 文件哈希不变。临时运行包按 manifest 校验并逐项删除，独立测试目录、模型进程、映射、租约、socket 和 armed 均清理；生产 journal 中的取消证据保留。未改开机配置、提交、合并或推送。

证据位于 `tmp/asr-shadow-20260918/interrupt-build/`：`live/`、`live-session.txt`、修改前失败记录、`lifecycle-fixed.txt`、`device-sequence.txt` 和 `regression.txt`。

仍需验证真实静音、最长收音和中途故障；历史 TTS 重试卡顿仍未修改。日常版还需处理取消记录的长期生命周期：目前这些拒绝证据受 256 条容量保护，不能因为用户主动取消就直接删除，否则旧 final 可能被误认为普通原生结果。当前有界实验入口不等于全天常驻版本。
