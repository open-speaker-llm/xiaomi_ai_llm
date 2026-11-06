# S25 并行规划与正文验收

版本为基于 `f42e1dc` 的 S25 本地提交（`feat(web): 并行启动联网规划与离线正文请求`）。真人及真机验收 **未执行**。

## 准备

- 在开发机运行 `./scripts/run_tests.sh` 和 `python3 -m unittest -v tests.test_web_speculative tests.test_native_web tests.test_native_client_failure_paths`。
- 在空闲维护窗口通过既有流程备份并替换设备端客户端及对应校验清单，保持既有 ettsc。使用 native DeepSeek 自动联网、端侧句级流式，保留延迟观测。准备 `LLM_WEB_SPECULATIVE=1` 和 `0` 两组，按既有配置维护流程切换后重启客户端。

## 步骤与预期

1. 普通问答至少 3 轮，同题与关闭组对照。检查开启组普通轮为 `spec=used`，正文开口比串行组快至少 0.8 秒，目标中位数不超过 3.3 秒。规划结论前不得有候选正文 PCM 提交。
2. 明确请求搜索至少 2 轮，可加一轮指定页面的抓取。开启组应先取消候选，日志为 `spec=cancelled`，听到一次垫话和联网正文。检查垫话开口与关闭组相比没有变慢，垫话到正文间隔估计不超过 1.5 秒，无先念离线正文或杂音。
3. 一次正常播报后直接追问，检查 `start=followup`、正文开口可计算，观察重试、播放错误和断流是否增加。
4. 用既有故障注入 `LLM_WEB_TEST_FAULT=plan_timeout` 分别验证两种兜底。 `answer` 复用候选并保留规划重试垫话，`fail` 取消候选并仅在垫话后播固定失败提示。关闭注入后确认正常问答恢复。

## 失败记录与恢复

记录提交、分区、轮次、开关、播放器状态、脱敏的 SANITIZED EVENTS 与本批次的 `[LATENCY]`。记录是否提前听到离线正文、是否有杂音及发生时的 `spec`。分享前移除问答原文、密钥、URL query、设备标识及 token。

设 `LLM_WEB_SPECULATIVE=0` 并重启客户端恢复串行请求。撤销故障注入并重启。若需回退客户端，按部署流程恢复成组备份及匹配校验清单。
