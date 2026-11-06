# C3 搜索阶段计时与可选垫话缓存

适用版本：`codex/S4-web-latency-cache` 的 C3 本地提交，父提交 `b062db1`（S3）。只扩展搜索观测、垫话缓存和规划时间位置；规划请求 JSON 结构和设备时区保持原样。本说明中的人工用例均为**未执行**，主机自动化不代表真机通过。

## 准备

开发机位于仓库根目录，使用已有 Python 环境，不安装依赖、不使用真实 key。音箱验收应先核对当前 boot、客户端安装来源及恢复点，由维护者按匹配版本的部署流程同步活动客户端、组合包内副本及清单；本轮未部署设备。

设备使用 native/device/句级流式链路，`BACKEND=deepseek`、`LLM_WEB_SEARCH=auto`，S3 的 `LATENCY_TRACE_ENABLED=1`。保留已有私有配置，不复制它到仓库或测试记录中。若另行测试缓存，只改真实配置中的唯一有效 `LLM_WEB_FILLER_CACHE` 赋值（默认 `0`），客户端空闲时按[操作手册](../runbooks/operations.md#客户端)重启。

## 开发机步骤与预期

```sh
./scripts/run_tests.sh
python3 -m unittest tests.test_native_web tests.test_latency_trace tests.test_web_filler_cache -v
python3 scripts/embed_native_web.py --check
python3 scripts/embed_native_protocol.py --check
git diff --check
```

专项应覆盖：五个搜索点的 `name ms` 格式、重试只产生一组开始/结束、未联网时不伪造阶段、S3 打点开关、有效结果数、规划提示最后一行的分钟精度时间；两轮真实队列的首次合成/缓存命中、0000 先于答案、缓存不进入答案历史/ttft、大小及 PCM 对齐拒收、文案/音色/增益/采样率改变后失效、缓存关闭/无垫话时不阻塞。BusyBox 不存在时对应测试跳过，保持未验证。

正式基线使用未修改的 S3 工作树及仓库已有 `.venv/bin/python`：475 项，469 通过、6 跳过，嵌入和 Shell 语法检查通过；日志保存于开发机 `/tmp/c3_baseline_venv.log`。系统 Python 的另一次运行因缺少现有项目依赖产生 5 个导入错误，正式对照统一使用已有虚拟环境，没有安装依赖。

C3 最终全量回归：491 项，484 通过、7 跳过，新增失败为 0；嵌入、Shell 语法及 `git diff --check` 通过。搜索、S3 与缓存专项共 59 项（包含在全量中），其中 55 通过、4 项 BusyBox 跳过；日志保存于开发机 `/tmp/c3_final_venv.log`。缓存专项另行运行 9 项，8 通过、1 跳过，包含缺少校验和工具和不完整合成的回退。

跳过项需单列：主机没有 BusyBox，因此 JSON/SSE 工具兼容、搜索重试、doctor、S3 汇总、S3 百分位以及 C3 缓存队列共六项 BusyBox 用例保持未执行；Linux CPU 限额信号用例在 macOS 跳过。

## 音箱步骤（全部未执行）

1. 先保持缓存默认关闭，观察 `/tmp/native_first_client.log` 和 `/tmp/native_first_latency.log`。说“呼叫 DeepSeek，帮我联网搜索上海今天的天气预报”，确保实际进入 LLM search；若原生天气直接处理，换成明确需要联网核实的实时新闻题。普通“今天上海天气怎么样”也要对照，原生路由无需强制改变。
   - 预期：`[WEB] action=search … results=N`（N 为有效来源数），marks 有五个点；轮末只有一条 S3 `[LATENCY]`，有 `plan=`、`search=`、`filler=`。短时重试耗时计入对应段。
2. 询问稳定知识，再关闭 `LLM_WEB_SEARCH` 对照。
   - 预期：普通 answer 只有规划点、`search=-`；off 没有搜索阶段点，`plan=- search=-`。原生家控、天气、报时保持原路由。整段非流式路径不播放垫话。
3. 设 `LLM_WEB_FILLER_CACHE=1` 后连续问两个实时问题，并确认每轮确实触发 search/fetch。
   - 预期：首次成功后有 `/data/web_filler.pcm.<cksum>`（按执行卡的校验和后缀命名）；第二轮在 `/tmp/native_first_stream/0000.pcm` 和 `.rdy` 发布缓存，只听一次垫话且先于答案。正常答案的历史、ttft 不含垫话。缓存关闭时没有 0000 段。
   - 对比每轮 `filler_t - llm_req/1000` 与 `fifo_commit1` 的相对时间，同时录音核对实际出声；网络、规划耗时可能不同，不用绝对 `filler_t` 判定优化收益。
4. 分别改变垫话或音色后重启，重新问实时问题；在客户端空闲时将当前键的缓存复制一份备份，再截断为空或超过 1 MiB。
   - 预期：新键不复用旧音频；无效文件删除，回到 SSE 合成，成功后重新缓存；不漏答案、不重复垫话。测试完成后恢复配置及备份，不能删除其它 PCM 文件。
5. 设 `LATENCY_TRACE_ENABLED=0` 对照同类问题。
   - 预期：不新增 marks 或 `[LATENCY]` 日志，播放和历史仍正常。重新开启后恢复计时。

## 失败记录方式

记录提交、设备 boot、用例编号、配置开关（不含 key）、脱敏 `[WEB]` 汇总与 `[LATENCY]`、marks、缓存字节数和实际声音/顺序。`filler_t`、FIFO 写入均不是声学首声证明。不保存问题/答案原文、URL query、设备 ID、token 或私有配置。失败标注为未通过，下一轮正常问答也要复验。

## 恢复方法

先设 `LLM_WEB_FILLER_CACHE=0`，空闲时重启客户端，回到 SSE/TTS。需要时设 `LLM_WEB_SEARCH=off` 关闭规划和搜索（聊天网络仍需要）。恢复原有文案、音色及计时开关；缓存文件可留存，关闭时不读取。完整撤回 C3 时使用匹配部署的已核对备份，成组恢复活动客户端、包内副本及清单，不能只覆盖一个脚本；本轮未执行真机回滚。
