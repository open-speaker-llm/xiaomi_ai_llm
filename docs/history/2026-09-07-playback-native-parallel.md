# LLM 播放期间保留原生家居控制

## 用户要求

LLM 回答继续播放，用户同时唤醒小爱控制智能家居。明确不停止或暂停当前 LLM；不将这类唤醒改造成播放打断。

## 故障证据

2026-09-07 22:14:31 至 22:15:03，LLM 正在播放“超级人工智能”回答。22:14:50 原生物理唤醒，新 dialog 为 `28866c23029cc5c9a2c9e62dd48968e9`；22:14:52.492 中间 ASR 文本“开灯”，22:14:55.499 最终为空，没有看到家居执行指令。不能把中间识别成功等同于家居控制已执行。

客户端 hook 在 22:14:55 将 think、ready 标成 NATIVE_FOLLOWUP_CUE_SUPPRESSED。原逻辑只检查 native_live 配置及 BUSY_MARKER；但 busy 同时用于 llm_playing 和 native_followup_listening。由此将播放中真正的原生回调误判为软件续听，原生 ready 中的状态收尾也被跳过。这是此前续听提示隔离范围过大的缺陷，最近回退仍包含它。

仅凭回调被屏蔽，不能证明最终 ASR 空文本完全由该缺陷造成；声学并行识别需用户实测确认。

## 修改

hook 在原有条件上增加 native_asr_ctl 当前 phase 判断，仅 1..6 的自有续听阶段屏蔽提示；IDLE、FAILED、NATIVE_HANDOFF 或状态不可用时透传原生回调。原有 busy 防止将播放期间的命令再次送 LLM，保持不变。

没有加入打断标记、停止/暂停 aplay 或 LLM 的逻辑，也未调整音量、云端 VAD 和原生 NLP。未安装的打断草稿已撤销。native_asr.so 重新编译后与原稳定版 SHA256 完全相同：`1417d670342a2ed237aea0e0caba740a96e19ad524f131d7e73d63c1b9086cc2`。

未启用的本地 VAD 实验从运行组件源文件移出；原始实验源文件暂存 `/private/tmp/xiaomi-local-vad-experiment-source.c`，纯算法头与测试在提交整理时一并移出仓库，暂存 `/private/tmp/xiaomi-local-vad-experiment-archive/`。此次部署沿用原稳定原生二进制。

## 验证

新增测试直接提取真实 hook，用独立临时文件和伪原生入口验证 10 种状态乘 3 种回调（ready、WuW、multirounds）。验证 playback/idle 的 busy 不再吞原生回调，自有续听仍隔离提示，handoff 正常透传。部署及实机结果后补。


89 项测试和 shell 语法检查通过。22:22:33 安装备份 `/data/native-asr-backup-20260907-222233/restore.sh`；安装后 healthy、phase=0。新客户端 SHA256 `ccc2c7b3618bb473a12fe89c0e0f2e8c5b179d1bf13e336ba9e86f76e1b64348`，原生组件保持稳定版哈希。实际设备 hook 配合隔离 busy 文件、伪原生入口验证 IDLE 时 busy 不再吞 ready；未触发家居动作。已邀请用户实测并行控制，尚待真实结果。


22:23 用户撤回误点的“未执行”反馈，该条不作为实测结论。之后设备真实日志：22:24:23 首次唤醒的“开灯”最终为空；22:24:29 第二次唤醒最终“开灯”，进入原生 Nlp.StartAnswer / Speak（单靠该状态不能判定灯已执行）。22:25:12 的第三次唤醒更明确暴露串音：中间先识别“开灯”，随后被 LLM 的“现在常见的人工智能不太一样……只擅长特定领域”覆盖，最终转交的是 LLM 播报内容。物理唤醒日志 is_aec_scene=0，但旧日志也有该值，不能单凭它断言回声算法被关闭。

原生播放通知 src=3/event=12、13 的成对探测均 code=0，固件记录 other_tone_status 并写 type=17 通知；尚不足以证明此通知能改善回声消除。


进一步对照：同一段现存 PCM、相同音量、软件 ASR-only 收听，baseline、不改变播放但发送 other_tone_status 开始/结束通知、临时开启 Loopback Enable 三组均完整识别出同一段 LLM 播报文本，未见串音改善。上述实验没有进入 NLP/家居执行；通知成对结束，Loopback Enable 已恢复 Disable，未写入正式配置。不能把 Loopback 的关闭单独当成根因，或声称播放状态通知已经修好回声。

用户对真实灯光动作表示“不确定，没注意”，因此没有得到家居执行成功的现场确认。目前完成的是原生回调隔离范围的修复；连续播放时的声学串音仍可复现，并行控制的稳定性尚未修复。保留 LLM 连续播放，不以打断或暂停作为替代。待解决项是核验原生 AEC 参考音频的真实采集路径并消除播报串入识别，之后验证灯光动作。
