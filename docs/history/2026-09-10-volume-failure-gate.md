# 2026-09-10：音量一致性与失败提示提前拦截

用户反馈 LLM 比小爱原声略响，以及失败提示“这个问题……”偶尔漏出开头，要求继续优化。保持既有要求：LLM 连续播放，并行唤醒和家居指令照常工作。本次沿用隔离 worktree `codex/fix-dirac-playback`，保留此前已部署的 Dirac 初始化修复。

## 证据与修改

### 音量

- 07:49–07:54 的 8 次 LLM 播放均为 Master 145 → 155，结束恢复 145。设备 TLV 步长 0.50 dB，因此固定 +10 是额外 +5 dB。
- 将 `DEVICE_TTS_STREAM_MASTER_BOOST` 默认值从 10 改为 0，保留 `DEVICE_TTS_GAIN=2.0`。显式配置的补偿仍可使用，不会多轮累加。
- 设备参数检查另复现旧自动映射的问题：原生媒体音量返回 170、Master 实际 145，旧算法直接比较后抬到上限 160。检查失败后立即恢复 145。
- 修正 `auto` 默认行为：当实际 Master 可读取且 `CURRENT_SCALE=100` 时直接沿用，包括低音量和 0；无需查询可能已被冻结的 mediaplayer。Master 不可读或用户显式更改比例时才保留旧映射。
- 最终真机验证两次应用都是 145 → 145，结束仍为 145；数字增益 2.0。不同 TTS 源本身的响度差尚无 LUFS/SPL 实测，不能宣称听感已完全相同。
- 当前 mysoftvol 为 170/170。系统日志显示原生 mediaplayer 在本次部署之前的 07:59 已执行音量恢复（用户层 48、内部 170）；没有将更早快照的 100 当作当前值强制恢复。

### 失败提示

- 07:54:02 原生文案为“这个问题我暂时还回答不上，需要再学习一下”。旧 guard 有命中记录，但它每 10 ms 读取日志后才暂停播放器，无法撤回已入队的声音。现有日志不能准确测量可听见片段的毫秒长度。
- 在匹配固件已使用的 JsonCpp 解析 hook 内增加同步检查，失败 Speak 在分发前被拒绝。只有存活客户端、think 激活、未 busy、有效 ASR final、同一 dialog 和期限内的匹配文案才有资格触发。
- 拒绝前原子写入 `failure_dialog`，只含客户端 PID 与 dialog_id；客户端用该标记关联原始 ASR 日志，继续交给 LLM，避免因 Speak 不再写入日志而失去接管信号。新标记不保存问题、回答或音频。
- 同一被拦截 dialog 的重复解析继续拒绝；普通回答、Miot、音量、对话结束，以及 LLM 播放期间新唤醒的原生会话透传。没有通过全局静音或暂停 LLM 来处理。
- 客户端不存在、空 ASR final、陈旧对话、超期标记、无效规则、异常策略文件、接管写入失败等情况下保留原生路径。日志 guard 仍作为后备。两条路径复用 `UNSUPPORTED_PATTERNS`，其文本误判/漏判边界没有改变。
- `AIVS_EARLY_GUARD_ENABLED=0` 可单独退回日志 guard。

## 验证

- 106 项自动测试与 shell 语法通过。使用项目已有虚拟环境；首次调用系统 Python 缺少 soundfile/fastapi/openai，切回项目环境后完整通过。
- 真实 C gate 测试覆盖所有者、对话隔离、普通回答、重复解析、busy、期限、异常规则、FIFO/符号链接及接管写入失败。
- 真机独立进程使用固件原生 JsonCpp，验证提前拦截、普通指令/Finish 透传及空 final。另通过真实 `CharReader → OurReader` 调用链验证 Unicode 解码后命中，而不只是直接调用判断函数。
- 既有 ASR-only、取消/迟到事件、重复 Finish、18 项唤醒回调及 15 项原生提示音 PCM 隔离验证仍通过。独立测试没有打开麦克风、播放声音或连接云端。
- 部署后原生 ASR healthy，AEC `Loopback Enable=Enable`；Dirac 两个文件摘要与上一轮成功部署相同。设备参数检查没有发送真实问答或家居操作。
- 用户完成后续体验后反馈“还不错”，并明确要求提交合并。08:29–08:32 的 5 次真实 LLM 播放均保持 Master 145 → 145、结束恢复 145；最近一次真实播放 Dirac 初始化返回 0，speaker 配置准备成功。原生 ASR healthy，AEC 参考仍为 Enable。
- 用户没有逐项报告失败提示和家居场景，本次读取的运行日志也没有同步失败 gate 命中记录。因此不将总体体验反馈写成每个失败文案或每种并行唤醒场景都已覆盖；同步拦截的确定性证据来自上述固件解析测试。

## 部署与回滚

- boot1，ROM 1.76.54。正式更新 `/data/native_first_client.sh`、`/data/native_asr.so`；原生 manager、ettsc、私有配置及 Dirac 文件保持当前版本。
- 最终客户端 PID=3901，08:27:43 进入 IDLE；mico_aivs_lab=3679、mipns-xiaomi=3779。
- 当前摘要：

```text
native_first_client.sh 4b9fe2d18dbddc20feedd14d0a7488049a06265a0672cdb05f7a3f17958e277a
native_asr.so 8a7d11ac76c90b60d7e42de48c02b3390205ce440650f0ef524a0c929091b0d6
```

- 回滚：空闲时运行 `/data/audio-opt-backup-20260910-082152/restore.sh`，恢复本次优化前的客户端和 native_asr.so，保留此前的 Dirac 修复。
- 更新前核验空闲、旧文件/新文件摘要与固件；精确核对客户端 PID 后 TERM 清理，必要时结束该残留 PID；使用现有 manager 重新装载库，保证 AEC 参考先启用再开麦。持久文件沿用已有开机入口，本轮没有整机重启或切换分区。
- 本机证据与部署清单：`/tmp/xiaomi-audio-opt-20260910/`。本次合并将 Dirac 初始化、音量一致性和失败提示提前拦截一起纳入主分支。
