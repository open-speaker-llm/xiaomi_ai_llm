# A/B 跨会话现场验证

目的：定位用户报告的“第一轮重复、第二轮文本出现重复”。既有日志只能证明重复已经存在于小米第二个独立 dialog 的渐进结果，不能证明声音的真实来源。20:34 的 A 被 SDK 超时及音箱错误提示打断，样本无效。22:44–22:45 重新执行 A/B，两轮完整且未复现串轮，详见文末；这不证明之前的重复问题已修复。

## 两句不同内容

- A：**苹果的种子为什么会发芽？** 连续说完，只说一次。
- B：**火车的车轮——停顿约一秒半——为什么是圆的？** 只说一次。

这些词仅供人工核对轮次。程序不按词判断是否调用模型、不改写或过滤小米文本，不因识别出 A/B 词汇而改变判停参数。

每轮由用户当轮就绪后单独启动，不自动连续执行两轮。提示语在启动之前展示，用户看到“开始 A”或“开始 B”才说；不用喊“小爱同学”。说完保持安静，等待明确的该轮结束通知；不要在没有收到结果时自行重说。若确实重说，记录是哪一轮及大致时刻。

## 执行条件与就绪判定

失败的 A 沿用 `e27f86bad97b8ef3d4e0924a25f3eeed2ae04655992e31512818695188bcc7bf` 主动探针，保持 VAD 模式 1 和所有既有参数。当时版本只改变 runner 的轮次标记、就绪确认与日志，不改变麦克风采样或识别请求配置。后续重测先解决独立 SDK 超时，并重新记录二进制哈希。

先确认空闲、设备哈希、无残留挂载/armed/busy，再临时 setup。A/B 尽量在同一次临时 setup、相同进程中执行，避免两轮之间重启服务清除了可能存在的缓冲问题。仍保留五分钟恢复计时器；若临近到期，结束并恢复，不跨自动恢复边界继续试验。

设备命令（由操作端逐轮执行）：

```sh
sh /tmp/xiaomi_endpoint_active/run_active.sh trial microphone 5 A
# 核对 A 已 final/Finish、原监听进程退出、busy 撤销；等用户准备 B。
sh /tmp/xiaomi_endpoint_active/run_active.sh trial microphone 5 B
sh /tmp/xiaomi_endpoint_active/run_active.sh restore
```

`PROTOCOL_TRIAL` 仅表示创建了记录目录。runner 现在在后台启动 CLI，最多等待四秒，轮询原生状态直到 **精确 sequence、phase=BOUND、非空 dialog、final=0**，才输出 `CAPTURE_READY case=A|B sequence=...`。操作端看到这个标记后才提示用户开始。未就绪则终止自己启动的 CLI，不提示发声，记录失败并恢复。退出清理也会收回尚未退出的监听子进程。

每轮新增 `case`、`before.state`、`ready.state`、`ready.time`，与已有 `start`、`state`、`text`、`probe.log`、`system.log`、云端事件/指令快照一起核对。不使用旧的 status 快照宣告新轮就绪。

## 结果核对

1. 两轮必须是不同 sequence/dialog；B 的 before.state 应显示 A 已结束，而非两个监听重叠。
2. 对齐 ready、云端第一条非空 partial、最后一条 partial、VAD 决定、EOF、final、Finish。用户阅读提示的等待时间不当作句末延迟；ASR offset 不当人工逐帧真值。
3. 若 B 的云端 partial 已包含 A 内容，问题在汇总程序之前。不要因 CLI 返回 0 就认定文本正确，也不要擅自删除重复词。
4. 如果只是最终汇总文本混入 A、云端 B 没有，则再查结果读取/归属层。
5. 如仍不一致，先保存日志、恢复原配置；再设计能区分音频来源的限时取证。此版本不保存新的音频，不使用 Mac 转写。

## 准备验证

- readiness 自动测试覆盖正确当前绑定、旧 sequence、未绑定、已 final、空 dialog。
- 非法 A/B 标签或多余参数在创建试验之前被拒绝。
- 音箱独立进程测试覆盖取消后不得重新激活同一轮、下一轮清空 VAD/计数器、不同 PCM 数据逐字节原样转发。它只验证本探针，不证明原生固件内部没有缓冲残留。
- 上述独立测试前后，生产 mipns/aivs PID、sequence/dialog 和状态不变；没有 armed/timer，也未启动麦克风、云端识别或 LLM。
- 准备阶段 122 项 Python 回归与 shell 语法检查通过，日志在主项目忽略目录 `tmp/asr-shadow-20260918/pair-checks.txt`。当时 runner SHA256 为 `e559110d672083365e20245cc64095a54c7f9ec926f13f98090fe7bf6436b092`。

## A 无效样本（20:34）

`trial.microphone.5.wtyBRs`、seq 33、dialog `0ddaab6d60a0dcf7905c0f81103bbe23`。已确认当前轮 BOUND 才提示“开始 A”，但没有非空 ASR。20:34:34.648654 收到初始空结果，20:34:44.656191 SDK 报 `50010005 TTS timeout`（相隔 10.0075 秒），随后原生采集 idle。20 秒硬上限后的 EOF 已无法完成该会话，CLI 124，final/finished 均 0。

用户确认在提示后尝试发声，但音箱说“网络遇到问题，请稍后再试吧”，影响了内容。因此不能把此轮当作安静、不发声或 ASR 漏字的证据。B 没有启动；已恢复原服务，记录 `pair-a-restore.txt`。先用已有录音验证 SDK 超时条件，不再要求用户重复现场发声。

## 22:44–22:45 现场复测

使用已通过回放对照的实验库 `ff7df7e73225b70686791e6de5771a7b0efdce421c3bfabd34ef0da722934bd7`，包含专属租约 SDK 超时保护。两轮在同一次 setup、同一对进程（mipns 3288 / aivs 3227）中进行；各自精确 BOUND 后提示开始，A 结束并获得用户 B 就绪反馈后才启动 B。

用户确认 A 无干扰；B 按要求停顿约一秒半、只说一次、没有干扰。停顿长度是用户确认的实验条件，没有保存 PCM，不能声称已经逐帧测出精确 1.5 秒。

| 项目 | A | B |
| --- | --- | --- |
| seq / 开始 CST | 39 / 22:44:40 | 40 / 22:45:25 |
| 目录 | `trial.microphone.5.QG9jCK` | `trial.microphone.5.dCmxZZ` |
| dialog | `5ccc912816c7c820c8a0b1ec6ba35b13` | `25a57a3a340f72fe43427c039e4681a8` |
| 文本 | 苹果的种子为什么会发芽 | 火车的车轮为什么是圆的 |
| 自动结束 | quiet | quiet |
| 音频累计 / 墙钟收音 | 12570 / 12301 ms | 10360 / 10090 ms |
| 最后确认 VAD 语音位置 | 10570 ms | 8360 ms |
| 小米最后可用语音 end offset | 7240 ms（partial） | 8280 ms（final） |
| EOF 到首个 final 日志 | 231 ms | 181 ms |

两轮 CLI 均 0、final=1、finished=1，SDK 覆盖日志确认 native_s=10 / experiment_s=30，无 TTS timeout。模式 5 原样传递麦克风，used=0，不回放旧 PCM、不保存新录音、不调用 LLM 或写入对话历史。A 的云端指令快照未包含 final 行；final/Finish 由探针日志、CLI 文本和状态交叉证明，不把该快照的最后一条 partial 当 final。

B 的云端渐进结果先出现“火车的车轮”，随后发展为完整问题，没有 A 的“苹果”内容。A/B 当前文本均未重复。这只说明本轮没有复现跨轮异常，不排除此前原生缓冲、ASR 重复或发声时序问题。

按 ASR offset 与本地累计音频粗估，A 句末等待约 5.33 秒，B 约 2.08 秒；两类时钟不是人工音频标注，不能当作精确延迟。A 在识别到的问题结束后仍出现 VAD 阳性，最后确认到 10570 ms；旁路模式 2/3 的候选为 12470/12440 ms，相比主模式只提早约 0.1 秒。因此这轮也不支持仅靠切换更严格模式解决句末拖延。用户无干扰反馈保留；没有 PCM 无法确定后段声音来源。

完成后主动 restore；首次立即读取服务状态为 inactive（重启尚在进行），随后复核为 healthy、mipns 4045 / aivs 3984。两个 init 哈希与 before 一致，客户端哈希未变；armed/timer/busy 均无，两个进程均不加载实验库。证据位于忽略目录 `pair-retest-trials/`、`pair-retest-restore.txt`、`pair-retest-health.txt`。本轮只执行现场验证并记录，没有进一步改动判停代码或部署生产。
