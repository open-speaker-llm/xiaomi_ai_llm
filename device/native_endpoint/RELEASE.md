# 候选整包发布与离线预检

这个入口用于确认本机候选包的内容、构建来源记录和目标约束。它不联网，不执行包内程序，不安装、升级、回退或重启音箱。现有[首次安装基线与回滚边界](README.md#安装)保持不变。

M05-A 的通用离线预检仍不批准部署。另有本文末尾的固定旧版受限维护事务，需私有整机备份和单独验证的目标候选。它不等于任意版本升级器。**包体检查通过不能作为部署许可，也不代表设备、云端或真人对话通过。**

## 构建候选包

准备 [README 中列出的本机 ARM32 运行库及头文件](README.md#构建输入)，在仓库根目录执行：

```sh
python3 device/native_endpoint/build_package.py \
  --assets /绝对路径/已核验的运行库目录 \
  --header /绝对路径/固定版本头文件目录 \
  --output /绝对路径/新的候选包目录
```

输出的父目录必须已存在，输出目录必须不存在或为空，且不能是符号链接。非空目录、旧包和失败残留目录会在编译前拒绝。构建在同一父目录下的新临时目录进行；只有输入、编译产物、归档、清单和发布元数据全部校验后才发布。命令失败返回 `1`，原有输出不被覆盖；正常构建失败会清理自己的临时目录。若构建进程被强制终止，可能遗留 `.endpoint-build-*`，不会据此生成可用输出；保留或人工核对该目录后处理，不把它作为候选包。

构建入口还会先执行 `scripts/embed_native_protocol.py --check`。协议源码与客户端嵌入区域不一致时，在编译和创建候选输出之前拒绝；按错误提示重新生成，再运行主机回归。此检查只处理开发机源码，不要求音箱安装 Python。维护方法见[协议模块](../../docs/reference/native-protocol.md)。

仍然只有五项部署 payload：

```text
runtime.tar.gz
native_asr.so
native_first_client.sh
manager.sh
lifecycle
```

`package.sha256` 仍只包含这五项，不包含旁置的 `release.json`。`runtime/` 和 `build/` 仍是本机构建中间目录。现有安装器不会上传 `release.json`；本阶段应连同候选包在开发机保存它，不能因此声称设备已有发布记录。

## 发布记录

`release.json` 使用固定的第 1 版结构，记录：

- `release_id` 与 `package_manifest_sha256`：绑定当前 `package.sha256` 的字节摘要。
- `source.revision` 与 `source.dirty`：本机 Git revision 和构建开始时是否有未提交改动，包括未跟踪文件。无法读取 Git 时二者均为 `null`。dirty 包可用于审阅，但不能仅凭 revision 重建其未提交源码。
- `inputs.assets`：十项运行库/模型的 SHA256；`assets_manifest_sha256` 为这些条目按文件名排序、固定双空格和 LF 换行后的规范化清单摘要，不是原输入清单的排版摘要。`sherpa_header_sha256` 为固定版本头文件摘要。
- `target`：S12A、boot1、ELF32/小端/ARM、`arm-linux-gnueabihf.2.25` 构建目标，固件 ABI 仍需单独核验。
- `validation`：本机构建和包体校验已完成；`arm_execution`、`device`、`human` 固定为 `not_run`。本机合成夹具测试不能将这些字段改成通过。
- `upgrade`：本阶段固定 `supported=false`、`allowed_source_packages=[]`，不存在可用的跨版本激活规则。

这些是构建机自述的记录，没有数字签名。检查器核验元数据与包及输入摘要的绑定，不证明源码 revision 的真实性、供应链来源或任意固件兼容性。提供的运行库清单也不替代资产来源核验。

## 执行离线检查

在仓库根目录，将候选路径替换为实际本机目录：

```sh
python3 tools/speaker-maintenance/check_native_endpoint_package.py \
  --package /绝对路径/候选包目录
check_rc=$?
printf '预检退出码：%s\n' "$check_rc"
```

标准输出是 JSON 报告，标准错误是中文摘要。可分别重定向保存；报告不包含原始程序、配置、日志或完整输入路径。检查器不读取音箱配置，也不调用 `ssh`、`scp`、`curl`、`git` 或包内管理器。

| 结果/退出码 | 含义 |
|---|---|
| `package=PASS` | 固定五项摘要、两层运行时清单、归档成员和 ARM 标识一致；不是完整 ELF/ABI 验证 |
| `release=PASS` | 元数据结构及包绑定一致；来源仍是无签名的自述 |
| `release=UNKNOWN` | 旧包没有 `release.json`；包体仍可独立检查 |
| `deployment=UNKNOWN`，退出 `2` | 缺少设备证据或活动分区未知；不允许部署 |
| `deployment=BLOCKED`，退出 `1` | 候选损坏、证据非法、目标不匹配，或没有允许升级来源规则 |
| 退出 `64` | 参数错误 |
| 退出 `0` | 仅 `--help`；本阶段预检不会返回部署成功 |

检查拒绝缺项、额外清单路径、重复清单/JSON 键、路径穿越、符号链接、硬链接归档项、特殊文件、额外或重复归档成员、扩展归档头、摘要不符及虚假的验证声明。归档只在内存读取，不解压到磁盘。单个输入文件最多 64 MiB，运行时归档解压上限为 128 MiB，清单与 JSON 最多 32 KiB。确需扩大格式或资源限制时应发布新约束并复验，不能自动放行。

可选 `--device-evidence /绝对路径/设备证据.json` 只读取已保存的脱敏 JSON，不收集或刷新设备信息。字段仅有：`schema_version=1`、`device_model`（`S12A` 或 `other`）、`root_partition`（`boot0`、`boot1` 或 `unknown`）、`installed_package_sha256`（实际设备包清单的 64 位小写摘要）。未知型号记录为 `other`，未知分区记录为 `unknown`；没有真实摘要就不要提供这个参数。它不接受配置、URL、密钥或原始日志。即使这些字段与目标相符，也会因没有已验证升级来源规则返回 `UPGRADE_RULE_UNAVAILABLE`、退出 `1`，不因提供一个文件而批准升级。

本轮没有提供真实设备证据。不要为通过检查编造字段或把历史设备记录当成当前状态。空间、空闲状态、固件 ABI、运行态及备份可恢复性均未在这个入口完成验证。

归档先按原始 512 字节块检查普通文件类型、受限八进制大小、成员数量、数据跨度、零填充和结束块，再交给标准库校验头摘要及名称，并核对解析后的边界。扩展头不会先被解析器消费或隐藏；坏压缩和坏归档均返回结构化拒绝结果。

## 本轮可执行测试

1. 无需音箱、运行库或 Zig，执行本机专项：

   ```sh
   PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
     -s tests -p test_native_endpoint_release.py -v
   ```

   测试使用临时目录、合成 ELF 头和替身编译命令，覆盖格式与故障行为。它不是 ARM 编译或运行证明。预期全部通过；记录测试数量、退出码与任何失败名称。

2. 已有真实候选包时运行上面的离线命令。无设备证据时预期包体及新发布记录为 `PASS`，部署为 `UNKNOWN`、退出 `2`。旧包可以是发布记录 `UNKNOWN`。不要把非零退出码直接当成损坏，查看具体 `code`。

3. 只在临时副本故意损坏一个文件，确认校验拒绝：

   ```sh
   candidate_package=/绝对路径/候选包目录
   test_copy=$(mktemp -d "${TMPDIR:-/tmp}/endpoint-release-test.XXXXXX")
   cp -R "$candidate_package" "$test_copy/corrupt"
   printf '\n# integrity-test\n' >> "$test_copy/corrupt/manager.sh"
   python3 tools/speaker-maintenance/check_native_endpoint_package.py \
     --package "$test_copy/corrupt"
   check_rc=$?
   printf '损坏副本预检退出码：%s（预期 1）\n' "$check_rc"
   ```

   预期 `HASH_MISMATCH`、不允许部署。原候选目录没有修改，无需回滚设备。确认检查对象确为该临时目录后，可删除 `$test_copy`；失败时保留副本和 JSON 结果供排查，不发送运行库或真实私有配置。

4. 使用同一候选目录再次执行构建命令，预期在编译前拒绝非空输出，既有包不变。发布新候选应换一个新目录，不能删除旧包来绕过版本化交付。

以上离线检查不执行真实 ARM 程序、不升级音箱，也不代替冷启动、云端请求和真人说话验收。实际受限维护及恢复按下面的独立流程记录。

## 固定旧日常版的低空间维护事务

`prepare_native_endpoint_upgrade.py` 为已安装日常包生成一次性的设备事务，不连接音箱。允许来源固定为包清单摘要 `43d832ee500ff2058216ad004830657022cb05c31f0cdf271238c15abd2822a3`，还核对旧客户端、SO、ASR 管理器/控制器和 init 摘要。设备执行前再次校验 live 文件、boot1、`uname -m=aarch64`、五项原厂 ABI 摘要、无 LLM/追问忙碌标记及实验恢复标记和空间。这些标记不证明原生首问收音空闲；须安排短暂静默维护窗口，期间可能中断语音对话。不能删除包目录或放松首次安装器校验来替代这些检查。

这里有两种架构：注入原生进程的 `native_asr.so` 和隔离模型运行库为 ELF32 小端 ARM；独立的 `native_asr_ctl` 为 ELF64 小端 AArch64 可执行文件，与设备内核匹配。二者不能互换。生成器的 ELF 标识检查不是实际执行验证；维护者仍须对具体候选完成独立 ARM 验证。

此事务更新整包六项文件、活动客户端/SO、`/data/init.sh`、`/data/native_asr_ctl`，并新增 `/data/speaker_doctor.sh`。默认保留 `native_first.env`；显式使用 `--enable-followup-controls` 时，在原配置字节之后追加两行 `export FOLLOWUP_EXIT_ENABLED=1`、`export FOLLOWUP_RESET_ENABLED=1`，并把私有新配置纳入校验、发布和回退。既有密钥、端侧 TTS、声音等原配置内容不重写，现有 v2 `ettsc` 和 ASR 管理脚本保持不变。`release.json` 仍只留在主机。诊断返回 `2` 表示信息不足，不能拿它替代包摘要、ASR 控制器和判停管理器的健康检查。

### 先准备可恢复的备份

主机备份目录必须包含完整 `data-full.tar.gz`、13 项应用文件及 `verified-manifest.json`。记录的 `device_root` 必须为 `boot1`，`files` 为下列相对路径到 SHA256 的映射，`data_archive_sha256` 为完整私有归档摘要：

```text
native_endpoint/{runtime.tar.gz,native_asr.so,native_first_client.sh,manager.sh,lifecycle,package.sha256}
native_first_client.sh  native_asr.so  native_asr.sh  native_asr_ctl
init.sh  native_first.env  ettsc
```

这些摘要应先与同一台音箱及完整归档核对，不能仅对一份未经设备核对的目录自行生成记录。配置和完整 `/data` 归档含私有数据，保存在本机受限目录，不提交 Git、不公开。生成器重新检查全部文件及归档摘要；设备 preflight 再检查 live 摘要，避免备份之后设备状态已经变化。

### 生成并检查事务

以下为本次已构建候选的输入；实际维护时使用已独立验收的目录，输出必须为新目录：

```sh
python3 tools/speaker-maintenance/prepare_native_endpoint_upgrade.py \
  --backup backups/full-upgrade-20261030 \
  --package /private/tmp/xiaomi-full-upgrade-build-20261030-2gtsmejt/package \
  --extras /private/tmp/xiaomi-full-upgrade-build-20261030-2gtsmejt/extras \
  --expected-candidate 069f8d946a1582c598cd508a4bea18533d67e109bbad9b580c880efd20b0d4d0 \
  --enable-followup-controls \
  --output /private/tmp/新的升级事务目录
```

`extras` 必须含 `init.sh`、`native_asr_ctl`、`speaker_doctor.sh`。输出包括候选包、额外文件、固定前后摘要、启动守卫、恢复辅助函数、`transaction.sh` 和 `plan.json`。示例已按本次用户授权开启两个控制；省略该选项则完全保留原配置。开启时输出含权限 `0600` 的 `extras/native_first.env`，事务目录为 `0700`：它包含原密钥，只能在本机和本设备之间私密传输，不能提交 Git 或公开。工具检查配置语法但不执行、不打印内容。`plan.json` 只记录开关选择及摘要，并给出唯一事务标识、准确设备暂存/备份路径、runner 摘要和空间门槛；不要手改生成的 shell、清单或路径。

本候选开启两个控制后的设备增量门槛为 `/data` **2120 KiB**、暂存完成后 `/tmp` 额外 **38312 KiB**、`MemAvailable` **71080 KiB**。预算含持久小文件恢复集、新小文件、运行包增长、事务文件余量、1 MiB data 预留、旧运行包临时副本和新运行库展开空间；以最终生成计划和设备实时检查为准，不能据历史 `df` 结果直接执行。

上传事务目录内容到 `plan.json.device_stage` 后，先比对设备 `transaction.sh` 的 SHA256 与 `plan.json.runner_sha256`，再在音箱执行：

```sh
# STAGE 必须使用 plan.json 中实际生成的绝对路径。
STAGE=/tmp/endpoint-upgrade-stage-实际事务标识
sh "$STAGE/transaction.sh" preflight
```

preflight 只读检查，不停止服务或建立持久备份。返回 `0` 并输出 `UPGRADE_PREFLIGHT_OK` 后，在已授权的空闲维护窗口执行：

```sh
sh "$STAGE/transaction.sh" apply
```

需要抵抗 SSH 连接中断时，可由维护端将该命令按既有受控方式后台运行并保存退出状态与日志；“后台进程已启动”不能作为升级成功。只有出现 `UPGRADE_COMMITTED`、持久状态为 `COMMITTED`，且活动摘要和 ASR/判停状态都通过，才记录这次部署完成。人声和冷启动验收另记，不由部署脚本代做。

### 低空间时的保护与恢复

完整新旧 10 MiB 运行包无法同时持久保存在当前 `/data`。本事务采用以下顺序：

1. 在设备持久备份小文件、私有配置及恢复程序，同时在 `/tmp` 校验保留旧运行包。旧完整归档已在主机保留并校验。
2. 原子安装启动守卫并同步，写入 `APPLYING` 并再次同步。未提交事务在重启后不启动自定义客户端或判停；原厂启动链保持原生小爱服务。
3. 先停止判停 supervisor/pool，再向 PID 文件及精确命令匹配的客户端发 TERM，以 0.5 秒间隔最多检查 60 次（进程扫描耗时另计）。固定旧版的 TERM 清理会返回 FIFO 主循环，因此只有同命令的 hook watchdog 等子进程全部退出、PID 文件和事件 FIFO 均清理完成、原父进程命令及启动标识仍一致时，才最终结束该父进程并确认退出；条件未满足则拒绝替换。随后停止原生写入者、归档旧指令/客户端日志，才原位替换唯一的大运行包。小文件以校验后的临时副本和 rename 发布，包清单最后更新。
4. 核对候选包和活动副本，启动并检查 ASR/判停，持久提交后发布正式新版 init。提交末段失败时先重新安装并同步守卫，再尝试恢复，避免把恢复拒绝误报成已经安全回退。

普通写入或启动失败时，事务使用仍在 `/tmp` 的旧运行包自动恢复，输出 `UPGRADE_ROLLED_BACK`。**突然断电并丢失 `/tmp` 时，只保证未提交事务不启动混版自定义链路；不会自动恢复旧判停或 LLM。** 此时必须从主机备份补回旧运行包，才能完整恢复。

若出现 `UPGRADE_RECOVERY_REQUIRED`，不要删包、旧备份或 busy 标志来强行继续。守卫保持原生降级，需要查明原因后恢复。若输出 `UPGRADE_BOOT_GUARD_UNCONFIRMED`，表示连守卫重新安装都失败，不能宣称下次开机安全，需立即人工维护。

仍有原 `/tmp` 暂存时，在设备执行以下命令；`BACKUP` 使用 `plan.json.device_backup`：

```sh
BACKUP=/data/endpoint-upgrade-实际事务标识
STAGE=/tmp/endpoint-upgrade-stage-实际事务标识
sh "$BACKUP/restore.sh" restore "$STAGE/old-runtime.tar.gz"
```

如果 `/tmp` 已清空，先从开发机上传已校验备份中的旧运行包：

```sh
HOST=root@192.168.8.152
scp -O -oHostKeyAlgorithms=+ssh-rsa -oPubkeyAcceptedAlgorithms=+ssh-rsa \
  backups/full-upgrade-20261030/native_endpoint/runtime.tar.gz \
  "$HOST:/tmp/endpoint-old-runtime-实际事务标识.tar.gz"
```

`HOST` 使用本次现场核验的设备地址；地址变化时先核验设备身份，不依赖未配置的 SSH 别名。然后在设备执行：

```sh
BACKUP=/data/endpoint-upgrade-实际事务标识
sh "$BACKUP/restore.sh" restore /tmp/endpoint-old-runtime-实际事务标识.tar.gz
```

恢复脚本校验旧运行包及持久小文件备份，恢复匹配整包、客户端、SO、控制器、旧配置和旧 init，并撤掉原先不存在且摘要仍匹配本次候选的 doctor。它保留既有 v2 `ettsc`。私有配置只接受本次 before 或 after 摘要：显式开启的两个控制可以随事务回退，其他用户改动则拒绝覆盖，先保留修改再安排恢复，不悄悄丢掉新密钥。成功标记为 `ROLLED_BACK`。手动恢复进入写入阶段后也受退出守卫保护；末段失败会重装守卫，不递归执行另一次恢复。持久备份不要立即删除，它仍是恢复凭据。

### 本机故障测试

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s tests -p test_native_endpoint_upgrade.py -v
```

测试在临时目录中模拟 `/data`、固件、服务命令和空间；覆盖成功与手动回退、源/候选/备份不符、缺空间、忙碌、符号链接、大包写入中断、小文件 rename 失败、启动失败、提交末段失败、守卫安装失败，以及强杀事务并清空模拟 `/tmp` 后从主机副本恢复。进程用例使用本机自建的旧版 TERM trap/FIFO 行为，检查延迟清理、watchdog 残留、未清理 FIFO、父进程身份变化和 `/proc` 读取期间正常退出。它不连接设备，也不能代替真实闪存断电、原厂启动链、ARM 执行和真人语音验收。
