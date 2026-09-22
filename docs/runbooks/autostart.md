<a id="native-first-自启动-init-hook"></a>

<a id="1-当前结论"></a>

<a id="11-2026-09-06-实机补齐与验证"></a>

<a id="12-2026-06-06-历史写入记录"></a>

<a id="2-和-ssh-hook-的关系"></a>

<a id="3-开源项目参考"></a>

<a id="4-不推荐的方案"></a>

<a id="41-直接写-dataai-crontabcrontabdat"></a>

<a id="42-直接改-etccrontabsroot"></a>

<a id="43-在-etcinitdsshen-里顺手启动-native-first"></a>

<a id="5-推荐的-datainitsh"></a>

<a id="6-验证步骤"></a>

<a id="7-风险和回滚"></a>

# 配置自启动：让音箱重启后自己恢复

手动启动并完成真实问答后，再把同一条链路交给开机入口。这里分清两件事：系统是否调用 `/data/init.sh`，以及该脚本是否能启动已经部署好的客户端和组件。

## 1. 理解启动入口

```text
当前 system 的 rc.local
  → 共享 /data/init.sh
  → native_first_client.sh
  → 已安装并启用的 guard / 原生追问 / 首轮判停管理器
```

推荐在两套系统的 `/etc/rc.local` 中只保留通用入口，把可调整逻辑放在持久、可写的 `/data`：

```sh
[ -f "/data/init.sh" ] && sh /data/init.sh >/dev/null 2>&1 &
```

本机 init 的后期阶段执行 `rc.local`，比 SSH 的 `S45sshen` 更适合等待原生语音服务。SSH 与助手使用不同生命周期，不能因为能 SSH 就推断助手已经自启动。

## 2. 先检查，不重复写系统分区

在音箱读取当前入口：

```sh
cat /etc/rc.local
ls -l /data/init.sh /data/native_first_client.sh
```

已有通用入口时，只需检查 `/data` 中的脚本和配置。入口缺失时，先按[双系统维护中的自启动补丁流程](owner-maintenance.md#为已有维护镜像补齐助手自启动)检查镜像基线，从另一套已验证系统写备用分区、读回校验后再切换。不要在这里直接写活动根分区。

rootfs 修改前保持串口可用，保留至少一套可启动系统。仅开关本地判停不需要再次修改 rootfs。

## 3. 部署或检查 init.sh

首次部署且没有自定义 `/data/init.sh` 时，在音箱安装已上传的模板：

```sh
[ -f /data/init.sh ] || cp /data/data_init_native_first.sh /data/init.sh
chmod +x /data/init.sh
```

已有脚本应先备份、比较内容，再决定是否调整。模板 [device/data_init_native_first.sh](../../device/data_init_native_first.sh) 会记录启动日志、等待原生环境、避免重复启动，并短暂探测可选服务端。默认 `START_WITHOUT_SERVER=1`，服务不可达也会启动客户端；设备 TTS 与原生兜底不依赖常驻 Mac。

先在音箱空闲且客户端未运行时手动检查脚本：

```sh
sh /data/init.sh
tail -n 60 /tmp/native_first_autostart.log /tmp/native_first_client.log
```

这只验证脚本可运行，还没有证明整机启动会调用它。

## 4. 单独验证整机启动

确认已经保存配置与回滚入口，且音箱没有播报或收听时重启：

```sh
sync
reboot
```

重连后不要手动启动客户端，先读取日志：

```sh
sh /data/native_first_client.sh status
tail -n 60 /tmp/native_first_autostart.log /tmp/native_first_client.log
```

预期看到 `autostart begin`、`starting native-first client`、`[HOOK]` 与 `[IDLE]`。随后验证原生报时和 LLM 首问；启用追问的设备再测试上下文衔接与静默退出。

### 首轮判停的启动与验证范围

已安装判停包时，客户端自动调用管理器。包持久保存在 `/data/native_endpoint/`，校验后展开到 `/tmp`，模型 READY 后才接管新唤醒；无需另加实验脚本。

```sh
sh /data/native_endpoint/manager.sh verify
sh /data/native_endpoint/manager.sh status
sh /data/native_asr.sh status
```

需要同时确认包校验通过、`ENDPOINT_READY`、native_asr `healthy`，以及模型与控制器未重复启动。按 [EP7](../../tests/manual_native_first_cases.md#ep-首轮本地判停)在重启后复验静默和停顿续说。整机 reboot、断电冷启动与全天运行是不同验证项；已有证据统一见[状态页](../status.md)。

## 5. 停用和恢复

仅调整组件时，按[日常操作](operations.md)停止客户端并修改对应开关；完整回滚使用该次安装输出的备份脚本，不能只替换共享 SO。

如果 `/data/init.sh` 本身导致问题，在确认目标备份名尚不存在、音箱空闲时，可停止客户端并临时移走入口：

```sh
sh /data/native_first_client.sh stop
mv /data/init.sh /data/init.sh.disabled
reboot
```

rootfs 通用入口仍在，但找不到 `/data/init.sh` 就不会执行。恢复前检查和修正脚本，再恢复文件名并重新验收。

## 设计依据与历史

原始自启动入口参考 open-xiaoai 的 `/data/init.sh` 方式。没有采用直接编辑二进制 `ai-crontab/crontab.dat`、在只读 rootfs 改 crontab，或把助手塞进过早的 SSH hook；这些方案的实验背景保留在[原始自启动记录](../archive/2026-06-07-pre-doc-reorg/AUTOSTART_INIT_HOOK.md)。

2026-06 的镜像、写入日志和失败条件也在该归档；后来补齐 system1 入口的事实见 [2026-09-06 记录](../history/2026-09-06-boot1-autostart.md)。它们解释设计由来，不替代操作前对当前镜像的检查。
