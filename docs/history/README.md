# 探索历程与已试路线

文档类型：历史和证据入口
适用范围：回看为什么当前主线会这样设计，或确认某条路线是否已经试过
当前结论：历史内容保留用于查证和讲故事，不作为当前部署入口

## 1. 从这里开始

- [journey.md](journey.md) —— **完整探索叙事**：从拆机焊串口、获取 root、squashfs 注入、KWS 弯路，到 native-first 成型、boot1 兼容、追问探索。想理解"为什么是现在这样"，读它。
- [followup-exploration.md](followup-exploration.md) —— 连续追问的专题记录：本地录音 vs 原生 reopen，试过哪些方向、为什么没打通。

## 2. 归档快照

文档重构前的完整 Markdown 原文在：

```text
docs/archive/2026-06-07-pre-doc-reorg/
```

里面是当年逐步写就的原始文档（`PROJECT_LOG.md`、`REMOTE_SHELL.md`、旧版 `DEV_COMMANDS.md` 等），保留所有命令和中间结果，用于查证具体某条命令的完整上下文。

## 3. 当前不推荐作为主线的旧路线

这些代码仍在 `device/` 里，但只用于历史对照或专项实验，不作为部署入口：

- KWS 自定义唤醒词路线：`stream_client.sh`、`wake_monitor.sh`（阶段 3，已被原生唤醒取代）。
- 早期原生唤醒 + 本地 ASR 中间形态：`native_client.sh`（阶段 4 前身）。
- 各类一次性 probe 脚本：`native_*_probe.sh`、`native_*_trace.sh`（探索时用）。
- native multirounds/reopen 追问路线（验证未打通，见 [followup-exploration.md](followup-exploration.md)）。
