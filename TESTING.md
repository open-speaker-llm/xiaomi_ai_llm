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

## 3. 修改后跑哪些测试

| 改动范围 | 必跑 |
|---|---|
| 服务端 LLM/TTS/ASR | `./scripts/run_tests.sh` |
| `native_first_client.sh` 状态机 | 自动化测试 + M1/M2/M3 |
| 原生路由 domain/action | 自动化测试 + M1/M2/M3 |
| 播放 freeze/replay | 自动化测试 + M1/M2/M3/B3 |
| boot1 兼容 | 自动化测试 + boot1 人工用例 |
| 追问相关 | 自动化测试 + 追问实验用例 |

## 4. 提交前建议

```sh
./scripts/run_tests.sh
git status --short
```

如果改了文档链接，还要跑 Markdown 链接检查或手动 `rg` 检查链接。

