# 2026-09-06 MiniMax LLM 接入

音箱 boot1 的 native 链路由 DeepSeek 切换为 MiniMax M2.7，地址为
`https://api.minimaxi.com/v1`。运行配置位于设备 `/data/native_first.env`，
密钥只保存在私密配置中，文件权限为 600。端侧 TTS 和原生连续追问沿用现有配置。

## 兼容修改

- `BACKEND=minimax` 使用 MiniMax 的默认地址、模型及 `MINIMAX_API_KEY`，显式 LLM 配置仍优先。
- MiniMax 请求使用 `reasoning_split=true`，只把正式回答送给 TTS。M2.x 无法关闭思考，原有 `LLM_THINKING` 只用于其他模型的请求。
- 两条设备流式路径共用 content 提取函数，忽略思考字段及 usage 空 choices，兼容 JSON 空格、转义引号和换行。
- 可选 Mac 客户端采用同样的思考分离设置，更新默认模型及地址；DeepSeek 请求不附带 MiniMax 参数。
- 配置模板给出 MiniMax 覆盖示例；实机保留原有直接呼叫词，并追加 MiniMax 和米尼麦克斯。

## 验证

- Mac 使用新密钥调用 MiniMax M2.7，HTTP 200，约 2.65 秒返回测试回答。
- 音箱使用候选配置及实际 BusyBox awk 解析器直连流式接口，返回“MiniMax 已接入。”。
- 部署脚本 SHA256：`079201e59d90375494e67c925f46a17391ace1a92405d496de2fd4d5aaef6b22`。
- 19:43 重启后的日志为 `Backend: minimax`、`native ASR-only ready; no external recognizer` 及 `[IDLE]`。另一次 SSH 连接确认客户端仍在运行。
- 46 项单元测试及 shell 语法检查通过，覆盖 MiniMax/DeepSeek 请求、流式内容过滤、转义文本、显式配置优先级及服务端 usage 空 choices。
- 设备没有 `nohup`，首次启动命令未启动成功；改用现有启动方式 `sh ... >日志 2>&1 </dev/null &` 后验证成功。
- 尚未验证现场语音唤醒到实际可听播报的完整体验。

## 回退

切换前的设备配置与脚本保存在 `/data/minimax-backup-20260906-1945/`，目录权限 700，配置权限 600。
需要回退时，在音箱空闲时停止助手，将该目录内 `native_first.env` 和
`native_first_client.sh` 恢复到 `/data/`，再执行 `sh /data/init.sh`。
此次未修改固件或启动入口；现有自启动读取同一个运行配置。

官方接口说明：[MiniMax OpenAI 兼容接口](https://platform.minimaxi.com/docs/api-reference/text-chat-openai)。
