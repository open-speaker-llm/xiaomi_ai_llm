# boot1 SSH 打通操作手册

文档类型：高风险操作手册  
适用范围：boot1/system1 无法 SSH 时，重新注入 SSH 启动 hook  
当前结论：system1 已验证可注入 `S45sshen`；日常登录不需要重复执行本文写入步骤

本文档记录如何在小米音箱 `system1` rootfs 中注入 SSH 启动 hook，使设备启动到 `boot1/system1` 时也能通过 SSH 登录。

目标读者：没有 LLM 协助时，能按本文独立完成操作。

> 高风险手册保留完整命令形式，不依赖 `ssh xiaomi` 别名。IP 均为示例值，约定见 [../README.md](../README.md#文档约定)。

本次实测结论：

- `system1` 已成功注入 `S45sshen`。
- `mtd -f write - system1` 写入后，`/dev/mtdblock5` 逻辑读回 hash 和本地镜像一致。
- 串口切到 `boot1` 后，Mac 可通过 SSH 登录音箱。
- 因此后续设备偶发启动到 `boot1` 时，理论上也能保持 SSH 可用。

## 1. 适用范围和风险

适用设备：

- 小米 AI 音箱 MDZ-25-DA / S12A
- 当前已能通过 `boot0/system0` SSH 登录
- 串口已连接，可进入 U-Boot 回退

本流程会写入 NAND 的 `system1` 分区。写入前必须确认：

- 串口可用
- 当前 `boot0/system0` SSH 可用
- Mac 上有 `unsquashfs`、`mksquashfs`、`fakeroot`
- 音箱和 Mac 在同一网络

风险点：

- `system1` 分区存在坏块，不能用普通 `dd of=/dev/mtdblock5` 作为最终写入方案。
- 本次验证中 `nandwrite -p /dev/mtd5 -` 写入后逻辑读回不匹配。
- 最终有效写入方式是 `mtd -f write - system1`。
- 切到 `boot1` 后如果 SSH 失败，需要串口进入 U-Boot 切回 `boot0`。

## 2. 当前已验证的分区信息

在音箱 SSH 中查看：

```sh
cat /proc/mtd
mount
cat /proc/cmdline
```

本设备实测分区：

```text
mtd2: boot0
mtd3: boot1
mtd4: system0
mtd5: system1
mtd6: data
```

当前 `system0` rootfs 挂载示例：

```text
/dev/mtdblock4 on / type squashfs (ro,noatime)
```

`system1` 对应：

```text
/dev/mtd5       # char device，用于 flash_erase/mtd/nandwrite
/dev/mtdblock5  # block device，用于逻辑读回校验
```

## 3. SSH hook 机制

`system0` 已验证可用的 SSH hook 是：

```text
/etc/init.d/sshen
/etc/rc.d/S45sshen -> ../init.d/sshen
```

脚本内容：

```sh
#!/bin/sh /etc/rc.common
START=45

start() {
    mkdir -p /data/dropbear
    if [ ! -f /data/dropbear/authorized_keys ]; then
        cp /etc/dropbear/authorized_keys /data/dropbear/authorized_keys
    fi
    mount --bind /data/dropbear/authorized_keys /etc/dropbear/authorized_keys

    echo "1" > /tmp/ssh_en
}
```

关键点：

- `START=45`：在 `/etc/init.d/dropbear` 启动前执行。
- `/tmp/ssh_en`：让系统允许 dropbear 启动。
- `/data/dropbear/authorized_keys`：把公钥放在可写 `/data`，切换 rootfs 后仍可复用。
- bind mount：把 `/data/dropbear/authorized_keys` 挂到 `/etc/dropbear/authorized_keys`。

仓库中对应模板文件：

```text
device/init.d/sshen
```

## 4. Mac 准备工具

在 Mac 上确认工具存在：

```bash
which unsquashfs
which mksquashfs
which fakeroot
```

如果缺少，可安装：

```bash
brew install squashfs fakeroot
```

## 5. 从音箱备份 system1

以下命令在 Mac 仓库根目录执行。通过 SSH 读出 `system1`：

```bash
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa \
root@192.168.8.152 \
'dd if=/dev/mtdblock5 bs=64k 2>/tmp/dd_mtd5_full.err' \
| gzip -c > /private/tmp/system1_current.img.gz
```

解压：

```bash
gzip -dc /private/tmp/system1_current.img.gz > /private/tmp/system1_current.img
```

查看大小：

```bash
ls -lh /private/tmp/system1_current.img /private/tmp/system1_current.img.gz
```

本次实测：

```text
/private/tmp/system1_current.img = 33554432 bytes
```

检查音箱端 `dd` 错误：

```bash
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa \
root@192.168.8.152 'cat /tmp/dd_mtd5_full.err'
```

如果看到：

```text
dd: /dev/mtdblock5: Input/output error
```

不一定代表备份不可用。本设备 `system1` 尾部/坏块相关读错误是已知现象，后续必须用 `unsquashfs` 校验镜像是否有效。

校验 squashfs：

```bash
unsquashfs -s /private/tmp/system1_current.img
```

正常应看到类似：

```text
Found a valid SQUASHFS 4:0 superblock
Compression xz
Block size 131072
```

## 6. 解包 system1

删除旧工作目录：

```bash
rm -rf /private/tmp/system1_root_probe
```

解包：

```bash
unsquashfs -d /private/tmp/system1_root_probe /private/tmp/system1_current.img
```

如果出现下面警告，一般可忽略：

```text
create_inode: could not create character device ... because you're not superuser
```

原因是普通用户不能创建 `/dev/console`、`/dev/null`、`/dev/ptmx` 等字符设备。后面用 `mksquashfs -pf` 补回伪设备定义。

## 7. 注入 SSH hook

复制 hook：

```bash
cp device/init.d/sshen /private/tmp/system1_root_probe/etc/init.d/sshen
chmod 755 /private/tmp/system1_root_probe/etc/init.d/sshen
```

创建启动链接：

```bash
ln -sf ../init.d/sshen /private/tmp/system1_root_probe/etc/rc.d/S45sshen
```

检查：

```bash
ls -l /private/tmp/system1_root_probe/etc/init.d/sshen
ls -l /private/tmp/system1_root_probe/etc/rc.d/S45sshen
sed -n '1,80p' /private/tmp/system1_root_probe/etc/init.d/sshen
```

## 8. 重新打包 system1

创建 pseudo file，补回关键字符设备：

```bash
cat > /private/tmp/system1_pseudo.txt <<'EOF'
/dev/console c 0600 0 0 5 1
/dev/null c 0666 0 0 1 3
/dev/ptmx c 0666 0 0 5 2
EOF
```

打包：

```bash
fakeroot mksquashfs /private/tmp/system1_root_probe \
/private/tmp/system1_ssh.img \
-comp xz \
-b 131072 \
-no-xattrs \
-all-root \
-pf /private/tmp/system1_pseudo.txt \
-noappend
```

把镜像补齐到 32MB：

```bash
dd if=/private/tmp/system1_ssh.img \
of=/private/tmp/system1_ssh_padded.img \
bs=33554432 conv=sync count=1
```

压缩，方便上传到音箱 `/tmp`：

```bash
gzip -c /private/tmp/system1_ssh_padded.img > /private/tmp/system1_ssh_padded.img.gz
```

计算 hash：

```bash
shasum -a 256 /private/tmp/system1_ssh_padded.img
shasum -a 256 /private/tmp/system1_ssh_padded.img.gz
```

本次实测：

```text
system1_ssh_padded.img    78d3f524a9a169af9e37b8bcac91e3eebdcb08181ce960c0b82934c7884562d1
system1_ssh_padded.img.gz 1fe295a9a79a29d550b60c9cd1b2fff63f4ceea504ae1c40cfa267fb005680b0
```

重新校验打包后的镜像：

```bash
unsquashfs -s /private/tmp/system1_ssh_padded.img
```

可选：展开一次确认 hook 存在：

```bash
rm -rf /private/tmp/system1_verify
unsquashfs -d /private/tmp/system1_verify /private/tmp/system1_ssh_padded.img
ls -l /private/tmp/system1_verify/etc/init.d/sshen
ls -l /private/tmp/system1_verify/etc/rc.d/S45sshen
```

## 9. 上传镜像到音箱

上传：

```bash
scp -O \
-o HostKeyAlgorithms=+ssh-rsa \
-o PubkeyAcceptedKeyTypes=+ssh-rsa \
/private/tmp/system1_ssh_padded.img.gz \
root@192.168.8.152:/tmp/system1_ssh_padded.img.gz
```

校验远端 gzip hash：

```bash
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa \
root@192.168.8.152 \
'sha256sum /tmp/system1_ssh_padded.img.gz; df -h /tmp'
```

远端 hash 必须和 Mac 上的 `.gz` hash 一致。

## 10. 写入 system1

先确认写入工具：

```bash
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa \
root@192.168.8.152 \
'which flash_erase; which mtd; which nandwrite; ls -l /dev/mtd5 /dev/mtdblock5'
```

正式写入：

```bash
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa \
root@192.168.8.152 \
'gzip -dc /tmp/system1_ssh_padded.img.gz | mtd -f write - system1; sync'
```

正常日志里可能看到：

```text
Skipping bad block at 0x00060000
```

这是已知坏块，`mtd write` 会跳过处理。

不要使用以下方式作为最终写入：

```sh
gzip -dc /tmp/system1_ssh_padded.img.gz | dd of=/dev/mtdblock5 bs=64k
gzip -dc /tmp/system1_ssh_padded.img.gz | nandwrite -p /dev/mtd5 -
```

本次实测这两种方式会导致逻辑读回和本地镜像不一致。

## 11. 写入后校验

在音箱上直接读回 `system1` 逻辑镜像并算 hash：

```bash
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa \
root@192.168.8.152 \
'dd if=/dev/mtdblock5 bs=64k count=512 2>/tmp/verify_mtd5_final.err | sha256sum; cat /tmp/verify_mtd5_final.err'
```

必须匹配 Mac 上的 `system1_ssh_padded.img` hash。

本次实测正确 hash：

```text
78d3f524a9a169af9e37b8bcac91e3eebdcb08181ce960c0b82934c7884562d1
```

再读回到 Mac 做本地校验：

```bash
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa \
root@192.168.8.152 \
'dd if=/dev/mtdblock5 bs=64k count=512 2>/tmp/readback_mtd5.err' \
> /private/tmp/system1_readback_after_mtd.img
```

比较 hash：

```bash
shasum -a 256 /private/tmp/system1_readback_after_mtd.img /private/tmp/system1_ssh_padded.img
```

校验 squashfs：

```bash
unsquashfs -s /private/tmp/system1_readback_after_mtd.img
```

展开读回镜像并确认 hook：

```bash
rm -rf /private/tmp/system1_readback_verify_final
unsquashfs -d /private/tmp/system1_readback_verify_final /private/tmp/system1_readback_after_mtd.img
ls -l /private/tmp/system1_readback_verify_final/etc/init.d/sshen
ls -l /private/tmp/system1_readback_verify_final/etc/rc.d/S45sshen
sed -n '1,80p' /private/tmp/system1_readback_verify_final/etc/init.d/sshen
```

如果解包时有字符设备警告，可忽略；重点是 `/etc/init.d/sshen` 和 `/etc/rc.d/S45sshen` 存在。

清理音箱 `/tmp` 临时镜像：

```bash
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa \
root@192.168.8.152 \
'rm -f /tmp/system1_ssh_padded.img.gz; df -h /tmp'
```

## 12. 切到 boot1 验证 SSH

确认串口已连接：

```bash
screen /dev/tty.usbserial-3120 115200
```

重启音箱，进入 U-Boot。看到启动倒计时或提示时按任意键，中断自动启动，进入：

```text
s12#
```

查看当前启动分区：

```text
s12# printenv boot_part
```

切到 `boot1`：

```text
s12# setenv boot_part boot1
s12# saveenv
s12# reset
```

等待系统启动完成后，在 Mac 上 SSH：

```bash
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152
```

能连上即成功。

进入后可确认：

```sh
mount
cat /proc/mtd
cat /tmp/ssh_en
ls -l /etc/init.d/sshen /etc/rc.d/S45sshen
```

## 13. 失败回退

如果切到 `boot1` 后：

- 设备不联网
- SSH 连不上
- 系统启动异常

用串口重新进入 U-Boot，切回 `boot0`：

```text
s12# setenv boot_part boot0
s12# saveenv
s12# reset
```

回到 `boot0` 后再用 SSH 进入排查：

```bash
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa root@192.168.8.152
```

## 14. 常见问题

### 14.1 为什么不能直接 dd 写 /dev/mtdblock5？

`system1` 分区有坏块。普通 `dd` 不会按 NAND 坏块语义正确写入，可能导致逻辑读回 hash 不匹配。

本次实测：

- `dd of=/dev/mtdblock5` 后 hash 不匹配
- `nandwrite -p /dev/mtd5 -` 后逻辑块出现错位
- `mtd -f write - system1` 后读回 hash 匹配

### 14.2 为什么读 mtdblock5 时可能出现 I/O error？

`system1` 分区尾部/坏块相关读错误在本设备上出现过。判断镜像是否可用，不能只看 `dd` stderr，要看：

- 文件大小是否合理
- `unsquashfs -s` 是否能识别有效 squashfs
- 写入后逻辑读回 hash 是否匹配

### 14.3 为什么需要 pseudo file？

普通用户解包 squashfs 时不能创建 `/dev/console`、`/dev/null`、`/dev/ptmx` 等字符设备。重新打包时用 `mksquashfs -pf` 把这些节点补回。

### 14.4 boot1 能 SSH 后，启动音箱助手用什么命令？

boot1/system1 上必须保持小米原生音频链路，配置保持 `auto`：

```sh
AUDIO_CAPTURE_SETUP=auto
NATIVE_RESULT_SOURCE=auto
WAKE_ON_THINK_SYSTEM1=1
NATIVE_AIVS_LAB_RESULT_SYSTEM1=1
```

不要在 boot1 上把 `AUDIO_CAPTURE_SETUP` 强制设成 `1`，否则可能导致原生 `recorder` 崩溃，表现为能唤醒但后续 ASR/NLP、开关灯、天气等都不响应。boot0/boot1 链路差异的完整说明（唤醒事件、结果源、freeze 策略）见 [../concepts/native-first.md](../concepts/native-first.md#5-boot0-与-boot1-兼容)。

Mac 服务端（仓库根目录）：

```bash
./start_server.sh
```

音箱客户端：

```sh
SERVER=http://192.168.8.150:8080 BACKEND=deepseek \
sh /data/native_first_client.sh > /tmp/native_first_client.log 2>&1 &
```

查看日志：

```sh
tail -f /tmp/native_first_client.log /tmp/native_first_events.log
```
