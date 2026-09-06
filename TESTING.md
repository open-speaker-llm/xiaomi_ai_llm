# 测试说明

文档类型：测试入口  
适用范围：代码改动后的自动化回归、真实音箱人工验证  
当前结论：自动化测试覆盖不依赖音箱的逻辑；真实唤醒、播报、boot 差异必须人工测

## 1. 自动化测试

运行：

```sh
./scripts/run_tests.sh
```

覆盖：

- 服务端 ASR 质量门控。
- 服务端流式 LLM/TTS 分句处理。
- Shell 脚本语法检查。
- `device/native_first.env.example` 可被 shell source。
- 关键推荐参数与客户端默认值一致。
- boot1 guard 的 C JSON/Unicode 分类、文案回归、暂停所有权，以及 boot0/缺少 helper 的兼容行为。
- 原生 ASR 控制程序的并发、取消、空结果、旧会话、参数及状态校验；shell 的同一 session、LLM 错误退出与 boot0 隔离。
- 旧处理后 PCM 新帧/WAV/错误退出、固件门控、独立 ASR 服务及静音清队列的顺序。

## 2. 人工测试

真实音箱用例见：

```text
tests/manual_native_first_cases.md
```

人工测试覆盖：

- 原生成功：家电控制、天气。
- 原生失败：失败播报拦截、LLM fallback。
- 播放控制：LLM 播放期间唤醒、短播报取消。
- boot 差异：boot0 与 boot1 的结果源适配。
- 连续追问：boot0 录音与原生文件识别；boot1 安装 native_asr 后验收原生实时 ASR、同一上下文、静默退出、提示音与重启加载。旧 PCM + Mac 路线单独验收。

2026-09-06 的 boot1 失败提示拦截已完成用户听觉确认，修正版重启后复测通过，原生报时对照正常；24 项自动测试和设备端 16 个分类样例通过。验证范围与首版遗漏见 [实测记录](docs/history/2026-09-06-boot1-fallback-guard.md)，不能据此断言所有文案都已覆盖。

2026-09-06 boot1 处理后 PCM 连续追问已完成同一 session 的用户实测，并在音箱重启后再次通过。33 项自动测试通过；退出时轻微残留声音的补充修复已获用户确认，独立追问 ASR 另增加现场低置信度误识别回归，见 [实测记录](docs/history/2026-09-06-boot1-pcm-followup.md)。

## 3. 修改后跑哪些测试

| 改动范围 | 必跑 |
|---|---|
| 服务端 LLM/TTS/ASR | `./scripts/run_tests.sh` |
| `native_first_client.sh` 状态机 | 自动化测试 + M1/M2/M3 |
| 原生路由 domain/action | 自动化测试 + M1/M2/M3 |
| 播放 freeze/replay | 自动化测试 + M1/M2/M3/B3 |
| boot1 兼容或 guard/失败文案规则 | 自动化测试 + P3/S2（含重启验证和原生报时对照） |
| 追问相关 | 自动化测试 + F1/F2；boot1 原生组件另跑 F-NATIVE 与独立设备 ABI/提示音隔离测试；修改旧 PCM 路线时跑 F-PCM |

## 4. 提交前建议

```sh
./scripts/run_tests.sh
git status --short
```

如果改了文档链接，还要跑 Markdown 链接检查或手动 `rg` 检查链接。


2026-09-06 原生 ASR 连续追问集成：42 项本地自动测试及独立设备 ABI/隔离测试通过，自动短播报后的续听与静默退出通过。Mac 识别服务停止期间验证。重启自启动通过；用户实测“介绍杭州西湖”后直接追问“那什么时候去呢”，原生 ASR 与同一 LLM session 已接续成功。该轮发现的“欸”提示音已补充直接 ALSA 播放路径的隔离，15 项设备提示音测试通过，修复后的听觉验收以 [本轮记录](docs/history/2026-09-06-boot1-native-followup.md) 为准。
