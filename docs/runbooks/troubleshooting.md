# 排障手册

文档类型：问题定位入口  
适用范围：有唤醒但无动作、错误转 LLM、播报串台、音量异常、追问失败  
当前结论：先看音箱两份日志，再看 Mac 服务端日志；不要只凭听感改参数

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

先看 `domain`：

```text
domain=weather
domain=smartMiot
domain=soundboxControl
```

这些应该走原生成功，不应 fallback。当前策略是优先看 `domain/action`，`query` 只作为兜底文本。天气里出现 `query=token` 是小米内部值，不代表要转 LLM。

检查配置：

```sh
grep '^NATIVE_SUCCESS_DOMAINS' /data/native_first.env
```

## 5. 原生不支持时听到“还在学习中”

这是原生失败播报没有被完全拦截。重点看：

```text
NATIVE_PRE_FREEZE args=think
[NATIVE] unsupported
[NATIVE] mediaplayer frozen
[LLM] fallback
```

推荐配置：

```sh
FREEZE_NATIVE_PLAYER_ON_THINK=1
FREEZE_NATIVE_PLAYER_ON_FALLBACK=1
STOP_NATIVE_SECONDS=15
```

## 6. 原生控制播报延迟

当前为了完整拦截失败播报，会在 `think` 阶段 freeze 原生播放器。原生成功后，脚本用 `speak/to_speak` replay 播报。

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

## 9. TTS 超时

Mac 日志里如果出现 EdgeTTS 连接错误：

```text
Cannot connect to host speech.platform.bing.com
Connection timeout
```

这是 TTS 网络连接问题，不是 DeepSeek 模型本身超时。可以稍后重试，或后续考虑加入备用 TTS。

