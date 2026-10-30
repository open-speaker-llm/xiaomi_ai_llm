# 设备协议模块维护

`device/lib/native_protocol.sh` 是设备 JSON 字符串与 LLM SSE 处理的维护入口。它只有函数定义，不读取配置、不访问设备、不联网。构建工具把该模块嵌入 `device/native_first_client.sh` 的 `BEGIN/END GENERATED NATIVE PROTOCOL` 标记区；音箱仍只运行原有单文件，整包也继续包含该文件。音箱不需要上传 `device/lib/`、安装 Python 或 jq。

修改模块后，在仓库根目录执行：

```sh
python3 scripts/embed_native_protocol.py
python3 scripts/embed_native_protocol.py --check
.venv/bin/python -m unittest tests.test_native_protocol tests.test_native_client_failure_paths tests.test_tts_sentence_recovery tests.test_minimax_integration -v
```

嵌入命令只替换标记区，保留两侧客户端代码及文件权限；输出一致时不重写文件。`--check` 不修改文件：一致返回 0，源码与产物不一致、标记缺失或重复时返回 1。并发修改被检测到时拒绝覆盖，待其他编辑完成后重试。协议函数应改源模块，再生成产物；直接修改嵌入区会被一致性检查发现。

## 函数契约

| 函数 | 输入与输出 |
|---|---|
| `json_escape` | stdin 原始文本 → JSON 字符串内容，不带外层引号；保留中文和 emoji，转义引号、反斜杠及所有 U+0000–U+001F 控制字符，包括末尾换行 |
| `json_unicode_decode` / `json_text_unescape` | 每行一个已去掉引号的 JSON 字符串 → 每行一段播报文本；解码 Unicode 与合法代理对，CR/LF/Tab 归一为空格，其余控制字符省略 |
| `json_text_field` | 从带前缀的原生日志中提取首个 `text` 字符串，保留转义供解码器处理 |
| `llm_sse_content [status_file]` | LLM SSE → 逐片播报文本；结束时向可选状态文件写入 `complete` 或 `incomplete` |

编码使用设备已有的 BusyBox `od` / `awk`；协议处理固定使用 C locale，按 UTF-8 字节输出。原生日志解码对孤立代理项保留替换字符的容错行为；LLM SSE 对无效转义和孤立代理项拒绝该帧，并将整轮标记为不完整。

SSE 处理只发布 `choices` 中 index 0 的 `delta.content`；缺失 index 时沿用首个 choice。思考字段、其他 choice 和 usage 不会进入播报。完整 JSON 帧验证通过后立即输出并 flush，不等待整段回答；支持 CRLF、注释、跨 `data:` 行的 JSON，以及既有逐行 JSON 输入。单个 JSON 帧上限为 256 KiB、嵌套深度上限为 32，超限标记不完整。

`[DONE]` 或目标 choice 的 `finish_reason=stop` 可表示正常结束；非正常 finish reason、错误事件、坏帧、未闭合 JSON、结束后的额外正文或缺少结束标记均得到 `incomplete`。该状态只描述协议结果；调用方仍必须同时检查 curl 退出状态。错误到达前已经输出的片段可能已经播放，调用方保持现有失败退出及历史提交规则，不把部分回答写成完整历史。

## 验证边界

`tests/test_native_protocol.py` 对维护源码和嵌入产物执行同一组合同：完整控制字符编码、Unicode/emoji/引号、错误和截断、逐片输出，以及产物一致性。上游保持打开时读取前两片输出的用例用于防止新增缓冲延迟；主客户端失败测试确认坏流不会触发完整播放或提交完整历史。可用时另用 BusyBox 的 shell、awk、od 运行兼容用例；本机缺少 BusyBox 会明确跳过，主机测试不替代音箱听觉验收。
