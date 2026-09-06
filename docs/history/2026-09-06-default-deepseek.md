# 2026-09-06 恢复 DeepSeek 默认后端

按用户要求，音箱默认恢复 `deepseek-v4-flash`，MiniMax、GLM、Kimi 保留为手动备选。
已清理 `/data/native_first.env` 中固定的 `LLM_API_BASE`、`LLM_MODEL`、`LLM_API_KEY`，
保留各厂商独立密钥和唯一的 `BACKEND=deepseek`。之后只改 BACKEND 并重启即可切换。
高级通用覆盖项仍受支持，但启用后优先于后端默认值。

配置模板同步采用同一方式。Mac 辅助服务通过 `config.yaml` 的
`llm.default_backend` 选择默认后端，默认值为 `deepseek`，不再依据密钥存在顺序自动选厂商。
原有显式 backend 请求仍按所选厂商处理。

验证：音箱使用候选配置直连 DeepSeek，返回“DeepSeek 已接入。”，含 SSH 耗时约 1.57 秒。
50 项单元测试及 shell 语法检查通过；新增测试加载实际模板，只修改 BACKEND，
验证四个后端分别选择正确地址、模型和密钥。旧测试的固定 LLM_MODEL 文本断言被此运行行为测试替代。

切换前 Kimi 配置和运行日志备份：`/data/deepseek-default-backup-20260906-201436/`。
此次仅部署运行配置，未更改音箱脚本、TTS、追问组件或固件。
操作步骤见 [日常运维：切换 LLM](../runbooks/operations.md#切换-llm默认-deepseek)。

## 后续语音验证汇总

- MiniMax：19:47 会话保存“呼叫 MINI MAX”的正式回答，切换前配置匹配 MiniMax M2.7；完整运行日志已被当时重启覆盖。
- GLM：19:50 日志确认 `glm-5.3-flash` 调用及 5 段语音播放，首个内容 28.71 秒、首声约 30.42 秒。
- Kimi：20:08 呼叫及后续两轮追问成功，20:10 新会话调用 `kimi-k2.6` 并播放 4 段语音，首声约 4.44 秒。20:09 的一轮追问出现空回答/调用失败，原因未确定，下一会话恢复成功。
- DeepSeek：20:17 日志确认 `deepseek-v4-flash` 调用及 3 段语音播放，首个内容 0.70 秒、首声约 2.71 秒，之后回到 IDLE。

以上是不同问题的单次观测，不能作为模型性能横向排名。模型口头回答的版本名称与请求模型 ID 可能不一致，判断路由以实际配置及调用日志为准。
