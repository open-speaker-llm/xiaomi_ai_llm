# 探索历程与已试路线

文档类型：历史和证据入口
适用范围：回看为什么当前主线会这样设计，或确认某条路线是否已经试过
当前结论：历史内容保留用于查证和讲故事，不作为当前部署入口

## 1. 从这里开始

- [journey.md](journey.md) —— **完整探索叙事**：从拆机接串口、获取 root、squashfs 注入、KWS 弯路，到 native-first 成型、boot1 兼容、追问探索。想理解"为什么是现在这样"，读它。
- [followup-exploration.md](followup-exploration.md) —— 连续追问的专题记录：本地录音、失败的旧 reopen/下行注入与后来成功的 NONWAKEUP 上行入口。

- [2026-09-05-ssh-ota-recovery.md](2026-09-05-ssh-ota-recovery.md) —— 实机 boot1 SSH 恢复、两套系统原生 OTA 拦截与重启验证；最终 boot0 唤醒和回复由用户确认正常。

- [2026-09-06-boot1-autostart.md](2026-09-06-boot1-autostart.md) —— 补齐 system1 的助手自启动入口，切回 boot1 后验证开机自动启动。

- [2026-09-06-boot1-fallback-guard.md](2026-09-06-boot1-fallback-guard.md) —— boot1 失败提示已实测拦截；含首版遗漏、修正版重启后听觉确认、报时对照及状态字段复核。

- [2026-09-06-boot1-native-followup.md](2026-09-06-boot1-native-followup.md) —— 当前 boot1 原生 ASR-only 连续追问实现、有声上下文测试、自启动及“欸”声修复的验证边界。
- [2026-09-06-boot1-native-asr-research.md](2026-09-06-boot1-native-asr-research.md) —— NONWAKEUP 入口研究；时间和算术免唤醒识别成功，后续由正式组件接入 LLM。
- [2026-09-06-boot1-pcm-followup.md](2026-09-06-boot1-pcm-followup.md) —— 已验证的 PCM + Mac Whisper 旧路线及退出残音修复，现保留供回退。

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
- 旧 `native_multirounds`/ExpectSpeech 下行注入路线（当时未打通，见 [followup-exploration.md](followup-exploration.md)）；当前 `device/native_asr/` 的 NONWAKEUP 上行入口已实现，不能归入旧失败路线。
- `device/pcm_tap/` + `server/followup_asr.py`：已实测但需要 Mac ASR，作为可选回退，当前 boot1 部署使用原生实时识别。
