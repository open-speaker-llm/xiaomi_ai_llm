# boot1 失败播报快速拦截

2026-09-10 增加了[原生解析入口的提前拦截](../native_asr/README.md)，将匹配失败 Speak 在分发前交给 LLM，本文描述的日志 guard 保留为后备。新路径复用同一份文案规则；普通回答、家居指令及 LLM 播放期间的新唤醒继续透传。日志 guard 单独使用时仍有下述异步窗口。

当前结论：2026-09-06 已在 S12A 的 boot1/system1（ROM 1.76.54）实测：匹配到的小爱失败提示可被拦截并转 LLM，修正版重启后用户确认正常转接、没有先播失败提示。报时对照完整正常，见 [实测记录](../../docs/history/2026-09-06-boot1-fallback-guard.md)。判定仍依赖文本规则，未知文案可能漏判，正常回答含相似词也可能误判；不保证所有文案、时序或固件都无漏音。

`aivs_speech_guard.c` 为现有 shell 客户端补充低延迟监听：每 10 ms 检查 AIVS 日志新增内容，仅在当前会话已由 `think` 激活、客户端未忙于 LLM 时，匹配 `SpeechSynthesizer/Speak` 的失败文案并暂停 `mediaplayer`。不暂停 ASR、mipns；未命中规则的播报指令直接放行。

背景：boot1 不能照搬 boot0 的 think 预冻结；原有 shell 轮询可能在原生 TTS 已出声后才判定 fallback。快速监听缩短这段窗口，但是否完全消除可听见的提示音，必须用实机对照验证，不能由代码时延推断。

## 构建与部署

Mac 上交叉编译（需要 Zig）：

```sh
mkdir -p build
zig cc -target aarch64-linux-musl -static -Os -Wall -Wextra -Werror \
  -o build/aivs_speech_guard device/aivs_guard/aivs_speech_guard.c
```

把该产物安装到音箱 `/data/aivs_speech_guard`（权限 0755），配合同版本 `/data/native_first_client.sh`，停止旧客户端后重新启动。主客户端仅在 system1 启动 helper；无需刷 rootfs。

配置：

```sh
AIVS_GUARD_ENABLED=1
AIVS_GUARD_BIN=/data/aivs_speech_guard
```

helper 缺失或配置关闭时保留原有轮询。`UNSUPPORTED_PATTERNS` 同时传给 helper 和 shell，避免两套分类规则不同。已有自定义配置需要自行合入新增的失败文案表达式。

## 恢复与边界

LLM 回答文本不送入本拦截器；LLM 请求及播报期间，busy 标记使拦截条件不成立，包括原生 TTS 降级的正常流程。

- 启动时跳过既有日志，跟随追加、重建与检测到的截断；只处理完整且有 dialog_id 的 Speak JSON，支持 UTF-8 和 Unicode 转义。
- 自己创建 `guard:<pid>` 暂停标记；主客户端 fallback 用原有时间戳标记接手。三秒内无人接手时，helper 只释放属于自己的暂停。退出和发现父客户端退出时也执行这项恢复。
- 客户端清理时停止 helper，再执行现有播放器恢复流程。不会改写音量设置或触碰音频采集设备。
- helper 不决定 LLM 提问内容、不代替 ASR，只按规则识别原生失败文案；正常播报含匹配词时仍可能误判，新增表达式应有实际文案证据。
- helper 无法撤回已经送入声卡的音频，也不能保证每个固件都先写日志再播放。需要重复实测；不要把“发送了暂停信号”写成“用户听不到”。

日志：`/tmp/native_first_aivs_guard.log`（仅记录暂停/恢复及单调时钟，不复制提问和回复）。主状态机记录仍在 `/tmp/native_first_client.log`。

## 本地验证

```sh
python3 -m unittest discover -s tests -p test_aivs_speech_guard.py -v
```

测试使用本机编译器，验证实际 C 解析、Unicode、错误 JSON、正常回答、非播报指令、之前漏掉的学习文案，以及通过模拟信号验证暂停所有权。测试不向真实进程发信号。
