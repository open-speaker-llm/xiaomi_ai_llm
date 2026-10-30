# 第二轮功能升级：实际测试步骤

日期：2026-10-30。基础版本为第一轮修复提交 `b618f38`；本轮增加只读诊断、TTS 专用服务、按实际配置启动，以及可选的追问结束语。**本轮没有连接、部署或重启音箱，真人验收保留为未执行。可以以后按本说明测试。**

## 先选要验证的部分

| 内容 | 是否需要安装新的音箱客户端 | 是否会改变正在运行的对话 |
|---|---|---|
| 只读诊断 | 不需要，只需运行独立诊断脚本 | 不停止、修复或重启服务 |
| 开发机 TTS-only | 不需要，先在本机独立端口测试 | 不改音箱配置时没有影响 |
| 独立模式自启动 | 需要更新并核对 `/data/init.sh`，保留已有自定义内容 | 只在明确停止客户端后的测试启动中验证 |
| 明确结束追问 | 需要本轮客户端，且追问原本可用 | 仅显式启用结束语开关后改变追问行为 |
| 旧 Mac ASR 兼容入口 | 不需要，仅旧 PCM/Whisper 路线使用者检查 | 独立测试端口不改变音箱当前服务地址 |

不要直接覆盖已安装的首轮判停组合包。新客户端的实机部署仍须按[整包维护说明](../../device/native_endpoint/README.md)核对版本和回滚路径；仓库提交成功不等于音箱已升级。

## A. 只读诊断，约 2 分钟

在开发机仓库根目录执行，使用已配置的 `xiaomi` SSH 别名：

```sh
scp -O device/speaker_doctor.sh xiaomi:/tmp/speaker_doctor.sh
ssh xiaomi 'sh /tmp/speaker_doctor.sh; result=$?; printf "诊断退出码=%s\n" "$result"; exit "$result"'
```

这只上传一个临时脚本，不覆盖 `/data` 中的客户端或配置。预期输出包含实际系统、运行模式、组件依赖、进程/状态快照、文件校验和下一步。不得出现密钥值、完整服务 URL 或原始对话。

| 退出码 | 怎么判断 |
|---|---|
| `0` | 可检查项目通过；仍不能据此判断音箱听说、云端或家电动作已验收 |
| `1` | 有明确缺陷，按对应项目的下一步处理；不要只重跑到得到 0 为止 |
| `2` | 存在未知或待确认，例如复杂配置无法静态解析；阅读具体说明 |
| `64` | 调用参数错误，按脚本帮助纠正 |

重点核对：boot0 没有启用的 boot1 组件不应被当作必需缺失；native + device 不应要求 Mac 在线；组件状态是只读快照迹象，不是通过控制器取得的实时健康结论。完整边界见[诊断说明](../reference/diagnostics.md)。

测试后无需重启设备。如果不想保留临时脚本，可以在空闲时删除 `/tmp/speaker_doctor.sh`；它不参与自启动。

## B. 在 Mac 上单独测试 TTS 服务，约 5 分钟

需要 Python 和可执行的 `ffmpeg`。先确认 `ffmpeg -version` 可运行。使用独立虚拟环境，不覆盖现有 `.venv`：

```sh
python3 -m venv .venv-tts
.venv-tts/bin/python -m pip install -r requirements-tts.txt
```

创建独立测试配置，不读取项目的私有 LLM 配置：

```sh
tts_test_dir=$(mktemp -d /tmp/xiaomi-tts-manual.XXXXXX)
cat > "$tts_test_dir/config.yaml" <<'YAML'
server:
  mode: tts-only
  host: 127.0.0.1
  port: 18080
  reload: false
tts:
  provider: edgetts
  edgetts:
    voice: zh-CN-YunjianNeural
YAML
PYTHON=.venv-tts/bin/python ./start_server.sh \
  --config "$tts_test_dir/config.yaml" --mode tts-only --no-reload
```

预期只初始化 TTS，没有加载 Whisper、下载 ASR 模型或要求 LLM 密钥。另开一个终端执行：

```sh
curl -fsS http://127.0.0.1:18080/
curl -i -X POST -F 'message=你好' \
  http://127.0.0.1:18080/api/v1/stream/text_chat
curl -f --max-time 30 -X POST -F 'message=你好，这是独立语音合成测试。' \
  http://127.0.0.1:18080/api/v1/tts/stream \
  -o /tmp/xiaomi-tts-check.wav
ffmpeg -v error -y -i /tmp/xiaomi-tts-check.wav \
  -c:a pcm_s16le /tmp/xiaomi-tts-check-fixed.wav
afplay /tmp/xiaomi-tts-check-fixed.wav
```

应分别观察到：

1. 健康返回 `mode=tts-only`，LLM/ASR 为 `disabled`，TTS 为 `ready`。`ready` 只表示组件初始化，云端合成是否可用要靠第三步验证。
2. 一体文字对话接口返回 HTTP 503，并说明当前模式已禁用该能力。
3. 纯 TTS 请求成功后，实际听到完整测试句子；此步骤需要网络访问所选 TTS 云服务。若返回 502 或播放失败，记录错误，不能用健康接口的 200 代替成功。

确认服务监听的是测试配置中的 **18080**，而不是写死的 8080。测试结束在服务终端按 `Ctrl+C`。现有项目配置和音箱配置没有改动；恢复原 full 服务时使用原环境和配置，例如 `./start_server.sh --mode full --no-reload`。

音箱若以后要使用这条服务，需要监听音箱可达的地址，并把设备 `TTS_SERVER` 设为开发机实际 IP 和端口；不能在音箱上使用 Mac 的 `127.0.0.1` 地址。完整配置优先级和依赖见[服务端说明](../reference/server.md)。

## C. 用明确短句结束追问，约 5 分钟

仅在未来完成候选客户端部署后执行。先备份实际 `/data/native_first.env`，在空闲时停止客户端：

```sh
config_backup="/data/native_first.env.before-exit-$(date +%Y%m%d-%H%M%S)"
cp -p /data/native_first.env "$config_backup"
printf '配置备份：%s\n' "$config_backup"
sh /data/native_first_client.sh stop
vi /data/native_first.env
```

把唯一有效的 `FOLLOWUP_EXIT_ENABLED` 赋值设为 `1`，再启动：

```sh
sh /data/init.sh
```

不要靠命令前临时设置变量来替代配置文件；文件中的赋值会覆盖它。

| 编号 | 实际操作 | 预期 |
|---|---|---|
| C1 | 唤醒并让模型用一句话介绍西湖；回答结束、绿灯续听时独立说“结束对话” | 不新增模型回答或“再见”确认播报，收听结束、回到待机 |
| C2 | 每次重新建立对话，在续听时分别说“退出对话”“停止对话”“不聊了”“退下” | 与 C1 一致；识别偏差另记，不能当成精确结束规则的通过证据 |
| C3 | 续听时说“不要结束对话，继续介绍西湖” | 正常继续模型回答，不因包含结束词而退出 |
| C4 | 首问说“问问 DeepSeek，解释结束对话的意思” | 正常问答，不拦截首问 |
| C5 | 已进入追问时说“帮我查一下”，听到补充提示后说“退出对话” | 停止补全并退出，不把退出词与残句拼接后提交 |
| C6 | 另开一轮较长播报，播放期间唤醒小爱开关灯 | 原生家控仍工作，LLM 保持播放；结束语功能没有变成播放中打断 |

日志应出现 `[FOLLOWUP] explicit exit; no LLM submission`，对应轮没有新增模型请求、完整问答历史或后续监听。单独说“不要再讲了”“请结束对话”不在精确词表内，仍按普通问句处理。结束词匹配边界见[配置参考](../reference/configuration.md#用结束语退出追问)。

恢复原行为：在实际配置中把该项改回 `0`，空闲时按 stop/init 重启客户端，再复测普通追问。本轮默认值一直是 `0`。

## D. 独立模式的自启动选择

需要先备份并核对 `/data/init.sh`，合并已有自定义内容后才更新，不能把模板直接覆盖用户自定义脚本。无需切换 boot、刷机或马上进行整机重启。

在音箱空闲、实际配置为 native + device、客户端已停止时运行 `sh /data/init.sh`，随后查看：

```sh
tail -n 60 /tmp/native_first_autostart.log
```

应看到 `startup dependency=none`、`skip server probe`、`starting native-first client`，然后做一轮真实问答。原有默认 20 秒等待仍保留；这项改进去掉的是无关 Mac 服务探测，不代表开机立即可用。

实际 native + server 配置应显示 `dependency=tts`，探测 `TTS_SERVER`；server 模式应显示 `dependency=server`，探测 `SERVER`。服务不可达时仍按既有等待预算和 `START_WITHOUT_SERVER` 决定启动。日志不得输出 URL 凭据和密钥。

异常时保留日志，恢复事先备份的 init 脚本及实际配置，再按[自启动说明](../runbooks/autostart.md)检查。不要为测试第二种模式临时覆盖生产密钥或破坏可用组件。

## E. 旧 Mac ASR 路线的兼容检查

仅仍在使用旧 PCM/Whisper 追问服务时执行；boot1 原生追问无需这一步。使用已安装完整依赖的原 `.venv`，不要使用 B 节的轻量环境：

```sh
.venv/bin/python -m server.followup_asr \
  --host 127.0.0.1 --port 18081 --model small --threads 2
```

Whisper 模型未缓存时会下载；已有本地模型可将 `small` 替换为其 `.pt` 绝对路径。启动后在另一终端执行：

```sh
curl -fsS http://127.0.0.1:18081/
curl -i -X POST http://127.0.0.1:18081/api/v1/stream/chat
```

预期健康结果为 `service=followup-asr`，未启动 LLM/TTS；第二个接口返回 404，因为此独立服务仅负责追问识别。不能出现 `main.WhisperASR` 属性缺失错误。按 `Ctrl+C` 停止测试进程，不修改音箱当前服务地址。真正的录音识别、低置信度拒绝和上下文追问继续按 [F-PCM 用例](../../tests/manual_native_first_cases.md#f-pcm-s12a-boot1-处理后-pcm-连续追问)验收，健康检查不能替代它。

## 记录结果

| 日期/提交或包摘要 | 用例 A/B/C/D/E | 结果：通过/失败/不适用/未测试 | 实际输出、听到的内容与恢复结果 |
|---|---|---|---|
| 待填写 | 每项分别记录 | 未测试 | 待填写 |

主机回归与真实依赖隔离结果见[状态页](../status.md)。声音、家电动作和升级恢复仍以未来真人实测为准，未执行项目不填“通过”。
