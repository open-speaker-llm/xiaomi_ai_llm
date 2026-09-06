# 2026-09-06：boot1 原生识别接入 LLM 连续追问

本轮已将 [NONWAKEUP 研究入口](2026-09-06-boot1-native-asr-research.md) 实现为音箱端功能，安装到 S12A boot1 / ROM 1.76.54。已接通 LLM 播放完成 → 原生 ASR-only → 当前 LLM session → 下一次播放和续听。安装说明见 [原生追问组件](../../device/native_asr/README.md)。

## 已取得的证据

- 音箱部署了客户端、两个原生进程共用的 preload、控制程序及 procd 覆盖管理器；两个进程均加载成功。
- Mac 的 `org.open-speaker-llm.followup-asr` 已停止，8080 端口连接被拒绝；原服务文件和模型保留，便于回退。
- 实际 outgoing Recognize 日志包含 `Execution.RequestControl` 的 `disabled=["NLP","TTS"]`；每次续听有新 dialog，实际 final 与结束事件关联到该 dialog。
- 13:10:48 左右自动调用实际 LLM/设备 TTS，播报“测试完成”；播报结束后进入原生续听，静默得到空 final，然后清理队列、恢复 Master 145 并回到 IDLE。该测试没有人为注入识别文本，没有让 Mac 识别；它证明播报到续听和静默退出流程，不等同于用户已验证有声多轮对话。
- 42 项本地自动测试通过；独立设备进程中实际 JsonCpp ABI、重复序列化、ASR-only 上下文、动作隔离、旧会话结果和 Finish 状态测试通过。
- 研究时的 10 秒延迟、3 秒全局改写窗口、一次性录音重放和限时探针均未用于正式功能。

13:19 重启自启动检查通过：内核 boot ID 已变化，客户端自动建立两项服务覆盖，mipns 与 mico_aivs_lab 均加载组件并返回 healthy，进入 IDLE；Hard Mute 为 off，Master 为 145。Mac ASR 服务仍停止。重启后再次直接发起静默原生识别，新 dialog `61d10bc39dab7c396ba8358999ad9475` 带 ASR-only 上下文，收到空 final 和 Finish，控制程序返回 124（静默结束）并恢复 IDLE。13:34–13:36 用户进行了正式有声多轮测试：首问“呼叫 DeepSeek，介绍一下杭州西湖”，13:35:35 播报结束后进入原生续听；13:35:37 识别“那什么时候去呢”，以 TURN 2 进入同一 LLM session，回答西湖适合春秋季游览。第二次播报后静默退出，恢复 Master 145 / Hard Mute off。由此确认无 Mac ASR 的实际 LLM 上下文追问已工作。用户反馈每轮回答后仍有小爱的“欸”，后续修复如下。

## 续听时“欸”的补充修复

系统日志与固件反汇编显示，`mipns-xiaomi` 的 `wakeup_tone_raw` 线程随机读取五个本地唤醒 WAV，跳过 80 字节文件头后直接调用 `snd_pcm_writei`。它不经过 `wakeup.sh` 或 mediaplayer，因此原脚本提示音拦截漏掉了这条路径。

正式组件增加线程创建时的续听归属记录，只在归属本次续听且线程名、文件路径均匹配时，将 `fread` 得到的 PCM 缓冲区置零。保留 WAV 文件、长度和原生播放结束时序；不修改音量，也不替换麦克风流。完成或取消后已创建的提示音线程仍受此归属保护。

- 独立设备测试通过 15 个提示音用例，覆盖所有五个文件、普通唤醒及其他线程/文件/进程的透传，以及完成和取消后的延迟读取；验证文件头及磁盘文件内容不变。
- 42 项项目测试与 shell 语法检查再次通过。
- 修正版正式安装后，实际程序续听记录 `cue silenced seq=1 bytes=9378`，新 dialog `ce417ecaf4b5d434a0a697b0e062c22d` 仍成功得到 ASR-only 空 final 和 Finish，并返回 IDLE。这证明真实原生播放路径已命中；是否听不到“欸”需用户再次听觉确认。
- 13:50 再次重启后，boot ID 为 `348f56f7-7fc9-4778-b4ce-6ef482bc8550`，新版组件由客户端自动加载，两项原生服务 healthy，客户端进入 IDLE；设备摘要与构建产物一致。

## 回退点

首次切换前备份：`/data/native-asr-backup-20260906-125559/restore.sh`，恢复 PCM + Mac ASR 客户端和配置。13:09 再安装的备份 `/data/native-asr-backup-20260906-130957/restore.sh` 恢复此前一版原生追问。

本次提示音修复前的组件另备份为 `/data/native-asr-cue-backup-20260906/native_asr.so`，只对应上一版原生追问组件；回退它会恢复“欸”声，不会恢复 Mac 识别路线。

Mac ASR 的文件和登录服务配置未删除。若确需恢复旧路线，可先恢复设备备份，再在 Mac 用原 LaunchAgent 重新启动识别服务。

## 范围

boot0 的默认路由、录音和文件 ASR 保持原样，已做兼容自动测试，本轮没有切换 boot0 做新现场测试。原生云识别依赖联网；本功能不增加播放中打断，也不为“退下”等结束语设特例。通用示例默认不启用 boot1 追问，须安装通过固件校验的组件后再启用。

## 最终构建一致性

隔离 worktree 构建的二进制与设备安装文件 SHA-256 一致；`native_asr.so` 已更新为上述提示音修复版本：

- `native_asr.so`：`d4413143fd0af589515c3a4dfe171e750c557def38b69a86fefe1962084c2802`
- `native_asr_ctl`：`6b36c86b860e3b3a29cb1b7dcee8a85be26592d39558e56142d0ffdeb80d439b`
- `native_first_client.sh`：`44b0541ac053245bfe48d2f4103e0b1b865ef43b803c0ee9f587d1ccd3ef899f`
