# S30 追问收尾与播放时序验收

适用版本为基于 `61ca40b` 的 S30 提交。真人与扬声器端到端验收 **未执行**。

## 准备

- 运行 `./scripts/run_tests.sh`。单独回归可运行 `.venv/bin/python -m unittest -v tests.test_native_playback_parallel tests.test_native_asr_control tests.test_route_beep tests.test_latency_trace tests.test_tts_stream_commit tests.test_web_speculative`。
- 在 boot1 上使用同版客户端和包含物理唤醒证据的组合原生组件。组合 SO 由 `device/endpoint_probe/build_native_wake.sh` 构建。按维护流程成组备份、校验和替换。
- 保留原音量，开启延迟打点。使用 24 kHz、S16_LE、单声道的 1.30 秒测试素材覆盖长提示音。在 S28b 与 S30 使用同题、同配置各采至少三轮普通及搜索回答。

## 步骤与预期

1. 追问窗口静默超时，核对 `[WAKE] ignored reason=followup_teardown event=think`，随后没有新会话、蓝灯或无结果等待。
2. 在追问超时边界真实喊“小爱同学”，分别覆盖追问仍有效及刚结束的时刻。真实 `WuW` 或带物理唤醒证据的 `think` 应继续进入正常路由。
3. 复测只有 `think` 的常规唤醒，确认有效的新原生结果仍可接管。没有新版物理唤醒证据时，兼容旧版事件处理。
4. 让原生否定回复已经开口。确认语句播完后才冻结、设置 Master 和触发提示音。如果不能确认播报完成，该轮继续交由原生。另测原生失败语音已在分发前拦截的轮次，确认仍走提前接管。
5. 普通和搜索轮分别检查同一 aplay 的 PCM 顺序。第一段语音若在长提示音结束前就绪，`beep_overlap=1`，应立即进入语音并淡出未提交的提示音。记录 `beep_drain`、`player_spawn`、`player_fifo_open`，对照 `player_spawn→player_fifo_open ≤0.7s` 和 S28b 的垫话、正文提交时间。等待已经开始的原生播报属于另一组安全用例。
6. 若出现欠载，对照 aplay 日志、全部 `player_underrun_at`、首次报告时间和阶段。报告时刻可晚于实际断流起点。

## 失败记录和恢复

保留设备分区、提交、播放器 stderr、脱敏的事件日志和 `[LATENCY]`，注明真实听感及是否有重叠或截断。临时关闭提示音可用 `LLM_ROUTE_BEEP=0` 后重启。整组回退需恢复客户端、组合 SO 和对应的校验清单。
