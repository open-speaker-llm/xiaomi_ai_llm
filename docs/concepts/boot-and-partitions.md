<a id="小米音箱启动链路与系统分区说明"></a>

# 从上电到助手：启动链路与双系统

同一份客户端在 boot0 和 boot1 上会面对不同的小米服务，原因藏在启动链路里。先分清三个层次：**boot 负责启动内核，system 提供原生系统，data 保存两边共用的文件。**

本页描述项目实测 S12A 的布局和已有核验，不是对你手中设备的实时检查。型号见[硬件参考](../reference/hardware.md)，具体写入和恢复步骤见[双系统维护](../runbooks/owner-maintenance.md)。

<a id="2-完整启动链路"></a>

<a id="3-关键概念"></a>

<a id="31-bootrom"></a>

<a id="32-u-boot--bootloader"></a>

<a id="5-kernel"></a>

<a id="6-initramfs"></a>

<a id="10-openwrt--lede"></a>

## 1. 上电之后发生什么

```text
上电 → 芯片 BootROM → U-Boot
  → 根据 boot_part 选择 boot0 或 boot1
  → 加载 kernel 与 initramfs，完成早期初始化
  → 挂载 system0 或 system1 为根文件系统 /
  → OpenWrt/LEDE init 启动网络、ubus、小米语音与音频服务
  → 在 /data 可用后，由 rc.local 调用 /data/init.sh
  → 启动 native_first_client.sh 及已启用组件
```

BootROM 是芯片固有的早期代码；串口中的 `s12#` 是 U-Boot 提示符。kernel 管理硬件、进程与文件系统，initramfs 是内核切换到完整系统前的小环境。OpenWrt/LEDE 提供 init、procd 和 ubus 等基础设施，小米用户态服务在其上提供语音能力。术语可查[词表](glossary.md)。

<a id="1-当前设备结论"></a>

<a id="4-boot0--boot1"></a>

<a id="7-system0--system1"></a>

<a id="8-rootfs"></a>

<a id="13-当前设备状态总结"></a>

## 2. 分区各自保存什么

| 分区 | 内容 | 与项目的关系 |
|---|---|---|
| mtd0 / bootloader，mtd1 / tpl | 启动引导 | 决定系统如何开始运行 |
| mtd2 / boot0，mtd3 / boot1 | kernel + initramfs | 选择启动环境；原始 failsafe 能力也与此有关 |
| mtd4 / system0 | 2019 原生用户态，ROM 1.54.8 | 运行时根设备通常为 `/dev/mtdblock4` |
| mtd5 / system1 | 2023 原生用户态，ROM 1.76.54 | 运行时根设备通常为 `/dev/mtdblock5` |
| mtd6 / data | 共享、可写、持久化文件 | 客户端、配置、自启动脚本和公钥 |

“rootfs”是当前挂载到 `/` 的根文件系统，不是另一个分区。例如 `/dev/mtdblock5 on / type squashfs` 表示 system1 正在提供根目录。

在音箱只读检查实际根分区：

```sh
mount | grep ' on / '
```

已有核验记录中，两套 boot 内容相同、内核为 Linux 4.9.61；这是调试时曾把 boot1 写入 boot0 后的状态，不是出厂保证。两套 system 仍不同，所以应用行为仍有差别。

<a id="11-小米服务层"></a>

<a id="12-和当前项目的关系"></a>

## 3. 为什么共享脚本，还需要两套适配

两套系统都能看到同一个 `/data/native_first_client.sh`、`/data/native_first.env`、`/data/init.sh` 和 `/data/dropbear/authorized_keys`。但脚本调用的原生进程、结果来源和音频行为由当前 system 决定。

| 系统 | 主要结果源 | 客户端适配 |
|---|---|---|
| boot0/system0 | `mibrain nlp_result_get` | `ubus_nlp_result`，结构化字段与文本辅助路由 |
| boot1/system1 | AIVS `instruction.log` | `aivs_lab_instruction`，final 与 Speak 文本规则 |

`NATIVE_RESULT_SOURCE=auto` 根据根分区选择适配。boot1 上旧 `nlp_result_get` 可能不刷新，也不能照搬 boot0 的音频采集覆盖。复制旧系统原生二进制去覆盖新系统可能破坏识别；应保留各自适配，详见[对话架构](native-first.md#4-识别之后交给谁回答)。

<a id="9-挂载"></a>

## 4. 哪些文件在重启后还在

| 位置 | 特性 | 常见内容 |
|---|---|---|
| `/` 下的 squashfs | 只读，修改通常涉及镜像 | 原生程序、系统库、init 入口 |
| `/data` | 可写并持久化，两套系统共享 | 项目脚本、私有配置、组件包和回滚备份 |
| `/tmp` | 临时运行空间，整机重启重建 | 日志、会话状态、默认对话历史、展开的判停运行库 |

bind mount 可以在运行时让某个路径指向另一份文件，例如替换唤醒 hook 或组件服务配置，但不会永久改写 squashfs。组件需要通过启动管理器在每次开机重建覆盖；不能把一次手动挂载视为已经持久安装。

## 5. 两套系统为什么都要验证

原生升级或失败切换机制可能改变启动槽位。只打通一边的 SSH，切到另一边就可能失联；只改一边 `rc.local`，另一边能 SSH 却不会自动启动助手。关闭 OTA 也不等于关闭所有失败切换。

这里有一个容易忽略的恢复条件：原始 boot0 的 failsafe 入口可能随内核覆盖而丢失。项目中发生过这样的事故，见[探索记录](../history/journey.md#14-学费failsafe-永久丢失)。因此，不能只靠“切回 boot0”推断一定能进入救援模式。

操作前确认实际启动环境、备份、目标备用分区和串口恢复能力。切换命令集中在[日常操作](../runbooks/operations.md#切换系统)，镜像校验与受控升级在[维护手册](../runbooks/owner-maintenance.md)，助手的后期启动入口见[自启动](../runbooks/autostart.md)。
