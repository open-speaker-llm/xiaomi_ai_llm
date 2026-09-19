# ASR-only 实验的 SDK TTS 超时

## 触发证据

20:34 的 A 现场样本 seq 33 无效。用户尝试发声时，音箱说“网络遇到问题，请稍后再试吧”，影响了内容。没有非空 ASR，不能据此说用户没有说话。详见 [A/B 记录](pair-test.md)。B 没有运行。

当轮在初始空 ASR 后约 10.0075 秒出现 SDK `50010005 TTS timeout`，SDK 清理连接、原生采集 idle，早于实验的 20 秒本地上限。关闭云端 VAD 和 `asr.tuning_params.enable_timeout` 并没有关闭这个本地 SDK 检查。错误提示本身不能证明网络故障；本次仅定位这条具体失败路径，不推断所有网络提示或播放卡顿的原因。

## 固件机制及临时调整

对已校验 SHA256 为 `21656da7ab6029e046e378270d7841629babc4d5b941ed27774bc25266678eda` 的 SDK 离线反汇编：TTS 超时分支在 `0xdf880` 调用 `AivsConfig::getInteger(Tts::RECV_TIMEOUT, out)`，返回地址为 `0xdf884`，随后将秒数乘 1000 与内部时间戳比较。汇编的缺省值为 5，本机此次实际读到配置值 10；不能把 10 秒泛化成所有固件的固定值。

主动实验构建新增 getter 包装：先调用原函数，仅当键、调用位置、当前 ASR-only 租约 sequence/owner、BOUND/RESULT 状态、非空 dialog、原生进程及截止时间都匹配时，将正数且小于 30 的返回值提高至 30 秒。保持原返回成功标志；零、负数和更长值不变。不写配置、不修改固件结构或代码，不影响非主动构建。租约最长 25 秒，真实唤醒交接、完成、失效或移除 armed 后不再覆盖。

**隔离边界：** getter 没有 dialog 参数，因此只证明“特定调用点＋专属测试租约”范围，没有证明 SDK 内部各 EventWrapper 的独立隔离。只能在设备空闲、单一 ASR-only 实验中使用，不能直接推广到并发原生对话。

第一版 `504f1a78…` 没有生效，seq 35 仍超时。诊断版 `ef99d77a…` 的 seq 36 确认实际命中 `0xdf884`，返回值 10，但键对象地址不匹配。原因是主程序对 `Tts::RECV_TIMEOUT` 有 `R_ARM_COPY`（`0x85f28`）；必须通过 `RTLD_DEFAULT` 找到实际全局对象，而非 `RTLD_NEXT` 找到 SDK 自身存储。最终版删去广泛 getter 日志，仅在覆盖成功时按线程/sequence 记一条证据。

## 同音频对照

使用已有 `protocol/live.pcm`（7.3 秒），前置 11 秒零 PCM，总长 18.3 秒、585600 字节。全部在音箱回放并由小米识别；没有保存新麦克风音频，没有 Mac ASR，没有新增服务或调用 LLM。模式 3 固定在回放结束 300 ms 后沿原生路径发送 EOF，用于单独检验 SDK 计时，不作为自动判停测试。

| 条件 | seq / 目录 | 结果 |
| --- | --- | --- |
| 原主动探针 `e27f86ba…` | 34 / `trial.delay.3.FxDcrD` | 约 10 秒 TTS timeout，未回放完，无 final/Finish，CLI 124 |
| 最终 getter 调整 | 37 / `trial.delay.3.Dsoq7j` | 完整回放、EOF、final/Finish，CLI 0；EOF 到 final 177 ms |
| 正常问题、模式 4 自动判停 | 38 / `trial.normal.4.aDBVHf` | quiet，音频 7850 ms、最后确认语音 5850 ms；EOF 到 final 135 ms，CLI 0 |

seq 37 返回“播放DEEPSEEK为什么月亮有时候白天也能看见请用一句话回答”，问句后半段完整。此处只核对旧录音内容保留与会话正常结束，不宣称所有词逐字识别正确。seq 38 返回“问问DEEPSEEK为什么月亮有时候在白天也能看见请用一句话回答”。两轮都有 native_s=10、experiment_s=30、caller=0xdf884 的命中日志，无 TTS timeout。

最终实验库 SHA256：`ff7df7e73225b70686791e6de5771a7b0efdce421c3bfabd34ef0da722934bd7`。独立设备 C 测试覆盖 owner/sequence、各阶段、截止、进程、键前的租约条件及保留禁用/更长超时值；实际回放验证了键对象与调用点匹配。122 项 Python 回归和 shell 语法检查通过。中间构建、反汇编、逐轮日志在主项目忽略目录 `tmp/asr-shadow-20260918/`，不提交语音及云端日志。

## 恢复与后续边界

结束后主动恢复。两份 init 哈希与 before 相同，客户端 SHA256 仍为 `70a7012f2c68c7ebc8e545d9481845068406a476dc4cff7e68808fe671f8f184`；进程不再加载实验库，armed/timer/busy 均不存在，native_asr healthy。证据 `sdk-timeout-restore.txt`。

这次没有部署到普通唤醒首轮。现场 A/B 仍需重新验证，重复文本来源、真实输入的开始资格和句末等待、生产对话隔离及两次播放停顿原因均未因此解决。30 秒仅是高于当前 25 秒租约的实验超时保护，不是让用户每次等 30 秒，也不是最终产品阈值。

后续 22:44–22:45 已完成现场 A/B：两轮完整、无超时，B 保留用户确认的停顿后半句，本轮没有串轮。A 句末仍有额外等待，之前重复的根因仍未确定。完整结果及恢复证据见 [现场复测](pair-test.md)。

2026-09-19 后续发现：解析 Finish 不等于 SDK 已从队列处理 Finish。原 guard 在 COMPLETE/IDLE 立即撤销，会在最后 partial 已超过 10 秒的长尾样本中重新触发超时。已将正常完成的排空阶段纳入原有有效租约范围，不延长截止时间；两个针对性旧音频回放验证 SDK 正常处理 Finish。详见 [结束竞态修正](contrast-20260919.md)。
