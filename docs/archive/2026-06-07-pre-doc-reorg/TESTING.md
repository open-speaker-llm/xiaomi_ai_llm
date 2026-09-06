# 测试说明

> 2026-09-06 结论更新：boot1 不做 think 预冻结，但已通过 AIVS 失败文本匹配与 C 快速拦截实现首轮转 LLM 前无失败提示，修正版重启后经用户确认；报时对照正常。domain/action 路由主要适用于 boot0；boot1 的 michat/model 是客户端合成标记。未知文案仍可能漏判或误判，连续追问限制不在此次修复范围。详见 [实测记录](../../history/2026-09-06-boot1-fallback-guard.md)。以下保留当时记录。

测试分两层：

- 自动化测试：不依赖音箱、不需要真实 API、不需要人工说话。
- 人工测试：需要真实音箱唤醒、听播报、观察日志。

## 自动化测试

运行全部自动化测试：

```sh
./scripts/run_tests.sh
```

覆盖范围：

- `server.main`：ASR 低置信度过滤、助手回声过滤、追问 ASR 门控。
- `server.streaming_pipeline`：`<think>` 标签过滤、分句 TTS 流程。
- Shell 脚本：关键设备脚本 `sh -n` 语法检查。
- `device/native_first.env.example`：可被 shell source，关键推荐参数和客户端默认值一致。

## 人工测试

见 [tests/manual_native_first_cases.md](tests/manual_native_first_cases.md)。

人工测试主要覆盖：

- 原生成功 domain：家电控制、天气。
- 原生失败 fallback：失败播报拦截、LLM 接管。
- LLM 连续追问：追问、无追问、播放期间唤醒。
- 异常恢复：服务端不可达、hook 被卸载、客户端重启。

## 何时跑

修改以下内容时，至少跑自动化测试：

```sh
./scripts/run_tests.sh
```

修改音箱端状态机、hook、VAD、音量、fallback 逻辑时，还要跑相关人工用例。

建议映射：

| 改动范围 | 自动化测试 | 人工测试 |
|---|---|---|
| ASR 过滤 | `test_asr_quality.py` | B1, B2 |
| LLM 流式/TTS | `test_streaming_pipeline.py` | B1, B3 |
| 音箱脚本/env | `test_shell_config.py` | M1, M3, E2, E3 |
| VAD 参数 | `test_shell_config.py` | B1, B2 |
