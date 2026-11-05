# S27 追问与垫话延迟验收

版本为基于 `2612518` 的 S27 本地提交（`fix(llm): 修正追问起点与垫话延迟汇总`）。真人及真机验收 **未执行**。

## 准备

- 开发机运行 `./scripts/run_tests.sh`，专项运行 `python3 -m unittest -v tests.test_latency_trace tests.test_web_filler_cache tests.test_tts_early_start tests.test_native_asr_shell`。
- 确认测试音箱及分区，空闲时按现有维护流程备份并替换 `device/native_first_client.sh` 对应的设备客户端，再重启客户端。保留现有配置和 ettsc。使用原有 native + 端侧流式与联网搜索设置，并确认 `LATENCY_TRACE_ENABLED=1`。
- 若需要离线百分位统计，将 `device/latency_summary.sh` 上传到测试音箱并用 `sh` 运行；它默认读取 `/tmp/native_first_latency.log`。记录开始验收的日志时间或行号。

## 步骤与预期

1. **普通问答 3 轮。** 每轮物理唤醒并问一个无需联网的问题。预期 `start=wake`。首段正常 PCM 播放时，`split1`、`commit1`、`wake→commit1` 有数值，无垫话时 `filler→answer_gap=-`。
2. **搜索 2 轮。** 各问一个应触发搜索的问题，确认听到垫话、再听到正文。记录使用的垫话路径（内联、缓存或提前提交）。两段都走 PCM 时，`wake→filler_commit` 和 `wake→answer_commit` 有数值，`split1` 和 `commit1` 对应正文首段。用两次提交的间隔减去垫话 PCM 秒数，与 `filler→answer_gap` 核对，负差按零计，`filler→answer_gap_kind=est`。录音可另行核对实际静音，估算值会受播放器缓冲影响。
3. **连续追问 1 轮。** 首轮播报后，直接在追问窗口继续说，不重复唤醒。预期追问汇总 `start=followup`、`wake→route=0.000`，正常 PCM 开口时 `wake→commit1` 有数值。下一次物理唤醒仍应为 `start=wake`。
4. 每轮核对实际播报的段序、次数及异常。若垫话或正文首段走原生兜底，涉及该段 PCM 提交的字段允许为 `-`。

## 失败记录与恢复

记录测试提交、分区、轮次、垫话路径、实际听感、该批次的全部 `[LATENCY]` 行，以及脱敏的 `SANITIZED EVENTS` 和 `PLAYBACK STATUS`。如需重算，保留当轮 `/tmp/native_first_stream/marks` 的数值事件，下一流式轮会覆盖它。分享前移除问答原文、密钥、URL query、设备标识与 token。

如需停止新增观测，按现有配置维护流程设 `LATENCY_TRACE_ENABLED=0` 并重启客户端。如需完整恢复旧版计时口径，恢复备份客户端及原有配置后重启。
