# 小米 AI 音箱 LLM 助手

这个项目的目标是：让一台小米 AI 音箱继续保留“小爱同学”的原生能力，同时在小米原生不会回答时，把问题转给 Mac 上的 LLM 服务端回答。

当前主线是 **native-first 原生优先路线**：继续使用“小爱同学”唤醒、小米原生 ASR/NLP 和家电控制；当小米原生明确处理不了时，再把小米识别出的文本转给 Mac 服务端 LLM。

一句话结论：

- 原生能做的，比如开关灯、音量、天气，优先交给小米原生。
- 原生不能回答的问题，拦截失败播报，转给 DeepSeek/MiniMax 等 LLM。
- 音箱里的 `boot0/system0` 和 `boot1/system1` 都要能 SSH，才能避免每次异常切系统后还要重新接串口。
- boot0 与 boot1 共用 `/data` 里的同一套客户端脚本，但底层小米服务版本不同，脚本会按系统自动选择结果源。
- boot1 当前稳定策略是保证原生命令和首轮 LLM；连续追问仍在探索更理想的“干净音频/原生 ASR reopen”方案。

## 1. 推荐阅读顺序

如果你是第一次拿自己的小爱音箱尝试打通 LLM，按这个顺序读：

```text
README
  -> BRINGUP_GUIDE：从串口、SSH、文件上传到第一次 LLM 响应
  -> BOOT_FLOW：理解 boot/system/rootfs，知道为什么要兼容两套系统
  -> QUICKSTART：SSH 已可用后的日常启动
  -> OPERATIONS：启动、停止、看日志、切 boot、自启动
  -> TROUBLESHOOTING：有唤醒但无动作、串台、音量、追问等问题
```

| 你要做什么 | 读这个 |
|---|---|
| 从零打通一台小爱音箱 | [docs/BRINGUP_GUIDE.md](docs/BRINGUP_GUIDE.md) |
| SSH 已可用后的快速联调 | [docs/QUICKSTART.md](docs/QUICKSTART.md) |
| 日常启动、停止、看日志、切 boot | [docs/OPERATIONS.md](docs/OPERATIONS.md) |
| 遇到没响应、播报串台、音量异常 | [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) |
| 理解 native-first 怎么工作 | [docs/NATIVE_FIRST_ARCHITECTURE.md](docs/NATIVE_FIRST_ARCHITECTURE.md) |
| 理解 boot0/system0/kernel/rootfs | [docs/BOOT_FLOW.md](docs/BOOT_FLOW.md) |
| 术语解释：KWS、TTS、VAD、ALSA 等 | [docs/GLOSSARY.md](docs/GLOSSARY.md) |
| boot0 SSH 注入操作 | [docs/BOOT0_SSH_RUNBOOK.md](docs/BOOT0_SSH_RUNBOOK.md) |
| boot1 SSH 注入操作 | [docs/BOOT1_SSH_RUNBOOK.md](docs/BOOT1_SSH_RUNBOOK.md) |
| 断电重启后自动运行 | [docs/AUTOSTART_INIT_HOOK.md](docs/AUTOSTART_INIT_HOOK.md) |
| 自动化测试和人工测试 | [TESTING.md](TESTING.md) |
| 历史探索和旧路线 | [docs/history/README.md](docs/history/README.md) |

旧版文档已原样归档到 [docs/archive/2026-06-07-pre-doc-reorg](docs/archive/2026-06-07-pre-doc-reorg)。

## 2. 当前主线

```text
小爱同学
  -> 小米原生唤醒
  -> 小米原生 ASR/NLP
  -> native_first_client.sh 读取原生结果
       -> 原生成功 domain：恢复/重放原生 speak
       -> 原生不支持：冻结失败播报，转 Mac LLM
  -> Mac 服务端调用 LLM + EdgeTTS
  -> 音箱播放 LLM 音频
```

当前部署到音箱的主脚本：

```text
/data/native_first_client.sh
```

推荐配置文件：

```text
/data/native_first.env
```

配置模板：

```text
device/native_first.env.example
```

## 3. 快速启动

Mac 服务端：

```sh
cd /Users/mac-mini-wx/research/xiaomi_ai/xiaomi_ai_llm
./start_server.sh
```

音箱端：

```sh
SERVER=http://192.168.8.150:8080 BACKEND=deepseek \
sh /data/native_first_client.sh > /tmp/native_first_client.log 2>&1 &
```

看日志：

```sh
tail -f /tmp/native_first_client.log /tmp/native_first_events.log
```

更完整步骤见 [docs/QUICKSTART.md](docs/QUICKSTART.md)。

## 4. 音箱上需要哪些文件

音箱端最小运行文件放在 `/data`：

```text
/data/native_first_client.sh       # 当前主客户端
/data/native_first.env             # 当前设备配置
/data/native_first.env.example     # 配置模板
/data/vad_record.sh                # boot0 追问/历史录音能力需要
/data/data_init_native_first.sh     # 自启动入口模板
/data/init.sh                      # 自启动时实际执行的入口
```

通过 SSH 上传时，常用命令是：

```sh
scp -O -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa \
  device/native_first_client.sh device/native_first.env.example device/vad_record.sh device/data_init_native_first.sh \
  root@192.168.8.152:/data/
```

然后在音箱上：

```sh
cp /data/native_first.env.example /data/native_first.env
chmod +x /data/native_first_client.sh /data/vad_record.sh /data/data_init_native_first.sh
```

如果还没有 SSH，就不能指望快速上传文件，只能先通过串口/failsafe 打通 SSH。完整过程见 [docs/BRINGUP_GUIDE.md](docs/BRINGUP_GUIDE.md)。

## 5. 服务端能力

Mac 服务端负责：

- 接收音箱 fallback 文本。
- 调用 DeepSeek、MiniMax、OpenAI、Claude 等 LLM 后端。
- 使用 EdgeTTS 生成语音，当前默认音色为 `zh-CN-YunjianNeural`。
- 保留 Whisper ASR 接口，作为历史路线、测试和兜底能力。

常用接口：

| 端点 | 用途 |
|---|---|
| `GET /` | 健康检查 |
| `POST /api/v1/stream/text_chat` | native-first 文本进入 LLM 并流式返回 TTS |
| `POST /api/v1/route/asr` | 录音 ASR + 路由，当前主要用于测试和兜底 |
| `POST /api/v1/stream/chat` | 录音上传、ASR、LLM、TTS 一体化历史接口 |

## 6. 测试

自动化测试：

```sh
./scripts/run_tests.sh
```

人工测试用例：

```text
tests/manual_native_first_cases.md
```

修改状态机、路由、音量、TTS、ASR 或启动脚本后，至少跑自动化测试；涉及真实音箱行为时，再跑对应人工用例。

## 7. 当前已知边界

- native-first 首轮 fallback 已是当前主线。
- 原生成功播报通过 `speak/to_speak` replay，控制类短播报可在下一次唤醒时取消。
- boot1/system1 的原生结果源和 boot0/system0 不同，脚本保留两套适配。
- 连续追问还不是最终形态。boot0 可走本地录音方案；boot1 默认关闭追问以优先保证主流程稳定。
- 原生 ASR reopen 多轮方案已多次验证未打通，后续更值得投入的是“获取小米处理后的干净音频”。

## 8. 目录速览

```text
server/                 Mac FastAPI 服务端
device/                 音箱端脚本和配置模板
docs/                   当前说明、架构、运维、排障、历史
tests/                  自动化测试和人工测试用例
config.yaml             LLM / ASR / TTS 配置
start_server.sh         Mac 服务端标准启动入口
```
