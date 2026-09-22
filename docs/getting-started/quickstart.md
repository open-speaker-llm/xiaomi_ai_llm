<a id="快速上手"></a>

<a id="0-前提"></a>

<a id="1-上传音箱端文件"></a>

<a id="2-选择-tts-路线"></a>

<a id="boot1-失败提示快速拦截"></a>

<a id="3-启动音箱客户端"></a>

<a id="4-确认启动成功"></a>

<a id="5-三条验证用例"></a>

<a id="6-之后"></a>

# 跑通第一轮对话

这一页只做一件事：让已具备 SSH 的音箱保留原生功能，并完成一次 LLM 问答。先完成这条最小闭环，随后再增加追问、首轮判停和自启动。

前提是型号与固件已确认、开发机能 `ssh xiaomi`、音箱 `/data` 可写且能访问所选云服务。没有 SSH 时从[零开始接入](bringup.md)。下文使用[统一地址约定](../README.md#文档约定)。

**本页用于首次部署。** 已安装本地判停包的设备按[整包维护说明](../../device/native_endpoint/README.md#安装)操作，不直接覆盖客户端或共享的 `native_asr.so`。

## 1. 上传客户端，建立私有配置

在开发机仓库根目录上传：

```sh
scp -O device/native_first_client.sh device/native_first.env.example \
    device/vad_record.sh device/data_init_native_first.sh \
    xiaomi:/data/
```

登录音箱后执行。已有配置不会被下面的首次创建命令覆盖：

```sh
[ -f /data/native_first.env ] || cp /data/native_first.env.example /data/native_first.env
chmod +x /data/native_first_client.sh /data/vad_record.sh /data/data_init_native_first.sh
vi /data/native_first.env
```

以 DeepSeek 为例，在配置文件中确认以下项，并填写自己的密钥：

```sh
BACKEND=deepseek
NATIVE_RESULT_SOURCE=auto
LLM_PIPELINE=native
DEEPSEEK_API_KEY=sk-...
TTS_FALLBACK_NATIVE=1
```

同一变量只保留一条有效赋值。配置文件由客户端直接读取，不需要在命令行重复填写密钥；其他模型和高级覆盖项见[配置参考](../reference/configuration.md)。

## 2. 选好回答的声音从哪里来

LLM 产生文字，TTS 把文字变成声音。音箱直连模型时，TTS 仍有两条路线，选一条部署即可。

| 你的部署方式 | 设置 | 前置工作 |
|---|---|---|
| 音箱独立运行 | `TTS_ENGINE=device` | 按 [ettsc 说明](../../device/ettsc/README.md)准备 Rust/Zig 工具链，构建并部署 `/data/ettsc` |
| 有常驻电脑提供 TTS | `TTS_ENGINE=server` | 按[服务端说明](../reference/server.md)启动服务，配置 `TTS_SERVER` |

通用模板默认 `TTS_ENGINE=server`。若要不依赖常驻电脑，需要显式切到 `device` 并完成组件安装。`TTS_FALLBACK_NATIVE=1` 允许 EdgeTTS 失败时尝试小爱原生 TTS，兜底也需单独验证。

选择设备端 TTS，准备好工具链后在开发机执行：

```sh
cd device/ettsc
./build.sh
./deploy.sh 192.168.8.152
```

音箱 `/data/native_first.env` 中设置：

```sh
TTS_ENGINE=device
DEVICE_TTS_BIN=/data/ettsc
DEVICE_TTS_VOICE=zh-CN-YunjianNeural
```

选择服务端 TTS，则在音箱配置中设置实际地址：

```sh
TTS_ENGINE=server
SERVER=http://192.168.8.150:8080
TTS_SERVER=http://192.168.8.150:8080
```

## 3. boot1 补齐失败提示拦截

boot0 可以继续下一步。boot1 按 [guard 构建部署说明](../../device/aivs_guard/README.md)安装 `/data/aivs_speech_guard`，保留 `AIVS_GUARD_ENABLED=1` 与 `FREEZE_NATIVE_PLAYER_ON_FALLBACK=1`。

只上传 shell 不会获得快速拦截，helper 缺失时退回轮询。稍后安装原生 ASR 组件还会提供匹配固件的提前拦截路径；文本规则的误判、漏判边界仍然存在。

## 4. 启动，并确认已进入待机

在音箱执行。若已有客户端运行，先按[日常操作](../runbooks/operations.md#客户端)在空闲时停止，不启动第二个实例。

```sh
sh /data/native_first_client.sh > /tmp/native_first_client.log 2>&1 &
tail -f /tmp/native_first_client.log /tmp/native_first_events.log
```

配置沿用 `/data/native_first.env`。预期日志包括：

```text
[HOOK] mounted /bin/wakeup.sh -> /tmp/wakeup.sh.native_first_client
[IDLE] 等待原生唤醒词：小爱同学
```

`IDLE` 表示客户端已经待机，接下来仍要分别验证原生处理、模型调用和出声。

## 5. 按顺序完成三条验证

每条等动作或播报完成后再说下一条。家电用例以音箱原本已经能控制该设备为前提。

| 说什么 | 检查什么 |
|---|---|
| 小爱同学，开灯 | 真实家电动作完成，没有进入 LLM |
| 小爱同学，今天天气怎么样 | 原生播报仍可用 |
| 小爱同学，问问 DeepSeek，用一句话介绍西湖 | LLM 回答并完整播放 |

boot1 再执行 [P3 失败提示用例](../../tests/manual_native_first_cases.md#p3-boot1-失败提示漏播对照)：用实际会触发失败提示的问题验证转接，再用正常报时作对照。直接说出 DeepSeek 触发词通过，不等于失败提示拦截也已验证。

出现问题时，带着这一步的日志进入[排障手册](../runbooks/troubleshooting.md)。全部通过后，首轮闭环就建立了。

<a id="boot1-开启原生免唤醒追问"></a>
<a id="boot1-首轮本地判停"></a>

## 下一步：让对话自然接续

继续阅读[逐步完善对话](conversation.md)，分别安装和验收免唤醒追问、首轮本地判停；只需要基本问答时，也可以直接配置[自启动](../runbooks/autostart.md)。已经部署的设备不需要反复执行本页的首次上传步骤。
