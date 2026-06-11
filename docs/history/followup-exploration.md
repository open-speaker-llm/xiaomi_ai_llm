# 原生追问探索记录

文档类型：历史探索结论  
适用范围：判断“连续追问到底试过哪些方向”  
当前结论：免唤醒追问在 boot1 未解决。原生 ExpectSpeech 多轮机制已摸清，但触发权在云端、设备端用不上；各设备端主动开麦手段（oneshot/event_notify/continuous reopen）已用对照实验确认不通。未尽方向是 `speech.usock` 干净音频。

## 1. 背景

理想追问体验是：

```text
小爱同学，呼叫 DeepSeek
LLM 回答：我在，有什么可以帮你
用户不用再说“小爱同学”，直接追问
追问文本进入同一个 LLM session
```

本项目先尝试过两类方案：

- 本地录音 + ASR：音箱录追问音频，再用小米 ai_service 或 Mac Whisper 识别。
- 原生 reopen：尝试让小米原生链路在 LLM 播放后重新开麦，直接拿原生 ASR 文本。

## 2. 已验证的问题

本地录音方案的问题：

- 多麦克风原始录音容易录到弱声、噪声或 LLM 尾音。
- boot1 上真实麦克风设备可能被 `mipns-xiaomi` 占用。
- 临时暂停/重启 `mipns-xiaomi` 会影响后续原生唤醒或 NLP。
- Mac Whisper 能识别一些录音，但稳定性不如小米原生 ASR。

原生 reopen 方案尝试过：

- `pnshelper event_notify` event=4 `pre_multirounds`
- `pnshelper event_notify` event=6
- `wakeup.sh multirounds`
- `pns + wakeup`
- `pns6 + wakeup`
- `oneshot_set open=true`
- LLM 播放前触发
- LLM 播放结束后触发

结果：

- `instruction.log` 只保留首轮“呼叫 DeepSeek”的 dialog。
- 追问时没有新的 `SpeechRecognizer/RecognizeResult`。
- 没有稳定拿到原生追问文本。

## 3. 当前策略

boot0：

- 可以继续保留本地录音追问作为实验功能。
- 修改前要跑人工追问用例。

boot1：

- 默认关闭追问。
- 优先保证原生命令和首轮 LLM 稳定。

配置：

```sh
SYSTEM1_FOLLOWUP_ENABLED=0
FOLLOWUP_MODE=local_record
```

## 4. 更值得继续的方向

优先探索“获取小米处理后的干净音频”：

- 曾观察到 `/tmp/mipns/usock/speech.usock` 里存在可解析的 16kHz mono PCM 数据。
- 这条链路可能已经经过小米前端处理，比直接多麦克风录音更适合作 ASR。
- 如果能稳定抽取，就可以减少 VAD/多麦克风通道选择问题。

暂不优先继续：

- 只靠调 VAD 阈值解决追问。
- 继续猜测 `pnshelper` reopen 事件。
- 在 boot1 上强杀/暂停 `mipns-xiaomi` 来抢麦克风。

## 5. 2026-06-11 boot1 系统性复查（AVS / mico_aivs_lab）

这次切到 boot1/system1（2023 ROM），逆向 `mico_aivs_lab` 并用**对照实验**重新验证设备端开麦手段。结论：免唤醒追问在 boot1 仍未解决，但把“哪些路不通、为什么不通”查清楚了（之前第 2 节只是“没拿到文本”，这次是严谨证伪）。

### 5.1 摸清的机制

- boot1 的 aivs 是标准 **AVS 协议**实现，`SpeechRecognizer` 命名空间下有 `Recognize`、`ExpectSpeech`、`RecognizeResult`、`StopCapture`。
- 追问 ASR 文本会写入 `/tmp/mico_aivs_lab/instruction.log` 的 `RecognizeResult`（明文 / `\u` 混合），可读，**不需要自己录音/ASR**。
- **ExpectSpeech 多轮确实工作**：原生 NLP 需要追问时（如“设闹钟”→反问“几点”），云端下发 `ExpectSpeech`，设备自动 reopen mic，用户免唤醒说的话被准确识别（实测“明天早上 7 点”）。
- `/data/mipns/dialog_continuous` = `on`，mipns 二进制有 `continuous dialog, reopen mic` 逻辑。

### 5.2 设备端主动开麦——对照实验确认不通

根本约束：**ExpectSpeech 由云端 NLP 决定，设备端无法主动触发**；LLM fallback 不经过云端 NLP，拿不到 ExpectSpeech。试过的设备端“主动开麦”手段：

| 手段 | 结果 |
|---|---|
| `pnshelper oneshot_set open=true` | 固件 `mipns::notify` 明确打印 `oneshot open not support` |
| `pnshelper event_notify {src:3,event:6}`（原生触发 multirounds 的真实调用） | **安静对照 + 无关词探针**确认不能开麦：触发后保持安静则无任何新会话；之前疑似的“新 dialog”是用户说话 / 上一轮 TTS 回声造成的假象 |
| `mibrain aivs_event_post`（Recognize / ExpectSpeech / SynchronizeState） | 一律 `code:1` 拒绝（payload 格式未深挖） |
| 普通问答后的 continuous reopen（非 ExpectSpeech 场景） | 用户主导节奏的干净测试下不自动续听 |

### 5.3 未尽方向（未验证，非“有希望”）

- `/tmp/mico_aivs_lab/usock/speech.usock`：boot1 上确实存在（boot0 没有），疑似 mipns→aivs 的处理后音频流。若 idle 时持续有 PCM，可“搭车”读它做 VAD+ASR，绕开抢麦。**有破坏原生链路风险，未验证**。
- `aivs_event_post` 的正确 payload（dialogRequestId / profile 等）。

### 5.4 方法教训

这次探索多次因单次实验就下结论而反复横跳（“铁证”→“翻盘”→“证伪”）。可靠做法：

- 不要用 `instruction.log` 的识别**内容**判断 mic 是否开（受说话时机、回声、误识别污染）；用“空 `RecognizeResult` + 新 dialog_id + 无 wakeup 事件 + 对照组”交叉判断。
- 每个结论要**对照 + 重复**，不是单次。**安静对照**（用户不说话看是否仍有反应）是区分“真开麦”和“回声/误触发”最干净的一刀。
- 现场交互实验的主要噪声源是时序对齐（用户是否在捕获窗口里说话）。让用户主导节奏、直接看持久日志，比脚本掐倒计时窗口可靠。

