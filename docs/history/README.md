# 历史探索索引

文档类型：历史和证据入口  
适用范围：回看为什么当前主线会这样设计，或确认某条路线是否已经试过  
当前结论：历史内容保留用于查证，不作为当前部署入口

## 1. 归档快照

文档重构前的完整 Markdown 原文在：

```text
docs/archive/2026-06-07-pre-doc-reorg/
```

如果想找过去某条命令的完整上下文，优先去这里。

## 2. 关键历史文档

| 文档 | 用途 |
|---|---|
| [NATIVE_FOLLOWUP_EXPLORATION.md](NATIVE_FOLLOWUP_EXPLORATION.md) | 原生连续追问、reopen、多轮 ASR、干净音频探索结论。 |
| [../BOOT0_SSH_RUNBOOK.md](../BOOT0_SSH_RUNBOOK.md) | boot0 SSH 当前操作手册。 |
| [../../REMOTE_SHELL.md](../../REMOTE_SHELL.md) | root shell / SSH 注入历史入口。 |
| [../../PROJECT_LOG.md](../../PROJECT_LOG.md) | 项目流水记录入口。 |

## 3. 当前不推荐作为主线的旧路线

- KWS 自定义唤醒词路线：`stream_client.sh`、`wake_monitor.sh`。
- 早期 `native_client.sh` 路线。
- 单次 probe 脚本直接作为部署入口。
- native multirounds/reopen 追问路线。
