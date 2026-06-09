# 小米音箱启动链路与系统分区说明

本文说明这台小米 AI 音箱从上电到运行 `native_first_client.sh` 的完整链路，并解释 `boot0`、`boot1`、`system0`、`system1`、`kernel`、`initramfs`、`rootfs`、OpenWrt/LEDE 等概念。

## 1. 当前设备结论

当前设备的分区布局：

```text
mtd0: bootloader
mtd1: tpl
mtd2: boot0
mtd3: boot1
mtd4: system0
mtd5: system1
mtd6: data
```

当前只读核验结果：

```text
boot0 sha256 = boot1 sha256
boot0/boot1 当前内容相同
```

当前 kernel：

```text
Linux S12A 4.9.61 #1 SMP PREEMPT Wed Sep 20 08:55:48 2023 aarch64
```

当前 system 版本：

| 分区 | rootfs 设备 | 小米 ROM | Build time |
|---|---|---:|---|
| system0 | `/dev/mtdblock4` | `1.54.8` | `Mon, 28 Oct 2019 14:35:07 +0800` |
| system1 | `/dev/mtdblock5` | `1.76.54` | `Wed, 20 Sep 2023 17:07:08 +0800` |

因此当前设备上，`boot0` 与 `boot1` 的 kernel 已经相同；`boot0/system0` 与 `boot1/system1` 的主要行为差异来自 `system0` 和 `system1` 的小米用户态 rootfs 不同。

## 2. 完整启动链路

```text
上电
  ↓
BootROM
  ↓
U-Boot / bootloader
  ↓
读取 boot_part，选择 boot0 或 boot1
  ↓
加载 kernel + initramfs
  ↓
kernel 启动
  ↓
initramfs / early init 初始化基础设备
  ↓
挂载 system0 或 system1 为 rootfs
  ↓
rootfs 成为 /
  ↓
OpenWrt/LEDE init 系统启动
  ↓
启动 ubus、网络、dropbear、小米语音服务、音频服务
  ↓
挂载共享 /data
  ↓
/data/init.sh 自启动 native_first_client.sh
```

## 3. 关键概念

### 3.1 BootROM

BootROM 是芯片内部固化的第一段代码。它不在普通 NAND 分区里，主要负责找到外部存储里的 bootloader。

正常开发和调试基本不会直接操作 BootROM。只有设备坏到 U-Boot 都进不去时，才会涉及 BootROM 级别救援。

### 3.2 U-Boot / bootloader

U-Boot 是可交互的启动管理器。串口里看到：

```text
s12#
```

就是 U-Boot 命令行。

U-Boot 读取环境变量决定启动哪个 boot 分区：

```sh
printenv boot_part
```

常见值：

```text
boot_part=boot0
boot_part=boot1
```

可以在 U-Boot 中切换：

```text
s12# setenv boot_part boot1
s12# saveenv
s12# reset
```

也可以在 Linux 里通过 SSH 切换：

```sh
fw_env boot_part=boot1 && sync && reboot
fw_env boot_part=boot0 && sync && reboot
```

## 4. boot0 / boot1

`boot0` 和 `boot1` 是两个启动分区：

```text
mtd2: boot0
mtd3: boot1
```

它们主要包含：

```text
kernel + initramfs
```

可以把它们理解为两套“启动器”。U-Boot 根据 `boot_part` 选择其中一个。

当前设备上，`boot0` 和 `boot1` 的内容相同。这是设备调试过程中曾把 `boot1` 写入 `boot0` 后形成的当前状态。原始出厂状态下，`boot0` 与 `boot1` 可能并不完全相同，例如 failsafe 能力曾经主要依赖 `boot0`。

## 5. kernel

kernel 是 Linux 内核，负责底层硬件和系统资源：

```text
CPU
内存
进程
文件系统
NAND
网络
声卡
I2C
驱动
```

当前设备 kernel：

```text
Linux 4.9.61
build time: Wed Sep 20 08:55:48 2023
```

kernel 启动后，还不能马上运行完整系统，因为真正的 `/bin`、`/etc`、`/usr` 等文件还在 `system0/system1` 里。因此 kernel 会先使用 initramfs。

## 6. initramfs

initramfs 是内核启动早期使用的临时根文件系统。

它通常负责：

```text
初始化基础设备
加载必要驱动
解析启动参数
判断正常启动还是 failsafe
选择并挂载真正的 rootfs
切换到真正系统
```

可以把 initramfs 理解成“启动早期的小工具箱”。它存在于 boot 分区随 kernel 一起加载。

## 7. system0 / system1

`system0` 和 `system1` 是两个系统分区：

```text
mtd4: system0
mtd5: system1
```

它们主要包含完整 rootfs：

```text
/bin
/etc
/lib
/sbin
/usr
/etc/init.d
/usr/bin/mibrain_service
/usr/bin/mipns-xiaomi
/usr/bin/mico_aivs_lab
```

当前设备上：

```text
system0 = 小米 ROM 1.54.8，2019 版
system1 = 小米 ROM 1.76.54，2023 版
```

这就是为什么同一份 `/data/native_first_client.sh` 在 boot0 与 boot1 下行为不同：脚本文件相同，但它面对的小米原生服务版本不同。

## 8. rootfs

rootfs 是“当前被挂载为 `/` 的根文件系统”，不是一个单独分区名。

当前启动到 system1 时：

```text
/dev/mtdblock5 on / type squashfs
```

含义：

```text
当前 rootfs = system1
```

启动到 system0 时通常会看到：

```text
/dev/mtdblock4 on / type squashfs
```

含义：

```text
当前 rootfs = system0
```

## 9. 挂载

挂载就是把一个存储分区接到 Linux 目录树里的某个位置。

示例：

```text
/dev/mtdblock5 挂载到 /
```

表示 system1 成为当前系统根目录。

`/data` 也是一个挂载点。它是共享、可写、持久化分区：

```text
/data
```

boot0/system0 和 boot1/system1 都能看到同一份 `/data`，所以以下文件两边共用：

```text
/data/native_first_client.sh
/data/native_first.env
/data/init.sh
/data/dropbear/authorized_keys
```

## 10. OpenWrt / LEDE

OpenWrt/LEDE 是这台音箱 rootfs 里的 Linux 发行版框架。

当前两套 system 的基础 LEDE 版本都显示：

```text
LEDE Reboot SNAPSHOT 70-1-1
```

它负责：

```text
/etc/init.d/*
/etc/rc.d/*
procd
ubus
网络
服务启动顺序
```

但 LEDE 只是底座。小米语音能力来自小米自己的用户态服务。

## 11. 小米服务层

系统启动后，会启动一批小米服务，例如：

```text
mipns-xiaomi
mibrain_service
mico_aivs_lab
mediaplayer
ubus
```

当前项目最关心的是这些服务的差异：

| 启动组合 | 原生结果来源 | 当前脚本适配 |
|---|---|---|
| boot0/system0 | `mibrain nlp_result_get` | `NATIVE_RESULT_SOURCE=auto` 选择 `ubus_nlp_result` |
| boot1/system1 | `/tmp/mico_aivs_lab/instruction.log` | `NATIVE_RESULT_SOURCE=auto` 选择 `aivs_lab_instruction` |

boot1/system1 上，`mibrain nlp_result_get` 可能不刷新；`mico_aivs_lab` 的 `instruction.log` 中会出现原生 ASR/TTS 指令，例如：

```text
SpeechRecognizer/RecognizeResult
SpeechSynthesizer/Speak
Dialog/Finish
```

因此不要简单复制 boot0 的服务文件去覆盖 boot1，也不要试图把两套系统“硬填平”。当前长期方案是在 `native_first_client.sh` 中保留两套结果源适配。

## 12. 和当前项目的关系

当前主线是 native-first：

```text
小爱同学唤醒
  ↓
小米原生 ASR/NLP 先处理
  ↓
原生支持：家电、天气、音量等直接走小米
  ↓
原生不支持：脚本拦截失败播报，转给 Mac LLM
```

脚本文件在 `/data`：

```text
/data/native_first_client.sh
/data/native_first.env
```

因为 `/data` 共享，所以两套系统使用同一份脚本；因为 `system0/system1` 的小米服务层不同，所以脚本内部需要按当前 rootfs 做适配。

## 13. 当前设备状态总结

```text
boot0 == boot1
kernel = Linux 4.9.61, 2023-09-20

system0 != system1
system0 = ROM 1.54.8, 2019-10-28
system1 = ROM 1.76.54, 2023-09-20

/data 共享
native_first_client.sh 两边共用
小米服务层两边不同
```

所以当前差异的主因是：

```text
system0/system1 rootfs 中的小米用户态版本不同
```

不是当前 `boot0/boot1` kernel 不同。

