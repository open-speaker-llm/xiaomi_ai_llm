# 2026-09-10：切换 DeepSeek-V4.1-Flash 正式模型名

用户要求使用最新 Flash。直接核对[官方当前模型页](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)后，确认模型版本为 DeepSeek-V4.1-Flash，推荐 API 名为 `deepseek-flash`。搜索结果仍可能展示旧的 V4-Flash-0731 或 Vision-Exp，不能仅凭搜索摘要判断当前版本。

官方说明旧名 `deepseek-v4-flash`、`deepseek-v4-flash-vision-exp` 也已路由到 V4.1 Flash。本次将配置显式更新为新模型名，避免继续依赖旧别名；没有改用视觉实验版。

## 修改及验证

- 从已合并的 main `01d18e7` 在现有隔离 worktree 创建 `codex/use-deepseek-flash`。
- 音箱客户端默认值、Mac 辅助服务项目配置、配置模板、日常运维说明和既有模型路由测试统一采用 `deepseek-flash`。历史版本记录保留原模型名。
- 音箱仍使用 DeepSeek 官方地址和既有独立密钥，`LLM_PIPELINE=native`、`LLM_THINKING=disabled`。未改通用覆盖项或其他厂商模型。
- 8 项模型路由与请求测试、shell 语法和 diff 检查通过。
- 部署前从音箱直连新模型成功；部署后加载正式客户端的配置解析段，再发出固定文本测试，确认实际配置和 API 返回的 model 均为 `deepseek-flash`，返回“连接正常。”，流式完成标记与停止原因正常。第二次检查含 SSH 约 0.92 秒，不代表语音首声延迟。
- 上述 API 连通性测试未播放音频，没有读取或修改对话历史；密钥未写入测试产物或输出。

## 真人测试及验收

- 16:24–16:28 的四次 LLM 请求均使用 `deepseek-flash`，14 个语音段均首次合成成功并完成播放；两次免唤醒追问正常衔接。
- LLM 首 token 为 0.47–1.53 秒，语音首声为 2.63–4.17 秒。约 49 秒的两次长回答主要是播报耗时，不能视为模型生成耗时。
- 四轮 Master 均保持 145，未额外抬高 LLM 增益。最后一次播放保留的 Dirac 日志中，初始化及重置均返回 0；实际感知响度不能仅由 Master 参数推断。
- LLM 播放期间成功唤醒并最终识别“开灯”，LLM 播放正常完成。原生“开啦”的播报请求在 LLM 结束后才进入播放器及清队列流程，未及时播出。
- 用户确认本轮开灯均正常，虽然没有听到“开啦”；失败提示抑制没有漏音，并同意提交。
- 本轮日志有后备 guard 的抑制记录，未看到提前拦截 Speak 的命中。现场无漏音已验证，但不能据此声称提前拦截路径也已单独验证。
- 有一次回答自称“不是 DeepSeek”，实际请求仍为 `deepseek-flash`。该内容问题保留为后续提示词优化项，本次提交仅切换模型名，没有修改模型身份提示。

## 部署

- 正式更新 `/data/native_first_client.sh`，14:02:42 进入 IDLE，客户端 PID=1576。
- SHA-256：`70a7012f2c68c7ebc8e545d9481845068406a476dc4cff7e68808fe671f8f184`。
- 原生 ASR healthy，进程 PID 3779/3679 保持不变；保留 Dirac、音量一致性、失败提示拦截和并行唤醒配置。
- 空闲时核验旧/新文件摘要、备份后原子替换并重载客户端；本轮没有重新部署原生组件、修改设备私有配置或重启整机。
- 回滚脚本 `/data/deepseek-flash-backup-20260910-140234/restore.sh` 恢复旧客户端及旧模型名。因官方已将旧名路由到新模型，这不能恢复下线的旧模型权重。
- 本机部署清单和 API 检查结果：`/tmp/xiaomi-deepseek-flash-20260910/`；真人测试日志及核对报告：`/tmp/xiaomi-flash-test-audit-20260910/`。原始日志不纳入 Git 提交。
