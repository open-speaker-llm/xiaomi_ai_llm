# 2026-09-06 GLM-5.3-Flash 接入

按用户选择，将音箱默认 LLM 从 MiniMax M2.7 切换为 `glm-5.3-flash`，保留 MiniMax 密钥和接入代码。
设备配置使用 `BACKEND=glm`、`LLM_API_BASE=https://open.bigmodel.cn/api/paas/v4`、
`LLM_API_KEY=$GLM_API_KEY`、`LLM_REASONING_EFFORT=low`。GLM 和 MiniMax 的密钥不进入版本库。

## 参数验证与实现

初次使用已有 `thinking.type=disabled` 请求，官方接口返回 HTTP 400、错误码 1210：
“该模型始终思考，不支持关闭思考；请使用 low、high 或 max。”
改为 `thinking.type=enabled`、`reasoning_effort=low` 后，HTTP 200，
流式正式回答为“GLM 已接入。”，`finish_reason=stop`，Mac 请求约 1.68 秒。

设备端为 GLM 增加独立密钥、地址和模型默认值，以及模型专用请求参数；
流式解析沿用上一轮的 content 提取，仅播报正式回答。可选 Mac 服务端也注册 `glm`，
配置了 GLM key 时优先作为默认 LLM，显式 `backend=minimax` 仍可选择 MiniMax。
直接呼叫词保留 DeepSeek/MiniMax，并增加 `GLM|glm|智谱|智普`。
这些呼叫词都进入当前默认后端，不代表按说出的厂商名自动切换模型。

## 实机验证

- 音箱使用实际 BusyBox shell、请求构造及流式解析直连 GLM，返回“GLM 已接入。”，该次含 SSH 的请求耗时约 8.06 秒。
- 19:49 重启日志为 `Backend: glm`、`native ASR-only ready; no external recognizer`、`[IDLE]`。
- 后续独立 SSH 连接确认进程仍在，实际模型是 `glm-5.3-flash`，当前密钥匹配 GLM，MiniMax 密钥仍保留。
- 部署脚本 SHA256：`2dd962cda49851e1c8d7f35fdd66cb8dbe4f30238294bc3f49cfa41614b3b500`。
- 48 项单元测试及 shell 语法检查通过，覆盖三个模型的请求参数和 GLM 独立密钥选择。
- 现场语音唤醒到实际可听播报仍待用户试用；本次没有修改 TTS、原生追问组件或固件。

## 配置与回退

当前配置在 `/data/native_first.env`，权限 600；Mac key 保存在本地忽略文件 `.env`，权限 600。
切换前 MiniMax 配置及客户端备份在 `/data/glm-backup-20260906-194842/`。
需要回退时，在音箱空闲时停止助手，将该目录内配置与客户端恢复到 `/data/`，再运行 `sh /data/init.sh`。
现有自启动继续读取当前配置。没有配置模型调用失败后的自动跨厂商切换。

官方资料：[OpenAI 兼容接口](https://docs.bigmodel.cn/cn/guide/develop/openai/introduction)。
该模型的思考限制以上述实时 API 反馈为准。
