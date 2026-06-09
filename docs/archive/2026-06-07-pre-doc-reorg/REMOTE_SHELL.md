# 小米AI音箱 远程Root Shell 操作手册

## 1. 最终效果：正常启动 SSH 免密登录

音箱断电重启，等启动完成，Mac 一行命令直达 root shell：

```bash
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.10.118
```

无需密码、无需串口。只要音箱连着 WiFi 就能连。

### 1.1 添加新设备的公钥

```bash
# SSH 进音箱后
echo "ssh-rsa AAA...  user@host" >> /data/dropbear/authorized_keys
# 立即生效，换设备无需重刷系统
```

### 1.2 原理

不改 boot0，不改内核。只在 system0 里加一个 init 脚本 `/etc/init.d/sshen`（START=45），
在 dropbear（START=50）之前执行，做两件事：

1. `echo "1" > /tmp/ssh_en` — 绕过 dropbear 的 channel=release 阻拦
2. `mount --bind /data/dropbear/authorized_keys /etc/dropbear/authorized_keys` — 把公钥存到可写 /data 分区

具体构建过程见 [2.3 构建 system0 镜像](#23-构建-system0-镜像)。

---

## 2. 核心思路：怎么拿到 root 的

音箱出厂串口被 `mico login:` 拦着（DSA 认证），不知道密码。拿到 root 靠两条路，对应两种救援方式：

### 2.1 发现 1：failsafe，万能后门

OpenWrt 内核 preinit 里有个 failsafe 机制——冷启动时按 `f + Enter`，直接进 `/bin/sh` root shell，不走正常 init。

但 failsafe 没有网络。需要手动：WiFi 驱动 → 连 AP → 启动 telnetd → Mac `nc` 连过来。这就是**方式 A**。

> telnetd 为什么不需要密码？启动参数 `busybox telnetd -l /bin/sh` 中的 `-l` 指定了登录程序为 `/bin/sh`，直接起 shell，完全绕过 `/bin/login` 的密码验证。

有了 failsafe，拿到了第一个 root shell。但每次都要插串口、等冷启动、按 f+Enter，太麻烦。

### 2.2 想要 SSH：正常启动也能连

目标：断电重启后，Mac 直接 `ssh root@音箱` 就是 root shell，不用串口、不用按 f。

首先得让音箱上有个 SSH 服务端。检查正常系统发现——dropbear（OpenWrt 的轻量 SSH 服务端，类似 sshd）是编译好的，但不启动。看它的 init 脚本：

```
if [ "$(cat /tmp/ssh_en)" != "1" ] || [ "$channel" = "release" ]; then
    exit 0
fi
```

两个条件拦住：
1. `/tmp/ssh_en` 必须是 `1`
2. `channel` 不能是 `release`（生产环境就是这个值）

**OpenWrt init 系统的规则**：`/etc/init.d/` 下的脚本按 `START=NN` 数字顺序执行。dropbear 是 `START=50`，在 `START=45` 写一个脚本 `echo "1" > /tmp/ssh_en`，就能在 dropbear 启动前设好 flag。只加一个文件，不碰 dropbear 本身。

另外，dropbear 启动后需要公钥认证——Mac 的私钥对音箱上的公钥，匹配了才放行。所以要把 Mac SSH 公钥写进 `/etc/dropbear/authorized_keys`。但 `/etc/` 在 squashfs 上（只读分区），公钥打进去就改不了。解决：S45sshen 脚本里多加一行 `mount --bind /data/dropbear/authorized_keys /etc/dropbear/authorized_keys`，公钥存可写 `/data` 分区，换设备加 key 一行命令。

### 2.3 构建 system0 镜像

在 Mac 上解包原 system0 → 加 S45sshen → 重新打包：

```bash
# 1. 解包原 system0
unsquashfs -d /tmp/system0 system0.img

# 2. 创建 S45sshen 脚本
cat > /tmp/system0/etc/init.d/sshen << 'EOF'
#!/bin/sh /etc/rc.common
START=45
start() {
    mkdir -p /data/dropbear
    [ -f /data/dropbear/authorized_keys ] || cp /etc/dropbear/authorized_keys /data/dropbear/authorized_keys
    mount --bind /data/dropbear/authorized_keys /etc/dropbear/authorized_keys
    echo "1" > /tmp/ssh_en
}
EOF
chmod +x /tmp/system0/etc/init.d/sshen
ln -s ../init.d/sshen /tmp/system0/etc/rc.d/S45sshen

# 3. 设备节点（macOS unsquashfs 不创建，用 pseudo 文件打入）
cat > /tmp/pseudo.txt << 'EOF'
/dev/console c 0600 0 0 5 1
/dev/null c 0666 0 0 1 3
/dev/ptmx c 0666 0 0 5 2
EOF

# 4. 重新打包
mksquashfs /tmp/system0 /tmp/system0_new.img \
    -comp xz -b 131072 -no-xattrs -all-root \
    -pf /tmp/pseudo.txt -noappend

# 5. 补齐到 32MB 分区大小
# system0 分区（mtd4）= 0x02000000 = 33554432 bytes
# dd conv=sync 用 NUL 字节填满尾部，覆盖整个分区
dd if=/tmp/system0_new.img of=/tmp/system0_new_padded.img bs=33554432 conv=sync count=1
gzip -cf /tmp/system0_new_padded.img > /tmp/system0_new_padded.img.gz
```

> **要点**：macOS 的 unsquashfs 不创建 Linux 设备节点，必须用 `-pf` 伪文件打入。每次必须加 `-noappend`，否则会在旧 .img 上追加导致损坏。NUL 填充无害——squashfs 自带结束标记，内核读到就停。

### 2.4 发现 2：boot1+system1 就是方式 B，独立拿 root

音箱里 boot1 和 system1 是 boot0 和 system0 的完整备份。也就是说，用 boot1 启动就能加载 system1，得到一个完全独立的原版系统。

这个发现有两层意义：

**意义一：改 system0 有安全网。** 如果改出来的 system0 有问题（squashfs 损坏、挂载失败），内核 preinit 检测到后触发看门狗：

```
system0 挂载失败
      ↓
boot_failed() 被调用
      ↓
curr_boot 从 boot0 自动切到 boot1
      ↓
重启 → U-Boot 读 curr_boot=boot1 → 加载 boot1 内核 + system1 根文件系统
      ↓
系统从备份启动（原版，小爱同学正常）
```

v2（preinit 崩溃）和 v5（squashfs 损坏）都触发了这个流程。

**意义二：另一条路拿 root shell。** boot1+system1 不只是备份——用 U-Boot 设 `rdinit=/bin/sh` 从 boot1 启动，可以完全绕过 failsafe，手动挂 system1 到 `/mnt` 取工具链。即使 system0 完好，也能用这条路得到 root shell。这就是**方式 B**，独立于 failsafe 的第二条 root 路径。

> **务必保留 system1 不动**——它是安全网，也是第二入口。

### 2.5 完整路径

```
冷启动 f+Enter → failsafe root shell  → WiFi + telnetd (方式 A)
                                          ↓
发现 dropbear + /tmp/ssh_en              → 创建 S45sshen 脚本
                                          ↓
macOS 上修改 system0 squashfs            → v4 能启动，但 authorized_keys 是写死的
                                          ↓
v5 构建失败，看门狗切 system1             → 发现 system1 可救 system0 (引出方式 B)
                                          ↓
S45sshen 加 bind mount from /data        → v6: 公钥持久化，免密 SSH
```

---

## 3. 系统信息

### 3.1 网络与设备

| 项目 | 值 |
|------|-----|
| 音箱 IP | 192.168.10.118 |
| Mac IP | 192.168.10.188 |
| SSH 端口 | 22 |
| 设备 MAC | E0:B6:55:AD:F3:5B |
| WiFi SSID | TP-LINK_5G_A8E0 |
| 主板代码 | S12A |
| CPU | Amlogic A113X |
| 固件版本 | 1.54.8（原版） |

### 3.2 当前分区状态 (2026-05-04)

| 分区 | 内容 | 状态 |
|------|------|------|
| boot0 (mtd2) | boot1 克隆 | ✅ 可用 |
| boot1 (mtd3) | 原版 kernel | ✅ 完好 |
| system0 (mtd4) | **v6 patched** | ✅ 当前使用 |
| system1 (mtd5) | 原版 rootfs | ✅ 完好 |
| data (mtd6) | 用户数据 + SSH 公钥 | ✅ 完好 |

✅ Failsafe 可用（冷启动按 f+Enter）
✅ system1 是完整备份，出问题可切回去

### 3.3 分区布局

```
mtd0: 00200000 "bootloader"   → U-Boot (2MB)
mtd1: 00800000 "tpl"
mtd2: 00800000 "boot0"        → kernel + initramfs (8MB)
mtd3: 00800000 "boot1"        → 备份 kernel (8MB)
mtd4: 02000000 "system0"      → rootfs squashfs (32MB)
mtd5: 02020000 "system1"      → 备份 rootfs (~32MB)
mtd6: 01fe0000 "data"         → 用户数据 UBIFS (~32MB)
```

启动链：U-Boot → boot0 (kernel + 嵌入式 initramfs) → system0 (rootfs squashfs)

---

## 4. 串口连接

两种救援方式都需要串口。音箱主板有 UART 焊盘，通过 USB-TTL 转接器（3.3V）连 Mac。

### 4.1 查看串口设备

```bash
ls /dev/tty.usbserial* /dev/cu.usbserial*
```

当前设备：`/dev/tty.usbserial-3120`

### 4.2 连接

```bash
screen /dev/tty.usbserial-3120 115200
```

| 参数 | 值 |
|------|-----|
| 设备 | `/dev/tty.usbserial-3120` |
| 波特率 | 115200 |
| 数据位 | 8 |
| 停止位 | 1 |
| 校验 | 无 |
| 流控 | 无 |

接通音箱电源后 screen 里会看到 U-Boot 和内核启动日志。

### 4.3 退出 screen

```
Ctrl+A → k → y
```

按 `Ctrl+A`，松开，再按 `k`，提示 `Really quit?` 时按 `y`。

> 如果 screen 卡住没反应，直接关终端窗口或用 `screen -X -S <session> quit`。

---

## 5. 救援方式

日常用 SSH 就够了。以下两种救援方式只在 **system0 损坏、SSH 连不上** 时需要。

### 5.1 方式对比

| | **方式 A: Failsafe** | **方式 B: rdinit** |
|---|---|---|
| 进入方式 | 冷启动 → 按 f+Enter | U-Boot 设 rdinit=/bin/sh |
| 命令量 | 少（内核 preinit 做了大部分） | 多（需手动挂载一切） |
| system0 挂载 | `/` (根文件系统) | `/mnt` (手动) |
| curl 路径 | `/usr/bin/curl` | `/mnt/usr/bin/curl` |
| 前置条件 | 无 | `export LD_LIBRARY_PATH=/mnt/lib:/mnt/usr/lib` |
| 适合场景 | 快速进 shell 修系统 | system0 损坏时，从 /mnt 取工具；或需要第二条独立 root 路径 |
| 下载目录 | `/tmp/` (121MB tmpfs) | `/tmp/` (tmpfs) |

> ⚠️ 两种环境 curl 路径不同！Failsafe 里直接 `curl`，rdinit 里必须 `/mnt/usr/bin/curl` 且先设 `LD_LIBRARY_PATH`。不要下载到 `/tmp/data/`（UBI data 只有 ~20MB 空闲）。

---

### 5.2 方式 A: Failsafe + telnetd（推荐，简单）

#### 5.2.1 进入

拔电源 → 重插 → 看到 `Press the [f] key...` → **按 f + Enter**。

#### 5.2.2 配网 + 启动远程 shell

```bash
# 挂载 data
mknod /dev/ubi_ctrl c 10 58 2>/dev/null
ubiattach -m 6 -d 0
mknod /dev/ubi0_0 c 242 1
mkdir -p /tmp/data
mount -t ubifs ubi0:data /tmp/data

# 加载 WiFi 驱动
insmod mlan
insmod sd8xxx "drv_mode=3 cfg80211_wext=0xf cal_data_cfg=mrvl/WlanCalData_ext.conf fw_name=mrvl/sdsd8977_combo_v2.bin sta_name=wlan mac_addr=E0:B6:55:AD:F3:5B reg_alpha2=CN drvdbg=0x80007 ps_mode=2 auto_ds=2"
sleep 5

# 连接 WiFi
# /tmp/data/wifi/wpa_supplicant.conf 正常由小爱 App 配网时生成。
# 如果不存在，手动创建：
cat > /tmp/data/wifi/wpa_supplicant.conf << 'WPAEOF'
ctrl_interface=/var/run/wpa_supplicant
ap_scan=1
country=CN

network={
    ssid="TP-LINK_5G_A8E0"
    psk="186****1255"
    key_mgmt=WPA-PSK
}
WPAEOF
ifconfig wlan0 up
wpa_supplicant -B -Dnl80211 -i wlan0 -c /tmp/data/wifi/wpa_supplicant.conf
sleep 8
ifconfig wlan0 192.168.10.118 netmask 255.255.255.0 up
route add default gw 192.168.10.1

# 启动 telnetd
busybox telnetd -l /bin/sh -p 2323 &
echo "=== READY on 2323 ==="
```

#### 5.2.3 Mac 连接

```bash
nc 192.168.10.118 2323
```

---

### 5.3 方式 B: rdinit + SSH（system0 损坏时用）

> system0 坏了，挂载 system1 到 `/mnt` 取工具。

#### 5.3.1 进入 rdinit Shell

拔电源 → 进 U-Boot (s12#)：

```bash
setenv bootargs "rootfstype=ramfs rdinit=/bin/sh console=ttyS0,115200"
imgread kernel boot1 ${loadaddr}
bootm ${loadaddr}
```

#### 5.3.2 环境 + WiFi + SSH（一次性粘贴）

```bash
mount -t proc none /proc
mount -t tmpfs none /dev
mount -t tmpfs none /tmp
mknod /dev/null c 1 3; mknod /dev/console c 5 1
mknod /dev/urandom c 1 9; mknod /dev/random c 1 8
for i in 0 1 2 3 4 5 6; do mknod /dev/mtdblock$i b 31 $i 2>/dev/null; done

# system0 坏了改用 system1 (mtd5)
mount -t squashfs /dev/mtdblock5 /mnt -o ro
export LD_LIBRARY_PATH=/mnt/lib:/mnt/usr/lib
mkdir -p /lib/firmware/mrvl /var/run/wpa_supplicant
cp /mnt/lib/firmware/mrvl/sdsd8977_combo_v2.bin /lib/firmware/mrvl/
cp /mnt/lib/firmware/mrvl/WlanCalData_ext.conf /lib/firmware/mrvl/
insmod /mnt/lib/modules/4.9.61/mlan.ko
insmod /mnt/lib/modules/4.9.61/sd8xxx.ko "drv_mode=3 cfg80211_wext=0xf cal_data_cfg=mrvl/WlanCalData_ext.conf fw_name=mrvl/sdsd8977_combo_v2.bin sta_name=wlan mac_addr=E0:B6:55:AD:F3:5B reg_alpha2=CN drvdbg=0x80007 ps_mode=2 auto_ds=2"
sleep 5
cat > /tmp/wpa.conf << 'WPAEOF'
ctrl_interface=/var/run/wpa_supplicant
ap_scan=1
country=CN

network={
    ssid="TP-LINK_5G_A8E0"
    psk="186****1255"
    key_mgmt=WPA-PSK
}
WPAEOF
# 关掉内核日志刷屏（WiFi 驱动加载后串口会被 debug 信息淹没）
echo "1 4 1 7" > /proc/sys/kernel/printk
/mnt/sbin/ifconfig wlan0 up
/mnt/usr/sbin/wpa_supplicant -B -Dnl80211 -i wlan0 -c /tmp/wpa.conf
sleep 20
/mnt/sbin/ifconfig wlan0 192.168.10.118 netmask 255.255.255.0
/mnt/sbin/route add default gw 192.168.10.1

# SSH（空密码认证，不是公钥认证）
# /etc/shadow 第二个字段为空 → 不设密码，直接回车登录
echo "root::18128:0:99999:7:::" > /tmp/shadow
mount --bind /tmp/shadow /etc/shadow
# dropbear 需要 /bin/sh 作为登录 shell，需要 PTY 设备
ln -sf /mnt/bin/busybox /bin/sh
mkdir -p /dev/pts && mount -t devpts none /dev/pts && mknod /dev/ptmx c 5 2
mkdir -p /tmp/dropbear
/mnt/usr/bin/dropbearkey -t rsa -f /tmp/dropbear/dropbear_rsa_host_key 2>&1
/mnt/usr/sbin/dropbear -p 2222 -r /tmp/dropbear/dropbear_rsa_host_key -E 2>&1 &
```

#### 5.3.3 Mac 连接

```bash
ssh-keygen -R "[192.168.10.118]:2222" 2>/dev/null
ssh -p 2222 -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.10.118
# 密码直接回车
```

> SSH 登录后，工具在 `/mnt` 下，必须先 `export LD_LIBRARY_PATH=/mnt/lib:/mnt/usr/lib`。

---

## 6. 刷写 system0

```bash
# Failsafe 环境
curl -o /tmp/vN.img.gz http://192.168.10.188:8080/api/v1/download/system0_vN_padded.img.gz
gzip -d /tmp/vN.img.gz
dd if=/tmp/vN.img of=/dev/mtdblock4 bs=64k
reboot
```

```bash
# rdinit 环境
export LD_LIBRARY_PATH=/mnt/lib:/mnt/usr/lib
/mnt/usr/bin/curl -o /tmp/vN.img.gz http://192.168.10.188:8080/api/v1/download/system0_vN_padded.img.gz
/mnt/bin/gzip -d /tmp/vN.img.gz
umount -l /mnt 2>/dev/null
dd if=/tmp/vN.img of=/dev/mtdblock4 bs=64k
reboot
```

> 备用的 system0 镜像：`~/research/xiaomi_ai/xiaomi_ai_llm/system0_v6_padded.img.gz`

---

## 7. U-Boot 切换启动分区

```bash
# 用 boot0 + system0 启动（v6 patched 系统）
setenv boot_part boot0
saveenv
reset

# 用 boot1 + system1 启动（原版系统，小爱同学正常）
setenv boot_part boot1
saveenv
reset
```

> `curr_boot` NAND key 由 U-Boot 在冷启动时自动同步，不需要手动设置。两种启动方式系统功能都完整，failsafe 均可通过 f+Enter 进入。

---

## 8. 关键教训

| 问题 | 原因 | 解决 |
|------|------|------|
| wpa.conf 单行分号不认 | wpa_supplicant 只认多行 | heredoc 多行格式 |
| WiFi 连上立刻被踢 | 缺 /dev/urandom | `mknod /dev/urandom c 1 9` |
| dropbear `No matching algo hostkey` | Mac OpenSSH 不认 ssh-rsa | `-o HostKeyAlgorithms=+ssh-rsa` |
| dropbear PTY allocation failed | 缺 PTY 设备 | `mount -t devpts` + `mknod /dev/ptmx` |
| SSH 公钥串口粘贴截断 | heredoc 换行问题 | 用 echo 单行写入 |
| curl/gzip not found | initramfs busybox 精简 | failsafe 用 `/usr/bin/curl`，rdinit 用 `/mnt/usr/bin/curl` |
| curl 报 libcurl.so.4 找不到 | 缺 LD_LIBRARY_PATH | `export LD_LIBRARY_PATH=/mnt/lib:/mnt/usr/lib` |
| squashfs 缺设备节点 | macOS unsquashfs 无权限 | `fakeroot` + mksquashfs `-pf` |
| 冷启动 preinit 死循环 | squashfs 缺 /dev/null | 用 pseudo files 打入设备节点 |
| UBI 设备号错误 | failsafe 设备号 242:1 | 先查 `/proc/devices` 确认 |
| v5 squashfs 损坏 | mksquashfs append 残留 | 每次用 `-noappend` + 干净源目录 |
