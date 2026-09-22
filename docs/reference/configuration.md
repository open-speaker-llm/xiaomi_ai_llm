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
| `LLM_HISTORY_TURNS=6` | native 主线默认保留最近 6 轮上下文 |
| `LLM_HISTORY_DIR` | 默认 `/tmp/native_first_llm_hist`，整机重启清空；如需持久化，应自行管理存储和隐私 |
| `LLM_SYSTEM_PROMPT` | 控制语音回答风格；默认要求口语、完整句子，不使用 Markdown |
| `SYSTEM1_FOLLOWUP_ENABLED` | boot1 追问开关，须先安装匹配原生组件 |
| `NATIVE_ENDPOINT_ENABLED` | boot1 首轮判停开关，须先完整安装判停包 |
| `NATIVE_DIALOG_INPUT_GUARD` | 对少量明确缺对象短句提示补充，不是收音判停 |

不要仅凭开关为 1 判断组件可用。安装与验证顺序见[逐步完善对话](../getting-started/conversation.md)，运行健康状态见[日常操作](../runbooks/operations.md)。

## 修改后怎么生效

先备份实际配置，在音箱空闲时停止客户端，编辑 `/data/native_first.env`，再通过已安装的 `/data/init.sh` 启动。完整命令见[客户端操作](../runbooks/operations.md#客户端)。随后做一次真实问答，确认使用的后端、声音和追问行为符合预期。
