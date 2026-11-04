# 联网搜索重试、垫话和未联网兜底验收

适用版本：`b196f96` 基线上的 C1 本地提交，提交标题为 `fix(web): 判断失败先播“搜索中，请稍等。”再重试，配置问题按 off 处理`。用 `git log -1 --format='%h %s'` 记录实际提交。只覆盖失败分类、配置降级、重试、垫话、预算、历史与兜底；请求体改走文件、抓取截断、PCM 缓存及搜索阶段打点均不在此版本内。

## 主机验证

准备：使用仓库现有 Python 环境、curl 和编译工具，不新增依赖；测试中的 key 都是假值。仓库根目录执行：

```sh
python3 scripts/embed_native_web.py --check
python3 scripts/embed_native_protocol.py --check
python3 -m unittest tests.test_native_web -v
python3 -m unittest tests.test_native_client_failure_paths tests.test_shell_config -v
./scripts/run_tests.sh
sh -n device/lib/native_web.sh device/native_first_client.sh device/speaker_doctor.sh
git diff --check
```

修改前基线：443 项，440 通过、3 跳过，嵌入和 Shell 语法通过；输出保存在开发机 `/tmp/baseline_tests.log`。修改后结果见本文末尾。

专项覆盖：真实本机 HTTP 及 curl 返回码 0/10/11/12、401/402/403、408/429/5xx、400/404/413/422、坏 JSON/NUL/超大响应；按次数返回错误的规划和工具桩、独立重试次数、429 退避、总预算及重试的 0.5 秒预留；配置 warning 只记录一次、别名、非法新增配置恢复默认；故障注入；SSE 在重试请求仍进行时可被读取；真实客户端生产者管道剥离垫话、ttft 跳过垫话、最终传输失败补播一次、部分答案不补播、鉴权/余额/固定失败提示不写历史。

主机测试中的合成和播放使用桩；不能证明设备上的声音、EdgeTTS 耗时、BusyBox 管道刷新或 boot0/boot1 行为。

## 真机准备（全部未执行）

1. 在 S12A 的 boot0 和 boot1 分别执行下表，记录系统、固件、提交、curl/BusyBox 版本及 TTS 路径。不要从另一系统的结果推定通过。
2. 音箱空闲时按[客户端维护流程](../runbooks/operations.md#客户端)备份并成组更新 `device/native_first_client.sh` 对应的活动客户端 `/data/native_first_client.sh`、安装包内客户端与 `package.sha256`，确认当前安装入口再操作。设备不需要源模块或 Python 生成器；此提交未部署到设备，也未修改真实配置。
3. 由机主保留私有配置备份，再在 `/data/native_first.env` 中调整下表测试开关；同名配置只保留一个有效赋值，空闲时重启客户端。不要将私有配置、key、完整对话或录音提交仓库。
4. 默认 `LLM_WEB_PLAN_TIMEOUT=4`、`LLM_WEB_TIMEOUT=8`、`LLM_WEB_RETRIES=1`、`LLM_WEB_RETRY_BACKOFF_MS=500`、`LLM_WEB_TOTAL_BUDGET=12`、`LLM_WEB_FILLER="搜索中，请稍等。"`、`LLM_WEB_FALLBACK=answer`。已有配置显式写了 8 秒规划超时的，升级不覆盖它；按此初始阈值验收时由机主临时设为 4。
5. 垫话验收需要 `TTS_ENGINE=device`、`DEVICE_TTS_STREAM=1`。整段路径（包括 server TTS）应无垫话，仍需验证错误提示与历史。正常测试应可调用最终回答与 TTS。

## 逐项步骤与预期

以下每一项在 boot0、boot1 的状态均为**未执行**。

| 用例 | 操作 | 预期 |
|---|---|---|
| 规划超时 | `LLM_WEB_TEST_FAULT=plan_timeout`，问“今天上海天气怎么样” | 流式先听到一次“搜索中，请稍等。”，随后按未联网口径回答；日志 `plan_try=2 plan_err=timeout filler=1 fallback=answer`。垫话出声 ≤ 规划超时 + 1.5 秒（初始阈值，待实测） |
| 规划 429 | `LLM_WEB_TEST_FAULT=plan_429`，问“讲个笑话” | 仅重试一次，间隔 ≥1 秒；一次垫话后正常回答 |
| 规划鉴权/余额 | 分别设 `plan_401`、`plan_403`、`plan_402`，问“你好” | 不重试、不播垫话；401/403 播“大模型密钥无效，请检查配置。”，402 播“大模型账户余额不足，请充值后再试。”；不发最终请求，历史不增加 |
| 工具临时故障 | `LLM_WEB_TEST_FAULT=tool_503`，明确要求联网查新闻 | 一次垫话，`tool_try=2 tool_err=503 fallback=answer`，回答说明没查到最新信息 |
| 工具鉴权/余额 | 分别设 `tool_401`、`tool_402`、`tool_403`，明确要求搜索 | `tool_try=1`，日志有 warning；继续未联网回答，不把工具 key 的错误当聊天 key 错误 |
| 总预算 | 分别用规划超时、`tool_timeout` 触发，保持 12 秒总预算 | 联网阶段到最终请求开始 ≤12.5 秒，汇总 `budget_left_ms ≥ -500`；预算不足不再重试；最终回答仍独立受 `LLM_DIRECT_TIMEOUT` 控制 |
| 配置降级 | 清空测试故障；机主临时使用第三方聊天地址且不给搜索 key，连续问 10 个闲聊题；另分别验证缺 jsonfilter、非法超时、非法模式 | 启动一次 `[WEB] warning … treating as off`；不规划、不垫话，10 题仍可普通回答。不要删除系统 jsonfilter，可在隔离测试环境模拟缺失 |
| 模式别名 | `LLM_WEB_SEARCH=on`，其余保持有效 | 启动按 auto 记录，实时问题可搜索；主机已覆盖 1/true/yes |
| 非重试错误 | 主机桩返回坏规划 JSON、finish_reason=length、HTTP 400，或空结果；设备自然遇到同类错误时记录 | 不重试模型输出错误/HTTP 400/空结果，直接未联网回答；不调用不合法工具地址 |
| 最终回答失败 | 清空注入；在隔离故障环境令最终 LLM 传输失败且无回答文本 | 本轮走过规划时，流式垫话后最多补播一次“暂时无法联网查询，请稍后再试。”；整段路径无垫话；LED 报错、历史不变。仅有部分回答或 TTS 故障时不补播该提示 |
| 历史干净 | 完成上述用例后仅统计历史中固定提示与垫话次数 | `搜索中，请稍等。`、`暂时无法联网查询`、鉴权/余额提示都为 0；成功答案的历史不带外部证据和垫话 |
| 空垫话/整段路径 | 分别设 `LLM_WEB_FILLER=`、`DEVICE_TTS_STREAM=0`，重复规划超时 | 无垫话；仍按次数/预算重试并未联网回答；不会把等待提示混入文本 |
| 固定失败回滚 | `LLM_WEB_FALLBACK=fail`，注入规划超时 | 重试后只输出固定失败提示，不发最终回答，历史不增加；流式垫话仍最多一次 |
| 正常回归 | 清空故障，分别闲聊 10 题、明确搜索 3 题、上下文追问及原生家控/天气/报时 | 正常回答、来源支持结论、路由和连续追问不退化；首声变化处于规划耗时波动范围，并记录实际值 |

查看安全汇总：在音箱日志 `/tmp/native_first_client.log` 查找 `[WEB] action=`。每行包含 `plan_ms/plan_try/plan_err/tool_ms/tool_try/tool_err/filler/fallback/budget_left_ms`；不把已有来源日志或完整对话直接上传。

## 失败记录

记录提交、系统/固件、配置开关（不含密钥）、用例编号、时间、实际听觉、汇总指标、历史条数是否变化、期望和实际差异。记录垫话第一次出声时间与最终回答首声；不能只凭 SSE 已输出认定音箱已经播放。人工用例未执行时保留“未执行”，不填通过。异常只保存经过脱敏的必要片段。

## 恢复

先清空 `LLM_WEB_TEST_FAULT` 并空闲重启，确认启动不再出现 `WARNING TEST FAULT INJECTION ENABLED`。可独立使用：`LLM_WEB_RETRIES=0` 关闭重试，`LLM_WEB_FILLER=` 关闭垫话，`LLM_WEB_FALLBACK=fail` 恢复固定失败策略，或 `LLM_WEB_SEARCH=off` 关闭整个联网判断/工具过程。普通聊天仍需要其后端网络。

需要恢复脚本时，使用本轮安装前核对过的备份成组恢复客户端和安装包清单；不要盲用旧测试文档的设备路径或摘要。恢复测试时由机主调整过的私有配置，并确认故障注入已关闭。本提交没有执行任何设备恢复或重启。

## 本地结果

开发机 macOS、仓库既有 Python 环境，2026-11-04：

- 基线：443 项，440 通过、3 跳过、0 失败；`/tmp/baseline_tests.log`。
- C1 专项：54 项，53 通过、1 跳过、0 失败；`/tmp/c1_special_tests.log`。
- 最终全量：462 项，458 通过、4 跳过、0 失败；`/tmp/c1_full_tests.log`。相对基线新增失败为 0。
- 两处嵌入 `--check`、完整 Shell 语法检查、`git diff --check` 和修改文档相对链接检查通过；协议生成块及执行卡禁改文件未变化。
- 前期一次专项中，既有 HTTP 连接拒绝用例出现 transport/player=137 的时序失败；该播放逻辑未修改，随后专项与最终全量均通过。模板默认值检查曾在模板同步前执行，模板同步后已通过。

跳过项单列，均不记为通过：

| 用例 | 原因 |
|---|---|
| `NativeProtocolTest.test_busybox_shell_awk_and_byte_readers_obey_the_same_unicode_contract` | 本机没有 BusyBox（基线已有） |
| `SpeakerDoctorTest.test_runs_under_busybox_ash` | 本机没有 BusyBox（基线已有） |
| `NeuralCpuLeaseTest.test_nonrenewing_worker_is_stopped_by_kernel` | 仅 Linux CPU 信号行为，macOS 跳过（基线已有） |
| `NativeWebTest.test_busybox_retries_and_filler_share_the_turn_directory` | 本机没有 BusyBox（C1 新增） |

真机验收全部未执行；未部署、未重启音箱、未修改私有配置。
