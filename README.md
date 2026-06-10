# 小米 AI 音箱 LLM 助手

> Bring your own LLM to a Xiaomi AI Speaker — keep "小爱同学" for what it's good at, route everything else to DeepSeek / MiniMax / Claude. Documentation is in Chinese.

让一台 2019 年的小米 AI 音箱（MDZ-25-DA / S12A）接上现代大模型：

- **原生能做的，继续交给小爱**：唤醒、开关灯、音量、天气、闹钟等走小米原生链路，体验不打折。
- **原生不会答的，转给 LLM**：拦截"我还在学习中"这类失败播报，把小米已经识别出的文本转给 Mac 上的服务端，由 DeepSeek / MiniMax / Claude / OpenAI 回答，EdgeTTS 合成后在音箱播放。

实际体验：

```text
小爱同学，开灯              → 灯开了（原生，毫秒级）
小爱同学，今天天气怎么样      → 原生播报天气
小爱同学，呼叫 DeepSeek     → 原生不支持，转 LLM："我在，有什么可以帮你？"
小爱同学，给我讲讲量子纠缠    → LLM 流式回答，逐句合成播放
```

## 工作原理

```text
"小爱同学" 唤醒
  → 小米原生 ASR/NLP 先处理
  → native_first_client.sh（音箱端，纯 shell）读取原生结构化结果
       → 原生成功 domain（家电/天气/音量…）：交回原生，replay 播报
       → 原生不支持：冻结失败播报，把识别文本 POST 给 Mac 服务端
  → Mac 服务端（FastAPI）：LLM 流式生成 → 逐句 EdgeTTS
  → 音箱边收边播
```

这条 **native-first（原生优先）** 路线的核心判断：不要替换小爱，而是复用它最稳的部分——高质量唤醒、原生 ASR 和家电控制——只接管它不擅长的开放问答。路由依据是小米 NLP 的结构化 `domain/action` 字段，不是文本关键词猜测。详见 [docs/concepts/native-first.md](docs/concepts/native-first.md)。

## 硬件与风险声明

- 适用设备：小米 AI 音箱 **MDZ-25-DA**（内部代号 S12A，Amlogic A113X，128MB NAND）。其他型号思路可参考，但命令不能照搬。
- 需要 **拆机焊接 TTL 串口线**（TX/RX/GND 三个触点），这是打通 SSH 之前唯一的控制通道，也是刷写出错后唯一的救援通道。
- 过程涉及 **读写 NAND 系统分区**，操作失误可能导致设备无法启动（变砖）。本仓库的操作手册都附带了备份和回退步骤，但请确保理解每条命令再执行，风险自担。
- 改造不影响小爱原有功能，但显然会失去保修。

## 从哪里开始读

| 你是谁 | 从这里开始 |
|---|---|
| 手里有音箱，想从零打通 | [docs/getting-started/bringup.md](docs/getting-started/bringup.md) —— 串口 → SSH → 部署 → 第一次 LLM 响应的完整路线图 |
| SSH 已可用，想快速跑起来 | [docs/getting-started/quickstart.md](docs/getting-started/quickstart.md) |
| 想先理解原理再动手 | [docs/concepts/native-first.md](docs/concepts/native-first.md) + [docs/concepts/boot-and-partitions.md](docs/concepts/boot-and-partitions.md) |
| 日常操作 / 出了问题 | [docs/runbooks/operations.md](docs/runbooks/operations.md) / [docs/runbooks/troubleshooting.md](docs/runbooks/troubleshooting.md) |
| 想看这一切是怎么一步步摸索出来的 | [docs/history/journey.md](docs/history/journey.md) —— 从焊串口到 native-first 的完整探索历程 |

完整文档地图和阅读路径见 [docs/README.md](docs/README.md)。

## 仓库结构

```text
server/                 Mac FastAPI 服务端：LLM 路由、流式 TTS、Whisper ASR 兜底
device/                 音箱端脚本：native_first_client.sh 主客户端、配置模板、探索用 probe 脚本
docs/
  getting-started/      从零打通、快速上手
  concepts/             native-first 架构、启动链路与分区、术语表
  runbooks/             日常运维、SSH 注入、自启动、排障
  history/              探索历程与已验证失败的路线
  archive/              重构前文档原貌快照（查证用）
tests/                  自动化测试 + 真实音箱人工用例
config.yaml             LLM / ASR / TTS 配置
start_server.sh         Mac 服务端启动入口
```

## 快速启动（已完成部署时）

Mac 服务端（仓库根目录）：

```sh
./start_server.sh
```

音箱端（SSH 登录后）：

```sh
SERVER=http://192.168.8.150:8080 BACKEND=deepseek \
sh /data/native_first_client.sh > /tmp/native_first_client.log 2>&1 &
tail -f /tmp/native_first_client.log /tmp/native_first_events.log
```

> 文档中的 IP（Mac `192.168.8.150`、音箱 `192.168.8.152`）均为示例，替换成你自己的。约定见 [docs/README.md](docs/README.md#文档约定)。

完整步骤见 [docs/getting-started/quickstart.md](docs/getting-started/quickstart.md)。

## 服务端能力

- 接收音箱 fallback 文本，调用 DeepSeek / MiniMax / OpenAI / Claude（`config.yaml` 配置，`.env` 放 key）。
- LLM 流式输出按中文句子边界切分，逐句 EdgeTTS 合成（默认音色 `zh-CN-YunjianNeural`），首句即可开播。
- 保留 Whisper ASR 接口，作为历史路线、测试和兜底能力。

| 端点 | 用途 |
|---|---|
| `GET /` | 健康检查 |
| `POST /api/v1/stream/text_chat` | native-first 主链路：文本进 LLM，流式返回 TTS 音频 |
| `POST /api/v1/route/asr` | 录音 ASR + 路由（测试/兜底） |
| `POST /api/v1/stream/chat` | 录音上传 → ASR → LLM → TTS 一体化（历史接口） |

## 测试

```sh
./scripts/run_tests.sh                    # 自动化：服务端逻辑 + shell 语法 + 配置一致性
tests/manual_native_first_cases.md        # 真实音箱人工用例
```

说明见 [TESTING.md](TESTING.md)。

## 当前边界

- native-first 首轮 fallback 是稳定主线；boot0 与 boot1 两套系统（2019/2023 ROM）均已适配。
- 连续追问（LLM 回答后不喊唤醒词直接追问）还不是最终形态：boot0 有实验性的本地录音方案，boot1 默认关闭。原生 ASR reopen 方向已多次验证未打通，下一步更值得探索"获取小米处理后的干净音频"。详见 [docs/history/followup-exploration.md](docs/history/followup-exploration.md)。

## 相关项目

本项目在探索过程中参考了这些开源工作，特此致谢：

- [open-xiaoai](https://github.com/idootop/open-xiaoai) —— 小爱音箱接入大模型的先行项目，自启动 `/data/init.sh` 方案来源
- [duhow/xiaoai-patch](https://github.com/duhow/xiaoai-patch) —— squashfs 解包/注入/写回路线参考
- [open-lx01](https://github.com/jialeicui/open-lx01) —— rootfs 只读、`/data` 可写的结论印证
- [xiaoai-crack](https://github.com/birdsofsummer/xiaoai-crack) —— ubus 接口调用参考
