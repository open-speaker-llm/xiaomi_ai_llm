# 首轮截断与本地判停：研究和验收索引

这些记录保留每个阶段当时的结论、失败样本及修正依据；其中“尚未接入”“已恢复旧版”不代表最终状态。**2026-09-20 最终日常包已启用并通过现场 C2 验收**，整机重启与全天运行仍待验证。当前用法见[快速上手](../../getting-started/quickstart.md#boot1-首轮本地判停)、[原理](../../concepts/native-first.md#首轮收音与结果提交)、[运维](../../runbooks/operations.md#boot1-首轮本地判停)；源代码和构建入口仍在 `device/endpoint_probe/` 与 `device/native_endpoint/`。

| 阶段 | 关键证据与结论 |
|---|---|
| 找出截断层次 | [基线](baseline-20260917.md)、[协议验证](protocol-20260918.md)：partial 提前提交与云端先结束收音是两个问题；final-only 无法找回未上传的尾句 |
| 轻量 VAD 与真实输入 | [旁路](shadow-20260918.md)、[主动判停](active-20260918.md)、[SDK 超时对照](sdk-timeout-20260918.md)、[A/B 对齐](pair-test.md)、[句末分析](turn-end-audit-20260918.md) |
| 环境声和轻声 | [同源采样](capture-20260919.md)、[纸张/轻声对照](contrast-20260919.md)、[成本与候选](noise-feasibility-20260919.md)：不能把有能量的声音一律当作人声 |
| 神经网络可行性 | [模型文件测试](neural-vad-20260919.md)、[实时旁路](neural-shadow-20260919.md)、[真正结束](neural-end-20260919.md)、[模型重置](neural-reset-20260919.md) |
| 真实唤醒首轮 | [请求归属](native-wake-20260919.md)、[接入反例与两轮成功](native-first-endpoint-20260919.md)、[连续轮](native-repeat-20260919.md)、[LLM 路由与追问接续](native-route-20260919.md) |
| 常驻与恢复 | [生命周期](native-lifecycle-20260919.md)、[常驻](native-resident-20260919.md)、[空闲](native-idle-20260919.md)、[轮换](native-rolling-20260919.md)、[池化](native-pool-20260919.md)、[常驻现场](native-resident-live-20260919.md) |
| 隔离与迟到结果 | [收音中再次唤醒](native-interrupt-20260919.md)、[恢复](native-recovery-20260919.md)、[拒绝记录保留](native-retention-20260919.md) |
| 日常安装与最终验收 | [完整记录](native-daily-20260919.md)：200 轮旧包回放、实际回滚；静默重叠报错和正常轮积压失败；6 秒无语音退出、取时兼容、突发积压恢复；最终 C2 完整问题进入一次 LLM |
| 独立待办 | [历史播放停顿](playback-stall-20260919.md)：本次未实施播放修复，现场无卡顿不等于旧问题已解决 |

所有录音、完整日志、第三方二进制、运行包和设备备份均留在私有忽略目录，文中 `tmp/asr-shadow-20260918/` 等路径是当时开发环境的证据位置，不是仓库提供的下载内容或新设备安装命令。旧文里的测试数量对应各自版本，不能累加为最终版覆盖率。
