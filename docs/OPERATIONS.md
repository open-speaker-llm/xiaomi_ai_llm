# 日常运维命令

文档类型：当前命令手册  
适用范围：日常联调、启动停止、看日志、切 boot、串口/failsafe  
当前结论：常规联调用 `native_first_client.sh`，旧 KWS/stream 路线只作为历史参考

## 1. Mac 服务端

启动：

```sh
cd /Users/mac-mini-wx/research/xiaomi_ai/xiaomi_ai_llm
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

查看状态：

```sh
sh /data/native_first_client.sh status
```

看日志：

```sh
tail -f /tmp/native_first_client.log /tmp/native_first_events.log
```

停止：

```sh
sh /data/native_first_client.sh stop
```

确认进程：

```sh
ps | grep -E 'native_first_client|mipns-xiaomi|mediaplayer|curl|aplay|arecord' | grep -v grep
```

## 4. 配置文件

推荐配置：

```text
/data/native_first.env
```

首次创建：

```sh
cp /data/native_first.env.example /data/native_first.env
vi /data/native_first.env
```

当前模板在仓库：

```text
device/native_first.env.example
```

## 5. boot 分区切换

查看当前启动分区：

```sh
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152 'fw_env -p 2>&1 | grep -A1 \"key: \\[boot_part\\]\"'
```

切到 boot0：

```sh
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152 'fw_env -s boot_part boot0 && reboot'
```

切到 boot1：

```sh
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152 'fw_env -s boot_part boot1 && reboot'
```

说明：

- 这是在已能 SSH 登录系统后执行的切换方式。
- 这台音箱使用 Amlogic 定制版 `fw_env`，通过 `/dev/nand_env` 直接读写 U-Boot 环境变量，不需要 `fw_env.config`。语法为 `fw_env -s <name> <value>`。
- 如果系统无法启动或无法 SSH，再走串口进入 U-Boot/failsafe。
- boot0/boot1 与 system0/system1 的关系见 [BOOT_FLOW.md](BOOT_FLOW.md)。

## 6. Mac 串口 screen

查看串口设备：

```sh
ls /dev/tty.*
```

连接串口：

```sh
screen /dev/tty.usbserial-3120 115200
```

退出 screen：

```text
Ctrl+A -> K -> Y
```

## 7. failsafe

failsafe 只在 boot0 上。进入 U-Boot 后：

```text
s12# setenv boot_part boot0
s12# saveenv
s12# reset
```

重启后看到：

```text
Press the [f] key and hit [enter]
```

立即按：

```text
f -> Enter
```

## 8. 自启动

当前长期方案见 [AUTOSTART_INIT_HOOK.md](AUTOSTART_INIT_HOOK.md)。

验证自启动日志：

```sh
tail -f /tmp/native_first_autostart.log /tmp/native_first_client.log /tmp/native_first_events.log
```

## 9. 历史命令

重构前完整命令手册已归档：

```text
docs/archive/2026-06-07-pre-doc-reorg/DEV_COMMANDS.md
```

旧 KWS、`stream_client.sh`、`native_client.sh`、各类 probe 脚本只在做历史对照或专项探索时使用。
