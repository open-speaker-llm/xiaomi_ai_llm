# 2026-09-05 S12A SSH 恢复与 OTA 控制实测

## 结果

| 系统 | ROM | SSH 公钥登录 | 原生 OTA 拦截 | 写入后 SHA256 |
|---|---|---|---|---|
| boot0/system0 | 1.54.8 | 重启后通过 | 验证通过 | `8e25aa82f0d46ee1560992b05b5a83b12dfe45b48265e439b12956b64ef3b231` |
| boot1/system1 | 1.76.54 | 重启后通过 | 验证通过 | `9067eef3e53c505c9da428f2df64d85744090cde49aa5da29c45bff7b98f3d49` |

最终默认启动 boot0，实际根分区为 `/dev/mtdblock4`；`boot_failcnt=0`。
两套系统均使用现有公钥登录，关闭密码认证。SSH 主机密钥保持原有身份，验证连接始终使用严格主机密钥检查。

## 修复前证据

- 设备在线，MAC 与项目记录一致，22 与 2222 端口拒绝连接。
- 串口日志实际启动 boot1/system1。
- U-Boot 中 `boot_part=boot1`、`boot_failcnt=0`、`bootdelay=1`。
- 切回 boot0 后 SSH 恢复，system0 的原有 SSH hook 完整。
- 实际读取的 system1 没有 `sshen`，`rc.local` 没有 `/data/init.sh` 启动入口。不能以旧文档曾写“SSH 已打通”替代当天检查。
- 两套系统都有自动 OTA 定时入口；升级代码会写入另一套系统并改变启动选择。
- U-Boot 也有失败切换逻辑。本次没有获得足够证据判断此前切到 boot1 的具体触发原因，不能认定一定发生过 OTA。

## 备份与部署

部署前保存了两套 boot/rootfs、启动环境、设备清单及完整 `/data`。本机备份位于仓库下 `backups/recovery-20260905-2312/`，包括镜像、哈希清单、读回与 SSH/升级拦截验证记录、串口日志和 `deployment-result.json`。该目录不提交 Git，也不随仓库分发。

可复用源码位于 `tools/speaker-maintenance/`：`patch_s12a_rootfs.py` 负责离线构建，`sshen` 与 `ota-blocked.sh` 是注入内容，`verify_owner_maintenance.sh` 用于启动后的实机核验。
原始 system0 SHA256：`1198c3ae7e799b5c82f27019452635fc75438b5a5d1d9b91ece93850221c8f46`。
原始 system1 SHA256：`e5fc9181ea5daccdbb5ea198b4cf285c5701140a5e3817ddd470dc0c37562733`。
原始 boot0/boot1 SHA256 相同：`97ecb8e6f3235fb81c5601410c6e538e42dd13c22cbb2aac91c652b3fcc45918`。

基于本次实机备份构建补丁，没有用仓库中的旧镜像覆盖设备。
从 system0 写 system1，通过完整 32 MiB 读回校验并启动验证后，再从 system1 写 system0。
system1 写入时跳过已知 `0x00060000` 坏块。内核、bootloader、分区布局未刷写。

## 验证范围

- 打包后重新解包，逐项比较文件哈希、权限、符号链接，并检查必要设备节点。
- 上传文件与设备读回镜像均匹配本机 SHA256。
- 分别在两个系统重启后建立 SSH 连接，确认根分区、公钥挂载和 Dropbear 状态。
- 先确认拒绝脚本哈希，再测试 `check/slient/upgrade/ble/test/success` 及 `flash.sh` 入口均返回 126；测试未改变启动选择。
- OTA 定时任务已注释，其余定时任务保留。
- 构建工具在错误输入哈希、未知 ROM 时拒绝继续；shell 语法检查与 Python 编译检查通过。
- system1 的 `mico_aivs_lab`、`mipns-xiaomi`、`mediaplayer` 进程存在；最终 system0 的小米语音服务和 `native_first_client.sh` 进程存在。
- `/data/init.sh` 修复前后 SHA256 一致：`9aefae73a82c923fa7ce31ec79e8ab482111bf2a2a06b69be6ed9953a9c0e807`。
- 最终 boot0 实际语音测试：用户在设备旁确认“唤醒和回复正常”。system1 仅验证上述服务进程，未做实际语音交互测试。

后续维护方法见 [双系统 SSH 与受控升级](../runbooks/owner-maintenance.md)。
