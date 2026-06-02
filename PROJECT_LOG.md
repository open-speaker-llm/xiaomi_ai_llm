# 小米AI音箱 (MDZ-25-DA) LLM 语音对话助手改造项目

## 最终目标

```
语音输入 → 音箱采集 → 客户端程序 → MiniMax LLM服务器 → TTS合成 → 音箱播放
```

让小米AI音箱变成能通过语音与 MiniMax 大模型对话的智能音箱。

---

## 设备信息

| 项目 | 信息 |
|------|------|
| 型号 | MDZ-25-DA |
| 内部代号 | S12A |
| CPU | Amlogic A113X (Cortex-A53 四核) |
| 存储 | 128MB NAND Flash |
| WiFi/BT | Marvell 88W8977 |
| 音频ADC | ES7243 |
| 当前固件 | 1.54.8 (channel: release) |
| TTL接口 | TPM24(TX), TPM25(RX), TPM26(GND) |

---

## 架构设计

```
┌──────────────┐   WiFi    ┌────────────────┐    API    ┌─────────────┐
│  小米AI音箱   │ ◄──────► │  后台服务器      │ ◄──────► │   MiniMax    │
│  (客户端)    │           │  (FastAPI)      │          │   LLM + TTS │
└──────────────┘           └────────────────┘          └─────────────┘
```

### 服务器端代码

`xiaomi_ai_llm/server/` 已完成：
- `main.py` - FastAPI 主服务
- `llm/minimax_client.py` - MiniMax LLM对接
- `tts/minimax_tts.py` - MiniMax TTS合成
- `asr/whisper_client.py` - Whisper语音识别
- `audio/processor.py` - 音频处理

### 客户端代码

`xiaomi_ai_llm/device/audio_capture.py` 已完成，待部署到音箱。

---

##  已尝试的路线汇总

### 功能路线

| # | 路线 | 实际结果 |
|---|------|---------|
| 1 | 项目代码框架 xiaomi_ai_llm/ | ✅ 完成 |
| 2 | TTL 焊接，串口连接进入 U-Boot | ✅ 成功 |
| 3 | 获取设备信息、分区表 | ✅ 成功 |
| 4 | 设置网络参数 `setenv ipaddr/serverip` | ✅ 成功 |
| 5 | 备份分区（通过TFTP） | ❌ U-Boot无tftp命令，NAND读取失败 |
| 6 | 降级旧版本 1.52.1 固件 | ❌ 串口传输33MB超时失败 |
| 7 | USB刷机模式，`update`命令 | ⚠️ 进InUsbBurn了，但无USB接口焊盘 |
| 8 | 切换启动分区 boot0/boot1 | ✅ 成功，boot0有failsafe，boot1没有 |

### 绕过密码登录路线

| # | 方法 | 原理 | 结果 |
|---|------|------|------|
| 1 | MD5(SN+通配符) 计算密码 | SN 18090/884527651 + 固定通配符 | ❌ 新版固件使用随机通配符 |
| 2 | 写空 shadow `root::...` | 让密码为空 | ❌ mi_console DSA签名验证 |
| 3 | 写passwd文件 `root:123456` | 设置新密码 | ❌ DSA验证拦截 |
| 4 | `setenv initargs init=/bin/sh` | 系统启动进root shell | ❌ storeargs覆盖了bootargs |
| 5 | `setenv bootargs init=/bin/sh` | 同上 | ❌ 每次被storeargs覆盖 |
| 6 | `single` 内核参数 | 进单用户模式 | ❌ 被忽略 |
| 7 | switch_root到/bin/sh | 获取root shell | ❌ 被忽略 |

### 在failsafe模式获取网络路线

| # | 方法 | 结果 |
|---|------|------|
| 1 | 手动 insmod wifi驱动模块 | ❌ 内核重复导出符号失败 |
| 2 | `/etc/rc.d/S61wireless start` + ubusd | ❌ 无线脚本死循环 |
| 3 | wpa_supplicant -B + udhcpc | ❌ 无法获取IP |
| 4 | 直接启动 procd/ubus | ❌ failsafe环境不完整 |
| 5 | mount_root 挂载完整系统 | ❌ squashfs真只读 |
| 6 | 写crontab 正常启动后执行 | ❌ cron格式不兼容 |

### 正常启动后自动运行路线

| # | 方法 | 结果 |
|---|------|------|
| 1 | 写 `/data/ai-crontab/crontab.dat` | ❌ 二进制格式，不执行 |
| 2 | 写 `/data/start.sh` | ❌ 系统不会自动调用 |
| 3 | `setenv bootargs init=/data/my_init.sh` | ❌ SSH没起来 |
| 4 | 利用 dropbear S50dropbear 脚本 | ⚠️ channel=release阻止启动 |

---

##  可能的路线（待尝试）

### 路线1：从 initargs 真正替换 init（重点）

**原理**：U-Boot 的 storeargs 用 `initargs` 构建 `bootargs`。直接改 `initargs`。

```bash
s12# setenv initargs "rootfstype=ramfs init=/data/my_init.sh console=ttyS0,115200"
s12# saveenv
s12# reset
```

让我们的脚本作为系统的第一进程运行。

### 路线2：创建 /data/my_init.sh 调用真实 init 并启动 SSH

```bash
#!/bin/sh
echo "1" > /tmp/ssh_en
exec /sbin/init
```

### 路线3：修改 boot0 固件的 rc.local

boot0 分区有 failsafe 机制。如果能修改 boot0 系统分区，可以注入启动脚本。

### 路线4：把客户端代码部署在 failsafe 模式

不在正常启动时运行，而是在 failsafe 手动：
1. 进入 failsafe
2. 加载驱动（S10boot + S61wireless）
3. 手动配网
4. 运行客户端程序

### ✅ 已经实现：Shell 客户端方案 (2026-05-01)

**最终采用 failsafe + 手动命令方式，成功实现端到端语音对话。**

流程：
```
音箱 arecord (32kHz) → curl POST → Mac服务器 → Whisper ASR → MiniMax LLM → MiniMax TTS → WAV返回 → 音箱 aplay
```

#### 音频关键修复

1. `/dev/snd/` 设备节点需手动创建（`mknod`，主设备号 116）
2. `Hard Mute` 需关闭 + `Ch1/Ch2` 需 unmute
3. 录音用 `hw:0,2` (PDM-dummy, 32kHz)
4. 播放用 `default` 设备（TDM-B DAC 时钟 48kHz，plughw 自动重采样）
5. Dirac 配置缺失只打印日志，不影响播放

#### 服务器配置

| 组件 | 模型/配置 |
|------|----------|
| LLM | MiniMax-M2.7 (api.minimax.chat) |
| TTS | speech-2.8-hd, male-qn-qingse, PCM → WAV 封装 |
| ASR | Whisper base (本地) |

修复了 config.yaml 环境变量三点嵌套替换 bug（此前 `${MINIMAX_API_KEY}` 在 `llm.minimax.api_key` 路径未被展开）。
修复了 MiniMax TTS 端点（`/v1/t2a_v2`）和 hex 音频解析。

#### 端到端命令（音箱单次对话）

```bash
arecord -D hw:0,2 -f S16_LE -r 32000 -c 1 -d 5 /tmp/rec.wav
curl -s -o /tmp/tts.wav -F "file=@/tmp/rec.wav" http://192.168.10.124:8080/api/v1/shell/chat
aplay /tmp/tts.wav 2>/dev/null
```

### 路线5：外部触发器

正常启动后小爱可以接到小米App指令。如果能：
1. 通过App/云端API推送文件到音箱
2. 然后用小爱语音命令触发脚本执行

### 路线6：Python/xmodem 重新尝试串口传固件

上次失败可能是参数问题。用更大的timeout、更小的block size重试。

### 路线7：open-xiaoai Bridge 方案

参考 https://github.com/coderzc/open-xiaoai-bridge ，用外部桥接方式。

---

##  参考资源

| 资源 | 链接 |
|------|------|
| open-xiaoai项目 | https://github.com/coderzc/open-xiaoai |
| dcl-lily刷机教程 | https://github.com/dcl-lily/esp8266/tree/main/继电器/刷小爱音箱 |
| Hassbian论坛 | https://bbs.hassbian.com/ |
| 拆机视频 | https://www.bilibili.com/video/BV1wW411K7Mm/ |
| 固件下载 | https://bigota.miwifi.com/xiaoqiang/rom/s12a/mico_all_c731c_1.52.1.bin |
| MiniMax API | MiniMax-Text-01 + MiniMax TTS |

### 流式服务端 (2026-05-01)

- `server/sentence_splitter.py` — 中文句子边界检测
- `server/streaming_pipeline.py` — LLM → TTS 真流式流水线（think 标签过滤 + 逐句合成）
- `server/main.py` — 新增 `POST /api/v1/stream/chat` 端点（HTTP chunked transfer，先发 WAV 头再流式输出 PCM）
- `device/stream_client.sh` — FIFO + curl + aplay 渐进式播放客户端

### 固件版本信息 (2026-05-01)

```
ROM:     1.54.8
CHANNEL: release
HARDWARE: S12A
UBOOT:   0.0.1
LINUX:   0.0.1
RAMFS:   0.0.1
SQAFS:   0.0.1
ROOTFS:  0.0.1
BUILD:   Mon, 28 Oct 2019 14:35:07 +0800
GTAG:    commit b9e9b6640c2491c7a77a22612e47790e6c8c0356
```

### 密码系统分析

| 固件版本 | 密码规则 | 状态 |
|----------|---------|------|
| 旧版 (1.52.x?) | `MD5(SN + "9C78089F-83C7-3CDC-BCC9-93B378868E7F")` 前14位 | 固定 UUID |
| 1.54.8 | DSA 签名验证 `magic = SN + 随机wildcard` (每次不同) | **无法破解** |

实测 login 日志验证了 DSA 签名机制：
```
magic[release]: 18090/884527651EC6769DA   (SN + 随机wildcard)
dsa verify sign len 14, digest(len 23)
DSA_verify err → Login incorrect
```

没有小米 DSA 私钥则无法计算正确签名。

### 固件修改路线（来自开源项目调研）

| 项目 | 方式 | 适用性 |
|------|------|--------|
| open-xiaoai (idootop) | Amlogic USB burning 刷 system0 | ❌ S12A 无 USB 口 |
| xuanxuanblingbling | Allwinner 芯片 mount --bind | ❌ 不同 CPU |
| duhow/xiaoai-patch | nc 传文件 + dd 写 MTD，解包 squashfs → 注入 → 打包 → 写回 | ⚠️ S12 标注 "not tested" |
| birdsofsummer/xiaoai-crack | ubus 接口调用（TTS、mediaplayer 等） | ✅ 架构参考 |

**duhow/xiaoai-patch 路线最可行**：通过网络传输（nc/curl），不依赖 USB。需要：
1. 确认 MTD 分区布局 (`cat /proc/mtd`)
2. 备份原版 rootfs
3. Mac 上 unsquashfs → 注入启动脚本 → mksquashfs
4. dd 写回 boot0

**安全网**：boot1 是完整备份系统，U-Boot 可切换分区恢复。

### 分区布局 (2026-05-01)

```
cat /proc/mtd
dev:    size   erasesize  name
mtd0: 00200000 00020000 "bootloader"   → U-Boot (2MB)
mtd1: 00800000 00020000 "tpl"          
mtd2: 00800000 00020000 "boot0"        → 当前 kernel + initramfs (8MB)
mtd3: 00800000 00020000 "boot1"        → 备份 kernel (8MB)
mtd4: 02000000 00020000 "system0"      → rootfs squashfs (32MB)
mtd5: 02020000 00020000 "system1"      → 备份 rootfs (~32MB)
mtd6: 01fe0000 00020000 "data"         → 用户数据 UBIFS (~32MB)
```

运行时挂载：
```
/dev/mtdblock4 → /        squashfs (30.9M/30.9M, 100% 满)
ubi0_0         → /data    ubifs   (24.1M total, 20.5M free)
tmpfs          → /dev     512K
tmpfs          → /tmp     121.2M
```

**启动链**：U-Boot → boot0 (kernel + 嵌入式 initramfs) → system0 (rootfs squashfs)

**注意**：system0 已用满 100%，unsquashfs → 注入文件 → mksquashfs 时可能超出 32MB，需删减无用文件或精简注入内容。

---

### Phase A 实操：固件修改 + Root 获取 (2026-05-02)

#### 操作记录

**1. 备份 system0**
- 音箱 dd → gzip → curl multipart → Mac
- 文件：`/tmp/system0.img.gz` (30MB), `/tmp/system0.img` (32MB)

**2. 解包分析**
- `unsquashfs -s`: squashfs 4.0, xz compressed, 128K block, 1699 inodes
- `unsquashfs -d /tmp/system0_root/`: 解出完整文件系统

**3. 注入启动脚本**
- 创建 `/tmp/system0_root/etc/init.d/sshen`:
  ```bash
  #!/bin/sh /etc/rc.common
  START=45
  start() { echo "1" > /tmp/ssh_en; }
  ```
- 创建符号链接 `/tmp/system0_root/etc/rc.d/S45sshen → ../init.d/sshen`
- 原理：S45 在 S50dropbear 之前运行，写 `/tmp/ssh_en=1` 使 dropbear 跳过 channel=release 阻拦

**4. v1 patched system0 — ✅ 成功**
- `mksquashfs` 重新打包（参数匹配原版：`-comp xz -b 131072 -no-xattrs`）
- 补齐到分区大小 (32MB = 33554432 bytes)
- 音箱从 Mac HTTP 下载 → gunzip → dd 写入 mtd4
- **结果：正常启动 mico login: root 无密码直接登录，SSH 2222 端口通**
- 小爱同学原有功能不受影响

**5. v2 patched system0 — ❌ 失败**
- 在 v1 基础上修改 sshen，增加了调用 `/data/start_ssh.sh &`
- 同样流程打包 → dd 写入 mtd4
- **结果：重启后 preinit 报错，`/dev/console` 不存在、`/tmp` 只读等连锁错误**
- 原因未完全确定，可能与打包时文件权限/所有者有关（uid 501 而非 root）

**6. 恢复 system0 原版**
- `curl → /tmp → gunzip → dd` 写回原版 system0
- 512+0 records in/out — 完整写入确认
- 正常启动到 S12A login，小爱功能正常

**7. ❌ 丢失 failsafe**
- 尝试修复引导问题时，执行了 `dd if=/dev/mtdblock3 of=/dev/mtdblock2`（boot1 kernel → boot0）
- **结果：boot0 的原始 kernel 被 boot1 覆盖，boot1 无 failsafe 入口，failsafe 永久丢失**

#### 当前分区状态

| 分区 | 内容 | 状态 |
|------|------|------|
| mtd0 bootloader | U-Boot | ✅ 完好 |
| mtd2 boot0 | boot1 的 kernel（无 failsafe） | ❌ 原版丢失 |
| mtd3 boot1 | 原版 kernel | ✅ 完好 |
| mtd4 system0 | 原版 rootfs | ⚠️ 可恢复到 v1 |
| mtd5 system1 | 原版 rootfs | ✅ 完好 |
| mtd6 data | WiFi配置、dropbear密钥等 | ✅ 完好 |

#### 恢复路径

| 方案 | 做法 | 难度 |
|------|------|------|
| A | U-Boot 设置 `initargs init=/bin/sh` → 进 shell → 配网 → curl下载v1 → dd写system0 | 需串口操作 |
| B | U-Boot `rdinit=/bin/sh` → WiFi → curl（之前多次尝试WiFi连不上） | 待验证 |
| C | 提取1.52.1固件的boot0 kernel → 刷入mtd2恢复failsafe | 文件已准备好 |
| D | 找到1.62.8修改固件（已开SSH/去密码）→ 直接刷入 | 百度盘失效 |

#### Mac 上已有文件

| 文件 | 大小 | 说明 |
|------|------|------|
| `/tmp/system0.img` / `.img.gz` | 32MB | 原版 system0 备份 |
| `/tmp/system0_patched_padded.img` | 32MB | v1 patched（已验证可用） |
| `/tmp/mico_1.52.1.bin` | 33MB | 1.52.1 完整固件 |
| `/tmp/boot0_1521_padded.img` | 8MB | 从1.52.1提取的boot0（含failsafe） |
| `/tmp/system0_root/` | - | 解包后的 system0 目录 |
| `/tmp/system1.img.gz` / `.img` | 30MB/32MB | system1 原始备份 (xmodem恢复源) |
| `/tmp/boot0_1521.img` / `_padded.img` | 4.6MB/8MB | 1.52.1 boot0 kernel (ANDROID格式) |

### 失败路线全记录 (2026-05-02 ~ 05-03)

#### 串口/网络传输

| 尝试 | 方法 | 结果 | 原因 |
|------|------|------|------|
| nc 传输 | 音箱 `nc < Mac IP 9999 < file` | ❌ | Mac 防火墙 9999 端口拦了 |
| Python xmodem 直连串口 | pyserial + xmodem 库 | ❌ | U-Boot loadx 握手超时 |
| screen exec !! lsx | U-Boot loadx + screen 内 xmodem | ✅ | 传了 boot0(8MB)、system0(32MB)、system1(32MB) |
| curl HTTP 下载 | curl 到 Mac 9999 端口 | ❌ | rdinit shell 缺 curl，需从 /mnt 取 |
| curl HTTP 下载（完整路径） | /mnt/usr/bin/curl 到 8080 端口 | ✅ | WiFi 通时可用 |

#### WiFi 连接（rdinit shell）

| 尝试 | 问题 | 解决 |
|------|------|------|
| 用 system1 模块 | `mlan: no symbol version for module_layout` + WiFi 无法关联 | 换 system0 模块 |
| 用 system0 模块 | 驱动加载成功但 `0002` 不关联 | 缺 /dev/urandom |
| 加 /dev/urandom | 连接成功但立刻被踢 (reason 1) | wpa.conf 格式问题或 regulatory domain |
| 加 country=CN | 仍然被踢 | - |
| heredoc 多行 wpa.conf | ✅ 稳定连接 | **单行分号格式不识别** |
| 换手机热点 | 同被踢 | 非热点问题 |
| 混用 system0/system1 模块 | 状态混乱 | 必须从零开始，只加载一次 |

#### SSH/dropbear（rdinit shell）

| 尝试 | 结果 | 原因 |
|------|------|------|
| dropbear + 公钥 | ❌ `No matching algo hostkey` | Mac 新 OpenSSH 不认 ssh-rsa |
| 加 `-o HostKeyAlgorithms=+ssh-rsa` | ❌ 认证后 shell failed | 缺 /bin/sh |
| 创建 /bin/sh 链接 | ❌ PTY allocation failed | 缺 /dev/pts 和 /dev/ptmx |
| mount devpts + mknod ptmx | ✅ | 完整 SSH 会话 |
| dropbear -R (空密码) | ❌ Permission denied (publickey) | -R 干扰公钥认证 |
| dropbear + bind shadow(空密码) | ✅ 空密码认证通过 | 必须同时有 PTY 设备 |
| dropbear + 公钥 authorized_keys | ❌ 写法导致截断 | echo 换行/空格问题 |
| telnetd | ❌ 连接无响应或进程退出 | initramfs busybox 太精简 |

#### 正常启动 root

| 尝试 | 结果 | 原因 |
|------|------|------|
| v1 patched system0 正常启动 | ✅ mico login: root 无密码直入 | S45sshen 设 ssh_en=1 |
| v2 patched system0 正常启动 | ❌ preinit 崩溃 | 脚本里加了 /data/start_ssh.sh 导致 |
| dd boot1→boot0 | ❌ failsafe 丢失 | boot1 无 failsafe 入口 |
| 1.52.1 kernel (ANDROID)→boot0 | ❌ U-Boot 不认 | genFmt 0x0 ≠ 0x3 |
| 1.52.1 kernel 用 booti 命令 | 未测试 | - |

#### curr_boot NAND key

| 尝试 | 结果 | 原因 |
|------|------|------|
| setenv curr_boot=boot0 | ❌ | 内核不认 U-Boot env |
| initargs 加 curr_boot=boot0 | ❌ | storeargs 覆盖/内核不认 |
| bootargs 加 root=/dev/mtdblock4 | ❌ | storeargs 覆盖 |
| keyman write curr_boot | ❌ | curr_boot 不在 U-Boot keyman 列表 |
| nand read nkey + md 查找 | ❌ | md 在 0x20000000 触发内存异常 |
| nand read nkey 到 0x08000000 | ✅ 读成功 | 但数据加密/编码，无法直接修改 |

#### system0/system1 刷写

| 尝试 | 结果 | 原因 |
|------|------|------|
| mtdblock5 dd 读 system1 | ❌ I/O error | 挂载占用 |
| 卸载后用字符设备 mtd5 | ✅ 成功备份 | 需先 mknod |
| nand write system1 0x2020000 | ❌ 超限 | 坏块后可用空间 < 分区名义大小 |
| nand write system1 0x2000000 | ✅ | 实际 squashfs 31.5MB < 32MB |
| system0 原版恢复后挂载失败 | ❌ Invalid argument | squashfs 损坏或之前写入残留 |
| xmodem raw image 直接写 | ✅ | 不压缩，U-Boot 直写 NAND |

#### 已确认可工作

- U-Boot xmodem 传输：`loadx` + screen `exec !! lsx`
- rdinit WiFi：system0 模块 + heredoc wpa.conf + /dev/urandom
- rdinit SSH：空密码 shadow + devpts + ptmx + /bin/sh 链接
- v1 patched system0 正常启动：root 无密码登录

### ✅ rdinit SSH 成功 (2026-05-03 00:39)

经过多次尝试，最终成功组合：

1. U-Boot → rdinit shell
2. system0 模块配网（system1 模块有符号冲突）
3. wpa.conf 多行格式（单行分号不认）
4. /dev/urandom 解决 WiFi 认证
5. dropbear 空密码 + PTY 设备 + /bin/sh 链接
6. Mac `-o HostKeyAlgorithms=+ssh-rsa` 协商

**SSH root shell 已获取**（端口 2222，空密码）。
完整操作记录见 `REMOTE_SHELL.md`。

**当前状态 (2026-05-03 00:39)**：
- ✅ system0 v1 patched（SSH 可用）
- ✅ system1 原版完好
- ✅ boot0 = boot1 克隆（可用）
- ⚠️ curr_boot=boot1 需修复，否则正常启动仍走 system1
- Mac `/tmp` 有 system0/system1/boot0 完整备份

### v4-v6 system0 迭代 (2026-05-04)

| 版本 | 改动 | 结果 | 原因 |
|------|------|------|------|
| v4 | 修复缺失空目录 (/root, /data, D-Bus dirs) + 设备节点 (pseudo files) | ✅ 小爱唤醒正常 | 对比 unsquashfs -ll 找到缺失项 |
| v5 | sshen 加 bind-mount authorized_keys 从 /data | ❌ squashfs 损坏 | 疑似 source 目录被之前 append 残留污染 |
| v6 | 从 v4 干净解包→改 sshen→重新打包 | ✅ SSH 免密登录正常 | 干净 source 目录 + -noappend |

**v6 核心机制**：S45sshen 在启动时 bind-mount `/data/dropbear/authorized_keys` 到 `/etc/dropbear/authorized_keys`，公钥存在可写 UBI 分区，换设备无需重刷 system0。

**Mac IP**: 192.168.10.188（不是 124！）