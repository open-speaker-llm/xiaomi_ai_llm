# 文档导航

本目录按"你想做什么"分四层组织：

```text
docs/
  getting-started/   上手教程：按顺序跟着做，从零到第一次 LLM 响应
  concepts/          原理：native-first 架构、启动链路与分区、术语表
  runbooks/          操作手册：日常运维、SSH 注入、自启动、排障（按需查阅）
  history/           探索历程：路线为什么是现在这样、哪些方向试过且失败
  archive/           重构前文档原貌快照（只用于查证，不要从这里开始）
```

## 推荐阅读路径

**路径 A：我想动手（新手）**

1. [getting-started/bringup.md](getting-started/bringup.md) —— 完整路线图：串口 → SSH → 部署 → 验证 → 自启动
2. 过程中按指引进入对应 runbook：[boot0-ssh](runbooks/boot0-ssh.md) → [boot1-ssh](runbooks/boot1-ssh.md) → [autostart](runbooks/autostart.md)
3. 跑通后日常使用 [getting-started/quickstart.md](getting-started/quickstart.md) 和 [runbooks/operations.md](runbooks/operations.md)
4. 遇到术语卡住，查 [concepts/glossary.md](concepts/glossary.md)

**路径 B：我有嵌入式/语音经验，想直奔重点**

1. [concepts/native-first.md](concepts/native-first.md) —— 路由标准、播放控制、boot0/boot1 兼容，10 分钟看完核心设计
2. [concepts/boot-and-partitions.md](concepts/boot-and-partitions.md) —— 双系统分区布局和它带来的所有麻烦
3. `device/native_first_client.sh` —— 主客户端就这一个文件，状态机全在里面
4. [history/journey.md](history/journey.md) 的失败路线表 —— 避免重走死路

**路径 C：我只想看故事**

- [history/journey.md](history/journey.md) —— 从拆机接串口到 native-first 的完整探索历程：密码绕过的七次失败、failsafe 丢失事故、squashfs 注入 v1–v6、KWS 弯路、追问探索

## 按任务查找

| 你要做什么 | 读这个 |
|---|---|
| 从零打通一台音箱 | [getting-started/bringup.md](getting-started/bringup.md) |
| SSH 已可用，快速联调 | [getting-started/quickstart.md](getting-started/quickstart.md) |
| 日常启动/停止/看日志/切 boot | [runbooks/operations.md](runbooks/operations.md) |
| boot0 打通 SSH（串口/failsafe） | [runbooks/boot0-ssh.md](runbooks/boot0-ssh.md) |
| boot1 打通 SSH（镜像注入） | [runbooks/boot1-ssh.md](runbooks/boot1-ssh.md) |
| 断电重启后自动运行 | [runbooks/autostart.md](runbooks/autostart.md) |
| 没响应/串台/音量异常/追问失败 | [runbooks/troubleshooting.md](runbooks/troubleshooting.md) |
| 理解 native-first 怎么路由 | [concepts/native-first.md](concepts/native-first.md) |
| 理解 boot0/boot1/system0/system1 | [concepts/boot-and-partitions.md](concepts/boot-and-partitions.md) |
| 和 open-xiaoai/mi-gpt/xiaogpt 有什么不同 | [concepts/comparison.md](concepts/comparison.md) |
| 查术语：KWS、VAD、ALSA、rootfs… | [concepts/glossary.md](concepts/glossary.md) |
| 测试怎么跑 | [../TESTING.md](../TESTING.md) / [../tests/manual_native_first_cases.md](../tests/manual_native_first_cases.md) |
| 某条路线是否已经试过 | [history/README.md](history/README.md) |

## 文档约定

所有文档使用统一的示例环境，**照抄前先替换成你自己的值**：

| 项 | 示例值 | 说明 |
|---|---|---|
| Mac（服务端）IP | `192.168.8.150` | 音箱配置里的 `SERVER` 指向它 |
| 音箱 IP | `192.168.8.152` | 路由器后台可查 |
| 服务端端口 | `8080` | `config.yaml` 可改 |
| 串口设备 | `/dev/tty.usbserial-3120` | `ls /dev/tty.*` 查看实际名称 |
| 仓库目录 | 命令默认在仓库根目录执行 | 文中不再写绝对路径 |

音箱的 dropbear 版本较老，新版 OpenSSH 需要显式允许 `ssh-rsa`。建议在 Mac 的 `~/.ssh/config` 加一段，后续所有文档中的 `ssh xiaomi` / `scp -O ... xiaomi:...` 都依赖它：

```text
Host xiaomi
    HostName 192.168.8.152
    User root
    HostKeyAlgorithms +ssh-rsa
    PubkeyAcceptedKeyTypes +ssh-rsa
```

不想配别名时，等价的完整命令是：

```sh
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152
```

需要直接通过 SSH 切到 `boot1` 时：

```sh
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152 'fw_env -s boot_part boot1 && sync && reboot'
```

高风险操作手册（boot0-ssh / boot1-ssh）中保留完整命令形式，保证在没有任何本地配置的环境里也能照着做。
