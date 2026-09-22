# 逐步完善对话

第一轮问答跑通后，接下来会遇到两个不同的问题：回答完能否直接继续问，以及第一句话中间停一下会不会被截断。它们发生在不同阶段，需要分别处理。

| 想改善的体验 | 对应组件 | 控制范围 |
|---|---|---|
| 回答后不再喊唤醒词，继续聊 | boot1 `native_asr` | 新建原生 ASR-only 追问会话，沿用同一 LLM 上下文 |
| 首轮句中停顿后继续说 | boot1 `native_endpoint` | 本机 VAD 控制真实唤醒首轮的收音结束 |

以下针对 **S12A、boot1/system1、ROM 1.76.54**。先完成[首轮问答验证](quickstart.md)。boot0 保留录音与文件 ASR 路线，不能套用这里的原生组件；能力差异见[当前状态](../status.md)。

## 1. 先让回答后的追问接起来

在还没有安装本地判停包的设备上，按 [native_asr 组件说明](../../device/native_asr/README.md)准备 Zig 和匹配固件。在开发机仓库根目录构建并安装：

```sh
sh device/native_asr/build.sh /tmp/native-asr-build
python3 tools/speaker-maintenance/install_boot1_native_followup.py \
  --host 192.168.8.152 --build-dir /tmp/native-asr-build
```

安装器校验固件、备份客户端和私有配置，并重启相关服务。记录实际输出的备份路径；安装后无需再手动启动第二个客户端。已有判停包时，`native_asr.so` 是组合库，不能用这个基础安装器覆盖，应整包维护或完整回滚后再处理。

在音箱上检查：

```sh
sh /data/native_asr.sh status
/data/native_asr_ctl status
```

管理器应为 `healthy`。随后做一次真实对话：先问“介绍一下西湖”，等回答结束、绿灯续听时直接问“那什么时候去呢？”。确认第二句沿用上下文，再保持安静，确认退出并能重新唤醒小爱。

这里的收听由原生 VAD 判停，空闲约 6 秒；20 秒参数是整轮保护超时。它不调用 Mac 识别程序，仍使用小米云。完整验收包括提示音、再次唤醒交接和重启，见[人工用例](../../tests/manual_native_first_cases.md)。

## 2. 再处理首轮停顿续说

原生追问正常后，如果首轮句中停顿容易丢失后半句，再考虑本地判停。它通过音箱内常驻的 Silero VAD 观察原生 PCM；文字仍由小米云识别，追问也仍使用原生 VAD。

这一步不是只打开一个开关。按 [native_endpoint 构建与安装说明](../../device/native_endpoint/README.md)准备固定依赖、构建安装包，并先暂存校验、再在维护窗口激活。

**当前安装器是基线受限的首次安装工具。** 它核对客户端、共享 SO、管理器及固件摘要；新设备即使完成前一步，也不保证与允许的基线一致。不匹配时先完成适配和回滚验证，不能删目录或跳过校验来强行安装。

安装成功后在音箱执行：

```sh
sh /data/native_endpoint/manager.sh verify
sh /data/native_endpoint/manager.sh status
sh /data/native_asr.sh status
```

需要同时看到 `ENDPOINT_READY` 与 native_asr `healthy`。按 [EP 系列用例](../../tests/manual_native_first_cases.md#ep-首轮本地判停)验证：只唤醒保持安静、停顿后轻声补充、超长输入、再次唤醒、连续轮和恢复。

当前策略是首帧起约 6 秒未开口退出、说话后约 2 秒静音结束、唤醒后整轮最多 20 秒。达到上限、取消或故障的残句不会进入 LLM 和历史。它不保证任意长停顿都被保留，阈值也不是全部能通过 env 调节的参数。

## 3. 把日常体验验收完整

使用 `LLM_PIPELINE=native`、`TTS_ENGINE=device` 并安装对应组件后，模型调用、语音播放和追问可不依赖常驻 Mac。仍需分别核对真实说话、出声和家居动作，进程存活不能替代听觉与动作验收。

蓝灯通常表示原生处理，绿灯表示 LLM 链路，绿灯常亮的追问窗口内可以继续说。灯效细节见[对话状态反馈](../concepts/native-first.md#状态反馈)。再次唤醒小爱可以交还原生会话，但尚未实现用语音停止正在播报的 LLM。

最后配置[自启动](../runbooks/autostart.md)，把整机重启和断电恢复单独验收。以后调整、停用或回滚从[日常操作](../runbooks/operations.md)进入；现有实机证据集中在[状态页](../status.md)，不代表新设备自动通过。
