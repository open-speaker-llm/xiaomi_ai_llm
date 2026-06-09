# 从零打通小爱音箱到 LLM

文档类型：从零接入路线图  
适用范围：读者手里有一台小米 AI 音箱，想让它接入自己的 Mac LLM 服务端  
当前结论：先打通 boot0 SSH，再补齐 boot1 SSH，之后把客户端脚本放到 `/data`，最后配置自启动

## 1. 最终要实现什么

目标体验：

```text
小爱同学，开灯
  -> 仍然走小米原生，灯能打开

小爱同学，今天天气怎么样
  -> 仍然走小米原生，播报天气

小爱同学，呼叫 DeepSeek
  -> 小米原生不会处理
  -> native-first 拦截失败播报
  -> 把“小米识别出的文字”转给 Mac LLM
  -> 音箱播放 LLM 回答
```

这不是把小爱替换掉，而是让小爱先处理它擅长的事，处理不了再转 LLM。

## 2. 为什么不能直接看 QUICKSTART

`QUICKSTART` 假设音箱已经能 SSH，而且 `/data` 里已有脚本。

一台新音箱通常还没有这些条件：

- 没有 SSH，不能用 `scp` 上传脚本。
- 如果只靠串口传文件，速度慢，也不适合长期调试。
- 音箱有两套系统，异常时可能从 boot0 切到 boot1。
- 只打通 boot0 SSH 时，一旦启动到 boot1，又会失去远程控制。
- 没有自启动时，每次断电重启都要 SSH 手动启动客户端。

所以完整路线应该是：

```text
串口可用
  -> boot0/failsafe 打通 SSH
  -> 用 SSH 上传脚本到 /data
  -> 启动 Mac 服务端和音箱客户端
  -> 验证 native-first 主流程
  -> 打通 boot1 SSH
  -> 验证 boot0/boot1 都能跑
  -> 配置 /data/init.sh 自启动
```

## 3. 准备 Mac 环境

安装 Python 依赖并准备配置：

```sh
cd /Users/mac-mini-wx/research/xiaomi_ai/xiaomi_ai_llm
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

在 `.env` 中填入至少一个 LLM key，例如：

```text
DEEPSEEK_API_KEY=...
```

启动服务：

```sh
./start_server.sh
```

健康检查：

```sh
curl http://127.0.0.1:8080/
```

## 4. 先通过串口进入音箱

Mac 查看串口：

```sh
ls /dev/tty.*
```

连接：

```sh
screen /dev/tty.usbserial-3120 115200
```

退出 screen：

```text
Ctrl+A -> K -> Y
```

如果需要进入 failsafe，优先切回 boot0。进入 U-Boot 后：

```text
s12# setenv boot_part boot0
s12# saveenv
s12# reset
```

看到：

```text
Press the [f] key and hit [enter]
```

立即按：

```text
f -> Enter
```

## 5. 打通 boot0 SSH

boot0 SSH 是后续高效开发的第一道门。正式操作手册见：

```text
docs/BOOT0_SSH_RUNBOOK.md
```

打通后，Mac 应该能登录：

```sh
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152
```

如果 host key 提示冲突：

```sh
ssh-keygen -R 192.168.8.152
```

## 6. 上传音箱端文件

SSH 可用后，上传文件就不再依赖串口。

从 Mac 执行：

```sh
cd /Users/mac-mini-wx/research/xiaomi_ai/xiaomi_ai_llm
scp -O -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa \
  device/native_first_client.sh device/native_first.env.example device/vad_record.sh device/data_init_native_first.sh \
  root@192.168.8.152:/data/
```

登录音箱后执行：

```sh
cp /data/native_first.env.example /data/native_first.env
chmod +x /data/native_first_client.sh /data/vad_record.sh /data/data_init_native_first.sh
```

编辑 `/data/native_first.env`，至少确认：

```sh
SERVER=http://192.168.8.150:8080
BACKEND=deepseek
NATIVE_RESULT_SOURCE=auto
```

## 7. 第一次启动联调

Mac 端保持服务运行：

```sh
./start_server.sh
```

音箱端启动：

```sh
SERVER=http://192.168.8.150:8080 BACKEND=deepseek sh /data/native_first_client.sh > /tmp/native_first_client.log 2>&1 &
```

看日志：

```sh
tail -f /tmp/native_first_client.log /tmp/native_first_events.log
```

应看到：

```text
[HOOK] mounted /bin/wakeup.sh -> /tmp/wakeup.sh.native_first_client
[IDLE] 等待原生唤醒词：小爱同学
```

## 8. 验证三条主流程

一条一条测：

```text
小爱同学，开灯
小爱同学，今天天气怎么样
小爱同学，呼叫 DeepSeek
```

判断：

- 开灯：原生成功，不应进 LLM。
- 天气：原生播报，不应进 LLM。
- 呼叫 DeepSeek：应进入 LLM。

完整用例见 [../tests/manual_native_first_cases.md](../tests/manual_native_first_cases.md)。

## 9. 为什么还要打通 boot1

小米音箱有两套系统：

```text
boot0/system0
boot1/system1
```

设备异常或系统策略可能导致它启动到另一套系统。如果只在 boot0 有 SSH：

- 启动到 boot1 后，你可能 SSH 不进去。
- 每次都要接串口切回 boot0，调试非常痛苦。
- native-first 在 boot0/boot1 上面对的小米原生结果源不同，必须分别验证。

因此长期方案是：

- boot0 能 SSH。
- boot1 也能 SSH。
- `/data` 共享，同一份客户端脚本两边可见。
- `native_first_client.sh` 自动适配 boot0/boot1 的结果源。

boot1 SSH 操作见 [BOOT1_SSH_RUNBOOK.md](BOOT1_SSH_RUNBOOK.md)。

## 10. SSH 下切换 boot

这台音箱使用 Amlogic 定制版 `fw_env`，通过 `/dev/nand_env` 直接读写 U-Boot 环境变量，不需要 `fw_env.config`。语法为 `fw_env -s <name> <value>`。

查看当前 boot：

```sh
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152 'fw_env -p 2>&1 | grep -A1 \"key: \\[boot_part\\]\"'
```

切到 boot0 并重启：

```sh
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152 'fw_env -s boot_part boot0 && reboot'
```

切到 boot1 并重启：

```sh
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152 'fw_env -s boot_part boot1 && reboot'
```

如果切换后 SSH 失败，需要回到串口 U-Boot 手动切回可用系统。

## 11. 配置断电自启动

否则每次重启后都要 SSH 手动启动：

```sh
SERVER=http://192.168.8.150:8080 BACKEND=deepseek sh /data/native_first_client.sh ...
```

当前长期方案：

- 在 system0/system1 的 `/etc/rc.local` 注入通用入口。
- 真正启动逻辑放在 `/data/init.sh`。
- 后续修改只改 `/data/init.sh`。

部署 `/data/init.sh`：

```sh
cp /data/data_init_native_first.sh /data/init.sh
chmod +x /data/init.sh
sh /data/init.sh
```

详细说明见 [AUTOSTART_INIT_HOOK.md](AUTOSTART_INIT_HOOK.md)。

## 12. 下一步读什么

- 想理解底层启动：读 [BOOT_FLOW.md](BOOT_FLOW.md)。
- 想日常操作：读 [OPERATIONS.md](OPERATIONS.md)。
- 出问题：读 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)。
