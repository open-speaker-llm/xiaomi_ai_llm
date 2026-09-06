# followup_probe —— 原生追问逆向工具

> 2026-09-06：这里的限制仅针对免唤醒追问。boot1 首轮失败提示快速拦截已实测通过，见 [修复记录](../../docs/history/2026-09-06-boot1-fallback-guard.md)。

这些是探索“无唤醒词连续追问”的实验工具。旧的下行注入方案失败；2026-09-06 新的 **NONWAKEUP 上行识别入口已实测成功**，现场免唤醒问时间、算术题均获原生回答，用户确认。见 [原生识别实测](../../docs/history/2026-09-06-boot1-native-asr-research.md)。后续已实现并安装 [原生 LLM 连续追问组件](../native_asr/README.md)；这里仍保留研究工具，不用作正式开机服务。

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

## 旧下行注入为什么失败

aivs（`mico_aivs_lab`）的 dialog 状态是权威的，`open_mic` 由云端 NLP 响应决定。我们从下行注入 `0x03` 被 mipns 以 `multirounds, no wakeup end!` 拒绝，因为 aivs 自己算的是 `open_mic:0`。这条方案绕过了 aivs 的会话创建流程。新 NONWAKEUP 方案让真实 aivs 自己建立新 dialog，已经取得有效识别；旧失败不能泛化为所有原生路径都不可用。


## NONWAKEUP 上行入口研究原型

- `native_wake_probe.c`：临时 ARM32 LD_PRELOAD 探针，保留真实回调与 PCM tap；触发单次原生会话，修改 prepare 的 activate_mode，并完成本地 IVW 门控。
- `native_wake_probe_setup.sh`：只接受本次固件及既有 PCM tap 的 PNS 内容哈希，再叠加一层临时挂载；480 秒后恢复。需要已经传到音箱的 `wake.so` 的本地 SHA-256，拒绝校验不符的文件。

这是研究代码，含固定 10 秒自动测试、3 秒 prepare 改写窗口、限时音频采样和可选录音对照，尚未完成正式服务的并发、LLM 路由和退出处理。不要写入开机启动。原始音频、设备日志和编译出的固件库不入库。

在仓库根目录构建：

```sh
zig cc -target arm-linux-gnueabihf.2.25 -shared -fPIC -Os -Wall -Wextra -Werror \
  device/followup_probe/native_wake_probe.c -ldl -lpthread -o /tmp/wake.so
shasum -a 256 /tmp/wake.so
```

经现有维护 SSH 连接，把共享库和安装脚本传至音箱的 `/tmp/boot1-native-wake/`（目录权限 700）。设备处于空闲状态时，用上一步的实际哈希运行：

```sh
EXPECTED_PROBE_SHA256=<本地构建文件的64位SHA256> sh /tmp/boot1-native-wake/native_wake_probe_setup.sh
touch /tmp/boot1-native-wake/auto.armed
```

然后正常唤醒问时间。探针只在这次真实 `0x1` 回调的 10 秒后触发一次 NONWAKEUP；下一声原生提示之后，不喊唤醒词直接说另一句。需要同时核对 `probe.log`、新的 `RecognizeResult` / dialog ID 和人的听觉结果；出现新 dialog 或空识别结果不能算成功。两次成功的现场实验都为 `mode=2`、`replay=0/0`。

主动恢复并取消未到期的自动恢复标记：

```sh
rm -f /tmp/boot1-native-wake/auto.armed /tmp/boot1-native-wake/trigger
sh /tmp/boot1-native-wake/restore.sh
rm -f /tmp/boot1-native-wake/rollback.armed
sh /data/native_pcm_tap.sh status
```

脚本退出失败时会尝试恢复；到期恢复还通过 480 秒定时器兜底。恢复后检查 PNS 内容与 `pns.before` 一致，`mipns` 不再加载临时 `wake.so`，正式 PCM tap 保持健康。该探针不会自动切换正式追问的 ASR 配置。
