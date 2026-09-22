<a id="文档导航"></a>

<a id="推荐阅读路径"></a>

<a id="按任务查找"></a>

# 文档导读

这个项目有两条阅读线：一条带你把音箱用起来，另一条解释它为什么这样工作。第一次阅读不必遍历所有目录；先沿着自己的问题走，遇到配置、构建或固件细节时再进入参考页。

## 先建立全貌

从[项目首页](../README.md)看一次实际对话，再读[当前状态](status.md)，了解自己的设备和固件能用到哪一步。如果还不熟悉 ASR、TTS、VAD，这些词分别指语音识别、语音合成和语音活动检测；其余术语可以随时查[词表](concepts/glossary.md)。

## 把音箱用起来

按下面的顺序，每完成一层再增加下一层。已经完成的步骤可以跳过。

| 顺序 | 要回答的问题 | 阅读入口 | 完成标志 |
|---|---|---|---|
| 1 | 我的音箱是否适用，需要准备什么？ | [设备与准备](reference/hardware.md) | 确认型号、固件、串口与恢复条件 |
| 2 | 如何取得可靠的维护入口？ | [从零接入](getting-started/bringup.md) | 可以 SSH，具备备份和恢复路径 |
| 3 | 怎样让它回答第一个问题？ | [跑通第一轮对话](getting-started/quickstart.md) | 原生命令和 LLM 问答分别通过 |
| 4 | 怎样继续追问，避免首轮提前截断？ | [逐步完善对话](getting-started/conversation.md) | 分别验收追问与首轮判停 |
| 5 | 断电之后如何自己恢复？ | [配置自启动](runbooks/autostart.md) | 整机重启后无需手动拉起 |
| 6 | 平时怎样检查、调整和恢复？ | [日常操作](runbooks/operations.md) | 能区分客户端、ASR 和判停的状态 |

选用服务端时，再读[可选服务端](reference/server.md)；它不是音箱直连方案的前置步骤。已经安装本地判停包的设备应按[组件整包维护说明](../device/native_endpoint/README.md)操作，不重新照抄首次部署步骤。

## 理解它为什么这样工作

读[一次对话的完整过程](concepts/native-first.md)：从唤醒与收音，走到路由、播放，再到追问和退出。随后读[启动链路与双系统](concepts/boot-and-partitions.md)，理解为什么同一份客户端要适配两套原生系统。

如果想比较不同接入思路，读[路线与取舍](concepts/comparison.md)。如果想知道哪些方法失败过、后来又如何找到新入口，读[探索故事](history/journey.md)，再按[历史索引](history/README.md)进入对应专题。历史结论只描述当时的版本；当前行为以原理页和状态页为准。

## 按问题查找

| 现在遇到的问题 | 入口 |
|---|---|
| 没响应、失败提示漏音、追问异常、音量或 TTS 问题 | [排障手册](runbooks/troubleshooting.md) |
| 切换模型、选择 TTS、调整会话历史 | [配置参考](reference/configuration.md) |
| 查看组件状态、停止或重启助手 | [日常操作](runbooks/operations.md) |
| 打通 boot0 / boot1 SSH | [boot0 手册](runbooks/boot0-ssh.md) / [boot1 手册](runbooks/boot1-ssh.md) |
| 系统切换后 SSH 失联、需要维护固件或控制 OTA | [双系统维护](runbooks/owner-maintenance.md) |
| 构建失败提示 guard / 原生追问 / 首轮判停 / 端侧 TTS | [guard](../device/aivs_guard/README.md) / [native_asr](../device/native_asr/README.md) / [native_endpoint](../device/native_endpoint/README.md) / [ettsc](../device/ettsc/README.md) |
| 修改代码后如何验证 | [测试方法](../TESTING.md) / [真实音箱用例](../tests/manual_native_first_cases.md) |
| 某项能力究竟验收到了哪一步 | [当前状态与证据](status.md) |

## 文档约定

文中的 IP、串口名都是示例；执行前替换成自己的值。**开发机命令**在仓库根目录执行，**音箱命令**在 SSH 登录后执行。各步骤会说明运行位置。

| 项 | 示例值 | 说明 |
|---|---|---|
| 音箱 IP | `192.168.8.152` | 在路由器中确认实际地址 |
| 可选服务端 IP | `192.168.8.150` | 仅选择相应 server 路线时使用 |
| 服务端端口 | `8080` | 启动脚本使用此端口；自定义时同步调整客户端地址 |
| Mac 串口设备 | `/dev/tty.usbserial-3120` | 用 `ls /dev/tty.*` 查实际名称 |

后文使用 `ssh xiaomi`。在开发机 `~/.ssh/config` 添加以下配置，首次连接时核对音箱身份：

```text
Host xiaomi
    HostName 192.168.8.152
    User root
    HostKeyAlgorithms +ssh-rsa
    PubkeyAcceptedKeyTypes +ssh-rsa
```

不使用别名时，等价命令是：

```sh
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152
```

SSH 与镜像写入手册保留完整命令，便于在救援环境查阅。型号、分区和校验值必须按实际设备核对。

## 文档怎样继续维护

| 内容 | 唯一主要维护位置 |
|---|---|
| 项目定位和阅读入口 | 根目录 `README.md` |
| 当前能力、验收日期、剩余边界 | `docs/status.md` |
| 第一次安装与验证顺序 | `docs/getting-started/` |
| 机制与设计理由 | `docs/concepts/` |
| 日常动作、故障诊断与恢复 | `docs/runbooks/` |
| 硬件、配置和服务端接口 | `docs/reference/` |
| 组件构建、ABI、安装基线、回滚限制 | 对应 `device/*/README.md` |
| 某次实验的事实、反例和证据 | `docs/history/`；原始快照保留在 `docs/archive/` |

新增能力时，先修改它所属的说明，再更新状态页和必要的入口链接。不要把同一段验收日志追加到首页、教程、架构和运维各处。历史记录保留当时的结论，后续变化由状态页指向新的证据；测试数量必须注明对应版本，不能跨版本累加。
