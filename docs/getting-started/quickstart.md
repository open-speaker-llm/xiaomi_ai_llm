# 快速上手

文档类型：SSH 已可用后的快速联调
适用范围：Mac 服务端 + 已打通 SSH + 已能向 `/data` 上传文件的小米音箱
当前结论：如果你还没有 SSH，先读 [bringup.md](bringup.md)

> 示例 IP、`ssh xiaomi` 别名等约定见 [../README.md](../README.md#文档约定)。

## 0. 前提

- Mac 和音箱在同一网络。
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
SERVER=http://192.168.8.150:8080
BACKEND=deepseek
NATIVE_RESULT_SOURCE=auto
```

## 2. 启动 Mac 服务端

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
