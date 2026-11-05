# TTS 提前准备测试

版本：基于 `dd4c24f`，分支 `codex/S20-tts-persistent`，本步骤本地提交。新增 `DEVICE_TTS_EARLY_START=0`，依赖 `DEVICE_TTS_PERSISTENT=1`。不改 ettsc 二进制、不新增依赖、不读取或修改私有 env、不改变默认播放时序。真人和声学用例均**未执行**。

## 准备

使用仓库现有 Python 环境与工具。先记录当前客户端/安装包/启动入口版本、boot 分区和设备空闲状态；不把代码跑通作为播放验收。实验仅在 native + device 流式启用，升级生产时应按维护流程成组校验客户端与安装包清单，保留匹配备份。

## 本机步骤

```sh
./scripts/run_tests.sh
.venv/bin/python -m unittest tests.test_tts_early_start tests.test_tts_persistent tests.test_tts_prewarm tests.test_web_filler_cache tests.test_latency_trace -v
python3 scripts/embed_native_web.py --check
python3 scripts/embed_native_protocol.py --check
git diff --check
```

预期：唤醒先启动 worker、取得原生结果后才可能预合成；原生成功不合成/不播放。LLM 路由预先提交垫话，但普通 answer 不播放它。搜索授权后，播放器在正文首 token 到达之前也能消费垫话，正文不重复垫话、历史只记录正文。垫话失败、超时按原预算回退，语音保持顺序；空回答不写完整历史。新唤醒、退出、换话题及 cleanup 仍回收自有 worker 和私有任务目录。

`test_tts_early_start` 的假模型在观察到播放器已收到固定垫话 PCM 之后才发正文 token，形成因果验证，不能靠固定 sleep 假定已播放；播放器写文件、不占声卡，无真实 LLM key 或真实问答。BusyBox 用例在本机工具缺失时单独标跳过。

## 隔离真机步骤

仅在自己创建的私有 `/tmp` 目录中上传当前函数与固定测试脚本；使用现有部署的 `serve` 二进制，LLM 用固定 SSE、假 key，播放器用文件替身。禁止读取生产 env，禁止调用实际 LLM 或播放音频，不能重启/中断生产会话。核对垫话先于正文 token 被替身消费、后续正文 reuse=1、同 worker，错误后原路径回退，退出后自有目录与进程清理。记录版本、阶段时间、长度及错误码，禁止记录真实问答或密钥。

## 真人步骤和预期（未执行）

1. 先关闭 EARLY_START，分别记录一条普通问答、一条搜索和同会话追问的计时与听感；再在音箱空闲时用独立非私有覆盖配置启用开关，不改原私有 env。
2. 搜索时检查垫话仅一遍，正文完整、顺序正确；普通回答、原生家控/报时和无识别结果不误播“搜索中”。
3. 连续追问、新唤醒、换话题、结束、网络失败/超时和下一轮恢复分别检查；确认没有前轮 PCM、重复播报、挂起播放器或残留 worker。
4. 记录 `[LATENCY]` 的 `player_open`、`wake→filler_commit`、`wake→answer_commit`；垫话为 sent0、正文从 sent1 起。`sent0_tts_end` 是检测发布时刻，精确服务耗时以 0000.attempt-1.log 的 `[T]` 为准。
5. 用同一类问题进行多次 A/B 和录音，分别统计首段与正文声学首声。不得直接把“提前识别 1.3 秒 + 提前合成 1 秒 + 播放 0.66 秒”相加当作收益；它们存在并行关系。

## 已执行记录

开工基线：510 项，501 通过、9 跳过，新增失败为 0；嵌入和 shell 语法通过。日志 `/tmp/tts-early-baseline.log`。最终全量：523 项、513 通过、10 跳过，无新增失败；嵌入、shell 语法及 diff 检查通过。日志 `/tmp/tts-early-final-verified.log`。10 项跳过分别为 9 项本机 BusyBox 缺失、1 项 Linux CPU-signal 用例在 macOS 不适用。

专项 52 项、46 通过、6 跳过，日志 `/tmp/tts-early-targeted-final.log`；最终提前准备用例 12 项、11 通过、1 跳过（含取消目录消失及请求准备期间 worker 重建），日志 `/tmp/tts-early-regressions.log`。主机缺失 BusyBox 的跳过项单列保留，不能由隔离设备测试概括为全部通过。

真实 S12A BusyBox 隔离验证：固定假模型、假 key、文件播放器，两轮各 3 段，共用同一个真实 ettsc worker。首轮 TCP 7 ms、TLS/WebSocket 929 ms，后续所有段与第二轮均无握手、reused=1/reconnects=0。两轮 PCM 各 358272 字节，垫话先于模型正文 token 被文件替身消费，历史只含固定正文。生产播放器未调用，不据此推断听感或声学首声。

BusyBox 假 TTS 的失败和超时注入均验证两轮：回退后每轮 PCM 3072 字节、顺序正确、同 worker，临时任务和进程全部清理。超时初测暴露取消目录已由 worker 删除、主进程再次重定向到该路径导致 ash 退出的竞态；取消写入已移入允许失败的子 shell，并补目录提前消失的回归用例，设备超时复验通过。

隔离记录在本机 ignored `tmp/tts-early-start-review/`：`device-check.log`、`device-fault-partial.log`、`device-fault-hang-final.log`、`production-postflight.log`。完成后原生产客户端 SHA 未变、客户端/ASR/首轮判停健康；仅本轮测试目录清理，残留测试进程为 0。当前生产仍是 `dd4c24f`，新实验尚未部署。

## 失败记录与恢复

记录提交、分区、开关、脱敏阶段时间、PCM 长度、错误码、是否复用/重连及实际听感。失败项保持未通过，不更新 `docs/status.md`。

恢复时在空闲维护窗口设 `DEVICE_TTS_EARLY_START=0` 并重启客户端，即回到 `dd4c24f` 的原准备时序；若需代码回退，用匹配备份成组恢复客户端和包清单。不要把旧版恢复脚本直接用于哈希不匹配的新部署。
