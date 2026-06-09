# Native-first 架构说明

文档类型：当前主线架构  
适用范围：理解为什么先走小米原生、什么时候转 LLM、boot0/boot1 如何兼容  
当前结论：路由依据优先是小米原生结构化结果，不是文本关键词

## 1. 目标

native-first 不是重写一个小爱，而是把小爱已经做得稳定的部分留下：

- 高质量唤醒：“小爱同学”
- 小米原生 ASR/NLP
- 家电、音量、天气等原生能力
- 原生执行链路里的设备上下文

LLM 只接管小米原生不擅长的开放问答。

## 2. 主流程

```text
用户说“小爱同学”
  -> /bin/wakeup.sh 被原生链路调用
  -> native_first_client.sh 的 hook 记录 WuW/think/ready 事件
  -> 小米原生 ASR/NLP 得到结构化结果
  -> native_first_client.sh 读取结果
       -> 成功 domain：交回原生/replay speak
       -> 不支持 domain 或失败文案：拦截原生播报，转 LLM
  -> Mac 服务端生成 LLM TTS
  -> 音箱播放
```

## 3. 路由标准

优先级：

1. `domain/action`：判断原生是否支持。
2. `speak/to_speak`：原生成功播报内容。
3. `query`：只在 fallback 到 LLM 时作为文本输入。
4. 文本关键词：只作为最后兜底，不作为主判断依据。

典型成功 domain：

```text
smartMiot
soundboxControl
weather
time
music
player
alarm
timer
system
volume
```

典型 fallback：

```text
michat
qabot
shopping
nonsense
```

这些 domain 不一定永远失败，但当前实测里经常对应“还在学习中”“正在搜索”等非目标能力，所以会进入 fallback 或继续观察。

## 4. 为什么 query 不能作为主判断

日志里可能出现：

```text
domain=weather action=query query=token speak=杭州上城今天...
```

这里 `query=token` 是小米内部字段，不代表用户真的说了 token。真正应该播报的是 `speak`，真正应该判断的是 `domain=weather`。

## 5. boot0 与 boot1 兼容

同一份 `/data/native_first_client.sh` 会面对两套不同用户态：

| 系统 | rootfs | 小米 ROM | 结果源倾向 |
|---|---|---|---|
| boot0/system0 | `/dev/mtdblock4` | 1.54.8，2019 | `ubus_nlp_result` |
| boot1/system1 | `/dev/mtdblock5` | 1.76.54，2023 | `aivs_lab_instruction` |

当前配置：

```sh
NATIVE_RESULT_SOURCE=auto
NATIVE_AIVS_LAB_RESULT_SYSTEM1=1
```

脚本会自动识别 rootfs 来选择结果源。

## 6. 播放控制

为了避免原生失败播报和 LLM 串台，脚本会：

- 在 `think` 阶段 freeze `mediaplayer`。
- 拿到原生结果后判断路由。
- 原生成功：resume 播放器，并按需要 replay `speak`。
- 原生失败：保持拦截，调用 Mac LLM。

控制类短播报支持“下一次唤醒取消旧播报”，避免用户已经进入下一轮对话时又听到上一轮“开啦/关啦”。

## 7. 连续追问状态

当前追问不是最终方案：

- boot0：本地录音追问可实验，但稳定性依赖录音链路。
- boot1：默认关闭追问，保证主流程。
- 已验证 native multirounds/reopen 方向尚未走通。
- 更值得继续探索的是从小米链路获取处理后的干净音频。

历史结论见 [history/NATIVE_FOLLOWUP_EXPLORATION.md](history/NATIVE_FOLLOWUP_EXPLORATION.md)。

