# 真实首轮判停接入：反例、开关对照与完整链路

后续已完成 [带唯一标识的重复唤醒验证](native-repeat-20260919.md)：不重启原生进程的两轮测试通过。下文保留此前阶段的单轮范围与证据。

本文件接续 `native-wake-20260919.md`。代码位于独立 worktree，尚未部署为日常功能；客户端 final-only 修正也尚未部署。模型在音箱本机运行，文本由小米云识别，没有 Mac 转写或新建外部服务。

## 先修正 3 秒等待的判断

`SYSTEM1_NATIVE_WAIT_SECONDS=3` 是客户端收到 `think` 之后的结果轮询预算，不是物理唤醒后的录音时长。首个接入试验中，StopCapture 的单调时间为 590960021 ms；保存的设备墙钟/uptime 对齐后约为 12:53:38.98，hook 的 think 约为 12:53:39.06。墙钟采样只有秒级精度、原日志毫秒也来自另一时钟，不能用这个差值声称精确的 79 ms 延迟，但能看到 think 处于收音结束附近，而不是刚刚唤醒。

因此上一阶段“延长收音必须同时扩大 3 秒轮询”的判断证据不足，不能直接改大参数。本轮保留其配置，继续观察真正的 EOF/final/think 时序。最终路由仍应只消费非空 final；现有 final-only 修正在此前回放测试中已有独立失败证据。

## 一次性控制入口

`native_wake_watch endpoint` 为模式 1，只修改 Recognize：asr.vad=false、is_using_local_vad=true、enable_natural_record_v2=false、asr.tuning_params.enable_timeout=false。保留全部原生 context、NLP/TTS 和请求 ID。模式 0 仍只观察。

`native_wake_watch endpoint-wakeup` 为后续对照模式 2：在模式 1 基础上，同时将同一真实 Wakeup 的 enable_natural_record_v2 置为 false。它不是已确认有效的修复；是否能阻止首轮额外的 StopCapture 需现场对照。

模型由试验进程预先在音箱载入。音频/提议共享文件的 nonce、owner、observer、producer、文件大小和私有权限全部检查，模型未就绪、进程不符、已有 ASR-only 会话、静音或缺少原生回调时不改 Recognize。模型只有在原生唤醒之后才能取得音频，无软件触发唤醒，也无音频替换。

执行判停前检查当前身份、同一 dialog、未 final/Finish/StopCapture、无并行 ASR-only 会话、未静音；quiet 提议必须新鲜且已处理全部已发布帧，执行前再核验。原始 PCM 原样传递一次。正常新唤醒持同一进程锁先撤销旧映射，再转交原回调。0x101 仍原样交给固件，不能因此创建新试验身份。

实验只允许服务重启后的**第一次正常唤醒、第一次 prepare 发出与收到**，并要求 pack→unpack 在 500 ms 内。两个进程各自累计全部 prepare，遇到先前请求或重复 prepare 就放弃接管，避免把内容相同的旧 prepare 当成新轮。第二次正常唤醒取消旧试验，不给下一轮重新武装。这个限制使当前入口只适用于明确的单轮测试；日常多轮运行还需设计长期请求序号同步，不能移除此限制后直接发布。

本机 quiet 可触发原有 `set_unwakeup_status` + oneshot(4)，20 秒为硬上限；模型中途失败则尝试结束仍属于自己的收音，不能把这种结束当作有效 quiet。原生本地计时读取在本轮设为 22 秒，作为控制器失效时的后备上限；owner 消失后不盲发 EOF，保留进程内的本轮计时标记，下一次 prepare/正常唤醒先清除。该 owner 崩溃路径仍缺少现场验证。没有套用纯识别会话的 SDK TTS 超时改写。

云端已经下发 StopCapture/final 时，立即撤销本地控制。CLI 只有在本机 quiet 结束、final 与 Finish 齐备且模型正常退出时才返回 0；原生自己提前结束、撞到硬上限或辅助进程异常均不能误记为成功。

## 检查与首个现场试验

136 项回归及 shell 语法通过。`test_first_endpoint` 在设备独立 ARM32 进程使用真实 JsonCpp ABI、私有测试目录和模拟音频/结束回调，验证了 JSON context/TTS 保留、PCM 原样转发、过期或落后提议拒绝、第二次正常唤醒撤销、0x101、模型失败、与 ASR-only 冲突、final、硬上限及 owner 撤销。后续补充的设备测试覆盖模式 2 的 Wakeup 修改，以及之前已有正常唤醒/prepare 时拒绝接管。测试不访问真实麦克风，不调用原生结束回调或云服务。

首个现场试验是模式 1。库 SHA256 `6ddfff2835d9212c886124953e9311da485aa62a1eff61c9a807f987986452c4`；runtime manifest `df6c3bdab10da6df96ff28b623739ea57af71b9fbbe2c7a677061f6a5d64a82c`。owner 2184，observer 2185，nonce 590938012，dialog `682aa50694fd056e08e975f3c00ebfb6`。

提示用户说“现在”，停约 1.5 秒再说“几点了”；用户回报“正常报时，没有提前回应、报错或干扰”，未单独确认停顿时长。最终文本完整，但**实际判停没有通过**：

| 项目 | 结果 |
| --- | --- |
| 正常唤醒 | 590955575 ms |
| Recognize 改写 | 590955964 ms，正确绑定当前 dialog |
| 本机语音触发 | audio 1640 ms |
| 小米 StopCapture | 590960021 ms |
| 实际输入长度 | 4080 ms / 408 帧 |
| 本机 quiet 候选/结束 | 0 次 / 0 次 |
| final | 现在几点了；ASR begin=2180 / end=4000 ms |
| Speak | 现在是中午12点53分 |
| Finish | 有；590960176 ms |
| 模型 / 试验退出码 | 0 / 1（正确标为未通过） |

ASR offset 与本机音频位置并非已校准的同一时间轴，不能用两者微小差值推导声学延迟。模型 init 1885.608 ms，CPU 998.873 ms / 4.08 秒音频（约单核 24.5%，包含起始负载），RSS 26048 KiB，最大单次推理 17.067 ms，最大积压 22 帧。这个短样本不代表稳定态资源成本。

原生事件中 Wakeup 的自然录音仍为 true，Recognize 对应字段与 VAD 为 false。partial 带 is_nlp_request=true 后出现 StopCapture，再 final 和原生回答。现阶段不能仅凭这个顺序认定是自然录音开关还是原生 NLP 抢先结束；模式 2 用来区分其中一个变量。试验后已显式恢复原服务。

私有证据：`tmp/asr-shadow-20260918/first-end-build/`。`live-first/` 保存该轮请求、指令、单调时间日志、模型输出、audit.json 与实际库；源码、实验和设备单测不等于生产验证。最初反馈的两次 LLM 播放停顿仍未调查。

## 本轮收尾及待测版本

恢复后 native_asr healthy，mipns 3268 / aivs 3206；原 client 与两个 init 的 SHA256 均与试验前一致。无观察/模型进程、试验映射、armed/state/busy 残留。已校验并移除私有运行包和独立测试可执行文件，音箱无需保留模型服务。证据 `live-first/final-status.txt`、`cleanup.txt`。

模式 2 对照版已编译并通过设备独立测试；截至本段记录，尚未进行模式 2 的现场试验，现场配合问题仍待回复。待测 probe SHA256 `7d7e442df835019d9081577cf0b00d4b60c36603a06a7762bd8eaeb1a6770f56`，watch `85157fd1ed54663d242c6acdacc8869e524ee3a0d5947631e33bfad2929f18a5`，runtime manifest 仍为 `df6c3bdab10da6df96ff28b623739ea57af71b9fbbe2c7a677061f6a5d64a82c`。下一次应重新部署整包、执行 setup，等 FIRST_ENDPOINT_READY 后才提示用户唤醒；不能在同一次服务启动里反复武装控制模式。

## 19:57 模式 2 报时对照：本地实际判停通过

使用上述原样待测产物，重新部署、重启两个原生进程，等待 NEURAL_READY 与 FIRST_ENDPOINT_READY。用户确认“按要求停顿，只说一次，正常报时且无干扰”。dialog `d575b4b4c89adf467f3e6ea271db2470`，owner 2146，observer 2147。

- Wakeup 和 Recognize 的自然录音均为 false，Recognize 的 cloud VAD 为 false、本地 VAD 标志为 true；原生 context/TTS 保留。
- 本地 quiet 候选为音频 5420 ms，实际结束为 5460 ms；单调时间 616390841 ms。模型估计语音结束 3408 ms，因此模型时间轴上的等待约 2.05 秒；这不是人工声学标注。
- final 在 616390997 ms 到达，完整“现在几点了”；原生回答“现在是傍晚7点57分”，Finish 616391231 ms。没有 StopCapture 指令。模型与试验进程均返回 0。
- helper init 1892.867 ms，CPU 1263.360 ms / 5.46 秒音频（约单核 23.1%，含起始负载），RSS 25928 KiB，最大推理 12.976 ms，最大积压 10 帧。

此对照支持“只关闭 Recognize 的设置不够，同轮 Wakeup 的自然录音设置也影响首轮结束行为”。只有一次模式 1 与一次模式 2 报时对照，不能推导所有固件或场景都由此单一因素决定。

## 19:59 模式 2 真实 LLM 链路：后半句完整进入请求和历史

再次恢复并重新 setup，保持相同产物，不改部署客户端。明确提示在完整月亮问题后停约 1.5 秒，轻声补充“请用一句话回答”。用户反馈“完整回答，播放中没有停住”；此回复没有单独确认停顿时长或只说一次，不能把提示条件全当作已验证事实。

dialog `c25cd103622ba0568fdab9cd547a8516`，owner 3784，observer 3785；客户端 session `native_first_deepseek_1789819169`。

| 环节 | 证据 |
| --- | --- |
| 本地语音结束估计 / quiet 候选 | 音频 7216 / 9220 ms |
| 本地实际结束 | 音频 9240 ms，单调时间 616510563 ms |
| 小米完整 final | 616510738 ms；问问DEEPSEEK为什么月亮有时候在白天也能看见请用一句话回答 |
| StopCapture / Finish | 无 StopCapture；Finish 616511171 ms |
| 实际 LLM 请求 | 19:59:30.430，包含上述完整文本，本 session 仅一次 |
| 会话历史 | 完整 user 一次、完整 assistant 一次 |
| 播放 | 一段，合成 attempt=1，LLM TTFT 0.64 秒，生成 0.93 秒，首声指标 3.63 秒；用户未听到停顿 |
| 收尾 | 播完后原有 native_live 追问窗口正常超时，客户端回到 IDLE |

模型 init 1900.075 ms，CPU 1917.901 ms / 9.24 秒音频（约单核 20.8%），RSS 25428 KiB，最大推理 11.688 ms，最大积压 6 帧；模型和试验进程均返回 0。partial 中先出现“问问DEEPSEEK”，随后问题正文与尾句，final 完整；这次在原有客户端上也未发生 partial 抢跑，但不能因此撤销已有独立失败证据支持的 final-only 修正。

私有证据为 `first-end-build/live-wakeup/` 与 `live-llm/`。各自的 `verified-audit.json` 核查请求字段、本地结束早于 final、没有 StopCapture、完整 final、Finish 和 helper/CLI 状态；LLM 审计按确切 session 限定范围核对请求一次和历史一次，不能把几天前相同测试句算作重复提交。最新源码全部 136 项回归及 shell 语法再次通过（48.742 秒）。

两轮后显式恢复原服务；原 client 与两个 init 哈希均不变，native_asr healthy，无实验映射、watch/helper、armed/state/busy 残留。核对运行包 manifest 和每个文件后，移除本轮 13 个命名 runtime 文件及空目录。没有把实验版安装为常驻功能。

## 已证实的方案与发布前剩余工作

通用链路为：音箱本机区分人声与静音 → 同一轮原生小米识别持续接收 → 本地确认结束后获得完整 final → 原有规则决定原生回答或转 LLM。客户端只消费 final 是另一层必要防护。无需 Mac 识别、额外外部服务、特定呼叫短语例外或额外 LLM 判句调用。

当前原型的代价约 19.34 MiB 私有运行包、25–26 MiB RSS、收音时单核约 20% CPU，以及句末约 2 秒等待。模型启动约 1.9 秒已在提示用户前完成；不能把实验预加载效果当作日常冷启动体验。生产方案应比较本机预加载的常驻内存成本与按唤醒启动的延迟、前段缓存成本。

**现在通过的是明确单轮试验，不是日常版本验收。** 不可直接去掉首次 wake/prepare 限制：先完成多轮请求归属与迟到报文隔离，再验证新唤醒打断、原生/LLM/追问交接、静音、helper 或 owner 退出、网络异常和最长收音兜底，最后整合 final-only 路由。两个现场成功样本也不代表任意停顿、噪声或轻声都不会截断。

原始播放停顿已找到独立证据，见 [播放停顿诊断](playback-stall-20260919.md)。判停模型运行结束后才播放 LLM，本轮未出现卡顿；不能把原始 TTS 问题归因于新模型。
