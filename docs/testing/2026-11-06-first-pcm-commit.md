# S26 正文首段 PCM 提前提交验收

版本为基于 `1569ee9` 的 S26 本地提交（`feat(tts): 正文首段边解码边提交 PCM`）。真人及真机验收 **未执行**。

## 准备

- 开发机运行 `./scripts/run_tests.sh` 和 `python3 -m unittest -v tests.test_tts_stream_commit tests.test_web_speculative tests.test_tts_sentence_recovery tests.test_tts_persistent tests.test_tts_prewarm`。
- 从 `device/ettsc` 运行 `cargo test --locked` 和仓库的 ARM 构建脚本 `./build.sh`。在设备空闲窗口按维护流程备份并成组更新客户端、校验清单及实际被客户端使用的 ettsc，重启客户端。
- 使用 native + device 句级流式、24 kHz PCM 和默认 MP3 格式。打开延迟记录，先用 `DEVICE_TTS_STREAM_COMMIT=0` 采对照，再用默认 `1` 和 `DEVICE_TTS_STREAM_MIN_MS=300` 复测同题。

## 步骤与预期

1. 普通问答至少三轮，比较 `tts1_to_commit` 和 `wake→answer_commit`，提前提交目标约省 0.4–0.5 秒。对照 `tts1_first` 和完整合成 `tts1`，确认首段音频到达阈值后才写 FIFO。后续段按原顺序整段交付。
2. 搜索至少两轮，确认只播一次垫话，S25 取消的候选正文无音频。检查垫话在授权正文之前，正文首段仍可提前提交。再做连续追问一轮，核对开口和首包时长。
3. 检查 `player_underrun` 及实际播放器状态，正常目标为零。若首段短暂无新 PCM，等待后续 PCM，期间不写入填充数据。
4. 在隔离故障桩验证首段提交后断流。已提交前缀相同的重试只追加余音，记录 `stream_commit_abort`。重试前缀无法对齐且预算耗尽时，停止该轮并保留已播音频，无完整历史。首次提交前失败仍可整句原生补播。

## 失败记录与恢复

记录提交、分区、开关、轮次、脱敏 `[LATENCY]`、SANITIZED EVENTS 与 PLAYBACK STATUS。记录听到的等待、断句或重复以及是否出现 `stream_commit_abort`。分享前移除问答原文、密钥、URL query、设备标识与 token。

设置 `DEVICE_TTS_STREAM_COMMIT=0` 并重启恢复旧提交时序。需要整组回退时恢复备份客户端、校验清单和 ettsc。
