# S12A 双系统 SSH 与受控升级

适用范围：本项目实机的 S12A，system0 ROM 1.54.8、system1 ROM 1.76.54。
设备 IP 需在每次操作前确认。本文不表示其他型号或更新固件已经兼容。

## 最近一次实机验证

2026-09-05：boot0（1.54.8）与 boot1（1.76.54）均在写入读回校验、重启后通过现有公钥 SSH 登录和升级拦截检查。默认启动 boot0，用户确认唤醒和回复正常。boot1 验证了语音服务进程，未做实际语音交互测试，也未增加助手自启动入口。

详细证据见 [本次恢复记录](../history/2026-09-05-ssh-ota-recovery.md)。这是该日实机状态，后续刷写或配置变动后需要重新核验。

## 维护策略

- 两套系统均通过 `S45sshen` 挂载 `/data/dropbear/authorized_keys`，再启用 Dropbear。
- 使用现有公钥与共享主机密钥，禁止密码登录；缺少持久公钥时不自动引入厂商默认公钥。
- 注释 `/etc/crontabs/root` 中唯一的 `/bin/ota slient` 定时任务，保留其余任务。
- `/bin/ota` 和 `/bin/flash.sh` 替换为拒绝脚本，所有参数均返回 126，不下载、不刷写、不重启。
- 厂商原脚本仅作为参考保存在 `/usr/lib/owner-maintenance/*.original`，权限 0600。不要用它们执行未打补丁的升级。
- 不依赖只驻留内存的 bind mount 来长期拦截 OTA；拒绝脚本直接包含在两套 rootfs 中。
- 保留原来的失败切换逻辑。关闭 OTA 不等于禁止所有 boot 分区切换。

这是对已检查原生入口的控制，不是针对拥有 root 权限程序的安全隔离。未来新固件如果增加升级入口，必须重新检查。

## 恢复与备份

先通过串口进入 U-Boot，记录 `boot_part`、`boot_failcnt`、`boot_failed`、`storeboot`、`initargs`。
恢复到至少一个已验证能够正常启动并通过 SSH 登录的系统后，备份：

- `boot0`、`boot1`、`system0`、`system1`；
- 完整 `/data`、启动环境、当前挂载与版本信息；
- 每份镜像的大小、SHA256、读取退出状态。

`/data` 备份可能含密钥和业务配置，只存本机受限目录，不提交 Git。
不能只凭 `unsquashfs -s` 识别了超级块就认为备份有效，必须完整解包并检查错误。

刷写顺序：从可用 system0 写备用 system1，读回校验并启动验证 system1；成功后，才从 system1 写备用 system0。不要写当前正在运行的根分区。
本机 system1 存在已知坏块，使用已验证的 `mtd -f write <镜像文件> system1`，不使用 `dd of=/dev/mtdblock5`。

## 构建补丁镜像

`tools/speaker-maintenance/patch_s12a_rootfs.py` 只在本机制作镜像，不连接设备，也不执行刷写。
安装本机 `unsquashfs`、`mksquashfs` 后，提供实际备份的哈希、ROM 和一个全新的输出目录：

```sh
python3 tools/speaker-maintenance/patch_s12a_rootfs.py \
  --input /绝对路径/system1.img \
  --input-sha256 <实际核对过的SHA256> \
  --rom 1.76.54 \
  --output-dir /绝对路径/新的构建目录
```

工具检查 S12A 标识、已审核 ROM、所有者、设备节点、原有升级入口和定时任务布局。
修改范围限定在 SSH hook、Dropbear 密码认证配置、OTA 定时任务和原生升级入口。
补齐必要设备节点，以 root 所有者重打 squashfs，限制为本机验证过的 32 MiB 逻辑容量。
打包后再次完整解包，比对文件内容、链接、权限和设备节点，输出 `manifest.json`。

构建记录中的 `flashed: false` 表示构建器没有操作设备；实机部署与验证另行记录。
当前工具拒绝未审核的新 ROM；必须先审核其内核/驱动、启动路径、分区容量和升级入口，才能扩展支持。不能通过仅修改版本白名单来声称兼容。

## 手动受控升级

1. 获取对应型号的官方固件，在本机提取并检查；不直接运行音箱上的原生 OTA。
2. 基于待安装的 rootfs 加入 SSH 与升级控制补丁，校验输出。
3. 核对实际活动根分区、目标备用分区和上传文件哈希。
4. 只写备用分区，读回与本机镜像比较 SHA256。校验失败时不切换启动。
5. 切换后通过原有密钥建立新的 SSH 连接，并确认实际根分区。
6. 执行验证脚本，再检查原生语音服务及实际音箱功能。
7. 保留旧系统，直到新系统验证完成。启动失败时通过串口切回。

不能保证未经检查的未来官方 OTA 自动继承 SSH。这里保留的是“审核、打补丁、再升级”的路径。

## 实机验证

通过已建立的公钥 SSH 连接运行 `tools/speaker-maintenance/verify_owner_maintenance.sh`，传入实际应启动的 `/dev/mtdblock4` 或 `/dev/mtdblock5`。
该脚本先校验拒绝脚本哈希，再测试 OTA 各入口和 flash 入口的拒绝行为，不会调用厂商刷写脚本。
同时检查根分区、SSH hook、持久公钥挂载、密码认证关闭、OTA 定时任务关闭，以及测试前后启动选择未变化。

以默认 boot0 为例，在仓库根目录执行（替换为实际音箱 IP）：

```sh
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes \
  -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa \
  root@192.168.8.152 'sh -s /dev/mtdblock4' \
  < tools/speaker-maintenance/verify_owner_maintenance.sh
```

验证 boot1 时将参数改为 `/dev/mtdblock5`，并确保设备实际已启动到该系统。脚本成功时会输出两行 `PASS`；哈希或状态不符时立即退出，应先查明原因。

刷机后的联网与 SSH 验证不能代替实际语音功能测试。
