# native-first 自启动 init hook

文档类型：长期部署操作手册  
适用范围：让音箱断电重启后自动启动 `native_first_client.sh`  
当前结论：system0/system1 的 `/etc/rc.local` 都已注入 `/data/init.sh` 入口；后续调整主要改 `/data/init.sh`

本文记录让音箱断电重启后自动运行 `native_first_client.sh` 的候选方案。

## 1. 当前结论

推荐长期方案：

1. 在 `system0/system1` 的 `/etc/rc.local` 中注入一行通用入口。
2. 把真正的启动逻辑放在可写、持久化的 `/data/init.sh`。
3. 后续调整启动命令时只改 `/data/init.sh`，不再反复改系统分区。

建议注入到 `rc.local` 的内容：

```sh
[ -f "/data/init.sh" ] && sh /data/init.sh >/dev/null 2>&1 &
```

原因：

- 当前 `system0` 和 `system1` 都有 `/etc/rc.local`。
- 当前 `system0` 和 `system1` 的 `/etc/init.d/done` 都会在 `START=95` 阶段执行 `/etc/rc.local`。
- `START=95` 足够靠后，比 SSH 的 `S45sshen` 更适合启动 native-first 客户端。
- `/data` 是可写且持久化的，适合放后续可调整的启动脚本。

## 1.1 2026-06-06 实际写入状态

已完成：

- `system1` 已写入 `rc.local -> /data/init.sh` hook。
- `system0` 已写入 `rc.local -> /data/init.sh` hook。
- `/data/init.sh` 已部署为 native-first 自启动脚本。
- 当前设备已切回 `boot0`，并验证 native-first 自动启动成功。

本次本地工作目录：

```text
/private/tmp/xiaomi_autostart_20260606_1420
```

关键文件：

```text
system0_live.img
system1_live.img
system0_autostart.img
system1_autostart.img
system0_after_write.img
system1_after_write.img
```

写入命令：

```sh
cat /private/tmp/xiaomi_autostart_20260606_1420/system1_autostart.img \
| ssh root@192.168.8.152 'mtd -f write - system1'

cat /private/tmp/xiaomi_autostart_20260606_1420/system0_autostart.img \
| ssh root@192.168.8.152 'mtd -f write - system0'
```

`system1` 写入时观察到已知坏块：

```text
Skipping bad block at 0x00060000
```

这与此前 boot1 SSH 注入时的坏块情况一致。不要用 `dd of=/dev/mtdblock5` 写 `system1`。

当前 boot0 自启动验证日志：

```text
ROOT=/dev/mtdblock4 squashfs ro,noatime
boot0
[14:35:22] autostart begin client=/data/native_first_client.sh server=http://192.168.8.150:8080 backend=deepseek
[14:39:40] starting native-first client
[14:39:43.910] [HOOK] mounted /bin/wakeup.sh -> /tmp/wakeup.sh.native_first_client
[14:39:44.010] [IDLE] 等待原生唤醒词：小爱同学
```

boot1 自启动验证日志：

```text
ROOT=/dev/mtdblock5 squashfs ro,noatime
boot1
[17:07:20] autostart begin client=/data/native_first_client.sh server=http://192.168.8.150:8080 backend=deepseek
[14:33:18] starting native-first client
[14:33:19.864] [HOOK] mounted /bin/wakeup.sh -> /tmp/wakeup.sh.native_first_client
[14:33:20.510] [IDLE] 等待原生唤醒词：小爱同学
```

boot1 自启动较早，`/tmp/mico_aivs_lab/instruction.log` 可能尚未生成。`native_first_client.sh` 已修正为：只要 root 是 `/dev/mtdblock5` 且 `NATIVE_AIVS_LAB_RESULT_SYSTEM1=1`，`NATIVE_RESULT_SOURCE=auto` 就直接选择 `aivs_lab_instruction`。

## 2. 和 SSH hook 的关系

之前打通 SSH 使用的是 rootfs init hook：

```text
/etc/init.d/sshen
/etc/rc.d/S45sshen -> ../init.d/sshen
```

核心动作：

```sh
mount --bind /data/dropbear/authorized_keys /etc/dropbear/authorized_keys
echo "1" > /tmp/ssh_en
```

这个方案证明了 rootfs 注入 init hook 可行。

但 native-first 不适合直接复用 `S45sshen`：

- `S45sshen` 太早，主要目标是让 dropbear 启动。
- native-first 依赖 `/data`、网络、`ubus`、`mibrain_service`、`mipns-xiaomi`、`mediaplayer` 等，应该晚启动。

因此 native-first 更适合走 `rc.local` 或独立 `S99native_first`。

## 3. 开源项目参考

Open-XiaoAI 的 Rust Client 文档中，开机自启动也是让用户下载 `boot.sh` 到 `/data/init.sh`，然后重启音箱。

Open-XiaoAI 的补丁里对 `/etc/rc.local` 的改动是：

```diff
 [ -f "/data/init.sh" ] && sh /data/init.sh >/dev/null 2>&1 &
```

这个做法的价值是：rootfs 只注入一次通用入口，后续功能脚本全部由 `/data/init.sh` 控制。

另一个 `open-lx01` 项目也明确说明：rootfs 是只读的，`/tmp` 和 `/data` 可写，rootfs 修改必须通过固件/镜像完成。这和我们当前设备观察一致。

## 4. 不推荐的方案

### 4.1 直接写 `/data/ai-crontab/crontab.dat`

已观察到它是二进制格式，不是普通文本 crontab。

设备上虽然存在：

```text
/usr/bin/mico_ai_crontab
ubus object: ai_crontab
/data/ai-crontab/crontab.dat
```

但 `ai_crontab new` 的 `personal_skill` 参数格式还没闭环验证。直接改 `crontab.dat` 风险高，不推荐作为当前主线。

### 4.2 直接改 `/etc/crontabs/root`

当前设备上 `crond` 在跑，但 `/etc/crontabs/root` 属于只读 rootfs，不适合作为不刷分区的持久方案。

### 4.3 在 `/etc/init.d/sshen` 里顺手启动 native-first

不推荐。

原因是启动太早，且 SSH 与 native-first 是两个生命周期。把两者耦合后，后续排障复杂度会上升。

## 5. 推荐的 `/data/init.sh`

仓库模板：

```text
device/data_init_native_first.sh
```

部署成 `/data/init.sh` 后，它会：

- 记录 `/tmp/native_first_autostart.log`。
- 等待一段启动延迟。
- 检查 `native_first_client.sh` 是否已存在。
- 避免重复启动。
- 等待 Mac 服务端健康检查通过。
- 后台启动 `native_first_client.sh`。

## 6. 验证步骤

注入 rootfs 前，只能手动模拟：

```sh
cp /data/data_init_native_first.sh /data/init.sh
chmod +x /data/init.sh
sh /data/init.sh
tail -f /tmp/native_first_autostart.log /tmp/native_first_client.log
```

完成 rootfs 注入后验证：

```sh
reboot
```

重启后 SSH 进入音箱：

```sh
ps | grep -E 'native_first_client|mipns-xiaomi|mediaplayer' | grep -v grep
tail -f /tmp/native_first_autostart.log /tmp/native_first_client.log /tmp/native_first_events.log
```

预期日志：

```text
autostart begin client=/data/native_first_client.sh ...
starting native-first client
[HOOK] mounted /bin/wakeup.sh -> /tmp/wakeup.sh.native_first_client
[IDLE] 等待原生唤醒词：小爱同学
```

## 7. 风险和回滚

这属于轻量 rootfs 修改，仍然算修改系统分区。

风险控制：

- 优先只注入 `rc.local` 的 `/data/init.sh` 入口，不把复杂业务逻辑写进 rootfs。
- 先写非当前启动分区，切换验证。
- 保持串口可用。
- `boot0/boot1` 至少保留一个可启动系统。

如果 `/data/init.sh` 出问题：

```sh
mv /data/init.sh /data/init.sh.disabled
reboot
```

这样 rootfs 入口仍存在，但不会执行 native-first。
