# 首轮判停实现与实验工具

日常使用从[项目原理](../../docs/concepts/native-first.md#首轮收音与结果提交)、[正式运行包](../native_endpoint/README.md)和[运维手册](../../docs/runbooks/operations.md#boot1-首轮本地判停)进入。按阶段形成的研究记录已归入现有文档架构的[历史目录](../../docs/history/first-turn-endpoint/README.md)，其中“未接入、已恢复旧版”等描述仅对应当次实验，不能当作当前部署状态。

本目录保留共用底层实现和可复现的独立实验代码。虽然目录名为 probe，下表前四组已是日常包的构建依赖，不可作为“旧探针”整体删除。

| 文件组 | 职责 |
|---|---|
| `native_wake_probe.c`、`first_endpoint.h`、`native_wake_state.h` | 原生回调关联、同轮请求改写、结束候选复核；组合构建现有 native_asr |
| `native_wake_pool.c`、`native_resident_session.c`、`native_pool*.h` | 常驻模型/控制器、多轮身份、原生进程换代、空闲续期与恢复 |
| `native_route.h`、`native_denials.h`、`native_route_restore.sh` 等 | 完成记录、取消与拒绝保留；安装/回滚的日志归档与原生恢复 |
| `neural_pool.c`、`neural_*.[ch]` | 模型流式推理、逐轮重置、有界积压、资源限制和旧内核取时 |
| `build_native_wake.sh`、`build_neural_bench.sh` | 日常包使用的 ARM 构建入口，后者校验固定版本 C API 头文件 |
| `test_*.c`、`audit_turn_trace.py` | 独立设备测试与时间线审计，配合 `tests/test_*.py` |
| `run*.sh`、`protocol_probe.c`、`active_*`、`shadow_*`、`bench_vad.c` 等 | 分阶段观察、回放或主动实验；不是日常启动脚本 |

## 开发与验证

在仓库根目录执行 `sh scripts/run_tests.sh`；分层验证要求见[TESTING.md](../../TESTING.md)。日常构建统一通过 `device/native_endpoint/build_package.py`，避免误把旧协议试验 SO 当作生产 native_asr。第三方模型/运行库、私有音频、日志和构建产物都留在忽略目录，不提交。

实验工具仅适配已校验的 S12A boot1 ROM 1.76.54。它们会建立临时 bind mount、重启原生服务或在明确的试验会话内改变识别请求，具体边界、现场提示和恢复步骤须读相应[历史实验记录](../../docs/history/first-turn-endpoint/README.md)。不要在正在运行的日常判停服务上直接叠加。`CAPTURE_READY` 才表示某轮采样可开始，进程已启动不等于可说测试句。

## 被动采样入口（专项诊断）

`run.sh` 是早期被动工具，不修改 VAD 参数、不改写识别请求、不主动调用 LLM。构建 `sh device/pcm_tap/build.sh /tmp/endpoint-build`，将 `xaudio_pcm_tap.so`、`capture_pcm` 和 `run.sh` 放到设备专用 `/tmp/xiaomi_endpoint_probe/`，以本次产物 SHA256 配置 `EXPECTED_TAP_SHA256` 与 `EXPECTED_CAPTURE_SHA256`。使用前需设备空闲、确认与现有服务不冲突并完成对应备份。

`setup` 临时叠加 PCM tap、重启一次 PNS，并在五分钟后自动恢复；显式 `restore` 只恢复仍与本工具哈希匹配的挂载。`capture 20` 才采样并保存短 WAV 与时间线，setup 本身只保留短环形缓冲。输出可能含用户语音及文本，保持私有。麦克风静音、过载、生产者替换或停滞时必须判失败，不能使用残缺样本宣称识别完整。恢复后核对 `native_asr.sh status`、原 PNS 哈希及临时库已卸载。
