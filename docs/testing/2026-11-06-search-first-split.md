# S24 搜索正文首段提前切分验收

版本为基于 `a5c7583` 的 S24 本地提交（`fix(tts): 让搜索和普通正文共用首段切分规则`）。真人及真机验收 **未执行**。

## 准备

- 开发机运行 `./scripts/run_tests.sh`。专项运行 `python3 -m unittest -v tests.test_web_filler_cache tests.test_latency_trace tests.test_tts_early_start tests.test_native_client_failure_paths.WebClientIntegrationTest`。搜索桩覆盖内联与缓存垫话、无标点长正文、UTF-8 边界及 PCM 告警，故障桩确认固定联网错误提示保持原分句。
- 核对测试音箱与当前分区，空闲时通过既有维护流程备份并替换设备端客户端，然后重启客户端。使用 native + device 句级流式，维持现有搜索与 ettsc 配置。确认 `LATENCY_TRACE_ENABLED=1`，首段切分采用默认值 `1 / 8 / 24 / 1`。

## 步骤与预期

1. 物理唤醒后做普通问答 3 轮。问能引出长开头的问题。记录 `[LATENCY]` 中正文首段的 `pcm1`、`split1` 和 `wake→answer_commit`，并听首段停顿。
2. 做实际触发搜索的问答 2 轮。确认每轮垫话只播一次且在正文前。正文首段不超过 24 个 UTF-8 字符，搜索轮首段 PCM 与普通轮同量级，日志无 `[WARN] sent1_too_long`。在 `/tmp/native_first_stream/marks` 中，内联垫话的正文从 `sent2_pcm_bytes` 读取，其余路径从 `sent1_pcm_bytes` 读取。下一轮会覆盖该文件。
3. 在一次正常播报后的追问窗口继续说，确认追问正常播报并沿用正文首段规则。记录首段是否出现明显断句、漏字或重复。
4. 可关闭 `STREAM_FIRST_SPLIT_ENABLED` 后以同类问题做听感对照，核对旧的 `。！？` 切句与搜索垫话顺序。

## 失败记录与恢复

记录提交、分区、轮次、垫话路径、正文首段字符数与 PCM 字节数、实际听感、相关 `[LATENCY]` 行和脱敏后的 `SANITIZED EVENTS`、`PLAYBACK STATUS`。若出现告警，附该行的字节数和预算。分享前移除问答原文、密钥、URL query、设备标识及 token。

将 `STREAM_FIRST_SPLIT_ENABLED` 设为 `0` 并重启客户端即可恢复旧切句规则。也可恢复准备阶段备份的客户端与配置后重启。
