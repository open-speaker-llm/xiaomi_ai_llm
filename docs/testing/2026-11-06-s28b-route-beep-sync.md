# S28b 提示音时序与响度验收

适用版本为 S28b 提交，基于 `33e8579`。真人与音箱端到端验收 **未执行**。

## 准备

- 在电脑上运行 `./scripts/run_tests.sh`。用 `python3 scripts/embed_route_beep.py --pcm /tmp/route-beep.pcm` 导出默认素材。
- 从音箱取一段完整的典型 TTS PCM，例如垫话。文件应为 24 kHz、S16_LE、单声道，已经过实际端侧 TTS 数字增益。运行 `python3 tools/route_beep_calibration.py /tmp/route-beep.pcm /tmp/reference.pcm`，默认配置预期差值在 ±3 dB 内。计算包含文件内的间隔和静音。
- 按设备维护流程备份并安装 S28b 客户端。保留原音量，启用 `LATENCY_TRACE_ENABLED=1`，用手机录像同时采集灯光和声音。

## 步骤和预期

1. 用会触发 early failure 的问法确认日志出现 `failure Speak suppressed before dispatch`。核对路由确认后 ≤100 ms 开始提交提示音，`wake→beep` ≤0.9 秒，`beep_commit` 与 `led_green` 差 ≤0.15 秒。原生播报应无叠音。
2. 用其他转 LLM 的路径复测。提示音在冻结后提交，`wake→beep` ≤1.3 秒。用录像确认实际起音和绿灯接近，响度与回答相当。
3. 普通、搜索各复测，核对提示音、垫话和正文按序，无爆音、截断或额外欠载。比对旧版的 `llm_req`、`spec_start`、`player_start` 和 `answer_commit`，正文提交增加不超过 0.1 秒。
4. 复测原生成功、无结果、追问默认设置和提示音关闭。预热阶段无 PCM 输出。原生成功仍需确认与预热播放器共存时的出声、音量和首声时序。

## 失败记录与恢复

保留设备分区、版本、脱敏后的 `[LATENCY]`、LED 日志和录音。区分软件提交与实际出声。临时关闭可设 `LLM_ROUTE_BEEP=0` 并重启。恢复旧行为使用部署前的客户端和对应校验清单。
