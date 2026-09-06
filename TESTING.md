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
- 追问实验：仅在明确开启追问时测试。

2026-09-06 的 boot1 失败提示拦截已完成用户听觉确认，修正版重启后复测通过，原生报时对照正常；24 项自动测试和设备端 16 个分类样例通过。验证范围与首版遗漏见 [实测记录](docs/history/2026-09-06-boot1-fallback-guard.md)，不能据此断言所有文案都已覆盖。

## 3. 修改后跑哪些测试

| 改动范围 | 必跑 |
|---|---|
| 服务端 LLM/TTS/ASR | `./scripts/run_tests.sh` |
| `native_first_client.sh` 状态机 | 自动化测试 + M1/M2/M3 |
| 原生路由 domain/action | 自动化测试 + M1/M2/M3 |
| 播放 freeze/replay | 自动化测试 + M1/M2/M3/B3 |
| boot1 兼容或 guard/失败文案规则 | 自动化测试 + P3/S2（含重启验证和原生报时对照） |
| 追问相关 | 自动化测试 + 追问实验用例 |

## 4. 提交前建议

```sh
./scripts/run_tests.sh
git status --short
```

如果改了文档链接，还要跑 Markdown 链接检查或手动 `rg` 检查链接。

