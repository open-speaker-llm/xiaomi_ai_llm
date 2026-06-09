# Native-first 人工测试用例

文档类型：真实音箱测试清单  
适用范围：需要人工唤醒、听播报、观察日志的场景  
当前结论：主流程先测原生成功和首轮 LLM；追问是实验项，不作为 boot1 稳定验收项

## 0. 测试前准备

看日志：

```sh
tail -f /tmp/native_first_client.log /tmp/native_first_events.log
```

启动成功应看到：

```text
[HOOK] mounted /bin/wakeup.sh -> /tmp/wakeup.sh.native_first_client
[HOOK] watchdog pid=...
[IDLE] 等待原生唤醒词：小爱同学
```

## 1. 主流程

### M1. 原生家电控制

说：

```text
小爱同学，开灯
```

期望：

- 家电动作成功。
- 日志出现 `domain=smartMiot` 或其他成功 domain。
- 日志出现 `success-domain`。
- 不进入 `[LLM] fallback`。

### M2. 原生天气

说：

```text
小爱同学，今天天气怎么样
```

期望：

- 播放天气结果。
- 日志出现 `domain=weather`。
- 不进入 LLM。

### M3. 原生不支持后转 LLM

说：

```text
小爱同学，呼叫 DeepSeek
```

期望：

- 原生失败播报被拦截，最好听不到“还在学习中”等失败文案。
- 日志出现 `unsupported` 或 `non-success-domain`。
- 日志出现 `[LLM] fallback`。
- LLM 正常播报。

## 2. 播放和串台

### P1. 控制类短播报取消

先说：

```text
小爱同学，关灯
```

在动作已执行但短播报还没出来前，再次唤醒：

```text
小爱同学
```

期望：

- 新一轮唤醒后不应再听到上一轮“关啦/搞定”。
- 天气这类纯语音回答不应被这个策略取消。

### P2. LLM 播放期间唤醒

在 LLM 正在播报时说：

```text
小爱同学
```

期望：

- 不串台。
- 不重复上一轮问题。
- 日志能看到 busy 忽略或等效保护。

## 3. boot 兼容

### S1. boot0 主流程

在 boot0/system0 下执行 M1/M2/M3。

期望：

- 结果源通常是 `ubus_nlp_result`。
- 三条主流程通过。

### S2. boot1 主流程

在 boot1/system1 下执行 M1/M2/M3。

期望：

- 结果源通常是 `aivs_lab_instruction`。
- 三条主流程通过。
- 如果配置保持推荐值，追问默认关闭。

## 4. 追问实验项

追问不是当前 boot1 稳定验收项。只有明确打开追问配置后再测。

### F1. 呼叫 DeepSeek 后追问

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
- 如果追问打开，追问文本进入同一个 LLM session。
- Mac 服务端日志中历史轮数递增，例如 `历史2轮`。

### F2. 呼叫 DeepSeek 后不说话

先说：

```text
小爱同学，呼叫 DeepSeek
```

LLM 播放完成后保持安静。

期望：

- 不应凭噪声触发追问。
- 不应自动调用 LLM。

## 5. 异常恢复

### E1. Mac 服务端不可达

停止 Mac 服务端后说：

```text
小爱同学，呼叫 DeepSeek
```

期望：

- 原生失败播报仍尽量被拦截。
- 日志里能看到服务端不可达或 curl 超时。
- 客户端最终回到 `IDLE`。

### E2. hook 恢复

手动卸载 hook：

```sh
umount /bin/wakeup.sh
```

期望：

- watchdog 重新挂载 hook。
- 后续唤醒仍能进入 native-first。

