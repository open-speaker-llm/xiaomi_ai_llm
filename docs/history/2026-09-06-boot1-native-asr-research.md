# 2026-09-06：boot1 NONWAKEUP 原生识别入口实测

适用设备：S12A / MDZ-25-DA，boot1/system1，ROM 1.76.54。

## 研究阶段结论

**程序主动建立原生识别会话、免唤醒识别现场语音并由小爱回答，已经实测成功。** 两次追问分别识别出“现在几点”和“3×7等于多少”，用户确认听到了第二次报时和“二十一”。识别结果来自小米 `mico_aivs_lab` 的 `SpeechRecognizer.RecognizeResult`，这两轮没有调用 Mac Whisper。

这证明 boot1 可以复用内置的小米云端识别链路，不必另外部署识别程序；仍然需要联网。**截至本次研究结束时，尚未接入 LLM 或开机启动。** 当时已撤下临时探针并恢复 PCM + Mac ASR。随后已完成 [原生 LLM 追问集成与安装](2026-09-06-boot1-native-followup.md)，当前状态请以该后续记录为准。

之前“原生路径不可达”的结论过于宽泛，应收窄为：已测试的公开接口和下行指令注入失败。此次从上行会话创建入口入手，绕开了那条失败路径。boot1 的 `ai_service asr_audio` 文件识别接口仍未打通。

## 关键发现

`libaivs-message-util.so` 保留了 protobuf-c 描述符，实际查到了以下字段，并通过动态实验验证 `activate_mode`：

| 请求字段 | 枚举值 | 本轮处理 |
| --- | --- | --- |
| `stream_prepare_request_message.activate_mode` | `WAKEUP=0`、`NONWAKEUP=1` | 只在实验触发的一次准备请求中改为 `NONWAKEUP` |
| `stream_prepare_request_message.interact_mode` | `NONCONTINUOUS=0`、`CONTINUOUS=1` | 保持原值；发现枚举不表示已验证 CONTINUOUS 功能 |

这不是给旧 dialog 强塞 `ExpectSpeech`。新请求进入真正的 AIVS 会话管理，由它生成新的 dialog ID，向小米云端发送 `SpeechRecognizer.Recognize`。成功的第二轮事件中有 `Recognize` / `RecognizeStreamFinished`，没有该轮的 `SpeechWakeup.Wakeup` / `WakeupStreamFinished`。

仅修改这个字段还不足以证明能识别。`mipns` 本地仍有“唤醒词音频是否处理完”的门控，普通回调触发后，ASR 音频会一直滞留在缓存。实验通过已注册的原生 IVW 回调，以零长度音频完成这个本地步骤，随后真实麦克风音频才能进入新识别会话。

## 调用路径与 ABI 依据

原生音频进程和库是 ARM32 hard-float；不能按内核的 ARM64 ABI 构建共享库。

1. 拦截音频库导出函数 `xaudio_register_callback(engine, callback, context)`，保留并照常调用原注册函数，取得真实唤醒回调与上下文。
2. 正常唤醒实测回调为 `callback(context, 0x1, angle)`。本固件记录的回调地址为 `0x18f68`，对应 `mipns_wakeup_1_cb`，上下文为 `0x597a0`。探针使用运行时注册值，没有硬编码这两个地址。
3. 程序调用同一回调，经过原生分布式唤醒协调及本地状态机，发出上行 stream prepare 请求。
4. 在 `speech_message__pack` 中识别该 prepare 请求，将 `activate_mode` 由 0 改为 1；打包后恢复结构体原值，其他消息照常打包。
5. 从 `register_data_upload_callback` 取得原 IVW 回调。本固件对应 `mipns_ivw_data_cb`，地址 `0x1867c`。实验调用 `ivw(1, empty_buffer, 0, 0, 0)` 完成本地缓存门控，未上传伪造的唤醒词音频。
6. 原生 ASR 音频回调继续输送当前麦克风音频，AIVS 返回实时识别文本，原生 NLP/TTS 作答。

ARM32 protobuf-c 布局核对：顶层 type 在 `+0x0c`、upward 指针在 `+0x10`；upward type 在 `+0x0c`、prepare 指针在 `+0x14`；prepare 的 activate_mode 在 `+0x0c`。描述符显示该字段为 enum，字段编号 1。以上仅对本次校验过的库成立。

真实唤醒后还观测到 `code=0x101`。不能把所有回调都当作新唤醒，或直接重放最后一条。对应代码把高字节非零的路径标为 unnormal/suspect；本轮只使用已经对照验证的 `0x1`。不能仅凭这条附加回调的出现时间，将它解释为结束信号。

## 实验记录与反例

时间均为设备北京时间 2026-09-06。

| 实验 | 结果 | 能证明什么 |
| --- | --- | --- |
| 11:58 正常唤醒问时间 | `0x1` 回调及正常 Wakeup → Recognize → Speak | 取得真实回调、上下文、参数和正常识别对照 |
| 11:59:59 只调用唤醒回调 | 新 dialog `da1ddc49a3726457ae763264cc37dd19`；只有 Wakeup，音频日志持续 `asr before wuw`，最后结束 | 回调可启动前半段流程，但没有可用识别；不能把新 dialog 当作成功 |
| 12:03:47 NONWAKEUP + IVW 零长度完成 | 新 dialog `cf1d8667a02b577314c2be353710bcb7`；空 partial/final RecognizeResult | 到达识别入口；安静对照不等于有效语音识别成功 |
| 12:04:46、12:10:17 按聊天提示说话 | final 文本为空；用户反馈无反应、可能没对准 | 这两次不算成功；原生空闲收听约 6 秒，不能仅靠聊天提示协调时机 |
| 12:08:20 已知录音对照 | 原生 ASR 返回“一起去风”，随后触发原生 NLP 和现有 LLM fallback | 外部录音能进入原生识别，但文本不完整、不能当准确率或现场免唤醒验收；这条原生 ASR 结果未经过 Mac |
| 12:14:58 自动触发，现场问时间 | 新 dialog `dd5eb44c9ec160aca2a9e06f4033add9`；final `现在几点`；Speak `现在是中午12点15分` | 第一次现场免唤醒成功；用户确认提示“欸”后再次提问获得正常回答 |
| 12:17:39 自动触发，现场换成算术题 | 新 dialog `a785a9b045999db1a405ec0934c77cf7`；final `3×7等于多少`；Speak `答案是二十一` | 用户确认回答 21；文本与首轮时间问题不同，排除上一轮识别文本残留 |

两次成功的自动测试：用户先正常唤醒问时间，探针在这次真实唤醒 **10 秒后**触发一次 NONWAKEUP 会话。第一轮有原生语音唤醒，第二轮只有探针触发；探针日志明确记录 `origin=probe`、prepare 改写和 `replay=0/0`。成功的现场实验没有使用固定录音替换音频。第一轮音箱报时结束后立即说话可能早于新窗口，用户听到下一声“欸”后再问才成功。

## 研究结束时的集成待办

以下记录研究结束时的差距；后续实现、部署与验收见 [原生追问集成](2026-09-06-boot1-native-followup.md)。

- 用 LLM 实际播报完成事件打开下一轮，替换研究用的固定 10 秒延迟。
- 将新原生 ASR 文本交给当前 LLM session，保留上下文；本次验证的是小爱原生作答。
- 处理小爱的唤醒提示音，并避免同一个追问同时触发小爱原生 NLP/动作和 LLM。目前 NONWAKEUP 默认仍运行原生 NLP/TTS，不能只把 ASR 文本读走就宣称完成集成。
- 收窄 prepare 改写作用范围，处理用户真实唤醒、播报、超时、静音、退出和恢复的并发边界。研究原型有一个 3 秒 prepare 改写窗口，不适合直接作为正式服务。
- 验证安静退出、不同追问、多轮连续运行和重启自启动，再决定替换正式的 Mac ASR 配置。

## 复现实验与恢复

探针源码：[native_wake_probe.c](../../device/followup_probe/native_wake_probe.c)。临时安装脚本：[native_wake_probe_setup.sh](../../device/followup_probe/native_wake_probe_setup.sh)。构建与操作见 [工具说明](../../device/followup_probe/README.md)。

本轮使用额外一层 `/etc/init.d/pns` bind mount，在原有 PCM tap 前增加临时 `LD_PRELOAD`。探针及控制文件只在 `/tmp/boot1-native-wake/`，没有替换 `/data/native_first_client.sh`、配置文件或正式 PCM tap。安装脚本设置 480 秒自动恢复；12:12:31 曾实际触发一次，恢复后 PCM 健康检查通过。最后一轮完成后再次主动恢复，并解除尚未到期的恢复标记。

恢复命令：

```sh
sh /tmp/boot1-native-wake/restore.sh
sh /data/native_pcm_tap.sh status
```

结束时验证：临时 PNS 叠加层已移除；PNS 内容哈希与实验前一致；`mipns` 只加载正式 `/data/xaudio_pcm_tap.so`，没有加载临时 `wake.so`；PCM 健康检查通过。正式客户端与 PCM tap 哈希保持不变。没有切换 boot0，没有提交或推送此次研究。

## 固件校验值

| 文件 | SHA-256 |
| --- | --- |
| `/usr/bin/mipns-xiaomi` | `a02071a39f3509d3a90dac638e323039a24de784a907f076a0a91f81cd5fbb9d` |
| `/usr/lib/libxaudio_engine.so` | `79f1a33d9683cd6940c8d23e3dd4e992f1958fe220c0dfff8d230f9f8a1b5e73` |
| `/usr/lib/libaivs-message-util.so` | `c0fc1b551e20962e6dceeb4b1a24b3d8a454e19bec8fd692f2229241691a0c31` |
| `/usr/bin/mico_aivs_lab` | `7063b44fbe779c04c8bfc89e2870e1716eeb62765ba0025f8e8b68ea8026d18c` |

原始音频、完整设备日志和私有配置不入库。这里仅保留与测试直接相关的文本、时间、会话标识和代码依据。
