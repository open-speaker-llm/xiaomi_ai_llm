# 调试命令索引

这个文件保留为老入口，当前命令已按用途拆到：

- [docs/QUICKSTART.md](docs/QUICKSTART.md)：第一次启动和最小验证。
- [docs/OPERATIONS.md](docs/OPERATIONS.md)：日常启动、停止、看日志、切 boot、串口、failsafe。
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)：问题定位。

重构前完整命令手册已归档：

```text
docs/archive/2026-06-07-pre-doc-reorg/DEV_COMMANDS.md
```

## 1. 最常用命令

Mac 服务端：

```sh
cd /Users/mac-mini-wx/research/xiaomi_ai/xiaomi_ai_llm
./start_server.sh
```

音箱登录：

```sh
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152
```

音箱启动主客户端：

```sh
SERVER=http://192.168.8.150:8080 BACKEND=deepseek sh /data/native_first_client.sh > /tmp/native_first_client.log 2>&1 &
```

看音箱日志：

```sh
tail -f /tmp/native_first_client.log /tmp/native_first_events.log
```

停止音箱客户端：

```sh
sh /data/native_first_client.sh stop
```

切 boot：

```sh
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152 'fw_env -p 2>&1 | grep -A1 \"key: \\[boot_part\\]\"'
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152 'fw_env -s boot_part boot0 && reboot'
```

或：

```sh
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152 'fw_env -s boot_part boot1 && reboot'
```

## 2. 当前主线判断

启动后应看到：

```text
[HOOK] mounted /bin/wakeup.sh -> /tmp/wakeup.sh.native_first_client
[IDLE] 等待原生唤醒词：小爱同学
```

三条基础用例：

```text
小爱同学，开灯
小爱同学，今天天气怎么样
小爱同学，呼叫 DeepSeek
```

期望：

- 开灯和天气走原生。
- 呼叫 DeepSeek 转 LLM。
