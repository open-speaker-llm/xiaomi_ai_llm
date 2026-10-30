# 第三轮实际测试：会话、协议与候选包维护

适用范围：在 `2156821` 基线上增加换话题、受限历史缓存、纯协议模块、异常进程恢复和 M05-A 候选预检的这一轮源码。执行时用 `git rev-parse HEAD` 记录具体提交；设备功能只有部署对应候选包后才存在。验证结果见[状态页](../status.md)，后续任务见[产品与架构路线](../plans/2026-10-30-product-architecture-roadmap.md)。

**真人音箱验收未执行，可以后再做。** 下述开发机测试现在即可运行，不需要 SSH、云端密钥或实际说话；不会触发家居动作。设备步骤须先满足匹配固件、候选包兼容和恢复条件，不能只把最新脚本覆盖到已有判停包上。

## 一、开发机检查

在仓库根目录执行；默认使用项目虚拟环境：

```sh
git rev-parse HEAD
.venv/bin/python scripts/embed_native_protocol.py --check
./scripts/run_tests.sh
```

预期：嵌入检查报告 `Native protocol embed is current.`，整套回归及 Shell 语法检查通过。记录总数、跳过项和退出码，BusyBox 不可用或平台不适用时不能记为通过。`--check` 不改文件；若报告漂移，由开发者修改协议源模块后重新生成、审查差异并回归，不在音箱上运行生成器。

本轮最终主机结果为 396 项：393 通过、3 项跳过。跳过项分别是 Linux CPU 信号平台限制、诊断 BusyBox 兼容和协议 BusyBox 兼容；没有把这些项目计为通过。

只检查本轮四个领域时：

```sh
.venv/bin/python -m unittest \
  tests.test_native_session \
  tests.test_native_protocol \
  tests.test_native_process_liveness \
  tests.test_native_endpoint_release -v
```

| 检查 | 应证明的行为 | 不能据此宣称 |
|---|---|---|
| 会话 | 新 session、精确控制词、确认失败不继续监听、完整问答对和缓存上限、外来文件保护 | 实际音箱已经听懂或播出确认 |
| 协议 | JSON 引号/换行/控制字节合法，中文和代理对解码，SSE 逐片输出，错误/截断不当完成，源码与单文件产物一致 | 云服务最新协议或设备 BusyBox 已兼容 |
| 进程恢复 | 真实退出子进程不再占用；检查不回收它；未知状态保留所有权；恢复不删旧路由拒绝记录 | 所有 PID 复用情形或目标固件 ABI 已验证 |
| 候选包 | 摘要、归档、元数据和构建输出边界；损坏拒绝；证据不足不批准部署 | 合成 ELF 夹具已证明真实 ARM 执行 |

原生恢复另有 ARM32 共享库、ARM64 控制器及首轮判停相关程序的本机交叉编译检查；这不是设备执行。若需要自己重跑，需已安装 Zig，在仓库根目录选择新的开发机临时输出目录：

```sh
sh device/native_asr/build.sh /tmp/xiaomi-session-asr-build
sh device/endpoint_probe/build_native_wake.sh /tmp/xiaomi-session-wake-build
```

不要把这两个独立输出目录当成完整部署包。构建失败记录编译器输出，保留当前设备版本。

## 二、候选包预检

有本机完整候选包时，在仓库根目录执行：

```sh
python3 tools/speaker-maintenance/check_native_endpoint_package.py \
  --package /绝对路径/候选包目录
check_rc=$?
printf '预检退出码：%s\n' "$check_rc"
```

预期结果：

- 新格式有效包：`package=PASS`、`release=PASS`；未提供设备证据时 `deployment=UNKNOWN`、退出 `2`。
- 旧包没有 `release.json` 时，来源记录为 `UNKNOWN`；仍需单独检查包体。
- 损坏包：`package=FAIL`、`deployment=BLOCKED`、退出 `1`。
- 即使离线证据记录 S12A/boot1，也因本阶段没有允许升级来源规则而 `BLOCKED`，不应反复修改证据来求通过。

要验证损坏检测，只改临时副本：

```sh
candidate_package=/绝对路径/候选包目录
test_copy=$(mktemp -d "${TMPDIR:-/tmp}/endpoint-release-test.XXXXXX")
cp -R "$candidate_package" "$test_copy/corrupt"
printf '\n# integrity-test\n' >> "$test_copy/corrupt/manager.sh"
python3 tools/speaker-maintenance/check_native_endpoint_package.py \
  --package "$test_copy/corrupt"
check_rc=$?
printf '损坏副本退出码：%s（预期 1）\n' "$check_rc"
```

预期 `HASH_MISMATCH`；原候选包和音箱均不变。核对 `$test_copy` 确为新建测试目录后再删除，失败时先保存报告。完整构建前置条件、只读设备证据格式和非空输出保护见[发布参考](../../device/native_endpoint/RELEASE.md)。没有本机候选包时跳过本节，第一节的合成包专项仍可运行。

## 三、以后在音箱上测试换话题

前置条件：对应客户端及依赖已通过适用的整包部署流程；先记录活动分区、组件摘要、有效配置及完整恢复点。已有判停组合包仍受旧安装基线限制，本轮没有提供可直接升级它的新安装器。使用[只读诊断](../reference/diagnostics.md)核对环境，先跑通普通首问与追问。

协议基础对照可先问“请解释欲穷千里目，更上一层楼，分两句话说”，核对完整问题、两句声音及随后追问，不应把 `\\u4f60` 这类编码当作正文播报。真人问句不能强制云端采用某种转义帧；中文转义、多行文本、emoji 和坏流的确定性验证使用第一节专项，不能只凭一次正常回答证明全部协议边界通过。

在音箱 `/data/native_first.env` 中保留自己的密钥与模型配置，只调整：

```sh
FOLLOWUP_RESET_ENABLED=1
```

它与 `FOLLOWUP_EXIT_ENABLED` 相互独立。按对应安装包的维护流程重启客户端后生效；不要重跑基础追问安装器覆盖组合库。默认值为 `0`，关闭时“换个话题”仍作为普通聊天输入。

1. 唤醒后用实际配置的 LLM 触发词说：“这轮临时口令是海棠，请记住。”回答结束、绿灯续听时说：“刚才的临时口令是什么？”预期同一会话可以引用前文。
2. 下一次追问窗口说：“换个话题。”预期播出固定确认“好，我们换个话题。你想聊什么？”，确认播完后才再次收听；该控制词不送 LLM，不新增问答历史。
3. 继续说：“用一句话介绍月球。”预期正常回答且使用新 session。日志中出现 `[SESSION] 已切换新会话`，之后的请求不再带旧 session 历史；模型偶然说对某个词不能作为历史隔离的证据。
4. 对“重新开始”重复测试。连续两次换题也应产生不同 session，之后仍可问答。如果原配置启用了 `SUPPRESS_DUP_SECONDS`，换题后第一问重复上一会话的问题也应得到回答；后续去重策略保持原配置。
5. 追问时说“不要重新开始”“解释一下‘换个话题’是什么意思”。预期按普通问题处理，不播固定确认。精确首问“重新开始”也不触发追问控制。
6. boot1 输入补全场景：追问时先说“帮我查一下”，听到补充提示后说“换个话题”。预期丢弃未完成的旧输入，确认后开启新 session，而不是把两段拼成模型问题。
7. 安静等待退出，再正常唤醒并问时间；还需按既有 B3 用例验证播放期间仍可唤醒小爱，保持原来的并行家控行为。

另行覆盖 boot1 `native_live`、`native_multirounds` 和 boot0 录音路线。每条只记录实际执行过的模式，不用一种模式的结果代替另一种。确认播报失败后的清理先用第一节故障注入测试验证；真人验收时若自然遇到此失败，预期不继续开麦、回到待机，下次正常唤醒可用，不要求为测试破坏真实云端配置。

恢复：将 `FOLLOWUP_RESET_ENABLED=0` 并按当前包流程重启客户端即可关闭换题控制。若下一轮不可用，保存脱敏日志和版本，按已验证的完整恢复点回退；不临时覆盖单个客户端或共享库。

## 四、以后在音箱上检查历史缓存

仅适用于 `LLM_PIPELINE=native`；可选服务器的存储策略独立。默认配置为最近 `6` 轮、最多 `16` 个受管 session、每个文件 `65536` 字节。新文件位于 `LLM_HISTORY_DIR/.native_first_history_v1/`，默认完整目录为 `/tmp/native_first_llm_hist/.native_first_history_v1/`。不会自动导入或清理根目录中的旧格式历史。

1. 在同一 session 正常完成至少 8 轮问答，每轮都等回答结束；只读检查当前受管文件中问答对数不超过 `6`，没有悬空 user 行，文件不超过默认字节上限。
2. 连续新唤醒或换题，建立超过 `16` 个成功问答 session；完整有效的受管历史应只保留最新限制内的 session，当前 session 不被淘汰。外来、损坏、符号链接和旧格式文件保留，不计入这个可清理集合。
3. 用超过缓存字节上限的一轮做压力测试时，记录提示和下一轮行为。实现拒绝保存过大的一对并结束追问，不截断半个 JSON 或保留只有 user 的记录；不要把“声音播完”当成“已成功保存上下文”。普通日常问句无需构造这种压力输入。

只查看大小和行数而不输出对话正文，在音箱执行：

```sh
history_store=/tmp/native_first_llm_hist/.native_first_history_v1
for history_file in "$history_store"/h_*; do
    [ -f "$history_file" ] && [ ! -L "$history_file" ] || continue
    wc -c -l "$history_file"
done
```

自定义过 `LLM_HISTORY_DIR` 时替换 `history_store`。正常非空受管文件的行数为 `1 + 2 × 轮数`；文件头占一行。此命令只检查尺寸与行数，格式完整性以专项测试及实际请求为准。

换题只让后续请求停止引用旧上下文；旧文件按保留策略处理，服务器旧 session 也不会被远程删除。没有需求时不手工清理历史目录；配置调错先恢复上述默认值并按包流程重启。该功能不是持久长期记忆，也不是安全擦除工具。

## 五、如何记录结果

每项记录：源码提交、安装包摘要、平台/分区、配置模式、操作步骤、预期与实际、通过/失败/未执行，以及是否已恢复。音频是否完整、确认后是否才开麦、实际家电动作必须由人确认；只上传脱敏失败片段，不上传密钥、完整私人对话、模型资产或固件。

本轮没有执行音箱升级、重启、故障注入或真实家居控制，所以没有已发生的设备状态需要回滚。未执行的用例继续保留为未执行，不用主机通过数覆盖它们。
