<a id="日常运维命令"></a>

# 日常操作：检查、调整与恢复

本文用于已经部署的音箱。第一次安装从[快速上手](../getting-started/quickstart.md)进入；参数含义查[配置参考](../reference/configuration.md)，异常症状查[排障手册](troubleshooting.md)。命令使用[统一登录别名](../README.md#文档约定)。

<a id="2-音箱登录"></a>

## 先确认现在运行的是什么

在开发机登录音箱：

```sh
ssh xiaomi
```

以下在音箱执行：

```sh
mount | grep ' on / '
sh /data/native_first_client.sh status
tail -n 50 /tmp/native_first_client.log
```

`/dev/mtdblock4` 对应 system0，`/dev/mtdblock5` 对应 system1。客户端进入 `[IDLE]` 只说明主状态机待机；已经安装的原生追问、本地判停还要检查各自状态。SSH 登录成功不等于语音链路已正常。

<a id="客户端"></a>

<a id="3-音箱客户端"></a>

## 客户端：启动、停止与重启

已有自启动入口时，在音箱空闲、没有播报或收听时重启：

```sh
sh /data/native_first_client.sh stop
sh /data/init.sh
```

首次联调、尚未部署 `/data/init.sh` 时，在没有其他客户端运行的前提下启动：

```sh
sh /data/native_first_client.sh > /tmp/native_first_client.log 2>&1 &
```

配置由 `/data/native_first.env` 读取。仅停止可执行 `sh /data/native_first_client.sh stop`；不要用宽泛的 `killall` 代替组件停止与恢复流程。

```sh
tail -f /tmp/native_first_client.log /tmp/native_first_events.log
```

看到 `[HOOK]` 与 `[IDLE]` 后，再用原生报时和一条 LLM 问答检查实际行为。配置选择和切换后端统一见[模型、声音与会话](../reference/configuration.md)。

## 已安装组件的状态与恢复

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

### boot1 首轮本地判停

安装与升级边界见[组件说明](../../device/native_endpoint/README.md)。它与上述原生追问共用 native_asr 库，但只控制真实唤醒首轮。客户端在 boot1 且 `NATIVE_ENDPOINT_ENABLED=1` 时自动启动管理器，退出时停止；日常无需运行实验目录下的 `run_*.sh`。

在音箱上检查：

```sh
sh /data/native_endpoint/manager.sh verify
sh /data/native_endpoint/manager.sh status
sh /data/native_asr.sh status
tail -n 60 /tmp/xiaomi_native_wake_probe/daily.log
tail -n 40 /tmp/native_followup/events.log
```

`verify` 检查安装包文件哈希；`ENDPOINT_READY owner=… model=… turns=…` 说明判停已就绪；native_asr 还应为 `healthy`。只有客户端 `[IDLE]` 或能正常报时，不能证明本地判停正在工作。日志和路由记录可能含识别文本，不要公开原始文件。

| 状态/需求 | 操作与判断 |
|---|---|
| 日常重启助手 | 空闲时 `sh /data/native_first_client.sh stop`，再 `sh /data/init.sh`；随后检查上述状态 |
| 判停未就绪 | 查看 daily.log 和客户端 `[ENDPOINT]`；新唤醒可能仅有原生收音，不能承诺停顿保护 |
| 临时停用 | 空闲时先停止客户端，再将配置中最后生效的 `NATIVE_ENDPOINT_ENABLED` 改为 `0`，然后运行 `sh /data/init.sh` |
| 重新启用已完整安装的同版包 | 空闲时停止客户端，设开关为 `1`，再运行 init.sh 并检查 READY |
| 完整回滚 | 空闲时执行本次安装输出的 `/data/endpoint-backup-时间/restore.sh`；它恢复原客户端、配置及 SO，并归档旧指令日志后重启，避免旧问题重放 |

不要直接删除 `/tmp/xiaomi_native_wake_probe/routes*`，其中的拒绝记录阻止超时、取消和故障的旧结果进入 LLM。不要用 `killall` 或仅替换 `native_asr.so` 代替停止和恢复流程。当前验收范围见[状态页](../status.md)，自启动机制见[自启动手册](autostart.md)。

<a id="音箱直连-llm默认主线llm_pipelinenative"></a>

<a id="切换-llm默认-deepseek"></a>

<a id="4-配置文件"></a>

## 修改配置

设备配置在 `/data/native_first.env`，模板在仓库 `device/native_first.env.example`。修改前保存实际配置备份，空闲时停止客户端，再编辑和启动。

```sh
vi /data/native_first.env
```

不要反复把模板复制到已有配置上；那会覆盖密钥、实际后端和组件开关。模型切换、TTS 路线、会话历史和高级覆盖项见[配置参考](../reference/configuration.md)。

<a id="1-mac-服务端"></a>

<a id="8-自启动"></a>

## 自启动与可选服务端

整机重启后，在音箱查看启动和客户端日志：

```sh
tail -n 60 /tmp/native_first_autostart.log /tmp/native_first_client.log
```

启动链路、验证与停用见[自启动手册](autostart.md)。选择 server LLM/TTS 的设备还需检查对应服务；启动与健康检查统一放在[服务端参考](../reference/server.md)。音箱独立模式不要求 Mac 服务在线。

<a id="切换系统"></a>

<a id="5-boot-分区切换"></a>

<a id="6-mac-串口-screen"></a>

<a id="7-failsafe"></a>

<a id="9-历史命令"></a>

## 切换系统与串口恢复

切换前确认目标系统已经具备 SSH、备份和助手自启动；当前能力以实际检查为准。先在开发机读取启动选择：

```sh
ssh xiaomi 'fw_env -p 2>&1 | grep -A1 "key: \[boot_part\]"'
```

需要切到 boot1 时执行：

```sh
ssh xiaomi 'fw_env -s boot_part boot1 && sync && reboot'
```

目标为 boot0 时，将上述 `boot1` 换成 `boot0`。重连后用 `mount | grep ' on / '` 确认实际根分区，并分别检查客户端和已安装组件。`fw_env` 是本机定制版本，不需要 `fw_env.config`。

如果无法 SSH，开发机通过串口查看：

```sh
ls /dev/tty.*
screen /dev/tty.usbserial-3120 115200
```

退出 screen：`Ctrl+A → K → Y`。启动时中断进入 U-Boot，先记录环境；确认 boot0 是可用恢复系统后，可切回：

```text
s12# setenv boot_part boot0
s12# saveenv
s12# reset
```

原始 boot0 内核可能提供 failsafe 提示；被替换过的内核不一定保留该入口。先核对[启动与恢复条件](../concepts/boot-and-partitions.md)，再按 [boot0 手册](boot0-ssh.md)处理。需要恢复 SSH、维护镜像或控制 OTA，进入[双系统维护](owner-maintenance.md)。

旧 KWS、`stream_client.sh` 和实验 probe 不是日常启动入口，相关背景统一见[历史索引](../history/README.md)。
