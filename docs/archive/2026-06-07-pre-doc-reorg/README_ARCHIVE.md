# 2026-06-07 文档重构前快照

> 2026-09-06 当前能力勘误：boot1 已实现[失败提示拦截](../../history/2026-09-06-boot1-fallback-guard.md)和[原生 ASR 连续追问](../../history/2026-09-06-boot1-native-followup.md)；后者已完成无 Mac ASR 的有声上下文测试及重启加载。续听“欸”声补丁已部署并通过设备检查，听觉复验待确认。boot0 保留录音 + 小米文件 ASR。两者仍依赖云服务，未实现播放中打断。以下保留历史原文；旧“boot1 追问未通”不代表当前能力。

这个目录保存文档重构前的 Markdown，方便回看早期探索过程和旧命令。2026-09-06 在涉及 boot1 路由/失败播报的文件与关键结论旁追加日期勘误，原实验内容保留；首轮失败提示拦截已实测通过，见 [最新记录](../../history/2026-09-06-boot1-fallback-guard.md)。

重构后的当前入口见仓库根目录 [README.md](../../../README.md)。

归档文件：

- `README.md`
- `DEV_COMMANDS.md`
- `REMOTE_SHELL.md`
- `TESTING.md`
- `PROJECT_LOG.md`
- `BOOT_FLOW.md`
- `BOOT1_SSH_RUNBOOK.md`
- `AUTOSTART_INIT_HOOK.md`
- `manual_native_first_cases.md`

