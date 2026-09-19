# 完成状态约束与自动接续现场验证

接续 [多轮身份隔离](native-repeat-20260919.md)。本轮临时运行 worktree 客户端，完成了“LLM 首轮 → 播放 → 免唤醒追问静默结束 → 新真实唤醒”的自动接续试验。未修改 `/data` 客户端或开机配置，试验后已恢复日常版本。

## 为什么 final 仍然不够

云端 final 只代表这次输入结束后得到的最终识别文本。设备达到录音上限、模型失败或控制器退出时，也可能通过强制 EOF 得到残句 final。仅在 CLI 标失败，无法阻止另一个客户端进程把残句送入 LLM。

新增 `native_route.h`，在实际修改 Recognize 之前，为精确 dialog 创建 `pending` 记录。记录包含 owner、nonce、随机标识和状态，不含文本。不能安全建立记录就放弃这次 Recognize 改写。watcher 只有在身份/租约仍有效、正常 quiet 结束、非失败、收到 final 与 Finish、helper 正常退出后，才能原子替换成 `quiet`；明确失败写成 `failed`。进程死亡留下 `pending`，不能被当成成功。

客户端在提取 query、识别触发词或失败回答之前检查该记录：受控 dialog 只有格式完整的 `quiet` 加非空 final 才允许路由。pending、failed、损坏记录、符号链接和多余内容均拒绝，仍保留对后续完整结果轮询的机会。不属于实验的原生和 ASR-only dialog 保持原路由。失败记录不随 watcher 退出删除，避免清理后误被当成未受控请求。

记录目录私有，拒绝非法 dialog 文件名；最多 256 条，达到上限就拒绝新接管，不自动淘汰尚未消费的失败证据。这是有界实验机制，日常版本仍需设计记录保留与消费策略。

## 自动就绪与播放交接

模型预加载约两秒，在此期间上一轮可能刚开始 LLM 播放。因此 watcher 在发布 READY 前，再次检查原生进程身份、ASR-only 占用、busy 与静音。正常忙碌返回 3，自动 session 等待后重试，不消费试验轮数；总时限仍生效。实际唤醒认领处也检查 busy，减少 READY 后交接竞态。

## 验证

先在旧实现重放 pending/failed final，得到两项失败；修正后全部 146 项主机回归及 shell 语法通过（52.583 秒）。独立 ARM32 设备测试再次通过，覆盖 journal 生命周期、错误身份、失败不可晋升、未完成/上限/撤销拒绝、目录与符号链接，以及已有的原生 JSON、原样 PCM、提议时效和带标识 IPC 用例。自动 session 测试增加忙碌一次后重试成功用例。

本轮实际构建：

- probe SHA256：`0ad8dab879cef56b4b1e59691cc12471c19dcd1796d3fee0ffd456fdc74d3138`
- watch SHA256：`31cd890ea998a162d73639a32b4b330347c5160851c066676adf659eefb1152e`
- 临时 client SHA256：`c88cfc80aa33df3ac1868c35e8136fe41ac53231bb0ffbb82b500603373f0013`
- runtime manifest：`df6c3bdab10da6df96ff28b623739ea57af71b9fbbe2c7a677061f6a5d64a82c`

### 20:26–20:27 真实自动两轮

运行 `run_native_wake_session.sh 2 180`，每轮均等 READY 后才提示用户。原生进程始终 mipns 391 / aivs 328，轮间没有重启。

| 项目 | A：LLM | B：原生报时 |
| --- | --- | --- |
| dialog | 96f18718f2361e7ff8042238d6168723 | aab35a781b6539538619c14f207eb956 |
| owner | 560 | 1922 |
| 实际 quiet EOF 音频位置 | 9060 ms | 6240 ms |
| 最终文本 | 问问DEEPSEEK为什么月亮有时候在白天能看见请用一句话回答 | 现在几点了 |
| 结果 | 一次 LLM 请求，一对历史记录 | 原生回答“现在是晚上8点27分” |
| final / Finish / helper / route | 全部成功 | 全部成功 |

两轮均收到 38 字节带标识 prepare，quiet EOF 早于 final，无 StopCapture。A 中约 1.5 秒停顿后的轻声尾句保留；原句中的“也”未出现在识别结果，不能说逐字完全一致。用户确认两轮按要求完成，回答正常，没有卡顿或干扰。

A 之后自动加载下一轮时，实际遇到播放 busy：owner 799 的 helper 被正常取消、watch 返回 3，未发布 READY。播放器结束后进入 ASR-only 追问，dialog `864a0b9cf70fd86c4cfac9fd4eac8473`，静默结束得到空 final，没有 LLM 请求，也没有首轮 route 记录。20:26:50 回到 IDLE，控制器自动重试并发布 B 的 READY。session 最终 `attempted=2 passed=2 consecutive_failed=0 expired=0 interrupted=0`。

B 客户端日志显示“3s 未拿到新结果，暂不 fallback”，这是原生成功回答没有交给 LLM 的既有路径；完整 final、原生 Speak、Finish 与用户正常报时反馈均已核对，不能把这条日志单独当成识别失败。

私有证据在 `tmp/asr-shadow-20260918/route-build/`：`live-session.txt`、`live/audit.json`、客户端与原生时间线、历史、恢复记录和设备测试。原生 instruction/event 日志随新请求轮换，最终快照只有 B；A 的文本用客户端和历史交叉核对，final/Finish 时序来自持续时间线。没有保存此次麦克风 PCM。

## 恢复与边界

外层临时 runner 从 `/tmp` 启动客户端，设有 480 秒令牌绑定恢复；原生 probe 另有 300 秒恢复。本轮显式先撤 probe，再恢复 `/data/native_first_client.sh`。已验证 client 与两个 init 脚本哈希不变、native_asr healthy、没有实验映射/watch/helper/state/armed/busy/session.lock 残留。运行包按 manifest 校验后逐项删除，测试可执行文件已删除；少量 route 记录保留为状态证据，不含文本。

当前证明两轮正常自动接续与独立故障用例。还未现场验收静音、抢占、模型/owner 中途退出、网络超时，也未解决常驻预加载和 journal 生命周期。约 25 MiB 模型 RSS、两秒预加载和句末约两秒等待仍需纳入日常版设计；当前脚本没有设为常驻。

ASR 继续使用小米，判停在音箱，无新增 Mac 识别服务。两次历史播放停顿的 [TTS 重试问题](playback-stall-20260919.md) 未在本轮修改；一次播放顺畅不能证明已修复。
