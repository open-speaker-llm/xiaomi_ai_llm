# M03 分段延迟计时实际测试

## 版本与范围

基于 `d66b630`，对应本地分支 `codex/S3-m03-latency-isolated` 的步骤 A 提交（`feat(llm): 增加 M03 分段延迟计时与 [LATENCY] 汇总`）；以 `git log -1 --oneline` 核对最终提交。本步骤只做观测，保持现有切句、串行合成、FIFO 顺序播放、重试、超时和原生兜底行为，不修改 `device/lib/`、生成块或服务端。

真人与设备验收：**未执行**。主机自动化不代表音箱播放通过。

## 准备

1. 开发机进入上述本地分支的仓库目录。备份既有客户端和 `/data/ettsc`，保留私有配置原文件；本步骤不覆盖或重写它。
2. 核对 SSH 别名 `xiaomi` 对应自己的音箱，确认当前 boot0/boot1 与所用固件；不要复用文档中的历史地址。
3. 确认既有配置使用 `LLM_PIPELINE=native`、`TTS_ENGINE=device`、`DEVICE_TTS_STREAM=1`。不符合时不会生成计时数据。
4. 客户端默认 `LATENCY_TRACE_ENABLED=1`、`LATENCY_LOG_MAX_LINES=200`、`ETTSC_TIMING=0`；未配置这三项也可使用。非法值只报一次固定警告后使用默认值。
5. 如需设备验证，空闲时通过项目既有维护流程替换客户端和匹配架构的新 ettsc；本轮没有自动部署。`cargo test` 产物为主机程序，不能上传到音箱充当 ARM 二进制。ettsc 构建见 [组件说明](../../device/ettsc/README.md)。
6. 在开发机手动上传新增统计脚本：

   ```sh
   scp -O device/latency_summary.sh xiaomi:/data/latency_summary.sh
   ```

## 主机自动化

全部使用假 key、临时 marks、假模型和假 ettsc，不读取真实配置或请求外部服务。

```sh
python3 -m unittest tests.test_latency_trace tests.test_native_client_failure_paths -v
./scripts/run_tests.sh
(cd device/ettsc && cargo test --locked)
sh -n device/latency_summary.sh
python3 scripts/embed_native_protocol.py --check
python3 scripts/embed_native_web.py --check
git diff --check
```

完整脚本优先用项目 `.venv/bin/python`；独立工作树无虚拟环境时，显式设置 `PYTHON` 指向已有环境，不安装新依赖。Rust 构建输出可以用 `CARGO_TARGET_DIR=/tmp/m03-ettsc-target` 放到 `/tmp`。本机没有 BusyBox 时，新增 ash 和 BusyBox awk 用例跳过并单列，不当作兼容性实测。

覆盖：marks 缺失/时序倒置、精确阶段差值、脱敏、默认 200 行截断、配置边界和回退、百分位最近秩、开关前后 PCM/历史/原有输出一致、两轮追问不继承唤醒数据，以及 `[T]` 不触发 `[!]` 失败判定。既有失败路径回归继续覆盖下载、播放器、LLM 不完整回答和历史保护。

主机验证记录（2026-11-04，macOS，已有 Python 虚拟环境；无 BusyBox）：

| 检查 | 结果 |
|---|---|
| 干净 `d66b630` 基线 | 462 个，458 通过、4 跳过；无失败 |
| 指定专项复测 | 29 个，27 通过、2 跳过；无失败；最终完整回归再次覆盖所有专项 |
| 最终完整回归（最终代码、串行） | 475 个，469 通过、6 跳过；无失败，Shell 语法检查通过 |
| Rust `cargo test --locked` | 12 个通过（5 个单元、7 个解码回归） |
| 两个嵌入 `--check` | 通过，生成块与基线逐字节一致 |
| 新脚本、客户端、doctor 的 `sh -n`；`git diff --check` | 通过 |

首次完整改后回归为 475 个，2 失败、6 跳过：`HttpPlaybackFailureTest.test_http_502_and_empty_wav_fall_back_once`（header，transport/player=137）及 `test_successful_http_audio_does_not_repeat_via_native`（player=137）。前者在初次基线运行也曾失败；HTTP 播放函数与基线逐字节一致。两者均在后续指定专项中通过，记录为既有播放测试的间歇失败，未修改播放逻辑或放宽断言。第二次完整回归为 475 个，HTTP 两项通过，但未修改的 `NativeLifecycleTest.test_protected_journal_full_refuses_before_loading_or_arming` 出现原生测试程序等待 3 秒超时（1 error、6 跳过）。扩展播放专项 45 个中，M03 和逐句恢复用例通过，HTTP 成功播放用例又出现一次 player=137。保留这些失败记录，不修改限时、测试断言或范围外代码。最终对全部代码串行运行 `./scripts/run_tests.sh`：475 个、6 跳过、无失败，243.338 秒；此前错误均保留，不将单次通过描述为稳定性结论。

跳过项单列：新增 `LatencyTraceTest.test_busybox_report`、`LatencySummaryTest.test_busybox_summary`；原有协议 BusyBox Unicode 契约、搜索 BusyBox 重试/垫话、doctor BusyBox ash 三项；原有 Linux CPU-signal 强制停止一项（macOS）。这些均未执行，不能视为 BusyBox/ARM 实测通过。真机项目保持未执行。

## boot0 与 boot1 分别执行（均未执行）

1. 空闲时按既有启动方式运行更新后的客户端。观察：

   ```sh
   ssh xiaomi 'tail -f /tmp/native_first_client.log | grep -E "\[LATENCY\]|\[TTS\]|\[LLM-NATIVE\]"'
   ```

   说“小爱同学，讲个笑话”。预期播放与升级前相同，轮末恰好 1 行 `[LATENCY]`，包含 `wake→route/route→req/ttft/split1/tts1/commit1`，不含问答原文、密钥或 URL。字段单位为秒，口径见[诊断参考](../reference/diagnostics.md#m03-分段计时)。失败轮次允许缺失阶段为 `-`，不能用零填充。

2. 连续对话至少 30 轮，再执行：

   ```sh
   ssh xiaomi 'wc -l /tmp/native_first_latency.log; sh /data/latency_summary.sh'
   ```

   预期日志不超过 200 行，统计输出各字段有效样本数和 P50/P90/max。为验证默认上限，可继续累计超过 200 轮后检查；30 轮只能检查当前行数，不能单独证明截断正确。日志仅写 `/tmp`，重启会消失。纯追问 `wake→route` 与 `wake→commit1` 为 `-`，不能沿用上一轮唤醒。

3. 搜索关闭或无垫话的 5 轮检查阶段之和：`wake→route + route→req + ttft + split1 + tts1 + commit1` 与 `wake→commit1` 差不超过 50 ms。存在缺失字段、队首原生兜底、垫话时单列记录，不能使用此加和校验。默认 ttft 仍含规划/工具耗时；本步骤没有新增搜索打点，`plan/search/filler` 通常为 `-`。

4. 如需 ettsc 细分，在自己维护的配置中启用 `ETTSC_TIMING=1` 并按既有方式重启客户端；不要替换整个私有配置。说一句话后在音箱私下检查 `/tmp/native_first_stream/0001.attempt-1.log`。预期有 `[T] tcp_ms=… tls_ws_ms=… first_audio_ms=… turn_end_ms=…`，播放成功；该行不带 `[!]`。可直接执行 `ETTSC_TIMING=1 /data/ettsc probe` 只观察握手，后两个字段为 `-`。这两种操作都实际联网，保持人工未执行状态。

5. 在播放中再次物理唤醒，确认既有打断和下一轮播放行为与升级前一致，不混入上一轮 marks。分别验证普通回答、搜索垫话、单句合成失败后的既有重试和原生补播；不修改重试策略以制造“通过”。

6. 校验关闭开关：手动设置 `LATENCY_TRACE_ENABLED=0` 并按既有方式重启客户端，重复同一组问题。预期没有新增 `[LATENCY]` 行和 marks 写入，声音、句序、重试和历史逻辑保持一致；已有日志不自动清空。

## 声学校准（未执行）

固定手机位置和音箱音量，录制至少 5 轮无垫话的回答，保留唤醒词末尾和首个回答语音波形。先通过同步录屏/音频或对齐事件，测量 `handle_wakeup` 入口相对唤醒词末尾的时间差；再从波形计算唤醒词末尾至实际首声的时长，用同一参考点减去 `wake→commit1`。只用这两段时长相减而未对齐参考点，会混入唤醒事件处理误差。

| 轮次 | 分区/音量 | 唤醒词末尾→首声 | 唤醒词末尾→wake 入口 | wake→commit1 | commit1→声学偏移 | 测量误差 |
|---|---|---|---|---|---|---|
| 1–5 | 未执行 | 未执行 | 未执行 | 未执行 | 未执行 | 未执行 |

不预设固定补偿值，不把 FIFO 提交称为声学首声；有垫话的轮次分别记录垫话与答案首声。私人录音不提交仓库。

## 失败记录

记录提交、分区/固件、上述三项计时配置、操作编号、退出码、脱敏 `[LATENCY]` 行、现象与预期差异。区分自动化失败、环境跳过、链路失败和缺失打点。原始对话、真实 key、URL query、设备标识、完整客户端/ettsc 日志与录音只在私有环境保存；公开记录仅取脱敏时间字段。

## 恢复

先将 `LATENCY_TRACE_ENABLED=0`、`ETTSC_TIMING=0` 并按既有方式重启客户端，保留原有其他配置。若仍异常，在空闲时按已有维护流程恢复备份客户端和 ettsc。统计脚本不在运行链路内，可以保留；不需要清空历史、修改重试参数或改动 `device/lib/`。本步骤不更新 `docs/status.md`。
