# 排障手册

文档类型：问题定位入口  
适用范围：有唤醒但无动作、错误转 LLM、播报串台、音量异常、追问失败  
当前结论：先看音箱两份日志，再看 Mac 服务端日志；不要只凭听感改参数

## SSH 连接被拒绝或启动分区改变

`Connection refused` 表示连接在认证前被拒绝，尚未到校验密码或公钥的阶段。先核对路由器上的设备 IP/MAC；串口启动日志可确认实际启动的是 boot0 还是 boot1。不要仅凭旧文档的“已打通”判断当前分区已有 SSH。

如果备用系统没有 SSH，通过串口进入 U-Boot，记录启动环境，再切回已验证可用的系统。随后备份两套系统并检查 `S45sshen`、公钥挂载与 Dropbear，操作见 [双系统 SSH 与受控升级](owner-maintenance.md)。

原生 OTA 会更新另一套系统并切换启动选择，启动失败计数也可能触发切换。只有发现 boot1 或 SSH 失联，不能认定发生过自动升级。本次证据与处理结果见 [2026-09-05 恢复记录](../history/2026-09-05-ssh-ota-recovery.md)。

## 1. 必看的三份日志

音箱状态机日志：

```sh
tail -f /tmp/native_first_client.log
```

原生唤醒事件日志：

```sh
tail -f /tmp/native_first_events.log
```

Mac 服务端日志：

```sh
tail -f /tmp/server.log | grep -E '📥|🎤|🌐|🔊|🤖|✅|⚠️'
```

## 2. 启动后没反应

先看是否进入待机：

```text
[IDLE] 等待原生唤醒词：小爱同学
```

再看 hook 是否挂载：

```text
[HOOK] mounted /bin/wakeup.sh -> /tmp/wakeup.sh.native_first_client
```

如果没有：

```sh
sh /data/native_first_client.sh stop
SERVER=http://192.168.8.150:8080 BACKEND=deepseek sh /data/native_first_client.sh > /tmp/native_first_client.log 2>&1 &
```

## 3. 有“欸”但没有动作

重点看结果源：

```text
[NATIVE] result source=...
domain=...
action=...
query=...
speak=...
```

判断：

- boot0 通常使用 `ubus_nlp_result`。
- boot1 通常使用 `aivs_lab_instruction`。
- 如果长时间没有 result，先确认小米原生链路是否正常，再看 `NATIVE_RESULT_SOURCE=auto` 是否被覆盖。

## 4. 原生成功却转了 LLM

先确认结果源。以下 `domain` 检查适用于 boot0 的 `ubus_nlp_result`：

```text
domain=weather
domain=smartMiot
domain=soundboxControl
```

这些应该走原生成功，不应 fallback。这里使用 `domain/action` 与失败文本辅助路由，`query` 作为 LLM 输入。天气里出现 `query=token` 是小米内部值，不代表要转 LLM。

检查配置：

```sh
grep '^NATIVE_SUCCESS_DOMAINS' /data/native_first.env
```

boot1 使用 `aivs_lab_instruction` 时，应检查提问触发词与原生 `Speak.text` 是否误命中规则；日志里的 `michat/model` 是客户端填入的。正常原生回答含“不会/不知道”等词也可能误转。

## 5. 原生不支持时听到“还在学习中”

2026-09-06 已在 S12A 的 boot1/system1（ROM 1.76.54）实测：匹配到的小爱失败提示可被拦截并转 LLM，修正版重启后用户确认正常转接、没有先播失败提示。部署和版本证据见 [实测记录](../history/2026-09-06-boot1-fallback-guard.md)。再次漏播应排查版本、helper、配置与文案，不应直接认定 boot1 不支持拦截。

这是原生失败播报没有被完全拦截。boot0 重点看：

```text
NATIVE_PRE_FREEZE args=think
[NATIVE] unsupported
[NATIVE] mediaplayer frozen
[LLM] fallback
```

boot0 配置（boot1 仍需开启 fallback 冻结，但跳过 think 预冻结）：

```sh
FREEZE_NATIVE_PLAYER_ON_THINK=1
FREEZE_NATIVE_PLAYER_ON_FALLBACK=1
STOP_NATIVE_SECONDS=15
```

boot1 会跳过 think 预冻结，因此仅设置 `FREEZE_NATIVE_PLAYER_ON_THINK=1` 无法关闭漏播。可部署 [AIVS 快速拦截器](../../device/aivs_guard/README.md)，查看 `/tmp/native_first_aivs_guard.log` 是否出现 `GUARD_BLOCK`，再用实际听觉测试验证。没有 helper 时仍使用原轮询。

如果完全没有转 LLM，还要核对失败文案是否匹配 `UNSUPPORTED_PATTERNS`。例如“这可把我难住了，看来要更努力学习了”曾漏掉；后续复测又出现“被难住了诶，看来我还要再学习一下”；新版按“难住 / 问住”和第一人称再次学习的表达族识别，不只列举一条原句。不要用修改 ASR 结果来掩盖分类缺失。

判定仍依赖文本规则，未知文案可能漏判，正常回答含相似词也可能误判；不保证所有文案、时序或固件都无漏音。LLM 请求与播报期间 guard 受 busy 标记保护，LLM 回答本身不走这套文本分类。

## 6. 原生控制播报延迟

boot0 为拦截失败播报，会在 `think` 阶段 freeze 原生播放器；原生成功后按配置 replay `speak/to_speak`。boot1 不采用 think 预冻结，guard 只在失败文案命中后暂停播放器。

控制类短播报可被下一次唤醒取消：

```sh
NATIVE_REPLAY_CANCEL_ON_WAKE=1
NATIVE_REPLAY_CANCEL_DOMAINS="smartMiot soundboxControl volume system"
```

不要把天气这类纯语音回答放进取消列表，否则可能导致天气结果不播报。

## 7. LLM 音量忽大忽小

看音量映射日志：

```text
[AUDIO] native media volume=...
[AUDIO] set LLM Master ...
[AUDIO] restore native Master=...
```

推荐让 LLM 跟随原生音量：

```sh
LLM_MASTER_VOLUME=auto
LLM_MASTER_SCALE=145
LLM_MASTER_CURRENT_SCALE=112
LLM_MASTER_MIN=96
LLM_MASTER_MAX=196
```

## 8. 追问失败

当前结论：

- boot0 可继续用本地录音追问方案做实验。
- boot1 默认关闭追问，优先保证原生命令和首轮 LLM 稳定。
- 原生 ASR reopen 多轮方案已经多次验证未打通。

先确认配置：

```sh
grep -E 'FOLLOWUP|SYSTEM1_FOLLOWUP' /data/native_first.env
```

如果在 boot1：

```sh
SYSTEM1_FOLLOWUP_ENABLED=0
```

追问探索历史见 [../history/followup-exploration.md](../history/followup-exploration.md)。

## 9. TTS 路线排障

先看当前配置：

```sh
grep -E 'TTS_ENGINE|TTS_SERVER|TTS_FALLBACK_NATIVE|DEVICE_TTS' /data/native_first.env
```

也可以直接手动测当前 TTS 链路：

```sh
sh /data/native_first_client.sh tts_test "TTS 链路测试。"
```

### 9.1 Mac/迷你 TTS 服务端不通

`TTS_ENGINE=server` 时，音箱会访问 `TTS_SERVER/api/v1/tts/stream`。先在音箱上测健康检查：

```sh
curl -sS -m 5 "$TTS_SERVER/"
```

Mac 日志里如果出现 EdgeTTS 连接错误：

```text
Cannot connect to host speech.platform.bing.com
Connection timeout
```

这是 TTS 网络连接问题，不是 DeepSeek 模型本身超时。可以稍后重试、升级 Mac 端 `edge-tts`，或临时改用 `TTS_ENGINE=device` / 原生兜底。

### 9.2 音箱端 EdgeTTS 失败

`TTS_ENGINE=device` 时，先确认二进制存在：

```sh
ls -l /data/ettsc
/data/ettsc probe
```

如果日志里看到 `403`，通常是微软提高了 EdgeTTS 的 Chromium / `Sec-MS-GEC-Version` 要求。按 [device/ettsc/README.md](../../device/ettsc/README.md) 更新 `DEVICE_TTS_GEC_VERSION` / `DEVICE_TTS_UA` / `DEVICE_TTS_ORIGIN`，无需重编。

### 9.3 原生 mibrain 兜底

保持：

```sh
TTS_FALLBACK_NATIVE=1
```

当 `server` 或 `device` 路线失败时，脚本会退回 `mibrain text_to_speech`。如果听到原生小爱音色，说明兜底生效；如果完全无声，再看日志中的 `[TTS] 微服务不可用，降级原生 mibrain`、`native fallback playback started/finished`。
