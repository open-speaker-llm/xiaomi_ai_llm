# 真实唤醒首轮：请求归属接入前检查

这是 seq 48 独立神经网络判停成功后的下一阶段。尚未将神经网络用于真实唤醒首轮，也未部署客户端 final-only 修改。此阶段保留原生 ASR/NLP/TTS、云端 VAD 和原有路由，只检查首轮的关联方法。Mac 不识别文本，没有新增外部服务。

## 原生对照

2026-09-19 12:22，dialog `ec6421d279aab229ac46f2034b48a63a`：用户真实唤醒后问“现在几点了”，final 完整，小米 Speak 为“现在是中午12点22分”，有 Dialog.Finish。用户反馈无报错、无干扰。

Wakeup、WakeupStreamFinished、Recognize、RecognizeStreamFinished 使用同一 header.id。Wakeup.type=wakeup_real，Recognize 保持 asr.vad=true、enable_natural_record_v2=true，context 没有关闭 NLP/TTS 的 RequestControl。原生理解在 partial 中可带 is_nlp_request=true，随后仍有 final；这个标志不能代替 final 作为完整问题提交条件。

客户端 boot1 默认结果轮询预算为 3 秒，按 ticks 而非严格墙钟执行；“未拿到新结果”不等于原生报时失败。后续对齐时间轴确认，这个预算从 think 开始，并非从物理唤醒开始，因此本阶段关于“延长录音必须扩大等待”的初步判断证据不足。参数未修改，纠正与下一轮实测见 [首轮判停接入](native-first-endpoint-20260919.md)。

## 只观察探针

`native_wake_probe.c` 包含现有 native_asr 实现并包装原生唤醒、protobuf pack/unpack、JSON 序列化。不调用结束回调，不采集/保存 PCM，不运行模型，不改 JSON 或 activate_mode，不写 LLM 历史。`native_wake_watch` 只创建 45 秒的私有 metadata 状态文件，实际麦克风由用户正常唤醒启动。

临时 init overlay 使用原服务的 preload 位置，校验四项固件 SHA256，安装前启动五分钟恢复定时器。试验后显式恢复，并复核原 init/client hashes 与进程 maps。独立目录 `/tmp/xiaomi_native_wake_probe` 不复用独立 ASR 会话的 control 文件。

状态关联为：正常回调 → 256 字节以内的精确 prepare 包 → 同线程处理该包时生成的真实 Wakeup.id → 后续相同 ID 的 Recognize。包按字节匹配，不只比较弱散列。owner、deadline、producer、consumer 均检查；第二个正常唤醒作废旧轮，不自动认领下一轮。**这些检查目前只支持观测，不构成执行结束回调的授权**。尚未验证新唤醒竞态、静音、进程退出和与连续追问并发时的实际控制策略。

首次观测库 SHA256 `3df546d5a296fd14d5e8e727a579d59c5b6ed032e0dd104310787c82a13f4bb1`：

- 12:30，dialog `339b34196639e5e7ab0111557c21aaae`，原生 final“现在几点了”，Speak“现在是中午12点30分”，有 Finish；用户确认正常报时、无报错或干扰。
- probe owner 3615；mipns 3440 在 589540511 ms 收到回调，33 ms 后记录 10 字节 prepare，aivs 3376 再过 1 ms 收到同包。
- 该版本尝试在 prepare 的线程上下文里直接绑定 Recognize，没有成功；589542930 ms 又收到低字节为 1 的回调，观察器按过宽规则取消，exit=1。这是**绑定失败**，不能记为首轮接入成功，也不能推断用户说了两次。
- 已有固件研究 `docs/history/2026-09-06-boot1-native-asr-research.md` 记录正常 0x1 与附加 0x101 的区别；首次探针没有记录完整事件码，故不能把它的第二条回调确定为 0x101。

修正的观察版记录完整 code，正常唤醒仅用 code==1；其他回调仍原样转发。先在 prepare scope 绑定 Wakeup，再依同一 ID 关联 Recognize，允许两者由不同消息/线程产生。对附加回调的忽略仅用于只读身份观察；未来控制版遇到异常事件如何回退仍须单独验证。

136 项完整回归与 shell 语法通过；改进关联后的定向测试另行通过，覆盖错误进程/包/ID、重复绑定、第二次正常唤醒作废、附加回调不被当成新正常唤醒、过期、非私有/截断/符号链接状态文件。没有将单元测试当作设备控制验证。

证据位于忽略目录 `tmp/asr-shadow-20260918/neural-vad/native-wake-baseline/`，包括原生对照 JSON、两类日志、首次探针库、watch 输出、回归输出与恢复检查。

## 修正版现场验证

12:34，用户确认只唤醒一次、只问一次，正常报时且没有报错或干扰。库 SHA256 `1068afceec737c6775fedb433d17405740d2796d166797fa1cfe8160f577a09a`，watch SHA256 `179ebaf91f6d8a55310cee6abc23eb30cdfdd648f253e9bd5f46e864216b3145`。

owner 1865、mipns 1620、aivs 1535，dialog `ed08690370fddcff943e0d9ff6e451a5`：

| 单调时间 ms | 事件 |
| --- | --- |
| 589803559 | 正常回调 code=1，angle=90 |
| 589803583 | 原生 prepare 打包，10 字节 |
| 589803584 | AIVS 收到相同 prepare |
| 589803585 | Wakeup 序列化，scope=1，绑定该 dialog |
| 589803984 | Recognize 序列化，scope=0，相同 dialog 关联成功 |
| 589805945 | 附加回调 code=257（0x101），angle=0；观察身份仍为 BOUND |

这证明 Recognize 已不在 prepare 的处理上下文内；仅凭现有日志不能进一步断言一定换了线程。修正版不依赖这两步在同一线程。

watch 在 45 秒到期后 exit=0。final 为“现在几点了”，Speak“现在是中午12点34分”，有 Finish；原生请求仍 vad=true / natural_record_v2=true，没有 NLP/TTS disabled。此次仍未运行 VAD 模型或改变收音结束位置。

下一步控制版仍需补齐：模型提前就绪门槛、只改当前请求的收音参数、同一首轮的音频与控制绑定、结束前二次验证、异常回调/新唤醒回退，以及客户端等待 final 的有界处理。prepare 包可能在不同轮次内容相同；本轮单会话按字节匹配成功**不能排除延迟旧包或并发唤醒误绑**，不能直接把观察结果作为执行 EOF 的许可。现有 ASR-only SDK 超时保护也不能原样扩到并行的原生 NLP/TTS 请求。

两次临时观察之后均显式恢复原服务。最终检查须确认 native_asr healthy、原 client/init hashes 不变、native-wake.state/timer.armed/busy 无残留、原生进程未映射观察库。问题 2 的 LLM 播放停顿仍未调查。
