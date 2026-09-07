# 本地控制停录实验：未启用

2026-09-07，用户同意试验关闭云端 VAD，改由设备判断停录。范围先限定在自有 ASR-only 追问轮次；物理唤醒首轮维持原生请求。

## 实现与验证

- 临时开关 `/tmp/native_followup/local_vad_experiment` 内容为 `1` 才启用；默认关闭。
- 仅修改实验请求：`asr.vad=false`、`is_using_local_vad=true`、`enable_natural_record_v2=false`。实际 event.log 已确认序列化字段生效。
- 读取原生 DNN 输出第一段 160 个 S16 样本，不保存录音；固定 RMS 115、连续三帧判声、开头忽略 400 ms、末尾静默 2500 ms、未开口 5000 ms。第一版最长 12000 ms，第二版为在云端截断前验证停录改为 8000 ms。
- 对当前自有轮次调用固件 `set_unwakeup_status()` 停止音频。物理唤醒交接后不会再停新轮次。
- 全套 88 项测试与 shell 语法检查通过；设备 JsonCpp ABI、请求字段和原有 Finish 重放/唤醒交接测试通过。修改最大时长至 8 秒后，本地端点算法测试与 ARM 交叉编译再次通过。

## 实机结果

1. 22:09:23 实验请求 `e235863ec5c56da5c20a362b83bfbf35`；没有出现本地停录。22:09:32.362 云端 `System.TruncationNotification`，随后才发送 RecognizeStreamFinished。虽 CLI 返回文本，仍是云端截断，不能判作本地控制成功。
2. 22:10:43 实验请求 `f518351ace6667f61769f8fdcc9d4e72`。设备统计 762 帧中 757 帧超过阈值，固定能量阈值不能可靠判定现场停顿。单靠该统计不能断言现场安静或具体噪声来源。
3. 第二轮本地 8016 ms 到达最大时长；22:10:51.643 调用 set_unwakeup_status，22:10:51.658 原生 `asr send end`，证明设备音频可以主动停止。
4. 第二轮 event.log 未出现对应 RecognizeStreamFinished；22:10:55.180 才到 Dialog.Finish，CLI 返回 124 空文本。停止设备音频未可靠完成云端 EOF 协议，不能作为可用方案。

## 结论及部署

可以修改每轮云端 VAD 开关；当前实验尚不能可靠控制整条识别链路何时结束，也没有解决首轮窗口短的问题。关闭实验并恢复先前已实测稳定的 Finish 重放修复版本。实验代码及纯算法测试已移出提交范围，保留在本机临时归档；本次只提交实验结论，不发布该实现。后续实现需要先确认原生流结束事件的完整调用路径，再验证真实说话/停顿与背景声音的区分，不能用“忽略云端 StopCapture”冒充延长有效录音。

稳定 native_asr.so SHA256：`1417d670342a2ed237aea0e0caba740a96e19ad524f131d7e73d63c1b9086cc2`。
首个实验安装前备份：`/data/native-asr-backup-20260907-220634/restore.sh`。
