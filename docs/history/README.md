<a id="探索历程与已试路线"></a>

<a id="1-从这里开始"></a>

<a id="2-归档快照"></a>

<a id="3-当前不推荐作为主线的旧路线"></a>

# 探索历程与证据索引

这里保存“当时为什么这样做”的答案：走过的弯路、失败样本、修正过程和验收边界。想顺着故事读，从[探索历程](journey.md)开始；只想知道现在能用什么，看[当前状态](../status.md)。安装从[上手路线](../getting-started/bringup.md)进入。

## 1. 从能进入设备，到能长期维护

最初的难点是取得可靠入口，后来又遇到双系统切换、SSH 失联和自启动缺失。相关证据：

- [SSH 与 OTA 恢复](2026-09-05-ssh-ota-recovery.md)：双系统备份、升级入口控制和重启核验。
- [boot1 自启动补齐](2026-09-06-boot1-autostart.md)：能 SSH 与助手能自动运行是两件事。
- [原始自启动记录](../archive/2026-06-07-pre-doc-reorg/AUTOSTART_INIT_HOOK.md)：2026-06 的镜像、写入和启动日志。

## 2. 从一次回答，到原生连续追问

早期接口失败之后，项目先验证 PCM + Mac ASR，再找到原生 NONWAKEUP 上行入口。阅读时按这个顺序，避免用早期失败否定后来的实现。

- [追问探索专题](followup-exploration.md)：本地录音、reopen 与下行注入等早期路线。
- [失败播报 guard](2026-09-06-boot1-fallback-guard.md)：文案遗漏、修正和听觉验收。
- [PCM + Mac 追问](2026-09-06-boot1-pcm-followup.md)：已验证的旧路线，现作为回退。
- [原生入口研究](2026-09-06-boot1-native-asr-research.md) → [原生追问集成](2026-09-06-boot1-native-followup.md)：ASR-only、同一上下文、提示音与自启动。

## 3. 从能对话，到播放与交接可靠

先读[对话可靠性阶段总结](2026-09-07-dialog-reliability.md)，再按症状查专题。阶段总结中的“尚未解决”属于当时版本，后续记录继续推进了其中一些问题。

| 问题 | 证据 |
|---|---|
| 续听中再次唤醒，应交还小爱 | [唤醒交接](2026-09-07-native-followup-wake-handoff.md) |
| 回答期间混入“网络异常” | [正常 Finish 被误拦截](2026-09-07-native-finish-timeout.md) |
| 下一轮回答音量改变 | [音量缓存回归](2026-09-07-followup-volume-regression.md) |
| LLM 播放期间调用原生功能 | [回调与串音](2026-09-07-playback-native-parallel.md) |
| 回声参考没有真正进入 AEC | [参考通道修复与实测](2026-09-09-parallel-wake-reference.md) |
| 独立播放器缺少原生音效初始化 | [Dirac 接入](2026-09-10-dirac-playback.md) |
| 响度与失败提示仍需对照 | [音量及失败提示记录](2026-09-10-volume-failure-gate.md) |

## 4. 从提前截断，到首轮本地判停

[2026-09-07 本地停录实验](2026-09-07-local-endpoint-experiment.md)没有形成可靠方案。后续重新区分 partial 提交、云端结束收音、噪声与真实语音，再逐步验证模型、原生入口、常驻与恢复。

进入[首轮判停专题索引](first-turn-endpoint/README.md)按阶段查证；最终日常包、失败反例、回滚、重启和冷启动证据集中在[日常验收记录](first-turn-endpoint/native-daily-20260919.md)。[历史播放卡顿](first-turn-endpoint/playback-stall-20260919.md)是独立问题，不因判停验收通过而自动解决。

## 5. 模型选择的演变

当前如何配置模型见[配置参考](../reference/configuration.md)。以下只记录各次接入与当时的验证：

- [MiniMax](2026-09-06-minimax-integration.md)、[GLM](2026-09-06-glm-integration.md)、[Kimi](2026-09-06-kimi-integration.md)。
- [默认切回 DeepSeek](2026-09-06-default-deepseek.md)。
- [DeepSeek Flash 模型名与语音链路验收](2026-09-10-deepseek-flash.md)。

## 6. 原始快照和旧代码怎么查

[2026-06-07 前的归档](../archive/2026-06-07-pre-doc-reorg/README_ARCHIVE.md)保留原始项目日志、SSH、启动和命令手册。里面的路径、镜像名、私有证据位置与阶段结论均属于当时环境，不能直接作为新设备安装命令。

| 旧路线或实验 | 保留用途 |
|---|---|
| `stream_client.sh`、`wake_monitor.sh` | 自定义 KWS 的早期链路 |
| `native_client.sh` | 原生唤醒配合本地识别的中间形态 |
| `native_*_probe.sh`、`native_*_trace.sh` | 专项实验与对照 |
| `device/pcm_tap/`、`server/followup_asr.py` | 已验证但需要 Mac ASR 的回退路线 |
| `device/endpoint_probe/` | 首轮判停共用底层实现和独立实验工具；日常启动用正式管理器 |

新增实验继续保存事实和反例。把变化后的使用方式写回相应教程或组件说明，并在状态页更新验收范围，而不是把历史记录改写成“从一开始就成功”。
