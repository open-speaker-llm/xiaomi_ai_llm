# 候选整包发布与离线预检

这个入口用于确认本机候选包的内容、构建来源记录和目标约束。它不联网，不执行包内程序，不安装、升级、回退或重启音箱。现有[首次安装基线与回滚边界](README.md#安装)保持不变。

本阶段完成 M05-A。完整 M05 仍需允许来源版本规则、固件 ABI 验证、空间预算、整包备份、切换事务和失败恢复验证。**包体检查通过不能作为部署许可，也不代表设备、云端或真人对话通过。**

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

未做的验收必须保持未做：真实 ARM 运行、音箱升级与回退、冷启动、云端请求和真人说话。本轮无设备修改，因此没有设备恢复步骤。
