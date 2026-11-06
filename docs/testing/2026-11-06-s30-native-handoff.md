# S30 原生播报交接验收

适用版本为基于 `7805ef2` 的交接修正。原生静默等待来自 `da308bb`，在本轮修正中将其交接期限限制为 4 秒。真人与实际音频验收 **未执行**。

## 准备

- 先运行 `.venv/bin/python -m unittest -v tests.test_route_beep.RouteBeepTest.test_three_incident_queries_force_handoff_at_four_seconds`，再运行提交前检查 `./scripts/run_tests.sh`。三条原始问法的 AIVS 回放和已开口的否定播报均由该检查收集。
- 设备空闲时按维护流程成组备份活动客户端、包内副本及校验清单。确认 boot1 与原生组件匹配。启用 `LATENCY_TRACE_ENABLED=1` 后记录唤醒、灯光和实际出声。

## 先复测故障问法

1. “呼叫 DeepSeek 搜索一下最近 24 小时的财经新闻。”
2. “呼叫 DeepSeek 让他搜索一下最近 24 小时内的财经新闻。”
3. “呼叫 DeepSeek 让他查一下最近 24 小时的财经新闻。”

三轮都应实际进入 LLM。复现原生新闻持续播放时，4 秒交接期限后应出现一次 `[HANDOFF] forced reason=timeout`，停止原生后接上提示音、垫话和正文。原生播报在期限内已确认结束时，走正常交接。

## 再测其余路径

1. 测已开口的短原生否定回复。播报在交接期限内结束时应完整播完，随后才接管。测试报时、音量和家居指令，仍由原生处理。
2. 等待原生播报结束期间真实唤醒，应取消旧交接，日志为 `[HANDOFF] cancelled reason=new_wake`，并继续处理新轮。
3. 按 [S28c 验收](2026-11-06-s28c-prewarm.md)复测 early failure 的绿灯、提示音和播放器交接顺序，再验证搜索垫话及淡出、追问超时与真实唤醒。

## 失败记录与恢复

保留提交、实际问法和听感，记录 `[HANDOFF]`、`[LATENCY]`、原始 marks 及播放器日志。服务无法正常使用时成组恢复已知可用的客户端、包内副本和校验清单。
