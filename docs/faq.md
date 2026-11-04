# 常见问题

[English](faq_en.md) · [项目首页](../README.md)

下面每条都按当前仓库的代码和文档核对。仓库里没有写明的，这里不补。

<a id="models"></a>

## 支持哪些型号？

只实测过一台：**小米 AI 音箱，产品型号 MDZ-25-DA**。系统 hostname、内部代号是 **S12A**，主控是 Amlogic A113X。主板丝印是 `DKSND-S12C-ECHO-AB-20180820`，和产品型号、hostname 不是同一串字符。文档把三样并列，以实测为准，没有收成一个名字。

其他型号没有测过。外观相似不能说明固件和接口相同，命令不能照搬。

<a id="hardware"></a>

## 要不要焊接，要不要刷机？

不用焊接。用十字螺丝刀打开后盖，主板上有现成的 JST 串口插座。文档里使用的线是 **SH1.0 转 2.54 mm 杜邦 3P**，USB-TTL 的例子是 CH340。接三根线：模块 TX 接音箱 RX，模块 RX 接音箱 TX，GND 接 GND。波特率 **115200 8N1**。不要把模块的 5V 或 3.3V 接到主板，也不要只按线的颜色判断 TX、RX、GND。接线前用万用表对过针脚。

这不是把音箱刷成另一套、由第三方程序接管麦克风和播放的改法。小爱原来的识别和家电控制还留着。SSH 还没有时，要往系统分区写入启动脚本，dropbear 才会起来。boot0 和 boot1 的手册都是改对应 rootfs；boot1 手册里记录过用 `mtd` 写 `system1`。分区写错可能无法启动。串口在 SSH 可用之后仍然是救援通道。设备已经能 SSH 时，文档写明不要为了照搬步骤再写一遍分区。

命令不在本页重复，按这几篇做：[设备与准备](reference/hardware.md)、[从零接入](getting-started/bringup.md)、[boot0 SSH](runbooks/boot0-ssh.md)、[boot1 SSH](runbooks/boot1-ssh.md)。

<a id="offline"></a>

## 是不是在音箱上跑大模型？能离线吗？

不是，也不能离线做大模型对话。

音箱上运行的是客户端：负责分流，以及播放。语音识别、家电控制、小爱自己的回答走小米云，和原来一样。大模型是你配置的云 API，默认由音箱直接调用；改成 `LLM_PIPELINE=server` 时，由你另外运行的服务去调用。EdgeTTS 是微软的在线语音合成，由音箱或 TTS 服务去调；失败时可以退回小爱原生 TTS。

断网之后，文档写的是只剩小爱的原生能力。boot1 可以选装本机 Silero VAD，它只判断一句语音有没有说完，文字仍由小米云识别，它不是大模型。

<a id="always-on"></a>

## 需要电脑或 NAS 一直开着吗？

部署、拷贝文件和改配置时需要一台电脑。每天对话，不一定需要。

下面几条同时成立时，对话不依赖一台一直开着的电脑或 NAS：

- `LLM_PIPELINE=native`（客户端没写这项时的默认值就是 native）
- `TTS_ENGINE=device`（音箱上的 `ettsc` 直连 EdgeTTS）
- 追问走 boot1 的原生识别，而不是把录音送到电脑

这时模型调用和语音合成都从音箱发出，识别仍走小米云。

仓库示例 [`device/native_first.env.example`](../device/native_first.env.example) 里 `TTS_ENGINE` 写的是 `server`。客户端在这项没有设置时也会退回 `server`。示例地址是 `http://192.168.8.150:8080`。保持这个默认，回答的时候那台 TTS 服务得在线。`LLM_PIPELINE=server` 时，可选的 FastAPI 服务要一直运行，由它调模型并合成语音。boot1 还有一条旧的追问路径，把音频送到 Mac 做识别，那种用法也要电脑在线。

状态页的说法是：使用设备端 TTS 和原生追问时，不需要常驻 Mac。

<a id="native"></a>

## 开灯、天气这些原来的功能还能用吗？

可以，这是项目的主路径，叫原生优先。开灯、天气、报时、音量这类小爱本来会处理的，仍交给小爱。boot0 看原生结果里的 domain、action 和失败文本。boot1 先看这句话是不是点名要问大模型，默认只匹配 `DEEPSEEK`、`DeepSeek`、`deepseek`；否则等小爱的失败播报文案，对上了才转给大模型。

boot1 用的是文本规则。文档写明：没见过的失败文案可能漏掉，相近的正常回答也可能被误判，不保证每一句都分对。

大模型正在播报时，还可以再喊“小爱同学”去做家电控制，播报继续。这是仓库说明和演示里的行为。用语音把正在播的大模型回答停掉，还没有做。

<a id="llm"></a>

## 支持哪些大模型？怎么切换？能联网搜索吗？

音箱直连时，改音箱上 `/data/native_first.env` 的 `BACKEND`，空闲时重启客户端。当前脚本里的默认模型是：

| `BACKEND` | 不额外覆盖时的默认模型 |
|---|---|
| `deepseek`（不填也是它） | `deepseek-flash` |
| `glm` | `glm-5.3-flash` |
| `kimi` | `kimi-k2.6` |
| `minimax` | `MiniMax-M2.7` |

`LLM_API_BASE`、`LLM_MODEL`、`LLM_API_KEY` 只要有值，就压过上表。只改 `BACKEND`、却留着旧的覆盖项时，请求仍会走到旧地址或旧模型。对音箱说“呼叫 Kimi”不会切换后端。点名触发词默认是上面三种 DeepSeek 写法，要改就改 `DIRECT_LLM_QUERY_PATTERNS`。

英文 README 写明本地模型（举例 Ollama）还没有测过。其他 OpenAI 兼容接口可以填进那三个覆盖项，不表示它们都在这台音箱上试过。

可选电脑服务的 [`config.yaml`](../config.yaml) 里另外列了 Claude 和 OpenAI。那只在 `LLM_PIPELINE=server` 时由那台服务使用，音箱直连不靠这两项。

联网搜索只在音箱直连、并且 `BACKEND=deepseek` 时有。默认 `LLM_WEB_SEARCH=auto`：先判断要不要实时信息（例如新闻、价格、营业状态、指定网页），需要时调用 DeepSeek 官方 Search 或 Fetch，回答里说明来源。其他后端没有这项，`server` 链路也没有。设为 `off` 就关闭判断和搜索。失败、空结果或判断无效时，固定说“暂时无法联网查询，请稍后再试。”，不会接着生成一条没核对过的实时答案。每一轮会多一次判断请求。说明见 [联网搜索参考](reference/native-web-search.md)。

<a id="followup"></a>

## 能免唤醒连续追问吗？怎么结束？

可以，但不是把示例配置拷上去就有。要先按文档安装并启用对应组件。boot1 上，大模型回答完整播完以后，可以开一段不用再说“小爱同学”的续听，沿用同一段上下文；文字仍由小米云识别。绿灯常亮时可以接着说。这段由原生 VAD 判断说完没有。文档写的是空闲大约 6 秒就退出；`NATIVE_ASR_LISTEN_TIMEOUT` 默认 20 秒，是整轮保护超时，不是“再等 20 秒才开口”。不说话就会结束。

boot0 的追问是另一条：本机录音，再走小米的文件识别。状态页把它列为实验方案。boot1 的原生追问组件不能直接套到 boot0。

口头结束语默认关闭。[`device/native_first_client.sh`](../device/native_first_client.sh) 里，`FOLLOWUP_EXIT_ENABLED` 不是 `1` 就直接返回；示例配置也是 `0`。设为 `1` 并在空闲时重启客户端之后，只有已经进入追问窗口、并且单独说出下面五句之一，才会直接结束。结束后不再请求模型，也不播确认语：

**结束对话、退出对话、停止对话、不聊了、退下**

句首句尾空白，以及句尾的 `。！？.!?` 可以有。首问里说这些词不会被这条规则截住。“不要结束对话”“请结束对话”“不要再讲了”都不在这五句里。状态页写明：这项打开之后的真人收听验收还没有做完。

续听时再喊“小爱同学”，会把这一轮交回小爱。配置细节见 [用结束语退出追问](reference/configuration.md#用结束语退出追问)。

<a id="compare"></a>

## 和 mi-gpt、open-xiaoai 有什么不同？

本仓库 README 把 [mi-gpt](https://github.com/idootop/mi-gpt) 和 [open-xiaoai](https://github.com/idootop/open-xiaoai) 写成参考过的项目，并写明两个仓库已经归档、停止维护。[接入路线与取舍](concepts/comparison.md) 说的是从哪一层接入，材料记于 2026-06，不是对它们当前功能或维护状态的评测。最新情况以它们自己的仓库为准。

mi-gpt 走小米账号相关接口，程序跑在电脑或 NAS 上。本项目不轮询账号，客户端在音箱上；要拆机接串口，而且只实测 MDZ-25-DA。

open-xiaoai 在本仓库的说明里，是刷机后自己管理音频，文档写到的机型包括 LX06 / OH2P。本项目把小爱的识别和家电控制留在原来的链路上，只把开放问题转给大模型，不支持 LX06 / OH2P。README 写明，音箱上 `/data/init.sh` 这种自启动写法来自 open-xiaoai。

两边都可以接 OpenAI 兼容接口。这里只说明接入位置不同。

<a id="cost"></a>

## 费用怎么算？

大模型 API 按你使用的服务商计费。本仓库不写单价。DeepSeek 联网搜索使用同一把 `DEEPSEEK_API_KEY`。文档写明：判断要不要搜，以及成功的 Search/Fetch，分别计费，价格以 DeepSeek 官方说明为准。

EdgeTTS 在 README 里标为免费。音箱端 EdgeTTS 客户端没有单独的 EdgeTTS 密钥配置项。小爱原来的识别和家电控制仍走音箱自己的小米服务。这个仓库不代收费用。

<a id="license"></a>

## 有什么风险？用的是什么许可证？

本仓库自己编写的代码是 [MIT](../LICENSE)。MIT 不覆盖第三方依赖。音箱端 EdgeTTS 里的 [`device/ettsc/src/gec_v2.rs`](../device/ettsc/NOTICE.edge-tts.md) 按该目录的说明是 LGPL-3.0-only，根目录的 MIT 不包括这个文件。

这不是小米或小爱的官方项目，没有隶属、关联或代表关系。名称只用来说明设备。只在自己拥有或已经获准改动的设备上使用。拆机、打开 SSH、写入系统分区，可能导致无法启动、数据丢失、保修失效，或违反相关服务条款。语音、文字和家电请求会发到你配置的模型与语音合成服务，以及小米的云识别。不要上传敏感内容。
