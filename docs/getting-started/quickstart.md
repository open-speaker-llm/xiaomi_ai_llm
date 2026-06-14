# 快速上手

文档类型：SSH 已可用后的快速联调
适用范围：已打通 SSH + 已能向 `/data` 上传文件的小米音箱；TTS 可选 Mac 服务端或音箱端 `ettsc`
当前结论：如果你还没有 SSH，先读 [bringup.md](bringup.md)

> 示例 IP、`ssh xiaomi` 别名等约定见 [../README.md](../README.md#文档约定)。

## 0. 前提

- Mac 和音箱在同一网络（如果不部署 Mac TTS 服务端，只需要 Mac 能通过 SSH 上传文件）。
- 音箱可以 SSH 登录（`~/.ssh/config` 已配置 `xiaomi` 别名）。
- 音箱 `/data` 可写。
- 已知道 Mac IP，例如 `192.168.8.150`。

如果还没有 SSH，先走完整路线：[bringup.md](bringup.md)。

## 1. 上传音箱端文件

在 Mac 仓库根目录执行：

```sh
scp -O device/native_first_client.sh device/native_first.env.example \
    device/vad_record.sh device/data_init_native_first.sh \
    xiaomi:/data/
```

登录音箱后执行：

```sh
cp /data/native_first.env.example /data/native_first.env
chmod +x /data/native_first_client.sh /data/vad_record.sh /data/data_init_native_first.sh
```

编辑配置 `vi /data/native_first.env`，至少确认：

```sh
BACKEND=deepseek
NATIVE_RESULT_SOURCE=auto
LLM_PIPELINE=native
DEEPSEEK_API_KEY=sk-...
TTS_FALLBACK_NATIVE=1
```

`LLM_PIPELINE=native` 时，音箱自己直连 LLM。TTS 由 `TTS_ENGINE` 选择，失败时由 `TTS_FALLBACK_NATIVE=1` 退回小爱原生 `mibrain` TTS。

## 2. 选择 TTS 路线

| 路线 | 配置 | 需要做什么 |
|---|---|---|
| Mac/迷你 TTS 服务端 EdgeTTS | `TTS_ENGINE=server` | 配置 `TTS_SERVER` 并启动下面的服务端 |
| 音箱端直连 EdgeTTS | `TTS_ENGINE=device` | 构建并部署 `/data/ettsc`，不需要 Mac 服务端 |
| 小爱原生 TTS 兜底 | `TTS_FALLBACK_NATIVE=1` | 保持默认，EdgeTTS 失败时自动出声 |

如果使用 Mac/迷你 TTS 服务端：

```sh
TTS_ENGINE=server
SERVER=http://192.168.8.150:8080
TTS_SERVER=http://192.168.8.150:8080
```

启动服务端：

```sh
./start_server.sh
```

健康检查：

```sh
curl http://127.0.0.1:8080/
```

后台运行时看日志：

```sh
tail -f /tmp/server.log | grep -E '📥|🎤|🌐|🔊|🤖|✅|⚠️'
```

EdgeTTS 音色在 `config.yaml` 的 `tts.edgetts.voice` 配置，默认是 `zh-CN-YunjianNeural`。

如果使用音箱端直连 EdgeTTS：

```sh
cd device/ettsc
./build.sh
./deploy.sh 192.168.8.152
```

音箱配置：

```sh
TTS_ENGINE=device
DEVICE_TTS_BIN=/data/ettsc
DEVICE_TTS_VOICE=zh-CN-YunjianNeural
```

`dist/ettsc` 是本地构建产物，不提交到仓库；如果不想使用 EdgeTTS，保持 `TTS_FALLBACK_NATIVE=1` 即可退回小爱原生 TTS。

## 3. 启动音箱客户端

登录音箱：

```sh
ssh xiaomi
```

前台调试：

```sh
SERVER=http://192.168.8.150:8080 BACKEND=deepseek sh /data/native_first_client.sh
```

后台运行：

```sh
SERVER=http://192.168.8.150:8080 BACKEND=deepseek sh /data/native_first_client.sh > /tmp/native_first_client.log 2>&1 &
```

## 4. 确认启动成功

```sh
tail -f /tmp/native_first_client.log /tmp/native_first_events.log
```

应看到类似：

```text
[HOOK] mounted /bin/wakeup.sh -> /tmp/wakeup.sh.native_first_client
[HOOK] watchdog pid=...
[IDLE] 等待原生唤醒词：小爱同学
```

## 5. 三条验证用例

按顺序一条一条测，每条等播报或日志稳定后再测下一条：

| 说 | 期望 |
|---|---|
| 小爱同学，开灯 | 走原生，不进 LLM |
| 小爱同学，今天天气怎么样 | 走原生播报 |
| 小爱同学，呼叫 DeepSeek | 原生不支持，转 LLM |

更完整人工用例见 [../../tests/manual_native_first_cases.md](../../tests/manual_native_first_cases.md)。

## 6. 之后

- 日常启动、停止、看日志、切 boot：[../runbooks/operations.md](../runbooks/operations.md)
- 不符合预期：[../runbooks/troubleshooting.md](../runbooks/troubleshooting.md)
- 断电重启自动运行：[../runbooks/autostart.md](../runbooks/autostart.md)
