# 2026-09-06 boot1 助手自启动恢复

## 原因与修复

用户实测 boot1 能唤醒小爱、查询时间，但原生无法回答的问题不转 LLM。实机没有客户端进程，`/etc/rc.local` 只有注释和 `exit 0`。手动执行现有 `/data/init.sh` 后，用户确认可以转 LLM，证明现有客户端和配置可用。

此次为 system1 的 `/etc/rc.local` 增加以下入口：

```sh
[ -f "/data/init.sh" ] && sh /data/init.sh >/dev/null 2>&1 &
```

该文件由原有 `S95done` 开机流程执行。`/data/init.sh` 继续负责启动延迟、避免重复启动和启动客户端；本次未修改它、客户端或配置。SSH 与原生 OTA 拦截保持原样。缺失入口是否由此前升级覆盖造成，仍未确认。

## 备份、构建与刷写

- 本机备份目录：`backups/boot1-autostart-20260906/`（不提交 Git）。保存当前 system1 完整逻辑镜像、启动环境、原 `rc.local`、`/data/init.sh` 和校验记录。
- 输入 system1（32 MiB）SHA256：`9067eef3e53c505c9da428f2df64d85744090cde49aa5da29c45bff7b98f3d49`，与 2026-09-05 SSH/OTA 修复后的镜像一致。
- 输出及设备完整读回 SHA256：`66a24051ca4063f4f85d3c954969d671684ce0d6b57b8d34a27b76c4bb1d59c5`。
- `patch_s12a_rootfs.py --autostart-only` 构建；再次解包比较内容、权限、链接和设备节点，仅 `etc/rc.local` 发生变化。
- 切回 boot0，验证 SSH/OTA 后，从 boot0 使用 `mtd -f write` 写入备用 system1；读回 512 × 65536 字节与输出哈希一致，之后切回 boot1。
- 未刷写 system0、内核、bootloader；最终保持 boot1 供用户使用和测试。

## 重启后的验证

- 实际根分区 `/dev/mtdblock5`，通过原有密钥重新建立 SSH。
- 未手动调用客户端或 init 脚本，开机约 54 秒时确认自动启动记录、`[HOOK]` 与 `[IDLE]` 日志以及客户端和 watchdog 进程。
- SSH/公钥挂载、关闭密码认证、原生 OTA/flash 拒绝行为和禁用定时升级均通过现有验证脚本。
- `/data/init.sh` SHA256 前后相同：`9aefae73a82c923fa7ce31ec79e8ab482111bf2a2a06b69be6ed9953a9c0e807`。
- 构建器拒绝未装 SSH/OTA 维护补丁的输入，以及已有自定义启动内容的输入，拒绝时不生成镜像。
- 本次重启后的实际语音测试：用户确认“已正常转 LLM 并播报”，无需手动启动客户端。

维护命令见 [双系统 SSH 与受控升级](../runbooks/owner-maintenance.md)，启动机制见 [自启动手册](../runbooks/autostart.md)。
