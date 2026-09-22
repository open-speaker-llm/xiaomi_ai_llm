# 可选服务端

音箱可以自己调用 LLM 和 EdgeTTS。只有选择服务端 TTS、服务端 LLM/TTS 一体链路，或研究旧 Mac ASR 路线时，才需要本页的 FastAPI 服务。

## 它在链路中的位置

| 选择 | 音箱做什么 | 服务端做什么 |
|---|---|---|
| `LLM_PIPELINE=native`、`TTS_ENGINE=server` | 调用模型，发送待播文字 | 合成流式语音 |
| `LLM_PIPELINE=server` | 发送识别后的文字 | 调用模型、切句并合成语音 |
| 旧 PCM / Whisper 路线 | 发送录音 | 识别与质量门控，按接口继续处理 |

第一种模式不把模型调用移到服务端。独立旧追问识别服务另见 [PCM 回退组件](../../device/pcm_tap/README.md)，不作为 boot1 `native_live` 的前置条件。

## 准备与启动

在开发机仓库根目录准备 Python 环境：

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install edge-tts python-multipart
[ -f .env ] || cp .env.example .env
```

当前服务代码还会导入 `edge_tts`、使用表单上传，并通过 `ffmpeg` 转换音频；前两项在现有 requirements 中未列全，以上单独补装。另需安装可执行的 `ffmpeg`。仅启动 EdgeTTS 接口不代表现有完整服务只初始化 TTS：`config.yaml` 默认也初始化 Whisper，可能需要准备相应模型和资源。

选择服务端调用 LLM 时，在 `.env` 填写所选后端密钥，在 `config.yaml` 核对 `llm` 和 `tts`。选择 EdgeTTS 时，音色在 `tts.edgetts.voice`。这与音箱 `/data/native_first.env` 是两份配置，详见[配置参考](configuration.md)。

前台启动：

```sh
./start_server.sh
```

脚本固定使用 `.venv/bin/uvicorn`、端口 `8080` 和开发用 `--reload`。仅修改 `config.yaml` 的端口不会改掉该启动命令；自定义启动时同步修改音箱地址。需要查看完整启动日志时保持前台运行。

已有环境需要后台运行时，在开发机执行：

```sh
nohup ./start_server.sh > /tmp/server.log 2>&1 &
tail -f /tmp/server.log
```

## 确认服务可用

先在服务端本机检查：

```sh
curl http://127.0.0.1:8080/
```

再从音箱检查实际局域网地址：

```sh
curl -m 5 http://192.168.8.150:8080/
```

根接口返回配置状态。HTTP 可达不等于云端 TTS 或 LLM 已成功；随后按[首轮用例](../getting-started/quickstart.md#5-按顺序完成三条验证)完成实际播放。端口不通、合成失败等情况见 [TTS 排障](../runbooks/troubleshooting.md#9-tts-路线排障)。

## 常用接口

| 接口 | 用途 |
|---|---|
| `GET /` | 健康与配置状态 |
| `POST /api/v1/tts/stream` | 纯文字转流式 WAV，不调用 LLM |
| `POST /api/v1/stream/text_chat` | 文字进入 LLM，再返回语音流 |
| `POST /api/v1/route/asr` | 录音识别与质量门控，供测试或旧路线 |
| `POST /api/v1/stream/chat` | 录音 → ASR → LLM → TTS 的历史一体接口 |

更多入口以 [server/main.py](../../server/main.py) 为准。接口选择不改变音箱原生首轮与 boot1 原生追问的云识别路径。
