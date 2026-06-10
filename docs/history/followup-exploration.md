# 原生追问探索记录

文档类型：历史探索结论  
适用范围：判断“连续追问到底试过哪些方向”  
当前结论：原生 ASR reopen 尚未打通，下一阶段更值得探索干净音频获取

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

