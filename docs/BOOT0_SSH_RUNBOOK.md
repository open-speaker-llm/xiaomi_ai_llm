# boot0 SSH 打通操作手册

文档类型：高风险操作手册  
适用范围：boot0/system0 还不能 SSH，需要从串口/failsafe 打通远程 root shell  
当前结论：通过在 system0 rootfs 注入 `S45sshen`，让 dropbear 正常启动，并把 SSH 公钥放到可写 `/data/dropbear/authorized_keys`

## 1. 先理解目标

打通 boot0 SSH 后，Mac 可以直接：

```sh
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152
```

这一步的价值：

- 不再依赖串口传文件。
- 可以用 `scp` 快速上传 `/data/native_first_client.sh` 等脚本。
- 可以通过 SSH 切换 boot 分区并重启。
- 后续调试 native-first 才能高效进行。

## 2. 原理

小米音箱底层类似 OpenWrt/LEDE。系统里已有 dropbear，但默认不会在生产环境启动。dropbear 启动前会检查类似条件：

```sh
/tmp/ssh_en 是否为 1
channel 是否允许
```

解决办法是在 system0 的 rootfs 中增加一个早于 dropbear 运行的 init 脚本：

```text
/etc/init.d/sshen
/etc/rc.d/S45sshen
```

这个脚本做三件事：

```sh
mkdir -p /data/dropbear
mount --bind /data/dropbear/authorized_keys /etc/dropbear/authorized_keys
echo "1" > /tmp/ssh_en
```

仓库里已有脚本：

```text
device/init.d/sshen
```

## 3. 风险

这是写系统分区的操作。开始前必须确认：

- 串口可用。
- 能进入 U-Boot。
- 至少有一个可回退系统。
- Mac 上准备好 `unsquashfs`、`mksquashfs`、`fakeroot`。
- 不要在不理解分区的情况下写 `boot0/boot1/system0/system1`。

建议先读 [BOOT_FLOW.md](BOOT_FLOW.md)，理解 `boot0/system0/rootfs`。

## 4. 进入 failsafe

通过串口连接音箱，重启时看到：

```text
Press the [f] key and hit [enter]
```

立即输入：

```text
f
Enter
```

如果当前不在 boot0，先在 U-Boot 中切回：

```text
s12# setenv boot_part boot0
s12# saveenv
s12# reset
```

## 5. failsafe 中临时联网

failsafe 里没有完整正常系统，需要手动挂载 `/data`、加载 WiFi、启动临时 shell。

以下命令中的 SSID、密码、IP、网关要按你的网络修改：

```sh
mknod /dev/ubi_ctrl c 10 58 2>/dev/null
ubiattach -m 6 -d 0
mknod /dev/ubi0_0 c 242 1
mkdir -p /tmp/data
mount -t ubifs ubi0:data /tmp/data

insmod mlan
insmod sd8xxx "drv_mode=3 cfg80211_wext=0xf cal_data_cfg=mrvl/WlanCalData_ext.conf fw_name=mrvl/sdsd8977_combo_v2.bin sta_name=wlan mac_addr=E0:B6:55:AD:F3:5B reg_alpha2=CN drvdbg=0x80007 ps_mode=2 auto_ds=2"
sleep 5

mkdir -p /tmp/data/wifi
cat > /tmp/data/wifi/wpa_supplicant.conf << 'EOF'
ctrl_interface=/var/run/wpa_supplicant
ap_scan=1
country=CN

network={
    ssid="你的WiFi名称"
    psk="你的WiFi密码"
    key_mgmt=WPA-PSK
}
EOF

ifconfig wlan0 up
wpa_supplicant -B -Dnl80211 -i wlan0 -c /tmp/data/wifi/wpa_supplicant.conf
sleep 8
ifconfig wlan0 192.168.8.152 netmask 255.255.255.0 up
route add default gw 192.168.8.1

busybox telnetd -l /bin/sh -p 2323 &
```

Mac 连接：

```sh
nc 192.168.8.152 2323
```

## 6. 准备 system0 镜像

你需要一份当前设备的 `system0.img`。如果已经有备份，直接使用备份；如果没有，先从设备读出再处理。

在能访问设备 root shell 的环境中，读出 system0：

```sh
dd if=/dev/mtdblock4 of=/tmp/system0.img bs=64k
```

再把它传回 Mac。具体传输方式取决于当前临时 shell 能力，可以用 HTTP、nc 或历史文档里的方式。

历史完整过程见：

```text
docs/archive/2026-06-07-pre-doc-reorg/REMOTE_SHELL.md
```

## 7. 在 Mac 上注入 SSH hook

```sh
WORK=/private/tmp/xiaomi_system0_ssh
mkdir -p "$WORK"
cd "$WORK"

unsquashfs -d system0_root /path/to/system0.img
cp /Users/mac-mini-wx/research/xiaomi_ai/xiaomi_ai_llm/device/init.d/sshen system0_root/etc/init.d/sshen
chmod +x system0_root/etc/init.d/sshen
ln -sf ../init.d/sshen system0_root/etc/rc.d/S45sshen
```

补设备节点伪文件：

```sh
cat > pseudo.txt << 'EOF'
/dev/console c 0600 0 0 5 1
/dev/null c 0666 0 0 1 3
/dev/ptmx c 0666 0 0 5 2
EOF
```

重新打包：

```sh
mksquashfs system0_root system0_ssh.img \
  -comp xz -b 131072 -no-xattrs -all-root \
  -pf pseudo.txt -noappend
```

补齐到 system0 分区大小：

```sh
dd if=system0_ssh.img of=system0_ssh_padded.img bs=33554432 conv=sync count=1
gzip -cf system0_ssh_padded.img > system0_ssh_padded.img.gz
```

## 8. 写回 system0

在 failsafe 或其他 root shell 中下载镜像后写入：

```sh
gzip -d /tmp/system0_ssh_padded.img.gz
dd if=/tmp/system0_ssh_padded.img of=/dev/mtdblock4 bs=64k
sync
reboot
```

注意：

- system0 是 `/dev/mtdblock4`。
- 不要把 system0 镜像写到 boot0。
- 写入前确认文件大小、分区和设备型号。

## 9. 验证 SSH

音箱正常启动后，在 Mac 上执行：

```sh
ssh-keygen -R 192.168.8.152
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152
```

如果需要添加新的 Mac 公钥：

```sh
echo "ssh-rsa AAA... user@mac" >> /data/dropbear/authorized_keys
```

## 10. 后续步骤

boot0 SSH 打通后：

1. 上传 native-first 脚本到 `/data`。
2. 启动 Mac 服务端和音箱客户端。
3. 验证 boot0 主流程。
4. 继续打通 boot1 SSH，见 [BOOT1_SSH_RUNBOOK.md](BOOT1_SSH_RUNBOOK.md)。

