# 原生追问探索记录

文档类型：历史探索结论  
适用范围：判断“连续追问到底试过哪些方向”  
当前结论：
- **文件式原生 ASR（`ai_service asr_audio`）在 boot0 可用、在 boot1 不支持**（§6.2 + §10 实测勘误）。boot0 追问就靠它，是工作路径，不要删。
- **“无唤醒词追问”（不靠录音、让原生链路重新开麦）在两个 ROM 都不可达**——开麦与云端 ASR 编排由 aivs/mipns 按云端指令掌控，本地中间人改写下行流也被 aivs 权威状态否决（§8.4）。
- 摸清的机制与对照证伪见 §5–§10。

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

## 6. 2026-06-12 现场复核（boot1，固件 1.54.x）

本轮直接在设备上 strace + 读 syslog 复核了几条关键路径，得到确定结论。

### 6.1 链路拓扑确认

`mipns-xiaomi`（前端，启动参数 `-r opus32`，做唤醒/AEC/波束）把处理后的音频通过 **Unix DGRAM 套接字** sendto 给 `mico_aivs_lab`（云 ASR 上传客户端）：

```text
mipns-xiaomi(pid)  --DGRAM-->  /tmp/mico_aivs_lab/usock/speech.usock  -->  mico_aivs_lab(pid)
```

两端各自 bind 一个 `speech.usock`（`/tmp/mipns/usock/` 与 `/tmp/mico_aivs_lab/usock/`）。干净的前端音频在这条链路上，是“获取小米处理后干净音频”的抓取点。

原生 ASR 的最终文本以 `RecognizeResult`（`namespace:SpeechRecognizer`）事件落在 `/tmp/mico_aivs_lab/instruction.log`，质量与原生一致。

### 6.2 `mibrain ai_service` 文件式 ASR 在 **boot1 不支持**（boot0 支持，见 §10 勘误）

> ⚠️ 重要勘误：本节最初写成“被固件硬拒、`transcribe_followup_voice_native` 是无效代码”，**这只对 boot1 成立**。2026-06-13 在 boot0 实测该接口完全可用（§10）。**boot0 追问就靠它，不要删。**

仓库里 `native_first_client.sh` 的 `transcribe_followup_voice_native()` 用
`ubus call mibrain ai_service '{"asr":1,"asr_audio":"/tmp/voice.wav",...}'`
把录音文件交给小米原生 ASR。**在 boot1（system1，2023 ROM）上走不通**：

- 任何带 `asr=1` + `asr_audio=<文件>` 的调用都返回 `{"code":-1,"info":"{ }"}`。
- strace 显示 boot1 的 mibrain **根本没 open 那个文件**就返回了。
- syslog（`/var/log/messages`）里 boot1 mibrain 打出 `enter aivs asr req process!` → `aivs asr req not support!`。
- boot1 二进制字符串：`aivs asr req not support!`（给了文件——boot1 固件未实现文件式 ASR）。

但 **boot0（system0，2019 ROM）的 mibrain 是另一套二进制**，有 `enter mibrain ai service asr audio fill!` 正向路径、**没有** `aivs asr req not support!`，实测返回 `code:0` + 正确 `query`（§10）。所以这是**按 ROM 区分**的能力，不是普遍死路。

### 6.3 `ai_service` 的 NLP 入口反而可用（附带能力）

同一个 `ai_service` 方法，**纯文本进 NLP** 是工作的：

```sh
ubus call mibrain ai_service '{"asr":0,"nlp":1,"nlp_text":"今天天气怎么样",...}'
# -> {"code":0,"info":"{ \"dialog_id\": \"...\" }"}
```

即可以不说话、直接把文本喂给小米原生 NLP（天气/闹钟/家电等原生 domain）。这是一条独立于追问的潜在能力（把文本路由回原生处理），与本文档主题分开记录即可。

### 6.4 重开麦是 mipns 内部状态机，外部脚本触发不了

- `wakeup.sh multirounds` 只是**反馈**（播 `multirounds_tone.opus` + `player_wakeup multistart` 亮灯），不是触发器；它是 mipns 决定 multirounds 之后才被调用。
- mipns 内部状态机字符串显示成功路径是 `local multirounds, idle ---> preparing!` → `continuous dialog, reopen mic`，但有大量 ignore 条件（mute / preparing / transmitting / unregistered…）。
- 关键阻断：`aivs dialog finish when idle, clear multirounds flag!` —— 一旦原生 dialog 结束、mipns 回到 idle，multirounds flag 就被清掉。我们的 fallback 是在原生播完“被你问住了”（`Finish/Dialog`）之后才有机会触发，此时已 idle，必然被忽略。这解释了历史上 `event_notify 4/6`、`oneshot_set` 等尝试全部无效。
- 本机 `pnshelper oneshot_get` 返回 `open:false`，且 mipns 有字符串 `oneshot open not support` —— oneshot 在该机型不支持。

### 6.5 下一步最值得试的新线索：`aivs_event_post`

`ubus -v list mibrain` 暴露了
`aivs_event_post {"namespace":String,"name":String,"payload":String}`。
它能直接往 AIVS 注入事件，字段结构与 `instruction.log` 的事件一致。推测可用它注入一个“继续对话 / ExpectSpeech”类事件，从云/dialog 状态那一侧驱动 mipns 重开麦——这比从 `pnshelper` 那侧猜 reopen 更接近原生连续对话的真实机制。

注意：注入事件会直接搅动正在运行的原生 dialog 状态机，需在能现场观察音箱、且 `native_first_client.sh` 可随时重启的交互式会话里做，不要在无人值守时盲试。

### 6.6 调试备忘

- mibrain/aivs 的内部日志走 syslog-ng，落地在 `/var/log/messages`；调试时 `grep -i mibrain /var/log/messages` 即可，比 strace 省事。注意 mipns 的 `[I]` info 级日志（含 `expect speech`）**不进** `/var/log/messages`，只有 `[W]/[E]` 进；要看 info 行得 strace。
- 设备 SSH（boot1，dropbear 只认 ssh-rsa）：
  ```sh
  ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa root@192.168.8.152
  ```

## 7. 2026-06-12 第二轮：解码 mipns↔aivs 协议并注入 ExpectSpeech

承接 §6.4/§6.5，本轮放弃 `pnshelper`/`aivs_event_post` 两条路（理由见下），改为直接逆向 `mipns` 与 `mico_aivs_lab` 之间的本地协议，并实测注入。

### 7.1 否定 pnshelper event_notify 路径（确定）

strace 对照 pns→mipns 的 fifo（`/tmp/mipns/pnshelper.fifo`）发现：`ubus call pnshelper event_notify {src:3,event:4,detail:pre_multirounds}` 会让 pns 写出一条 fifo 消息，但 mipns 收到后报 **`unexpected event type: 6!`**。扫描 event=0..11 得到 pns→mipns 的 type 映射（3/6/7/8/9/14…），其中**没有一个**是 mipns 的 multirounds/开麦信号。结论：`pnshelper event_notify` 这个接口从设计上就触发不了重开麦，历史上的 `event=4/6` 尝试是在敲错的门。

`aivs_event_post` 也排除：它是 **upward**（设备→云上报）消息，而 `ExpectSpeech` 是 **downward**（云→设备）directive，方向相反，注入不了。

### 7.2 mipns↔aivs 本地协议（speech.usock，protobuf）

拓扑：`mipns-xiaomi` bind `/tmp/mipns/usock/speech.usock`（收 **downward**），`mico_aivs_lab` bind `/tmp/mico_aivs_lab/usock/speech.usock`（收 **upward/音频**）。downward 消息是 protobuf：

```
\x08\x01 \x1a<len> \x08<TYPE> \x12\x20<32字节 dialog_id(ASCII hex)> [尾部]
         └─内层msg─ └类型     └─dialog_id───────────────────────┘
```

strace 抓真实一轮对话 + 对照 `instruction.log` 锚定的 TYPE：

| TYPE | 含义 | 长度/尾部 |
|---|---|---|
| 0x01 | 对话/prepare 开始 | 44B，尾 `\x1a\x02\x08\x01` |
| 0x07 | asr partial（识别中间结果） | 46B，尾 `\x2a\x04\x08\x00\x10<offset>` |
| 0x02 | **ExpectSpeech（开麦听追问）** | 40B，纯 type+dialog_id，无参数 |
| 0x04 | asr timeout | 40B |
| 0x05 | Dialog.Finish | 48B，尾 `\x32\x06...` |

### 7.3 注入工具

设备是 **aarch64**，无 python/perl/lua/gcc/socat，`nc` 不支持 `-U`。用 Mac 上 `zig cc -target aarch64-linux-musl -static` 交叉编译了一个 ~30 行的 `usock_send <path> <hex>`（sendto unix DGRAM），连同 `inject_expectspeech.sh` 持久化在设备 **`/data/followup_probe/`**。`usock_send` 已验证能把消息送达 mipns（mipns 的 `recvfrom(8)` 确实读到）。

### 7.4 实测结论：从 mipns 侧注入 ExpectSpeech 无效

- **idle 注入**：把 0x02 ExpectSpeech 发给 idle 的 mipns，mipns 收到但无任何动作（无开麦、无 sendto aivs）。印证 §6.4 的“idle 忽略继续信号”。
- **对话中注入**：`inject_expectspeech.sh` 监控 `instruction.log`，在某轮 `FinishSpeakStream` 瞬间为该 dialog 注入 0x02。结果——注入成功送达，但紧接着 **`Dialog.Finish` 照常发生**，mipns 未重开麦，第二句（无唤醒词）未产生任何 `RecognizeResult`。

**根因**：`Dialog.Finish`（0x05）是 **aivs 主动发**的，是否继续对话由**云端 NLP 响应**决定。从 mipns 侧注入 ExpectSpeech 绕过了 aivs 的 dialog 状态机，aivs 随后的 Finish 会覆盖注入。**决策权在 aivs（云驱动），不在 mipns。**

### 7.5 下一步：mipns↔aivs 中间人（MITM）

唯一能从本地完全掌控 mipns 所见 downward 流的办法，是在 `mipns` 与 `aivs` 之间做代理：
- 把 mipns 收 downward 的 socket 路径接管（rename `/tmp/mipns/usock/speech.usock` + 自建代理 bind 原路径），代理把 aivs 的消息转发给真 mipns；
- 在我们的 LLM 追问场景里，**吃掉/改写 `Dialog.Finish`（0x05）并补发 `ExpectSpeech`（0x02）**，让 mipns 保持开麦；
- 追问音频经 mipns→aivs→云 ASR，文本仍走 `instruction.log` 的 `RecognizeResult`，质量与原生一致。

风险高（接管 mipns 的核心 socket 可能影响唤醒/正常对话），必须在能现场观察音箱、`native_first_client.sh` 可随时重启、且 boot 分区可回退的交互式会话里做。工具已备在 `/data/followup_probe/`。

## 8. 2026-06-12 第三轮：实现并实测 mipns↔aivs 中间人

按 §7.5 把中间人方案真正落地实测了。**结论：本地中间人改写下行流仍然无法实现原生追问**，撞上了固件的权威状态设计。但这一轮把机制钉到了最底层，且产出了可复用的 MITM 工具与协议全图。

### 8.1 MITM 可行性确认

strace `mico_aivs_lab` 确认：下行控制（含 Dialog.Finish）由 **aivs 发**，且用 **`sendto(fd, ..., sun_path="/tmp/mipns/usock/speech.usock")`——每条都带显式路径地址，不是 `connect()`**。因此把 mipns 的 socket 改名 + 代理 bind 原路径，能拦下 aivs 的全部下行。`/data/followup_probe/down_proxy`（zig 交叉编译）+ `proxy_setup.sh` / `proxy_restore.sh` 即此方案。**透明转发模式实测不影响正常唤醒和对话**（rename 不破坏 mipns 的 recv，因为 socket 绑定的是 inode 而非名字）。

### 8.2 下行 type 修正

上一轮把 `0x02` 误判为 ExpectSpeech。代理日志显示 `0x02` 在**每轮**对话里都出现（连非连续的“现在几点”也有），故 `0x02` 是例行帧。真正的“继续/ExpectSpeech”指令是 **`0x03`**：`\x08\x01\x1a\x28\x08\x03\x12\x20<id>\x22\x02\x10\x01`（44B，带参数 `{field2:1}`），它**只在连续对话那轮出现**，紧随其后才有新 dialog 的 `0x01` prepare 开麦。

### 8.3 实测：注入 0x03 + 0x01 仍被拒

代理在目标对话的 `0x05 Finish` 前注入 `0x03`（同 dialog）、Finish 后注入 `0x01`（新 dialog）。注入确实触发了 mipns 的 multirounds 逻辑，但 mipns 日志：

```
mico_aivs_lab: [ns::dialog] finish open_mic:0, valid_speech:0, valid_speak:0
mipns: [worker] multirounds, no wakeup end!
```

mipns 报 `multirounds, no wakeup end!` 拒绝；注入后无任何上行音频（mic 未开）。

### 8.4 最终的墙

**aivs 的 dialog 状态是权威的，且 `open_mic` 由云端 NLP 响应决定**。本轮这轮普通查询，aivs 自己算出 `open_mic:0`（云端没让继续），mipns 以 aivs 的状态为准，无视我们从下行注入的 `0x03`。即便强行让 mipns 开麦，上行音频是发给真 aivs 的，而 aivs 不认识我们伪造的 dialog，云端 ASR 也不会转写。所以：

> 用原生链路做“无唤醒词追问”在本固件上不可达——开麦与云端 ASR 编排都由 aivs 按云端指令掌控，本地无法凭空让某轮“继续”。

### 8.5 仍然可行的现实路线（重新确认）

回到 §4 的结论但有了新证据支撑：唯一能本地拿到追问的路，是**自己采麦 + 自己 ASR**，不依赖 aivs/云的连续编排：

- mipns 的录音线程常开（做唤醒检测），原始多麦 PCM 一直在采（但噪声/通道问题见 §2）。
- 更优的是**上行 MITM**：代理 `mipns→aivs` 的上行 socket（同样 sendto-with-path，可拦），在我们 LLM 播放后的时间窗内，把 mipns 上传的、经小米前端处理（AEC/波束）的干净音频截下来，送我们自己的 ASR（Mac Whisper / 云）。难点仍是“让 mipns 在该时刻开麦上传”——而这一轮证明了从下行注入开麦会被 aivs 权威状态否决，所以上行 MITM 也得配合一个能真正触发采集的手段（目前无解）。

务实判断：**继续投入原生连续对话的边际收益很低**。无唤醒词追问要么接受“每轮喊唤醒词”，要么走纯本地采音 + 自有 ASR 并接受其音质/稳定性代价。

### 8.6 复用资产（持久化在设备 `/data/followup_probe/`）

| 文件 | 作用 |
|---|---|
| `usock_send <path> <hex>` | 向 unix DGRAM socket 注入一条消息（aarch64 静态） |
| `down_proxy <listen> <forward> <log> <flag>` | aivs→mipns 下行中间人，透明转发 + flag 触发 0x03/0x01 注入 |
| `proxy_setup.sh` / `proxy_restore.sh` | 架设 / 安全还原下行代理（rename socket 方案） |
| `inject_expectspeech.sh` | 监控 instruction.log 在 TTS 结束时注入（早期实验脚本） |

交叉编译：Mac 上 `zig cc -target aarch64-linux-musl -static`。源码已入库 `device/followup_probe/`，协议格式见 §7.2/§8.2。

## 9. 2026-06-12 第四轮：音频管线与上行 PCM 解码

回答“为什么原始多麦质量差、干净音频在哪”，并实测解码上行流。

### 9.1 音箱端音频处理（确认在设备上做）

- 麦克风：**Knowles MEMS 阵列**，PDM 接口（ALSA card0 device2），原始 **7 声道 16kHz**。
- `mipns-xiaomi` 的 xaudio_engine 做：**AEC**（消自身 TTS 回声，`aec=%d`）+ **波束成形**（按唤醒 DOA 角 `angle:%f` 把 7 路合成 1 路定向）+ 唤醒词检测，再下混单声道上传。
- 原始多麦质量差的两层根因：① `arecord` 抓麦 `Device or resource busy`——mipns 独占麦设备；② 即便抢到也是波束**之前**的全向多通道。音箱自存的 `/data/mipns/audio/wakeup/*/audio.flac` 即 7 声道原始阵列（`meta.json: channel:7`），实测下混喂 Whisper 识别为空。

### 9.2 上行流解码：裸 PCM，ASR 级质量

strace aivs 的 `recvfrom(8)`（mipns→aivs 上行），帧是三层嵌套 protobuf：

```
\x08\x00 \x12\x8a\x0f{ \x08\x03 \x22\x85\x0f{ \x08\x02 \x12\x80\x0f <1920字节音频> }}
```

- 最内层音频负载 = **裸 PCM S16LE / 16kHz / 单声道**，每帧 1920B = 960 采样 = 60ms。**不是 opus**（opus32 同时长仅约 240B）。
- 实测：拼 62 帧 ≈ 3.66s，喂服务端 Whisper 转写**“帮我讲讲杭州西湖的历史”一字不差**；电平 -27dB 峰值 / -36dB RMS，干净不削波。
- 注：strace `-s 2000` 会截断 4015B 大帧，完整捕获需更大 `-s` 或上行代理 dump。

### 9.3 对“现实路线”的影响

干净音频**存在且可截获**（上行 sendto-with-path 可 MITM），自有 Whisper 能完美转写——**本地 ASR 追问在音质上完全可行**。瓶颈仍只是“无唤醒词时无法让 mipns 进入采集+波束状态”（§8）。故可落地方案：**第一句正常唤醒 → MITM 截获本轮上行 PCM → 喂自己的 ASR/LLM**，拿原生级音质、控制权回到本地，但省不掉首次唤醒。工具与格式见 `device/followup_probe/README.md`。

## 10. 2026-06-13 勘误：文件式原生 ASR 在 boot0 是支持的

§6.2 最初把“`ai_service asr_audio` 不支持”写成了普遍结论，并据此（错误地）删了 `transcribe_followup_voice_native`。复查发现**那只是 boot1 的特性**，已 `git revert` 还原。

**关键事实：这是 boot0/boot1 两套 ROM 的差异，必须分开记。**

| | boot0 / system0（2019 ROM，root=`/dev/mtdblock4`） | boot1 / system1（2023 ROM，root=`/dev/mtdblock5`） |
|---|---|---|
| `mico_aivs_lab` 进程 | 无 | 有 |
| `ai_service asr_audio` 文件式 ASR | **支持** | 不支持 |
| mibrain 二进制特征串 | `enter mibrain ai service asr audio fill!`，无 `not support` | `aivs asr req not support!` |

boot0 实测（2026-06-13，设备恰好跑在 system0）：

```sh
# /tmp/voice.wav = 16k/单声道/S16_LE，内容“明天天气怎么样”
ubus call mibrain ai_service '{"asr":1,"nlp":1,"tts":0,"asr_audio":"/tmp/voice.wav",...}'
# -> code:0, asr_result.query = "明天天气怎么样"（一字不差，还顺带跑了 weather NLP）
```

所以：

- **boot0 追问就靠 `ai_service asr_audio`（`FOLLOWUP_ASR_ENGINE=native`），是工作路径，保留。**
- boot1 追问本就由 `SYSTEM1_FOLLOWUP_ENABLED=0` 整体关闭，根本不会调到这条；其文件式 ASR 不支持只是顺带结论，不影响主线。
- 教训：跨 ROM 的能力结论，必须标注是在哪个 system 上测的；boot1 上的 `not support` 不能外推到 boot0。

