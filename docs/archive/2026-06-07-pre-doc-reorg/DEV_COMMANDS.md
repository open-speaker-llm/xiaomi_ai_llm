# 开发调试常用命令

本文档记录小米 AI 音箱改造项目开发和调试时常用的命令。

启动链路和分区概念说明见 [docs/BOOT_FLOW.md](docs/BOOT_FLOW.md)，包括 `boot0/boot1`、`system0/system1`、`kernel`、`initramfs`、`rootfs`、OpenWrt/LEDE 等基础概念。

## 1. 当前网络信息

```text
Mac IP: 192.168.8.150
音箱 IP: 192.168.8.152
```

## 2. Mac 上进入 screen 串口

### 2.1 查看串口设备

```bash
ls /dev/tty.*
```

找到类似下面的设备名：

```text
/dev/tty.usbserial-3120
```

### 2.2 连接串口

```bash
screen /dev/tty.usbserial-3120 115200
```

如设备名不同，把 `/dev/tty.usbserial-3120` 替换为实际设备。

### 2.3 退出 screen

```text
Ctrl+A -> K -> Y
```

## 3. 进入 U-Boot

### 3.0 通过 SSH 切换 boot 启动分区

如果当前系统还能 SSH 登录，可以不用手动进 U-Boot，直接在 Linux 里写 U-Boot 环境变量并重启。

前提：

- 当前 SSH 可用。
- 串口已连接，或者至少确认可以通过串口进 U-Boot 回退。
- 只在明确需要切换启动分区时执行。

查看当前启动分区相关信息：

```bash
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152 'fw_env boot_part 2>&1; mount | head -5'
```

切到 `boot1` 并重启：

```bash
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152 'fw_env boot_part=boot1 && sync && reboot'
```

切回 `boot0` 并重启：

```bash
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152 'fw_env boot_part=boot0 && sync && reboot'
```

这等价于在 U-Boot 中执行：

```text
s12# setenv boot_part boot1
s12# saveenv
s12# reset
```

或：

```text
s12# setenv boot_part boot0
s12# saveenv
s12# reset
```

注意：`fw_env boot_part=...` 会直接写 U-Boot env。写错或切到异常系统后，仍需要串口进 U-Boot 回退。

### 3.1 先连接串口

```bash
screen /dev/tty.usbserial-3120 115200
```

### 3.2 断电重启音箱

先给音箱断电，再重新插电。

### 3.3 中断自动启动

串口窗口开始刷启动日志时，立即反复按：

```text
Enter
```

如果看到类似下面的提示，按提示键中断启动：

```text
Hit any key to stop autoboot
```

### 3.4 确认进入 U-Boot

成功后会停在 U-Boot 命令行：

```text
s12#
```

如果已经进入 Linux 启动或出现 `mico login:`，说明错过了时机，断电重来。

## 4. 进入 failsafe 模式

failsafe 只在 `boot0` 上。重新进入 failsafe 前，先在 U-Boot 中查看当前启动分区：

```text
s12# printenv boot_part
```

如果不是 `boot0`，切回 `boot0`：

```text
s12# setenv boot_part boot0
s12# saveenv
s12# reset
```

重启后不停机自动启动。看到下面提示时，立即按 `f`，再按 `Enter`：

```text
Press the [f] key and hit [enter]
```

## 5. SSH 连接音箱

```bash
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152
```

## 5.1 boot1 SSH 打通

`boot1/system1` 的 SSH 注入、写入、校验、切换和回退流程见：

```text
docs/BOOT1_SSH_RUNBOOK.md
```

核心结论：

- `system1` 有坏块，最终写入使用 `mtd -f write - system1`。
- 不要用 `dd of=/dev/mtdblock5` 作为最终写入方案。
- 切 `boot1` 验证前必须确保串口可用，失败时从 U-Boot 切回 `boot0`。

## 6. Mac 服务端

### 6.1 前台启动

在 Mac 项目目录执行：

```bash
cd /Users/mac-mini-wx/research/xiaomi_ai/xiaomi_ai_llm
./start_server.sh
```

前台启动适合开发调试，日志直接显示在当前终端。停止服务按：

```text
Ctrl+C
```

### 6.2 后台启动

```bash
cd /Users/mac-mini-wx/research/xiaomi_ai/xiaomi_ai_llm
nohup ./start_server.sh > /tmp/server.log 2>&1 &
```

### 6.3 检查服务状态

Mac 本机检查：

```bash
curl http://127.0.0.1:8080/
```

从音箱检查 Mac 服务端：

```sh
curl -s -m 5 http://192.168.8.150:8080/
```

正常应看到类似：

```json
{"status":"ok","service":"xiaomi_ai_llm","llm":"minimax (MiniMax-M2.7)","asr_configured":true,"tts_configured":true}
```

### 6.4 查看服务端日志

```bash
tail -f /tmp/server.log | grep -E '📥|🎤|🌐|🔊|🤖|✅'
```

如果是前台启动，直接看启动终端输出。

### 6.5 关闭后台服务

先查进程：

```bash
ps aux | grep 'uvicorn server.main:app' | grep -v grep
```

关闭：

```bash
pkill -f 'uvicorn server.main:app'
```

再确认 8080 是否关闭：

```bash
curl --max-time 2 http://127.0.0.1:8080/
```

如果返回连接失败，说明已关闭。

## 7. 音箱客户端（当前主线）

### 7.1 前台启动

当前主线使用 `native-first` 客户端。它复用小米原生“小爱同学”唤醒、ASR/NLP 和家电控制；原生不支持时再转 Mac 服务端 LLM。

在音箱 SSH 里执行：

```sh
SERVER=http://192.168.8.150:8080 BACKEND=deepseek sh /data/native_first_client.sh
```

前台启动时，主流程日志直接显示在当前 SSH 窗口。

### 7.2 后台启动

```sh
SERVER=http://192.168.8.150:8080 BACKEND=deepseek \
sh /data/native_first_client.sh > /tmp/native_first_client.log 2>&1 &
```

### 7.3 检查客户端状态

```sh
sh /data/native_first_client.sh status
ps | grep -E 'native_first_client|mipns-xiaomi|mediaplayer|curl|aplay|arecord' | grep -v grep
```

正常至少应看到：

```text
sh /data/native_first_client.sh
/usr/bin/mipns-xiaomi ...
```

### 7.4 查看客户端日志

后台启动后查看主日志：

```sh
tail -f /tmp/native_first_client.log
```

同时查看客户端日志和原生唤醒事件：

```sh
tail -f /tmp/native_first_client.log /tmp/native_first_events.log
```

关键启动成功日志：

```text
[HOOK] mounted /bin/wakeup.sh -> /tmp/wakeup.sh.native_first_client
[HOOK] watchdog pid=...
[IDLE] 等待原生唤醒词：小爱同学
```

### 7.5 关闭客户端

```sh
sh /data/native_first_client.sh stop
```

确认是否停干净：

```sh
ps | grep -E 'native_first_client|curl|aplay|arecord' | grep -v grep
```

如果只剩系统音频进程，例如 `mediaplayer`、`bluealsa-aplay`，说明助手已关闭。

## 8. 原生小米唤醒实验

本节是历史/实验路线。当前主线见第 7 节和第 11 节。

早期 KWS 方案是：

```text
/data/open-xiaoai/kws/kws -> /data/wake_monitor.sh
```

如需实验小米原生唤醒链路，可临时启用探针。探针会停止当前助手，恢复原生 `mipns-xiaomi`，并通过临时 bind-mount 包装 `/bin/wakeup.sh` 记录原生唤醒事件。

### 8.1 启动原生唤醒探针

```sh
sh /data/native_wakeup_probe.sh start
```

然后对音箱说原生唤醒词：

```text
小爱同学
```

### 8.2 查看原生唤醒日志

```sh
sh /data/native_wakeup_probe.sh log
```

或直接看：

```sh
tail -f /tmp/native_wakeup_events.log
```

### 8.3 查看探针状态

```sh
sh /data/native_wakeup_probe.sh status
```

### 8.4 停止并恢复

```sh
sh /data/native_wakeup_probe.sh stop
```

恢复后重新启动当前助手：

```sh
SERVER=http://192.168.8.150:8080 BACKEND=deepseek \
sh /data/native_first_client.sh > /tmp/native_first_client.log 2>&1 &
```

## 9. 历史路线：原生小米唤醒客户端

本节记录旧的 `native_client.sh` 实验路线，保留用于对照。当前推荐部署路径见第 11 节 `native_first_client.sh`。

旧原生客户端使用小米自带 `mipns-xiaomi + wakeup_model.bin` 检测“小爱同学”。唤醒后先播放“欸”，再录音并做路由：

```text
设备/家电/播放控制命令 -> 小米原生 mibrain ai_service
普通问答 -> Mac ASR + DeepSeek/MiniMax + TTS
```

默认 LLM 后端是 `deepseek`。

防串台策略：

```text
唤醒提示音后等待 0.5s 再开始录音
native 控制命令执行后等待 3.0s，直接退出对话，回到等待唤醒
native 控制退出后 2s 内忽略新的唤醒事件，避免“开了/好了”等原生播报误触发
FIFO 唤醒事件带时间戳，超过 2s 的旧事件会被忽略
LLM 回答播放完成后等待 1.0s，再进入 6s follow-up
follow-up 中如强命中 native 控制，也执行后退出对话
```

默认 sherpa 客户端仍然保留：

```sh
sh /data/stream_client.sh > /tmp/stream_client.log 2>&1 &
```

### 9.1 启动原生唤醒客户端

```sh
sh /data/native_client.sh > /tmp/native_client.log 2>&1 &
```

指定其他后端，例如 MiniMax：

```sh
BACKEND=minimax sh /data/native_client.sh > /tmp/native_client.log 2>&1 &
```

### 9.2 查看日志

```sh
tail -f /tmp/native_client.log
```

关键日志示例：

```text
[WAKING] 原生唤醒 -> backend=deepseek
[ROUTE] text=打开客厅灯 route=native reason=control_action_and_device
[NATIVE] 转发小米原生控制: 打开客厅灯

[ROUTE] text=太阳为什么从西边升起 route=llm reason=default_llm
[SEND] text -> http://192.168.8.150:8080
```

查看原生唤醒事件：

```sh
tail -f /tmp/native_wakeup_events.log
```

### 9.3 停止原生唤醒客户端

```sh
sh /data/native_client.sh stop
ps | grep -E 'native_client.sh|mipns-xiaomi|curl|aplay|arecord' | grep -v grep
```

停止后如需切回 sherpa 客户端：

```sh
sh /data/stream_client.sh > /tmp/stream_client.log 2>&1 &
```

## 10. Native-first 观察模式

用于验证“先让小米原生链路实时处理，失败后再 fallback 到 LLM”的可行性。该模式不会 `STOP mipns-xiaomi`，小米原生小爱会正常收音、识别和回答；脚本只做旁路记录。

### 10.1 启动观察模式

```sh
sh /data/native_first_observer.sh start
```

启动后测试三类 case：

```text
小爱同学，开灯
小爱同学，现在几点
小爱同学，太阳为什么从西边升起
```

### 10.2 查看观察日志

```sh
tail -f /tmp/native_first_observer.log
```

查看原生唤醒事件：

```sh
tail -f /tmp/native_first_wakeup_events.log
```

查看状态：

```sh
sh /data/native_first_observer.sh status
```

### 10.3 停止观察模式

```sh
sh /data/native_first_observer.sh stop
```

观察日志会记录：

```text
每次 WuW 唤醒事件
旁路录音文件 /tmp/native_first_voice_*.wav
mibrain nlp_result_get 的连续轮询结果
```

## 11. Native-first 正式客户端

原生小爱优先处理。小米原生返回白名单 domain 时，直接使用小米原生回答/控制；非白名单 domain 会立即停止原生播报并把小米识别出的 `query` 发给 Mac LLM。

默认白名单：

```text
smartMiot time weather music player alarm timer system volume
```

路由优先看结构化字段：

- `domain` 是强路由信号，例如 `weather`、`smartMiot`、`soundboxControl`。
- `query` 只在 fallback LLM 时作为文本输入；原生成功场景里可能是 `token` 等内部占位值。
- `speak` 是小米原生准备播报的文本；当前默认成功 domain 后立即恢复播放器并 replay `speak`，不再额外等待。
- 已验证 `/data/mibrain/mibrain_asr_nlp.rcd` 不比 `mibrain nlp_result_get` 更早，且中文 `query/speak` 在 `strings` 输出里会断行，不适合作为正式路由来源。
- 已验证 `ubus monitor` 未看到更早的 `RESULT_ASR/RESULT_NLP` push 事件；公开可用的结构化结果来源仍是 `mibrain nlp_result_get`。

结果源按系统自动适配：

- boot0/system0：`NATIVE_RESULT_SOURCE=auto` 会选择 `ubus_nlp_result`，读取 `mibrain nlp_result_get`。
- boot1/system1：`NATIVE_RESULT_SOURCE=auto` 会选择 `aivs_lab_instruction`，读取 `/tmp/mico_aivs_lab/instruction.log` 中的 `RecognizeResult` 和 `Speak`。该路径主要用于识别需要 fallback LLM 的场景；原生成功命令仍由小爱链路直接完成。
- 启动日志会打印 `Native result: source=... selected=...`，每轮唤醒会打印 `[NATIVE] result source=...`。

### 11.1 启动

当前主客户端是：

```text
/data/native_first_client.sh
```

可选配置文件：

```text
/data/native_first.env
```

首次部署配置示例：

```sh
cp /data/native_first.env.example /data/native_first.env
vi /data/native_first.env
```

常调参数：

```sh
FOLLOWUP_ASR_ENGINE=native
FOLLOWUP_NATIVE_ASR_TIMEOUT=30
FOLLOWUP_NATIVE_ASR_FALLBACK_MAC=0
FOLLOWUP_NATIVE_MIN_QUERY_BYTES=10
FOLLOWUP_RECORD_MODE=window
FOLLOWUP_WINDOW_SECONDS=5
FOLLOWUP_WINDOW_CAPTURE_DEV=Capture
FOLLOWUP_WINDOW_CAPTURE_FORMAT=S16_LE
FOLLOWUP_WINDOW_CAPTURE_RATE=16000
FOLLOWUP_WINDOW_CAPTURE_CHANNELS=1
FOLLOWUP_WINDOW_MIN_PEAK=300
FOLLOWUP_WINDOW_MIN_RMS_THRESHOLD=40
FOLLOWUP_WINDOW_MIN_ACTIVE_PERMILLE=5
FOLLOWUP_TIMEOUT=8
FOLLOWUP_ARM_DELAY=0.2
FOLLOWUP_THRESHOLD=180
FOLLOWUP_START_HITS=1
FOLLOWUP_END_THRESHOLD=100
FOLLOWUP_SILENCE_LIMIT=3
PAUSE_NATIVE_ASR_DURING_LLM=0
WAKE_EVENT_MAX_AGE=4
WAKE_IGNORE_QUERIES="小爱同学 小爱 小爱小爱 小爱同学小爱同学 我在 在呢"
NATIVE_REPLAY_SUCCESS_SPEAK=1
NATIVE_REPLAY_SUCCESS_DELAY=0
LLM_MASTER_SCALE=145
LLM_MASTER_CURRENT_SCALE=112
```

```sh
SERVER=http://192.168.8.150:8080 BACKEND=deepseek \
sh /data/native_first_client.sh > /tmp/native_first_client.log 2>&1 &
```

### 11.2 查看状态和日志

```sh
sh /data/native_first_client.sh status
tail -f /tmp/native_first_client.log
tail -f /tmp/native_first_events.log
```

关键日志示例：

```text
[STATE] IDLE -> NATIVE_PROCESSING
[NATIVE] result after 5s ts=... domain=smartMiot action=operate query=开灯 speak=开啦。
[NATIVE] success-domain，交给小米原生
[STATE] NATIVE_HANDLED -> IDLE

[NATIVE] result after 5s ts=... domain=shopping action=query query=... speak=正在搜索
[NATIVE] non-success-domain，立即 fallback LLM
[STATE] NATIVE_PROCESSING -> NATIVE_FALLBACK
[LLM] fallback -> backend=deepseek text=...
[STATE] LLM_DIALOG -> LLM_SPEAKING
[STATE] LLM_SPEAKING -> FOLLOWUP_WINDOW
[FOLLOWUP] prearm recorder: mode=window wait_playback_done timeout=5s
[STATE] FOLLOWUP_WINDOW -> FOLLOWUP_LISTENING
[VAD] 窗口统计 peak=... rms=... active=...‰
[FOLLOWUP] Native ASR code=... text=...

[NATIVE] result after 5s ts=... domain=michat action=dialog query=小爱同学 speak=在呢
[NATIVE] ignored query result，忽略并回到待机
```

`ignored query` 只在 `query` 精确等于 `WAKE_IGNORE_QUERIES` 中的短语时触发，不根据 `speak=在呢` 等播报文案判断。这个列表用于忽略“只唤醒/唤醒应答被 ASR 写入 query”的无效输入，例如 `小爱同学`、`我在`。

连续追问当前默认使用小米原生 `ai_service` 对 `/tmp/voice.wav` 做 ASR。录音格式必须是 `S16_LE / 16000Hz / 1ch`，调用时关闭原生执行和播报，只取返回 JSON 里的 `query`：

```text
asr=1, nlp=1, tts=0, nlp_execute=0, asr_audio=/tmp/voice.wav
```

如果追问失败，优先看这几行：

```text
[VAD] 窗口统计 peak=... rms=... active=...‰
[FOLLOWUP] Native ASR code=... text=...
```

只有 `peak/rms/active` 三个指标都低于窗口门槛时，才判定“窗口无有效语音”。

LLM 会话上下文规则：

```text
一次“小爱同学”唤醒 -> 生成一个新的 session_id
本次唤醒进入 LLM 后 -> 首轮 LLM 和所有连续追问复用同一个 session_id
追问退出后再次唤醒 -> 生成新的 session_id，新会话开始
```

音箱日志里可看：

```text
[WAKE] native-first session=native_first_deepseek_...
[TURN 2] 发送追问到 LLM: ...
```

Mac 服务端日志里可看 `历史2轮`、`历史4轮` 等字样。如果历史轮数递增，说明追问在同一个 LLM 会话里。

### 11.3 停止

```sh
sh /data/native_first_client.sh stop
```
