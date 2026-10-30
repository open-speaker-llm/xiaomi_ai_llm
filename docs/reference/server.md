# 可选服务端

音箱可以自己调用 LLM 和 EdgeTTS。只有选择服务端 TTS、服务端 LLM/TTS 一体链路，或研究旧 Mac ASR 路线时，才需要本页的 FastAPI 服务。

## 它在链路中的位置

| 选择 | 音箱做什么 | 服务端做什么 |
|---|---|---|
| `LLM_PIPELINE=native`、`TTS_ENGINE=server` | 调用模型，发送待播文字 | 合成流式语音 |
| `LLM_PIPELINE=server` | 发送识别后的文字 | 调用模型、切句并合成语音 |
| 旧 PCM / Whisper 路线 | 发送录音 | 识别与质量门控，按接口继续处理 |

第一种模式不把模型调用移到服务端。独立旧追问识别服务另见 [PCM 回退组件](../../device/pcm_tap/README.md)，不作为 boot1 `native_live` 的前置条件。

旧的 `python -m server.followup_asr --model small --threads 4` 入口仍独立运行，仅在应用启动时加载自身的 PyTorch / Whisper 依赖，不初始化 LLM 或 TTS。它需要完整 ASR 依赖，不能只安装 `requirements-tts.txt`；沿用中文、CPU 推理和 `-0.75` 识别质量门槛，监听地址与端口仍由该入口的 `--host` / `--port` 指定。

## 准备与启动

先选择服务模式。`config.yaml` 的 `server.mode` 默认仍为 `full`，已有完整环境可以继续使用 `./start_server.sh`。

| 模式 | 启用组件 | 依赖入口 |
|---|---|---|
| `full`（默认） | 按配置初始化 LLM、ASR、TTS；默认 ASR 是 Whisper | `requirements.txt` |
| `tts-only` | 仅初始化所选 TTS；不导入或加载 Whisper、LLM SDK 与模型 | `requirements-tts.txt` 支持默认 EdgeTTS |

音箱使用 `LLM_PIPELINE=native`、`TTS_ENGINE=server` 时可选 `tts-only`：模型密钥仍在音箱配置中，服务端不需要 LLM 密钥。轻量依赖清单只包含 EdgeTTS 路线需要的库；改用 ChatTTS、MiniMax TTS 等后端仍需安装对应额外依赖。

首次准备轻量 EdgeTTS 环境，在仓库根目录执行：

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-tts.txt
ffmpeg -version
./start_server.sh --mode tts-only --no-reload
```

系统需另有可执行的 `ffmpeg`。EdgeTTS 初始化时会检查它；缺失会明确报错并停止启动，不会继续加载 Whisper。`edge-tts`、`python-multipart` 已列入依赖，不需要再单独补装。已有完整 `.venv` 的用户可直接使用上述启动命令；切换模式不会卸载已有依赖。

需要服务端调用 LLM 或识别录音时，准备完整模式：

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
# 在 .env 填写所选模型密钥，并核对 config.yaml 的 llm/asr/tts。
./start_server.sh
```

完整模式的默认 Whisper 可能需要下载模型并占用较多内存。EdgeTTS 音色在 `tts.edgetts.voice`。服务端的 `.env`/`config.yaml` 与音箱 `/data/native_first.env` 是两份配置，详见[配置参考](configuration.md)。

`start_server.sh` 使用 `.venv/bin/python` 调用统一启动器；也可设置 `PYTHON=/绝对路径/python` 使用其他虚拟环境。监听地址、端口、模式、自动重载从同一份配置读取，例如：

```yaml
server:
  mode: full
  host: "0.0.0.0"
  port: 8080
  reload: true
```

保留了原有开发重载默认值，日常运行可将 `reload` 设为 `false`，或加 `--no-reload`。`--reload`、`--mode tts-only` 只覆盖此次启动；`--config /绝对路径/config.yaml` 选择另一份配置。修改端口后，服务端启动和应用使用的端口一致，音箱 `SERVER`/`TTS_SERVER` 地址仍需由用户同步修改。

配置文件同目录的 `.env` 由 Python 解析，不再交给 shell 展开或 `xargs` 拆词。已导出的环境变量优先于 `.env`；引号内的空格、`#`、`$()`、反引号及 `${...}` 按值保留，不执行命令或递归替换。YAML 中单独的 `${变量名}` 仍会读取该环境变量。模式优先级为 `--mode` → `XIAOMI_SERVER_MODE` 环境变量或 `.env` → `server.mode`；配置路径优先级为 `--config` → 已导出的 `XIAOMI_SERVER_CONFIG` → 仓库 `config.yaml`。启动器在读取 `.env` 前固定配置路径，`.env` 中的同名变量不能重选配置文件，重载进程也使用这一固定路径。

已有环境需要后台运行时，在开发机执行：

```sh
nohup ./start_server.sh --mode tts-only --no-reload > /tmp/server.log 2>&1 &
tail -f /tmp/server.log
```

后台完整模式将 `--mode tts-only` 改为 `--mode full`。首次检查建议保持前台运行，方便停止和查看启动错误。

## 确认服务可用

先在服务端本机检查：

```sh
curl http://127.0.0.1:8080/
```

再从音箱检查实际局域网地址：

```sh
curl -m 5 http://192.168.8.150:8080/
```

根接口保留原有配置字段，并增加 `mode` 与 `components`。`tts-only` 下 LLM/ASR 的 `state` 是 `disabled`，已初始化的 TTS 是 `ready`；完整模式未配置的组件是 `not_configured`，顶层 `status` 为 `degraded`。`ready` 表示本地初始化完成，不表示云端请求已经验证成功。

`tts-only` 保留健康、纯 TTS 和临时调试文件传输接口。LLM、ASR、一体语音对话及会话历史 HTTP 接口返回 503，并说明需要 `full` 模式。WebSocket 语音接口也拒绝连接；支持握手拒绝扩展时返回 503，否则发送关闭码 1013。HTTP 可达不等于云端 TTS 或 LLM 已成功；随后按[首轮用例](../getting-started/quickstart.md#5-按顺序完成三条验证)完成实际播放。端口不通、合成失败等情况见 [TTS 排障](../runbooks/troubleshooting.md#9-tts-路线排障)。

## 服务模式人工检查与恢复

这些操作由使用者在准备好环境后执行，不能把主机自动化通过当作音箱验收完成。

1. 前台运行 `./start_server.sh --mode tts-only --no-reload`，在另一终端执行 `curl -s http://127.0.0.1:8080/`。确认 `mode=tts-only`、TTS `ready`、LLM/ASR `disabled`；启动日志不应出现 Whisper 模型加载。
2. 执行 `curl -s -w '\nHTTP=%{http_code}\n' -X POST http://127.0.0.1:8080/api/v1/asr`。应返回 503，而不是开始识别或下载模型。
3. 需要测试真实云端 TTS 时，执行以下命令并在电脑听取一句话。它会调用配置的 TTS 云服务；不向音箱部署任何代码。

   ```sh
   curl -f --max-time 30 -F 'message=这是仅语音合成模式的测试。' \
     http://127.0.0.1:8080/api/v1/tts/stream -o /tmp/xiaomi-mode-test.wav
   ffmpeg -v error -y -i /tmp/xiaomi-mode-test.wav -c:a pcm_s16le /tmp/xiaomi-mode-test-fixed.wav
   afplay /tmp/xiaomi-mode-test-fixed.wav
   ```

4. 自定义端口检查应使用临时配置副本：将 `config.yaml` 复制到单独临时目录，把副本的 `server.port` 改为 `18080`，运行 `./start_server.sh --config /该临时目录/config.yaml --mode tts-only --no-reload`，确认 `curl http://127.0.0.1:18080/` 可达。该目录不需要 LLM 密钥或 `.env`；不修改音箱地址。
5. 恢复时用 `Ctrl+C` 停止前台测试进程，再运行 `./start_server.sh --mode full --no-reload`，或继续使用既有启动方式。完整模式仍需完整依赖与 ASR/LLM 配置；只安装轻量依赖的环境先安装 `requirements.txt`。测试使用命令行覆盖和临时副本时，无需改回仓库配置或音箱配置。

## 常用接口

| 接口 | 用途 |
|---|---|
| `GET /` | 健康与配置状态 |
| `POST /api/v1/tts/stream` | 纯文字转流式 WAV，不调用 LLM |
| `POST /api/v1/stream/text_chat` | 文字进入 LLM，再返回语音流 |
| `POST /api/v1/route/asr` | 录音识别与质量门控，供测试或旧路线 |
| `POST /api/v1/stream/chat` | 录音 → ASR → LLM → TTS 的历史一体接口 |

更多入口以 [server/main.py](../../server/main.py) 为准。接口选择不改变音箱原生首轮与 boot1 原生追问的云识别路径。

## 纯 TTS 的失败处理

`POST /api/v1/tts/stream` 仍返回单声道、32 kHz、16-bit 的流式 WAV。服务端从合成结果的 RIFF `data` 块提取音频，跳过 `LIST/INFO` 等元数据，核对声道、位宽和采样率，并兼容 ffmpeg 管道输出的未知长度标记。非空文本必须先合成出有效 PCM 才返回 HTTP 200；首句合成失败、WAV 截断、格式不符、零帧或纯静音时返回 HTTP 502。后续句子保持逐句合成，不等待整段合成完成。

响应开始后发生合成失败，服务端会中断传输，不跳过失败句子，也不以正常结束表示完整播放。此时 HTTP 状态码已经发出，仍可能显示 200；调用方必须同时检查下载进程退出状态，例如使用 `curl -f` 并检查返回码。首段尚未播放时可交给原生 TTS 兜底；已有部分声音播放时应结束本轮，避免把整段重新播一遍。

这项约定针对纯 TTS 接口；旧的服务端 LLM/TTS 一体接口仍需单独验收失败时的播放和上下文行为。

## 临时调试文件传输

调试接口保留如下形式：

| 接口 | 用途 |
|---|---|
| `PUT /api/v1/upload/{filename}` | 上传原始二进制请求体 |
| `POST /api/v1/upload_file` | 上传 multipart 的 `file` 字段 |
| `GET /api/v1/download/{filename}` | 下载同一服务进程收到的文件 |

文件写入系统临时目录下、本进程专属的 `xiaomi-ai-uploads-*` 目录。上传响应仍包含 `status`、`size`、`path`，以返回的 `path` 为实际路径；不再写入固定的 `/tmp/{filename}`。目录只对当前用户开放。服务进程正常退出后临时目录自动清理，重启或开发模式 reload 后不应继续使用旧文件名；多进程服务各自保存文件，调试传输应使用同一服务进程。

文件名长度为 1–128 个字符，首字符为英文字母或数字，其余只允许英文字母、数字、`_`、`-`、`.`。路径、隐藏文件名和其他字符返回 HTTP 400；同名文件或符号链接不会被覆盖，上传返回 HTTP 409。下载只允许目录中的普通文件，缺失文件、目录、FIFO 和符号链接返回 HTTP 404。

这些接口用于现有局域网调试，没有新增身份认证、上传配额或长期文件存储能力，不属于音箱日常对话的依赖。
