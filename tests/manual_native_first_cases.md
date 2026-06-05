# Native-first 人工测试用例

这些用例需要真实音箱、真实唤醒和听感判断。执行前先确认：

```sh
tail -f /tmp/native_first_client.log /tmp/native_first_events.log
```

客户端启动日志应包含：

```text
[HOOK] mounted /bin/wakeup.sh -> /tmp/wakeup.sh.native_first_client
[HOOK] watchdog pid=...
[IDLE] 等待原生唤醒词：小爱同学
```

## 主流程

### M1. 原生家电控制

说：

```text
小爱同学，开灯
```

期望：

- 家电控制成功。
- 日志出现 `domain=smartMiot` 或其他原生成功 domain。
- 日志出现 `success-domain`。
- 没有进入 `[LLM] fallback`。
- 播报延迟可接受。

### M2. 原生天气问答

说：

```text
小爱同学，今天天气怎么样
```

期望：

- 播放天气结果。
- 日志出现 `domain=weather`。
- 日志出现 `replay native speak`。
- 没有进入 LLM。

### M3. 原生不支持后 fallback LLM

说：

```text
小爱同学，电脑怎么关机
```

期望：

- `think` 阶段出现 `NATIVE_PRE_FREEZE`。
- 不应听到“这个问题我还在学习中”等原生失败播报。
- 日志出现 `unsupported` 或 `non-success-domain`。
- 日志出现 `[LLM] fallback`。
- LLM 正常播报。

## 分支流程

### B1. 呼叫 DeepSeek 后追问

先说：

```text
小爱同学，呼叫 DeepSeek
```

听到 LLM 响应后，在追问窗口内说：

```text
Mac 电脑怎么重启
```

期望：

- 日志出现 `FOLLOWUP`。
- 日志出现 `mode=window`、`窗口统计 peak=... rms=... active=...‰`。
- 日志出现 `Native ASR code=... text=Mac电脑怎么重启` 或相近文本。
- 不应录到 LLM 尾音。
- 追问进入 LLM。

### B2. 呼叫 DeepSeek 后不说话

先说：

```text
小爱同学，呼叫 DeepSeek
```

LLM 播放完成后保持安静。

期望：

- 最终日志出现 `窗口无有效语音，超时退出` 或 `Native ASR ... text=<empty>`。
- 不应调用 LLM 追问。

### B3. LLM 播放期间再次唤醒

在 LLM 正在播放时说：

```text
小爱同学
```

期望：

- 日志出现 `NATIVE_WAKE_IGNORED_BUSY` 或类似 busy 忽略。
- 不应打断当前 LLM 播放。
- 不应串台或重复上一轮问题。

## 异常流程

### E1. Mac 服务端不可达

临时停止 Mac 服务端后，说：

```text
小爱同学，电脑怎么关机
```

期望：

- 原生失败播报仍被拦截。
- 日志里能看到服务端不可达或 curl 超时。
- 客户端最终恢复到 `IDLE`。

### E2. hook 被卸载后的恢复

手动卸载 hook：

```sh
umount /bin/wakeup.sh
```

等待 2 到 3 秒。

期望：

- 日志出现 `[HOOK] missing，重新挂载 /bin/wakeup.sh`。
- `mount | grep ' /bin/wakeup.sh '` 能看到 bind mount。
- 后续唤醒仍能进入 native-first。

### E3. 重启客户端

执行：

```sh
pid=$(cat /tmp/native_first_client.pid 2>/dev/null)
[ -n "$pid" ] && kill -9 "$pid"
SERVER=http://192.168.8.150:8080 BACKEND=deepseek sh /data/native_first_client.sh > /tmp/native_first_client.log 2>&1 &
```

期望：

- 只有一个主客户端和一个 watchdog。
- hook 已挂载。
- 唤醒后日志正常。
