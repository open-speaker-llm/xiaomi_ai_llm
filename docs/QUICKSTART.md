# 快速上手

文档类型：SSH 已可用后的快速联调  
适用范围：Mac 服务端 + 已打通 SSH + 已能向 `/data` 上传文件的小米音箱  
当前结论：如果你还没有 SSH，先读 [BRINGUP_GUIDE.md](BRINGUP_GUIDE.md)

## 0. 前提

继续本页前，需要已经完成：

- Mac 和音箱在同一网络。
- 音箱可以 SSH 登录。
- 音箱 `/data` 可写。
- 已知道 Mac IP，例如 `192.168.8.150`。

如果还没有 SSH，先走完整路线：[BRINGUP_GUIDE.md](BRINGUP_GUIDE.md)。

## 1. 确认当前网络

当前常用地址：

```text
Mac IP：192.168.8.150
音箱 IP：192.168.8.152
服务端端口：8080
```

如果 IP 变化，先改音箱 `/data/native_first.env` 里的 `SERVER`。

## 2. 上传音箱端文件

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

编辑配置：

```sh
vi /data/native_first.env
```

至少确认：

```sh
SERVER=http://192.168.8.150:8080
BACKEND=deepseek
```

## 3. 启动 Mac 服务端

```sh
cd /Users/mac-mini-wx/research/xiaomi_ai/xiaomi_ai_llm
./start_server.sh
```

健康检查：

```sh
curl http://127.0.0.1:8080/
```

后台日志：

```sh
tail -f /tmp/server.log | grep -E '📥|🎤|🌐|🔊|🤖|✅|⚠️'
```

## 4. 登录音箱

```sh
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152
```

## 5. 启动音箱客户端

前台调试：

```sh
SERVER=http://192.168.8.150:8080 BACKEND=deepseek sh /data/native_first_client.sh
```

后台运行：

```sh
SERVER=http://192.168.8.150:8080 BACKEND=deepseek sh /data/native_first_client.sh > /tmp/native_first_client.log 2>&1 &
```

## 6. 确认启动成功

看日志：

```sh
tail -f /tmp/native_first_client.log /tmp/native_first_events.log
```

应看到类似：

```text
[HOOK] mounted /bin/wakeup.sh -> /tmp/wakeup.sh.native_first_client
[HOOK] watchdog pid=...
[IDLE] 等待原生唤醒词：小爱同学
```

## 7. 第一组验证

按顺序一条一条测，每条等播报或日志稳定后再测下一条：

```text
小爱同学，开灯
小爱同学，今天天气怎么样
小爱同学，呼叫 DeepSeek
```

期望：

- 开灯：走原生，不进 LLM。
- 天气：走原生播报。
- 呼叫 DeepSeek：原生不支持，转 LLM。

更完整人工用例见 [../tests/manual_native_first_cases.md](../tests/manual_native_first_cases.md)。
