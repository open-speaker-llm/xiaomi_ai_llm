# 探索历程：从接串口到 native-first

文档类型：历史叙事
适用范围：想知道当前方案是怎么一步步摸索出来的，以及哪些方向已经试过、为什么放弃
当前结论：主线经历了"获取 root → 旁路链路 → 自定义唤醒 → 原生唤醒 → native-first"五次换挡，每次换挡都是被实测结果推着走的

> 本文是按时间线整理的叙事版。每个阶段的完整命令和原始记录在 `docs/archive/2026-06-07-pre-doc-reorg/` 的归档文档里，文中随时标注出处。

## 阶段 0：目标与设备（2026-04 末）

目标很朴素：让一台 2019 年的小米 AI 音箱（MDZ-25-DA / S12A，Amlogic A113X，128MB NAND）能和大模型对话。

```text
语音输入 → 音箱采集 → 客户端程序 → LLM 服务端 → TTS 合成 → 音箱播放
```

设备没有任何官方开放接口，第一步只能拆机。主板上有现成的 JST 串口插座（免焊），用杜邦线接上 USB-TTL 模块的 TXD/RXD/GND 后，就能看到 U-Boot 和系统启动日志——但 login 要密码。

## 阶段 1：获取 root（最曲折的部分）

### 1.1 密码绕过：七连败

| 尝试 | 结果 |
|---|---|
| `MD5(SN + 固定通配符)` 算密码（旧版固件规则） | ❌ 1.54.8 固件改用随机 wildcard |
| 写空 shadow / 写新 passwd | ❌ 被 mi_console 的 DSA 签名验证拦截 |
| `init=/bin/sh`（initargs / bootargs 两种写法） | ❌ U-Boot 的 storeargs 每次重建 bootargs，覆盖掉 |
| `single` 单用户模式 / switch_root 到 /bin/sh | ❌ 被忽略 |

串口日志证实了 1.54.8 的登录机制：`magic = SN + 随机wildcard`，DSA 签名验证，没有小米私钥就无解。**结论：正面绕过密码此路不通，必须改 rootfs。**

### 1.2 rdinit shell + WiFi：每一步都是坑

要改 rootfs 先得有个能干活的 shell 和网络。从 U-Boot 进 rdinit shell 后，联网的每一步都踩过坑（完整表格见归档 `PROJECT_LOG.md`）：

- WiFi 驱动必须用 system0 的模块，system1 的有内核符号冲突；
- 驱动加载成功但不关联——缺 `/dev/urandom`；
- 连上又立刻被踢——`wpa_supplicant.conf` 必须用多行 heredoc 格式，单行分号格式不识别；
- dropbear 起来了但 SSH 进不去——依次补上 `-o HostKeyAlgorithms=+ssh-rsa`（Mac 新版 OpenSSH 默认禁用 ssh-rsa）、`/bin/sh` 链接、`devpts` + `ptmx` 设备节点。

文件传输同样试了一圈：nc 被 Mac 防火墙拦、Python xmodem 握手超时，最后可靠的组合是 U-Boot `loadx` + screen 的 `exec !! lsx`（串口 xmodem），以及联网后的 curl HTTP。

### 1.3 squashfs 注入：v1 到 v6

思路来自 duhow/xiaoai-patch：备份 system0 → `unsquashfs` 解包 → 注入启动脚本 → `mksquashfs` 打包 → 写回分区。注入物是一个 `S45sshen` init 脚本：在 dropbear（S50）之前运行，写 `/tmp/ssh_en=1` 让 dropbear 跳过 channel=release 的阻拦。

六个版本的迭代记录：

| 版本 | 改动 | 结果 |
|---|---|---|
| v1 | 注入 S45sshen | ✅ root 免密登录，SSH 通，小爱功能不受影响 |
| v2 | sshen 里顺手调用 `/data/start_ssh.sh` | ❌ preinit 连锁崩溃（`/dev/console` 不存在等） |
| v4 | 对比 `unsquashfs -ll` 补回缺失空目录和设备节点（pseudo file） | ✅ 修复 v2 类问题 |
| v5 | sshen 加 bind-mount authorized_keys | ❌ squashfs 损坏（源目录被 append 残留污染） |
| v6 | 从干净目录重做 v5 + `-noappend` | ✅ 最终形态 |

v6 的核心机制沿用至今：`S45sshen` 启动时把可写分区里的 `/data/dropbear/authorized_keys` bind-mount 到只读 rootfs 的 `/etc/dropbear/authorized_keys`——换公钥不用重刷系统。这就是现在 [../runbooks/boot0-ssh.md](../runbooks/boot0-ssh.md) 的方案来源。

### 1.4 学费：failsafe 永久丢失

修引导问题时执行了 `dd if=/dev/mtdblock3 of=/dev/mtdblock2`（boot1 kernel → boot0），导致 boot0 原始 kernel 被覆盖。而 failsafe 入口只在 boot0 的原始 kernel 里——**failsafe 能力就此丢失**，尝试从 1.52.1 固件提取 kernel 恢复也因镜像格式（genFmt 不匹配）失败。

教训直接写进了后来所有 runbook：写任何分区前先备份、确认目标分区、保留至少一个可启动系统。

## 阶段 2：第一条端到端链路（2026-05-01）

root 到手后，先用最笨的办法验证可行性——failsafe 环境 + 手动命令：

```text
音箱 arecord (32kHz) → curl POST → Mac：Whisper ASR → MiniMax LLM → MiniMax TTS → WAV 返回 → 音箱 aplay
```

音频链路的关键修复：`/dev/snd/` 节点要手动 `mknod`（主设备号 116）；`Hard Mute` 要关、`Ch1/Ch2` 要 unmute；录音用 `hw:0,2`（PDM，32kHz），播放用 `default`（48kHz 自动重采样）。

同期服务端完成了真流式改造：LLM 输出按中文句子边界切分（`sentence_splitter.py`），逐句 TTS，HTTP chunked 先发 WAV 头再流式输出 PCM，音箱端 FIFO + curl + aplay 渐进播放（`stream_client.sh`）——首句出来就开播，不等全文。

## 阶段 3：自定义唤醒词路线（KWS，后放弃）

有了链路，下一个问题是"怎么免提触发"。第一个方案是完全旁路小爱：用 open-xiaoai 的 KWS 模型在音箱上检测自定义唤醒词"你好小智"，配 dsnoop 共享录音、本地 VAD 断句、LED 状态反馈（`wake_monitor.sh` + `stream_client.sh`，脚本仍保留在 `device/`）。

这条路线能跑，但有结构性缺陷：

- 自训 KWS 的唤醒率/误唤醒率远不如小米原生"小爱同学"；
- 完全旁路意味着放弃了小米原生的家电控制、天气等成熟能力，等于把小爱降级成普通蓝牙音箱；
- 录音链路要和原生服务抢设备，稳定性差。

## 阶段 4：转向原生，进化出 native-first

先是中间形态 `native_client.sh`：用 bind mount 把 `/bin/wakeup.sh` 换成自己的 hook，借小米原生唤醒（"小爱同学"）触发，但后续仍走本地录音 + Whisper。唤醒质量问题解决了，可 ASR 和家电控制还是不如原生。

于是走到最终形态 `native_first_client.sh`：**唤醒、ASR、NLP、家电控制全部留给小米，只在原生明确处理不了时接管**。关键发现：

- 小米 NLP 的结果是结构化的（`domain/action/query/speak`），可以通过 `ubus call mibrain nlp_result_get` 拿到——路由判断应该基于 `domain`，而不是猜文本关键词；
- `query` 字段是陷阱：`domain=weather` 时 `query` 可能是 `token` 这种内部值，真正要播报的是 `speak`（这条教训写进了 [../concepts/native-first.md](../concepts/native-first.md)）；
- 拦截"还在学习中"失败播报的办法是在 `think` 阶段 freeze `mediaplayer`，原生成功再 resume 并 replay `speak`；
- `/data/mibrain/mibrain_asr_nlp.rcd` 不比 `nlp_result_get` 更早，且中文断行，不能作为路由来源（验证后排除）。

## 阶段 5：boot1 兼容（2026-06 初）

设备异常时会自动切到另一套系统 boot1/system1（2023 ROM），SSH 失联、客户端行为全变。与其每次接串口救援，不如把 boot1 也打通。这一仗的实测结论都在 [../runbooks/boot1-ssh.md](../runbooks/boot1-ssh.md)：

- system1 分区有坏块：`dd` 和 `nandwrite -p` 写入后读回 hash 都不匹配，**只有 `mtd -f write - system1` 是对的**；
- 2023 ROM 的语音链路换了架构：`mibrain nlp_result_get` 不再刷新，结果要从 `/tmp/mico_aivs_lab/instruction.log` 解析；唤醒 hook 事件只有 `think/ready` 没有 `WuW`；
- 试图把 boot0 的服务文件复制过去"填平"差异会弄崩原生 `recorder`——正确做法是在客户端脚本里保留两套结果源适配器，按 rootfs 自动选择。

之后补上断电自启动（`/etc/rc.local` 注入一行 `/data/init.sh` 入口，方案参考 open-xiaoai），boot0/boot1 都验证了上电自动恢复。期间还排除了两条歧路：`/data/ai-crontab/crontab.dat` 是二进制格式不可直接写；`/etc/crontabs/root` 在只读 rootfs 上。详见 [../runbooks/autostart.md](../runbooks/autostart.md)。

## 阶段 6：连续追问（进行中，未到最终形态）

理想体验是 LLM 回答后不用再喊"小爱同学"直接追问。试过两类方案：

- **本地录音 + ASR**：能跑但不稳——多麦克风原始录音弱声/噪声/录到 LLM 尾音，boot1 上麦克风被 `mipns-xiaomi` 占用；
- **原生 reopen**：尝试了 `pnshelper event_notify`（event=4/6）、`wakeup.sh multirounds`、`oneshot_set open=true` 等八种组合，`instruction.log` 始终只有首轮 dialog，拿不到追问文本。

当前策略：boot0 保留本地录音追问做实验，boot1 默认关闭追问保主流程。下一个值得投入的方向是"获取小米处理后的干净音频"——曾观察到 `/tmp/mipns/usock/speech.usock` 里有 16kHz mono PCM，可能已经过小米前端处理。完整记录见 [followup-exploration.md](followup-exploration.md)。

## 回头看：几条贯穿始终的经验

1. **优先复用，而不是替换**。从"旁路一切"到"native-first"，每一次回退到原生能力（唤醒、ASR、家电），体验和稳定性都明显变好。
2. **结构化信号优于文本猜测**。路由看 `domain`，不看关键词；判断写入成功看读回 hash，不看命令退出码。
3. **给自己留退路**。串口常驻、写前备份、双系统保一个可启动、`/data` 放可变逻辑 rootfs 只放入口——这些都是用 failsafe 丢失换来的纪律。
4. **失败记录和成功方案一样值钱**。本文里的每张失败表格，都避免了后来者（包括自己）重走死路。
