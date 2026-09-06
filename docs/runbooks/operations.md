# 日常运维命令

文档类型：当前命令手册
适用范围：日常联调、启动停止、看日志、切 boot、串口/failsafe
当前结论：常规联调用 `native_first_client.sh`，旧 KWS/stream 路线只作为历史参考

> 本文使用 `ssh xiaomi` 别名和示例 IP，约定见 [../README.md](../README.md#文档约定)。

## 1. Mac 服务端

本节仅在选择 server LLM/TTS 或旧 Mac 识别路线时需要。音箱直连 LLM + 设备 TTS + 原生追问模式不需要常驻 Mac，仍需联网。

启动（仓库根目录）：

```sh
./start_server.sh
```

后台启动：

```sh
nohup ./start_server.sh > /tmp/server.log 2>&1 &
```

看日志：

```sh
tail -f /tmp/server.log | grep -E '📥|🎤|🌐|🔊|🤖|✅|⚠️'
```

健康检查：

```sh
curl http://127.0.0.1:8080/
```

## 2. 音箱登录

```sh
ssh xiaomi
```

不配 `~/.ssh/config` 别名时，用完整命令：

```sh
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152
```

如果提示 host key 冲突：

```sh
ssh-keygen -R 192.168.8.152
```

## 3. 音箱客户端

启动：

```sh
SERVER=http://192.168.8.150:8080 BACKEND=deepseek sh /data/native_first_client.sh > /tmp/native_first_client.log 2>&1 &
```

查看状态 / 停止：

```sh
sh /data/native_first_client.sh status
sh /data/native_first_client.sh stop
```

看日志：

```sh
tail -f /tmp/native_first_client.log /tmp/native_first_events.log
```

确认进程：

```sh
ps | grep -E 'native_first_client|mipns-xiaomi|mediaplayer|curl|aplay|arecord' | grep -v grep
```

启动成功的标志：

```text
[HOOK] mounted /bin/wakeup.sh -> /tmp/wakeup.sh.native_first_client
[IDLE] 等待原生唤醒词：小爱同学
```

### 音箱直连 LLM（默认主线，LLM_PIPELINE=native）

**默认就是 native**——音箱直连 LLM，TTS 由 `TTS_ENGINE` 独立选择。`/data/native_first.env` 关键项：

```sh
LLM_PIPELINE=native                     # 默认；音箱直连 LLM
DEEPSEEK_API_KEY=sk-...                 # native 模式必填，否则无法直连 LLM
TTS_SERVER=http://192.168.8.150:8080   # TTS 微服务地址，可指向任意常驻设备
TTS_ENGINE=server                       # server=Mac/迷你 TTS 服务；device=音箱端 ettsc
TTS_FALLBACK_NATIVE=1                   # TTS 微服务不可用时走小爱原生 TTS
LLM_THINKING=disabled                   # deepseek-v4-flash 关思考，首句 ~2s
```

启动后日志里会看到 `[LLM-NATIVE] direct → ...`。TTS 有三种用法：

| 需求 | 做法 | 效果 |
|---|---|---|
| Mac/迷你 TTS 服务端 EdgeTTS | `TTS_ENGINE=server`，启动 `./start_server.sh` 或其他 `/api/v1/tts/stream` 服务 | 端点切句流式返回 WAV，音色在 `config.yaml` 的 `tts.edgetts.voice` 调整 |
| 音箱端直连 EdgeTTS | `TTS_ENGINE=device`，部署 `/data/ettsc` | 不需要 Mac 服务端，音箱自己连 EdgeTTS 并用原生播放器播放 MP3 |
| 小爱原生 TTS 兜底 | 保持 `TTS_FALLBACK_NATIVE=1` | EdgeTTS 路线失败时自动走 `mibrain text_to_speech`，保证不哑 |

也就是说，Mac 服务端不是 native 主线的必需项；想要 EdgeTTS 可以选 Mac/迷你服务端，也可以选音箱端 `ettsc`。原理见 [../concepts/native-first.md](../concepts/native-first.md)。

回退到经 Mac 调 LLM：把 `LLM_PIPELINE` 改成 `server` 重启即可。

### boot1 原生连续追问

先按 [组件安装说明](../../device/native_asr/README.md) 安装通过固件校验的 `native_asr`。在音箱上查看：

```sh
sh /data/native_asr.sh status
/data/native_asr_ctl status
tail -n 30 /tmp/native_followup/events.log
tail -n 50 /tmp/native_first_client.log
```

预期管理器为 `healthy`，客户端记录 `native ASR-only ready; no external recognizer`。每次追问有新 dialog 和 `ASR-only ... disabled=NLP,TTS`，最终文本进入同一 LLM session；静默结束返回 124 并回到 IDLE。

日常使用：唤醒并让 LLM 回答，绿灯续听时直接追问，保持安静退出。没有播放中打断，“退下”等结束语交给 LLM 正常处理。

临时停用追问：将配置最后生效的 `SYSTEM1_FOLLOWUP_ENABLED` 设为 `0` 后重启客户端；完整卸载/回退使用安装器输出备份目录内的 `restore.sh`。boot0 保留原录音与文件 ASR；不要全局改成 `native_live`。旧 PCM + Mac 路线与原生追问管理器不同时加载。

## 4. 配置文件

音箱上的运行配置：

```sh
cp /data/native_first.env.example /data/native_first.env   # 首次创建
vi /data/native_first.env
```

仓库中的模板：`device/native_first.env.example`（各参数含义见模板内注释）。

## 5. boot 分区切换

2026-09-05 本项目实机已验证两套系统公钥 SSH 与原生 OTA 拦截，当次最终回到 boot0，用户确认唤醒和回复正常。2026-09-06 已在 boot1 部署并验证原生连续追问，当前使用哪套系统应读取实际根分区。其他设备或后来刷入的镜像需单独核验。维护策略和验证命令见 [双系统 SSH 与受控升级](owner-maintenance.md)。

切换前确认目标系统已具备 SSH；SSH 可用不代表助手已配置自启动。2026-09-06 已补齐本机 system1 的入口，并持久安装失败提示快速拦截器；boot1 重启后自动启动、转 LLM 无先行失败提示已验证。见 [自启动恢复](../history/2026-09-06-boot1-autostart.md) 、[拦截修复](../history/2026-09-06-boot1-fallback-guard.md) 及 [原生追问自启动](../history/2026-09-06-boot1-native-followup.md)。

查看当前启动分区：

```sh
ssh xiaomi 'fw_env -p 2>&1 | grep -A1 "key: \[boot_part\]"'
```

切换并重启：

```sh
ssh xiaomi 'fw_env -s boot_part boot0 && reboot'
ssh xiaomi 'fw_env -s boot_part boot1 && reboot'
```

不配 `ssh xiaomi` 别名时，切到 `boot1` 的完整命令：

```sh
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152 'fw_env -s boot_part boot1 && sync && reboot'
```

重启完成后再次连接，并确认根分区是 `system1`：

```sh
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152 'fw_env -p 2>&1 | grep -A1 "key: \[boot_part\]"; mount | grep " on / "'
```

说明：

- 这台音箱使用 Amlogic 定制版 `fw_env`，通过 `/dev/nand_env` 直接读写 U-Boot 环境变量，不需要 `fw_env.config`，语法为 `fw_env -s <name> <value>`。
- 如果切换后系统无法启动或无法 SSH，走串口进入 U-Boot 切回（见下文第 6、7 节）。
- boot0/boot1 与 system0/system1 的关系见 [../concepts/boot-and-partitions.md](../concepts/boot-and-partitions.md)。

## 6. Mac 串口 screen

```sh
ls /dev/tty.*
screen /dev/tty.usbserial-3120 115200
```

退出 screen：`Ctrl+A → K → Y`。

串口下进 U-Boot 切 boot：启动时按任意键中断，然后：

```text
s12# setenv boot_part boot0
s12# saveenv
s12# reset
```

## 7. failsafe

failsafe 只在 boot0 上。先按上节切回 boot0，重启后看到：

```text
Press the [f] key and hit [enter]
```

立即按 `f → Enter`。

## 8. 自启动

长期方案见 [autostart.md](autostart.md)。验证自启动日志：

```sh
tail -f /tmp/native_first_autostart.log /tmp/native_first_client.log /tmp/native_first_events.log
```

## 9. 历史命令

重构前完整命令手册已归档：`docs/archive/2026-06-07-pre-doc-reorg/DEV_COMMANDS.md`。

旧 KWS、`stream_client.sh`、`native_client.sh`、各类 probe 脚本只在做历史对照或专项探索时使用，见 [../history/README.md](../history/README.md)。
