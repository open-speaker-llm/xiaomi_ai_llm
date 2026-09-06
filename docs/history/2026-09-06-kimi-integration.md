# 2026-09-06 Kimi 接入

按用户选择，将音箱默认后端切为 Kimi，保留 GLM、MiniMax 和 DeepSeek 的密钥与接入代码。
官方模型列表接口返回 `kimi-k3`、`kimi-k2.6`、`kimi-k2.7-code` 和 `kimi-k2.7-code-highspeed`。
本次选择支持非思考模式的 `kimi-k2.6` 用于语音对话，固定发送
`thinking.type=disabled` 与 `temperature=0.6`，沿用现有纯回答多轮历史。

设备当前配置在 `/data/native_first.env`：

```sh
BACKEND=kimi
LLM_PIPELINE=native
LLM_API_BASE=https://api.moonshot.cn/v1
LLM_MODEL=kimi-k2.6
LLM_API_KEY=$KIMI_API_KEY
```

密钥在设备私密配置和本地忽略文件 `.env` 中，权限均为 600，不写入源码。
设备为 Kimi 增加独立默认配置和请求参数，可选 Mac 服务端注册 `kimi` 并在配置密钥时优先使用。
原有直接呼叫词保留，并追加 `Kimi|KIMI|kimi|基米|奇米`；呼叫词只触发当前默认后端，不自动选择厂商。

## 验证

- 新密钥调用官方 `/models` 返回 HTTP 200。
- Mac 非思考流式请求返回 HTTP 200、“Kimi 已接入。”、`finish_reason=stop`，耗时约 1.84 秒。
- 音箱用实际 shell 请求构造和 SSE 解析器直连，返回“Kimi 已接入。”，含 SSH 耗时约 1.99 秒。这是短测试请求，不代表所有问题的响应时间。
- 20:07 重启日志确认 `Backend: kimi`、`native ASR-only ready; no external recognizer` 和 `[IDLE]`。
- 独立 SSH 复查确认助手仍在运行，`LLM_API_KEY` 匹配 Kimi，GLM/MiniMax 密钥仍存在。
- 部署脚本 SHA256：`200d634e7d55071976650ecc90926a47695d2d26fab51876553c0efddb04d5ad`。
- 49 项单元测试及 shell 语法检查通过，覆盖四个模型的参数、Kimi 独立密钥、流式解析和现有音箱功能。
- 实际语音唤醒、播报和追问体验待用户现场测试；本次未修改 TTS、原生追问组件或固件。

## 备份与回退

切换前 GLM 配置、脚本及运行日志保存在 `/data/kimi-backup-20260906-200700/`，目录权限 700。
需要回退时，在音箱空闲时停止助手，恢复该目录内 `native_first.env` 和
`native_first_client.sh` 到 `/data/`，再运行 `sh /data/init.sh`。
`client-before.log` 与 `events-before.log` 保存切换前语音测试证据。

官方资料：[模型列表](https://platform.kimi.com/docs/models)、[对话接口](https://platform.kimi.com/docs/api/chat)。
