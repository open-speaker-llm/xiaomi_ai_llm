# 配置参考：模型、声音与会话

首次部署先读[快速上手](../getting-started/quickstart.md)。本页用于部署后的选择和调整；参数的完整默认值以 [device/native_first.env.example](../../device/native_first.env.example) 及客户端为准。

## 配置放在哪里

| 文件 | 管哪一侧 | 如何生效 |
|---|---|---|
| 音箱 `/data/native_first.env` | 客户端、LLM、TTS、追问和判停开关 | 空闲时重启客户端 |
| 仓库 `config.yaml` | 可选 FastAPI 服务的模型、ASR、TTS | 重启服务端 |
| 仓库 `.env` | 可选服务端使用的私有密钥 | 重启服务端 |
| 音箱 `/data/init.sh` | 开机等待及启动入口 | 下次执行或整机启动 |

设备配置会作为 shell 文件读取：只写受信任的配置，不把识别文本或模型输出当作配置执行。不要提交真实密钥。同一变量只保留一条有效赋值，后面的赋值会覆盖前面的；客户端还会读取配置文件，不能假设命令行临时值一定优先。

## 先选 LLM 在哪里调用

| `LLM_PIPELINE` | 行为 | 需要在线的自建服务 |
|---|---|---|
| `native`（默认主线） | 音箱直接调用模型，再按 `TTS_ENGINE` 播放 | TTS 可选 |
| `server` | 音箱向 `/api/v1/stream/text_chat` 发文字，服务端调用模型并合成音频 | FastAPI 服务 |

选用 server 时，先按[服务端说明](server.md)配置 `SERVER` 和对应后端。它是一条 LLM/TTS 一体链路；下面独立选择 TTS 的表针对 native 主线。

## 选择模型后端

在音箱 `/data/native_first.env` 填好相应密钥，再修改 `BACKEND`。下表是仓库当前默认配置，不是对厂商最新型号的声明。

| `BACKEND` | 默认模型 | 设备端密钥变量 |
|---|---|---|
| `deepseek` | `deepseek-flash` | `DEEPSEEK_API_KEY` |
| `minimax` | `MiniMax-M2.7` | `MINIMAX_API_KEY` |
| `glm` | `glm-5.3-flash` | `GLM_API_KEY` |
| `kimi` | `kimi-k2.6` | `KIMI_API_KEY` |

`LLM_API_BASE`、`LLM_MODEL`、`LLM_API_KEY` 是高级覆盖项，非空时优先于后端默认值。只是切换 `BACKEND` 时，先确认没有遗留的通用覆盖项，否则请求可能仍发往旧地址或旧模型。

后端由配置选择，不会在请求失败时自动切换，也不会因用户说“呼叫 Kimi”而自动选择 Kimi。默认直接转 LLM 的触发词匹配 DeepSeek 的大小写写法；需要调整触发词时同时检查 `DIRECT_LLM_QUERY_PATTERNS`。

DeepSeek 默认 `LLM_THINKING=disabled`，GLM 使用 `LLM_REASONING_EFFORT=low`；MiniMax 分离思考内容，Kimi 使用非思考模式。语音链路只播回答内容，首声时间还受网络、切句和 TTS 影响。

服务端另支持 Claude/OpenAI 等配置，地址和模型见 `config.yaml`，密钥放 `.env`。音箱发送的显式 `BACKEND` 优先于服务端默认后端，两边需要保持一致。

## 联网搜索

`LLM_PIPELINE=native`、`BACKEND=deepseek` 时默认 `LLM_WEB_SEARCH=auto`：进入 LLM 的问题先结合当前会话做语义判断，明确搜索、实时信息及需要新事实的追问调用 DeepSeek 官方 Search API；指定网页调用 Fetch API。稳定知识、创作、翻译和整理上一回答直接回答。小爱原生已处理的家控、天气和报时保持原路由。

| 配置 | 默认值 | 含义 |
|---|---|---|
| `LLM_WEB_SEARCH` | `auto` | `auto` 按语义联网（`on/1/true/yes` 同义）；`off` 关闭判断和搜索，恢复纯聊天 |
| `LLM_WEB_PLAN_TIMEOUT` | `4` | 单次联网判断的最长秒数，允许 1–20 |
| `LLM_WEB_TIMEOUT` | `8` | 单次搜索或网页读取的最长秒数，允许 1–20 |
| `LLM_WEB_RETRIES` | `1` | 规划和工具各自最多重试 0–2 次，只重试返回类别 10 |
| `LLM_WEB_RETRY_BACKOFF_MS` | `500` | 网络错误或 5xx 的退避毫秒，允许 0–3000；429 默认 1 秒，整数 `Retry-After` ≤2 秒时采用它，>2 秒不重试 |
| `LLM_WEB_TOTAL_BUDGET` | `12` | 规划、退避、重试及工具共用秒数，允许 4–30；最终回答仍由 `LLM_DIRECT_TIMEOUT` 控制 |
| `LLM_WEB_FILLER` | `搜索中，请稍等。` | 仅流式链路在规划准备重试或调用工具前输出，每轮最多一次；空值关闭；不接受换行 |
| `LLM_WEB_FALLBACK` | `answer` | 联网失败后附加“未联网”system 提示并正常回答；`fail` 只播固定失败提示 |
| `LLM_WEB_TEST_FAULT` | 空 | 调试故障：`plan_timeout/plan_429/plan_401/plan_402/plan_403`、`tool_timeout/tool_429/tool_401/tool_402/tool_403/tool_503`；非空启动时醒目警告，使用后清空 |

搜索使用 `DEEPSEEK_API_KEY`；只有官方 DeepSeek 聊天地址才允许回用通用 `LLM_API_KEY`，不会把其它服务商的通用密钥发送给 DeepSeek。需要系统已有的 `jsonfilter`，不需要 Python、jq 或 Mac 搜索服务。判断本身每轮增加一次模型请求；搜索最多返回三条来源，Search/Fetch 及模型调用分别计费。

配置模式非法、缺 `jsonfilter`、缺可用搜索 key 或超时配置非法时，启动只记一次 warning 并按 off 处理，普通回答继续。新增配置非法时记一次警告并用表中默认值。规划/工具的网络临时故障各自重试，预算不足则停止；200 但规划内容损坏或 `finish_reason` 不是 stop 时不重试。默认联网失败、空结果或无效判断后追加“未联网、不得声称查过、实时信息无法确认”的提示并继续回答；`LLM_WEB_FALLBACK=fail` 可恢复固定失败提示。规划 HTTP 401/403 直接提示“大模型密钥无效，请检查配置。”，402 提示“大模型账户余额不足，请充值后再试。”，不请求最终回答；工具鉴权或余额错误只降级。垫话与固定错误提示不写入历史，ttft 不把垫话当答案首片。只有本轮经过规划、最终传输失败且没有答案（或只有垫话）时，补播一次“暂时无法联网查询，请稍后再试。”。回答用口语说明来源，原始网址保留在客户端日志的 `[WEB] source=` 行。具体行为和限制见[联网搜索参考](native-web-search.md)，操作见[重试与兜底测试](../testing/2026-11-04-web-search-retry.md)。可选 `server` 链路不包含此功能。

## 再选文字怎样变成声音

| 配置 | 所需部署 | 音色配置 |
|---|---|---|
| `TTS_ENGINE=device` | 音箱 `/data/ettsc`，直连 EdgeTTS | `DEVICE_TTS_VOICE` |
| `TTS_ENGINE=server`（模板默认） | `TTS_SERVER` 指向可用的 `/api/v1/tts/stream` | 服务端 `tts.edgetts.voice` |
| `TTS_FALLBACK_NATIVE=1` | 允许 EdgeTTS 失败时尝试小爱原生 TTS | 沿用原生语音 |

端侧 `DEVICE_TTS_STREAM=1` 默认逐句合成，PCM 按顺序播放；单句失败会重试，仍失败时可按序原生补播，补播也失败则结束本轮。端侧 TTS 并非只能等待整段 MP3 合成完再播放。组件和协议版本参数见 [ettsc](../../device/ettsc/README.md)。

本机现有的 Dirac 播放适配、音量恢复与参考通道各有固件限制；音效的构建和验证见 [Dirac 组件](../../device/dirac/README.md)，出现音量异常从[排障](../runbooks/troubleshooting.md#7-llm-音量忽大忽小)进入。

## 会话与可选组件

| 项 | 用途 |
|---|---|
| `LLM_HISTORY_TURNS=6` | native 主线保存并发送最近最多 6 个完整问答对；允许 0–100，0 不保存对话内容 |
| `LLM_HISTORY_DIR` | 默认 `/tmp/native_first_llm_hist`；新格式仅管理其中 `.native_first_history_v1` 子目录，整机重启清空默认缓存 |
| `LLM_HISTORY_MAX_SESSIONS=16` | 新格式缓存保留最多 16 个会话，允许 1–64；保护本轮，按文件修改时间淘汰其他托管会话 |
| `LLM_HISTORY_MAX_BYTES=65536` | 每会话最多 64 KiB，允许 1024–1048576；只删除完整旧问答对，不截断文本 |
| `LLM_SYSTEM_PROMPT` | 控制语音回答风格；默认要求口语、完整句子，不使用 Markdown |
| `SYSTEM1_FOLLOWUP_ENABLED` | boot1 追问开关，须先安装匹配原生组件 |
| `FOLLOWUP_EXIT_ENABLED=0` | 默认关闭；设为 `1` 后，允许在追问窗口用独立结束语直接结束会话 |
| `FOLLOWUP_RESET_ENABLED=0` | 默认关闭；设为 `1` 后，允许在追问窗口用“换个话题/重新开始”开启新会话 |
| `NATIVE_ENDPOINT_ENABLED` | boot1 首轮判停开关，须先完整安装判停包 |
| `NATIVE_DIALOG_INPUT_GUARD` | 对少量明确缺对象短句提示补充，不是收音判停 |

不要仅凭开关为 1 判断组件可用。安装与验证顺序见[逐步完善对话](../getting-started/conversation.md)，运行健康状态见[日常操作](../runbooks/operations.md)。

### 用结束语退出追问

在音箱实际使用的 `/data/native_first.env` 中将 `FOLLOWUP_EXIT_ENABLED` 的唯一有效赋值设为 `1`，再在空闲时重启客户端。不要只在启动命令前临时设置变量：配置文件中的赋值仍会覆盖它。

回答结束、进入追问窗口后，独立说出以下任一短句即可结束：**结束对话、退出对话、停止对话、不聊了、退下**。允许两端空白及句尾 `。！？.!?`；命中后直接恢复待机，不发送新的 LLM 请求、不播结束确认、不写入新一轮历史，也不再开启下一轮收听。此行为覆盖原生实时追问、本地录音追问和实验性原生多轮模式。

首问与首问输入补全中的这些词仍正常交给模型；已进入追问后的输入补全可以被结束语取消。`不要结束对话`、`解释结束对话的意思`、带引号的 `“结束对话”` 及含其它词的句子不匹配。开关不改变播放期间的原生唤醒和家居控制。

恢复原行为时，将实际文件中的 `FOLLOWUP_EXIT_ENABLED` 改回 `0`，空闲时重启客户端。主机回归不代表真人听觉与设备状态已经验收。

### 在追问中换话题

将实际 `/data/native_first.env` 中 `FOLLOWUP_RESET_ENABLED` 的唯一有效赋值设为 `1`，空闲时重启客户端。此开关独立于 `FOLLOWUP_EXIT_ENABLED`，不会改变首问、播放中的原生唤醒或并行家居控制。

回答播完、进入追问窗口后，独立说 **换个话题** 或 **重新开始**。音箱切换到新的会话标识，固定确认“好，我们换个话题。你想聊什么？”，确认播完后再收听下一问。控制词和确认语不调用 LLM、不写成问答历史；下一问不携带旧会话上下文。确认播报失败时清理并回到待机，不继续开启监听。原生实时、本地录音和实验性原生多轮追问使用相同语义；native 与 server 链路均通过新会话标识隔离后续上下文。

成功换话题后的下一问即使与旧会话最后一问相同，也会正常提交；这次放行只属于新会话的下一问，不清空全局防重记录，之后继续使用原有防重规则。

仅允许外侧空白和句尾 `。！？.!?`；`不要重新开始`、`“换个话题”`、`解释换个话题的意思` 不触发。首问和首问补全正常提交模型；已经进入追问后的补全过程可以换话题，未完成的旧问题片段不会带入新会话。恢复原行为时设回 `FOLLOWUP_RESET_ENABLED=0`，空闲时重启客户端。

“换话题”表示后续请求使用新上下文，**不表示永久删除旧数据**。音箱缓存、服务端记录或云端数据分别遵循各自保留策略。

### native 历史缓存的范围

生成完整结束、传输与播放均成功后，客户端才把一个完整的 `user/assistant` 对原子提交。新格式同时限制轮数、字节数和会话数量；最后一个新问答对本身超出字节上限，或写入失败时，不保存该轮完整历史并结束追问，避免下一轮假定未保存内容仍在上下文中。

目录须为不含符号链接和 `..` 的绝对路径。客户端只读写带本项目格式标记的普通文件；读取和清理均先验证文件大小、原始 NUL 字节及完整问答格式。损坏格式、符号链接和未知的同名存储目录会被拒绝，损坏文件不会被缓存清理删除。旧版直接放在 `LLM_HISTORY_DIR` 下的文件、其他文件和未知格式均不会自动迁移、覆盖或删除。默认缓存位于 `/tmp`；改成持久路径不会增加跨唤醒自动续聊，仍需自行决定旧文件的保留与清理。

以上容量设置只管理音箱 native 历史，不能视为服务端或云端的数据删除接口。恢复旧缓存参数时使用表中默认值；新唤醒仍按新会话处理。

## 修改后怎么生效

先备份实际配置，在音箱空闲时停止客户端，编辑 `/data/native_first.env`，再通过已安装的 `/data/init.sh` 启动。完整命令见[客户端操作](../runbooks/operations.md#客户端)。随后做一次真实问答，确认使用的后端、声音和追问行为符合预期。
