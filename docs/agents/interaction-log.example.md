# Agent 交互日志示例

这个文件用于展示跨 Agent 沟通的公开记录格式。真实流水请写入本地 `interaction-log.md`，不要提交到 Git。

## 2026-06-13 22:12 - 示例：需求澄清转交开发

- From: 产品需求 Agent
- To: 开发实现 Agent
- Type: handoff
- Related: native-first 首轮问答体验
- Summary: 产品侧确认首轮 fallback 是当前主线，开发侧需要检查实现是否与文档一致。
- Payload: 请检查主客户端在原生不支持时，是否优先走音箱直连 LLM，并在 TTS 服务不可用时降级到小爱原生 TTS。
- Result: 待开发实现 Agent 回复。
- Next: 开发实现 Agent 输出涉及文件、验证方式和风险点。

## 2026-06-13 22:30 - 示例：验收反馈转交开发

- From: 验收审查 Agent
- To: 开发实现 Agent
- Type: issue
- Related: 手工验收用例
- Summary: 验收侧发现文档中的运行命令和脚本默认配置可能不一致。
- Payload: 请核对 README、quickstart 和 `device/native_first_client.sh` 的默认参数说明。
- Result: 待开发实现 Agent 修复或解释。
- Next: 修复后由验收审查 Agent 复查文档一致性。

