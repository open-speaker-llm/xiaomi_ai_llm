# Agent 协作协议

本目录记录 Codex 多会话 Agent 的协作方式和跨 Agent 沟通约定。

## Agent 分工

| Agent | 职责 |
|---|---|---|
| 主控 / 协调会话 | 拆任务、转发消息、维护日志、决定下一步 |
| 产品需求 Agent | 澄清需求、维护 PRD / 验收标准 / 非目标 |
| 开发实现 Agent | 实现功能、补测试、说明验证结果 |
| 验收审查 Agent | 独立验收、发现缺口、给开发反馈 |

## 沟通规则

1. 跨 Agent 消息统一通过主控会话路由。
2. 主控会话在发送跨 Agent 消息前，先在本地 `interaction-log.md` 追加一条日志。
3. 收到 Agent 回复后，主控会话继续追加处理结果、结论或待办。
4. 产品需求 Agent 不直接改实现代码；开发实现 Agent 不重新定义需求；验收审查 Agent 不直接修代码。
5. 如果需要多人协作同一问题，主控会话先把问题拆成清楚的请求，再分别发给对应 Agent。

## 公开与本地文件

| 文件 | 是否提交 | 用途 |
|---|---|---|
| `README.md` | 是 | 公开协作规范 |
| `interaction-log.example.md` | 是 | 可公开的日志格式示例 |
| `interaction-log.md` | 否 | 本地真实交互流水，可能包含会话 ID、未公开计划或调试细节 |

## 日志格式

```md
## YYYY-MM-DD HH:MM - 简短标题

- From:
- To:
- Type: request | response | decision | handoff | issue
- Related:
- Summary:
- Payload:
- Result:
- Next:
```

## 推荐消息格式

```md
目标：
背景：
需要你判断/完成：
输入材料：
输出格式：
截止条件：
```
