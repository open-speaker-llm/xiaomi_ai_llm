# Root Shell / SSH 历史入口

文档类型：历史入口  
适用范围：回看早期如何获取 root shell、failsafe、SSH 注入  
当前结论：日常不从这里开始；当前 boot1 SSH 操作看 `docs/BOOT1_SSH_RUNBOOK.md`

## 1. 当前应该看哪里

| 场景 | 文档 |
|---|---|
| 日常 SSH 登录 | [docs/OPERATIONS.md](docs/OPERATIONS.md) |
| boot1/system1 SSH 打通 | [docs/BOOT1_SSH_RUNBOOK.md](docs/BOOT1_SSH_RUNBOOK.md) |
| 启动链路和分区原理 | [docs/BOOT_FLOW.md](docs/BOOT_FLOW.md) |
| 断电重启后自启动 | [docs/AUTOSTART_INIT_HOOK.md](docs/AUTOSTART_INIT_HOOK.md) |

## 2. 历史全文

重构前完整 `REMOTE_SHELL.md` 已归档：

```text
docs/archive/2026-06-07-pre-doc-reorg/REMOTE_SHELL.md
```

其中包含早期 system 镜像解包、注入、重新打包、写入等完整过程。那些内容保留用于追溯，不作为日常操作入口。

