# 日常运维命令

文档类型：当前命令手册
适用范围：日常联调、启动停止、看日志、切 boot、串口/failsafe
当前结论：常规联调用 `native_first_client.sh`，旧 KWS/stream 路线只作为历史参考

> 本文使用 `ssh xiaomi` 别名和示例 IP，约定见 [../README.md](../README.md#文档约定)。

## 1. Mac 服务端

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

**默认就是 native**——音箱直连 LLM、Mac 只出 TTS。`/data/native_first.env` 关键项：

```sh
LLM_PIPELINE=native                     # 默认；音箱直连 LLM
DEEPSEEK_API_KEY=sk-...                 # native 模式必填，否则无法直连 LLM
TTS_SERVER=http://192.168.8.150:8080   # TTS 微服务地址，可指向任意常驻设备
LLM_THINKING=disabled                   # deepseek-v4-flash 关思考，首句 ~2s
```

启动后日志里会看到 `[LLM-NATIVE] direct → ...`。TTS 微服务不可用时自动降级原生 mibrain TTS（原生音色）。原理见 [../concepts/native-first.md](../concepts/native-first.md)。

回退到经 Mac 调 LLM：把 `LLM_PIPELINE` 改成 `server` 重启即可。

## 4. 配置文件

音箱上的运行配置：

```sh
cp /data/native_first.env.example /data/native_first.env   # 首次创建
vi /data/native_first.env
```

仓库中的模板：`device/native_first.env.example`（各参数含义见模板内注释）。

## 5. boot 分区切换

查看当前启动分区：

```sh
ssh xiaomi 'fw_env -p 2>&1 | grep -A1 "key: \[boot_part\]"'
```

切换并重启：

```sh
ssh xiaomi 'fw_env -s boot_part boot0 && reboot'
ssh xiaomi 'fw_env -s boot_part boot1 && reboot'
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
