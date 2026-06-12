# followup_probe —— 原生追问逆向工具

这些是探索"无唤醒词连续追问"过程中写的实验工具。**结论：原生链路做无唤醒词追问在本固件不可达**，详见 [../../docs/history/followup-exploration.md](../../docs/history/followup-exploration.md) §6–§7。保留它们用于复现与后续研究。

## 编译

设备是 aarch64 Linux，Mac 上交叉编译：

```sh
zig cc -target aarch64-linux-musl -static -Os -o usock_send usock_send.c
zig cc -target aarch64-linux-musl -static -Os -o down_proxy down_proxy.c
```

产物 scp 到设备 `/data/followup_probe/`。

## 工具

- `usock_send <path> <hex>` —— 向 unix DGRAM socket 发一条（hex 解码的）数据报。用于向 mipns 的 `/tmp/mipns/usock/speech.usock` 注入下行控制帧。
- `down_proxy <listen> <forward> <log> <flag>` —— aivs→mipns 下行控制通道的中间人。默认透明转发；当 `<flag>` 文件存在时，把下一条 `Dialog.Finish(0x05)` 改写为"继续"：注入 `0x03` 继续指令 + 新 `0x01` prepare 试图重开麦。
- `inject_expectspeech.sh` / `inject_v2.sh` —— 监控 `instruction.log`，在对话特定时机注入 ExpectSpeech 的早期脚本（已被 `down_proxy` 取代）。

## mipns↔aivs 下行协议（speech.usock，protobuf）

```
\x08\x01 \x1a<len> \x08<TYPE> \x12\x20<32字节 dialog_id(ASCII hex)> [尾部]
```

| TYPE | 含义 |
|---|---|
| 0x01 | prepare/start（开麦，44B，尾 `\x1a\x02\x08\x01`） |
| 0x03 | 继续/ExpectSpeech（仅连续对话出现，44B，尾 `\x22\x02\x10\x01`） |
| 0x05 | Dialog.Finish（48B，尾 `\x32\x06...`） |
| 0x07 | asr partial（46B，尾 `\x2a\x04\x08\x00\x10<offset>`） |
| 0x02 | 例行帧（每轮都有，非继续信号） |
| 0x04 | asr timeout |

## 上行流（mipns→aivs）= 干净 PCM，可截获自用

上行音频走 `mipns -> sendto(/tmp/mico_aivs_lab/usock/speech.usock)`（同样带显式路径，可 MITM）。报文是三层嵌套 protobuf，最内层是音频负载：

```
\x08\x00 \x12\x8a\x0f{ \x08\x03 \x22\x85\x0f{ \x08\x02 \x12\x80\x0f <1920字节音频> }}
```

- **音频格式：裸 PCM S16LE / 16kHz / 单声道**，每帧 1920B = 960 采样 = 60ms（虽然 mipns 支持 `opus32`，实际传未压缩 PCM）。
- 这是 mipns 经 **AEC + 7 路 Knowles 阵列波束成形**处理后的定向单声道，**ASR 级质量**：实测拼 3.66s 喂服务端 Whisper，转写"帮我讲讲杭州西湖的历史"一字不差；电平 -27dB 峰值 / -36dB RMS，不削波、底噪低。
- 对比：`arecord` 抓原始麦 `Device busy`（mipns 独占）；音箱自存的 `/data/mipns/audio/wakeup/*/audio.flac` 是 **7 声道原始阵列**（`meta.json: channel:7`），未经波束，又弱又吵——这才是"原始多麦质量差"的根因。

解码方法：strace aivs 的 `recvfrom(8)`（用 `-s 2000` 拿全 1935B 帧，更大的 4015B 帧需 `-s 4096`），按上面结构剥三层 LEN 取最内层负载，拼接为 `s16le/16000/mono` 即得 WAV。解析脚本思路见会话记录（逐帧走 protobuf 嵌套取最深 LEN）。

> 局限：上行 PCM **只在原生对话期间流动**，波束方向也由唤醒那一刻确定。所以可落地的本地方案是“第一句正常唤醒 → MITM 截获本轮上行 PCM → 喂自己的 ASR/LLM”，省不掉首次唤醒（原因见下）。

## 为什么“无唤醒词追问”不可达

aivs（`mico_aivs_lab`）的 dialog 状态是权威的，`open_mic` 由云端 NLP 响应决定。我们从下行注入 `0x03` 被 mipns 以 `multirounds, no wakeup end!` 拒绝，因为 aivs 自己算的是 `open_mic:0`。即便强行开麦，上行音频发给真 aivs，云端 ASR 也不转写我们伪造的 dialog。
