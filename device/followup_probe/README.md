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

## 为什么不可达

aivs（`mico_aivs_lab`）的 dialog 状态是权威的，`open_mic` 由云端 NLP 响应决定。我们从下行注入 `0x03` 被 mipns 以 `multirounds, no wakeup end!` 拒绝，因为 aivs 自己算的是 `open_mic:0`。即便强行开麦，上行音频发给真 aivs，云端 ASR 也不转写我们伪造的 dialog。
