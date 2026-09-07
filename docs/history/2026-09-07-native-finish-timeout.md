# LLM 播放期间小爱误报网络异常

## 原因与证据

用户反馈 2026-09-07 晚上播放人工智能解释时，混入小爱“网络异常”语音。

- 21:42:26.217，原生追问 `aa999f7c948eb1d3105d4cafdc81ac89` 已正常收到 final；该轮是 ASR-only，请求禁用 NLP/TTS。
- 组件收到 Finish 并发布 COMPLETE，但原生 SDK 日志缺失这一轮的 `client start process Dialog.Finish` 和会话清理。
- 21:42:26.750，客户端开始 LLM 第二轮，解释超级人工智能 ASI，分句合成全部成功，持续播放至 21:43:11。
- 21:42:36.229，同一原生 dialog 出现 `50010005 / TTS timeout`。SDK 主动清理并重连，随后 qplayer 开始本地提示音播放。

根因是上一轮真实唤醒交接修复扩大了旧指令过滤范围。固件对 Finish 有多次解析：第一次解析已更新 COMPLETE，后续解析时本地状态不再 active，或 CLI 已消费并置回 IDLE，于是被错误拒绝。SDK 未收到正常结束通知，仍等待本应禁用的 TTS，十秒后误报。此次不能据提示文案判断为 Wi-Fi 或 LLM 网络故障。

证据快照：本机 `/private/tmp/xiaomi-network-prompt-20260907/`，包括系统日志、客户端日志、ASR 组件日志及修复前后回归测试结果。

## 修复与边界

仅对同一 dialog、final/finished 均已记录、phase 为 COMPLETE 或 IDLE 的正常结束通知，允许再次送达原生 SDK。放行不修改共享文本和控制状态。

HANDOFF、FAILED、被新会话取代等情况仍隔离旧 Finish；旧 StopCapture、Abort、Speak、家居动作不因该例外放行。没有全局静音或屏蔽真正网络故障的提示。

## 验证

- 设备独立测试先复现第二次 Finish 被拒绝的断言失败，修复后通过。
- 覆盖 COMPLETE、CLI 消费后的 IDLE、已有 completed 标记的 HANDOFF、新 dialog 替代等边界。
- 87 项本地测试及 shell 语法检查通过。
- 设备 JsonCpp ABI、动作隔离、旧文本隔离及 15 项提示音隔离测试通过。
- 新 `native_asr.so` SHA-256：`1417d670342a2ed237aea0e0caba740a96e19ad524f131d7e73d63c1b9086cc2`。

21:48 已安装到音箱并恢复 healthy；备份为 `/data/native-asr-backup-20260907-214818/restore.sh`。

真实语音复测：

- 21:50:17，追问“A GI是什么”：组件记录 `finish replay permitted`，原生 SDK 记录 `clear speech event id 2165ca00a32dbc00306342dc2941a25a` 和 `Dialog.Finish done`。
- 21:50:57，追问“超级人工智能是什么”：相同结束处理正常，长回答完整播放至 21:51:29。
- 21:51:34，继续追问“什么时候能实现”：保持原 LLM session，结束通知正常送达，后续播放已超过原来的十秒故障点。
- 从安装后至 21:51:43 的系统日志中，没有新的 `50010005`、`TTS timeout` 或 qplayer 异常提示音播放记录。用户随后确认复测“没有再出现”，听觉结果与日志一致。

本轮只新增原生 ASR 组件中的正常结束通知例外及回归测试，保留已通过用户实测的真实唤醒交接。所有改动仍在隔离 worktree，尚未提交或合并 main。
