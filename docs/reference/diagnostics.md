# 音箱只读诊断

`device/speaker_doctor.sh` 把配置、组件、进程、安装包和空间检查集中到一个入口。它不修改配置、不启动或停止服务、不播放声音、不调用云端，也不执行自动修复。

适用主线为 S12A 的 boot0/system0 与 boot1/system1。诊断按 `/data/native_first.env` 中的静态配置区分 `native-device`、`native-server` 和 `server`，不把可选组件缺失统一判成故障。配置正常、文件存在或进程存活，均不代表真实对话已通过验收。

## 在音箱上运行

开发机进入仓库根目录，使用已经配置好的 `xiaomi` SSH 别名。下面把脚本通过标准输入交给音箱执行，不上传文件：

```sh
ssh xiaomi 'sh -s' < device/speaker_doctor.sh
rc=$?
printf '诊断退出码：%s\n' "$rc"
```

这个命令只诊断，不需要用户说话。没有 SSH 别名时，先按[文档约定](../README.md#文档约定)配置实际设备地址；不要把历史 IP 当作当前地址。SSH 自身返回 `255` 时先排查连接，这不是下面定义的诊断退出码。

希望以后直接在音箱执行，可以单独上传脚本。上传这一步会写入该脚本文件；随后诊断仍然只读，不要求覆盖客户端或其他组件：

```sh
scp -O device/speaker_doctor.sh xiaomi:/data/speaker_doctor.sh
ssh xiaomi 'sh /data/speaker_doctor.sh'
```

脚本使用 POSIX shell 和 BusyBox 常见的 `awk`、`od`、`tr`、`wc`、`grep`、`sha256sum`、`df`，不依赖 Python、jq 或 Mac 服务端。未安装 SHA256 工具时报告未知，不跳过校验后宣称通过。

## 读懂结果

每项以固定标识和中文说明输出，必要时提供下一步。固定标识适合定位同一问题，但不要从中文文案推导设备控制指令。

| 状态 | 含义 |
|---|---|
| `PASS` | 该项可读取的静态证据符合检查条件 |
| `INFO` | 路线、快照迹象或未覆盖边界，不表示产品验收通过 |
| `SKIP` | 当前路线不要求该组件，或开关未启用 |
| `WARN` | 有证据需要复核，例如重复配置、低空间或判停正在排空 |
| `UNKNOWN` | 信息不足、配置无法静态解析、布局未知或离线快照缺失 |
| `FAIL` | 已确认不符合检查条件，例如文件摘要不符或 PID 指向其他进程 |

最后一行为：

```text
DOCTOR_SUMMARY failures=0 uncertainties=0 human_acceptance=not_run
```

| 退出码 | 判断 |
|---|---|
| `0` | 可检查项没有确定缺陷或未知项；真人验收仍未执行 |
| `1` | 至少一项确定缺陷；同时出现未知项时也返回 `1` |
| `2` | 没有确定缺陷，但有未知项或待确认事项 |
| `64` | 命令参数错误 |

例如 `CLIENT_PROCESS` 通过，只表示 PID 文件、进程命令和非僵尸状态相符。`ASR_SNAPSHOT` 与 `ENDPOINT_SNAPSHOT` 最多说明数字状态头、进程和租约的快照迹象相符，不宣称完整的 `healthy` 或 `ENDPOINT_READY`；AEC 硬件状态、原生回调、真实收音和实际出声仍需单独验证。

## 检查范围与下一步

| 检查项 | 读取的证据 | 失败或未知时怎么处理 |
|---|---|---|
| 配置与运行路线 | `/data/native_first.env` 的受支持字面量和客户端默认值 | 按[配置参考](configuration.md)核对最后生效值；不反复覆盖已有私有配置 |
| 型号、ROM、分区 | `/usr/share/mico/version`、`/proc/mounts` | 先核对适配与活动分区；版本识别不替代安装器的 ABI 校验 |
| 客户端、TTS、追问组件 | 所选路线对应的文件、可执行位 | 按对应安装文档补齐；已有判停包使用整包维护路径 |
| 进程 | PID 文件、`/proc/PID/cmdline` 和 `status` | 核对是否缺失、重复或 PID 陈旧，不直接按诊断结果 kill 进程 |
| 原生 ASR 快照 | 状态文件固定数字头、原生 PID、共享库映射 | 核对同版组件和同次启动证据；不输出状态里的对话内容 |
| 判停包与活动文件 | 五项白名单清单、包文件 SHA256、活动客户端和 SO | 恢复完整匹配包，不只替换共享 SO，也不删除目录绕过安装门禁 |
| 判停快照 | 数字状态头、租约、控制器/模型 PID、引用的原生进程 | 新唤醒可能退回原生收音；保留拒绝记录，不清空路由日志 |
| 空间 | 音箱 `df -Pk /data /tmp` | `/data` 少于 1 MiB、`/tmp` 少于 32 MiB 时提示复核；不自动删除文件 |

空间阈值只是排障提示，不是安装容量、模型内存或长期稳定保证。完整回滚后保留的旧包可以继续校验自身清单；判停关闭时，不要求活动客户端必须等于保留包中的版本。

配置只接受独立的 `KEY=字面量`，支持 `export` 前缀、单引号、无展开的双引号以及行尾注释。重复项按最后一条读取并提示清理。变量展开、命令替换、反引号、条件分支、转义或其他复杂 shell 表达式均标未知，绝不 `source` 或 `eval`。脚本不读取进程环境，也不推定自定义启动环境、其他配置路径或未知组件布局的实际值。

密钥只显示已填写、缺失或未知，不验证有效性。URL、认证信息、查询参数和原始日志均不输出。路径中的符号链接不会被跟随；自定义路径无法安全解析时会报告未知或缺陷。清单仅允许 `runtime.tar.gz`、`native_asr.so`、`native_first_client.sh`、`manager.sh`、`lifecycle` 五项；摘要一致只表示内容符合该清单，不证明清单来源可信。

诊断不运行已有 `status/verify` 脚本：客户端入口会先求值私有配置；原生控制器和判停状态读取会使用独占锁。这里只读取文件与数字头，不与实时链路争抢这些锁，也不执行 `ubus`、`amixer`、OTA 或维护拒绝测试。

## 离线快照

```sh
sh device/speaker_doctor.sh --root /绝对路径/音箱快照
```

`--root` 必须是实际快照目录，不能为 `/`。它不会借用当前电脑的进程、分区、uptime 或磁盘空间。缺少对应证据时报告 `UNKNOWN`，不能把未收集的组件判成音箱未安装。

快照使用音箱绝对路径对应的目录结构，主要输入如下：

```text
音箱快照/
  data/native_first.env
  data/native_first_client.sh
  data/ettsc                         # native-device 才需要
  data/native_asr.sh                 # 按所选组件补齐
  data/native_asr_ctl
  data/native_asr.so
  data/native_endpoint/...           # 已安装的五项文件与 package.sha256
  usr/share/mico/version
  proc/mounts
  proc/uptime
  proc/<PID>/cmdline
  proc/<PID>/status
  proc/<模型PID>/cwd.txt              # 相对 loader 路径需要工作目录证据
  proc/<原生PID>/maps
  tmp/native_first_client.pid
  tmp/native_followup/state
  tmp/xiaomi_native_wake_probe/native-pool.state
  doctor/df-k.txt
```

`doctor/df-k.txt` 保存音箱 `df -Pk /data /tmp` 的输出，保留 `/data` 和 `/tmp` 挂载点两行。该文件缺失时不会对快照所在的 Mac 磁盘执行 `df`。模型按当前运行脚本使用相对路径时，`proc/<模型PID>/cwd.txt` 保存音箱 `readlink /proc/<模型PID>/cwd` 的输出；缺少时标未知，工作目录不符时拒绝认作模型。诊断不会跟随该目录读取外部文件。组件文件需保留可执行位，状态、uptime 与进程快照应来自同一次启动和相近时刻。脚本不把离线结果描述为设备此刻状态。

快照是私有排障资料：配置副本应把已填写的密钥替换为非空占位值，原本为空的保持为空；状态文件可能含对话内容，进程参数也可能含敏感信息。不要公开快照、原始日志、模型或原厂组件。诊断报告本身不输出这些值，但脱敏报告不能让原始快照变成可公开资料。

## 可实际执行的验收步骤

以下说明如何验证诊断工具，不表示已经在音箱执行。仅运行诊断不需要说话；只读诊断与真人语音验收分别记录结果。

1. 在开发机运行隔离回归：

   ```sh
   .venv/bin/python -m unittest discover -s tests -p 'test_speaker_doctor.py' -v
   sh -n device/speaker_doctor.sh
   ```

   预期覆盖三种调用路线、危险配置不执行、敏感信息不输出、陈旧 PID、缺失快照、包摘要和越界清单。测试使用临时目录，不连接音箱或云服务；环境没有 BusyBox 时相应测试单列跳过。

2. 需要设备诊断时，执行本页第一条 SSH 命令并记录退出码。预期没有声音、灯效或服务重启；每项结果带固定标识，最后有 `human_acceptance=not_run`。报告 `UNKNOWN` 时先补齐证据，不能把它改写为通过。

3. 对照实际配置确认路线：独立运行应显示 `native-device`；使用自建 TTS 时显示 `native-server`；自建服务调用模型时显示 `server`。服务地址与任何密钥不应出现在输出。路线不符时核对配置，而不是立即重装。

4. 若启用了 boot1 追问或判停，分别检查组件文件、包摘要与快照项。出现 `FAIL` 时按对应“下一步”排查；仅有进程或快照迹象时仍不能记作真实语音验收通过。

5. 后续另行安排真人用例时，按[人工验收](../../tests/manual_native_first_cases.md)检查原生报时、LLM 完整播放、上下文追问、静默退出与首轮停顿续说。诊断不代替听觉、家居动作、重启、断电或全天稳定性测试。
