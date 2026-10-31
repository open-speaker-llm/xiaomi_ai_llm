# 2026-10-31 boot0 微软男声播放修复

## 现象与原因

boot0 已识别问题并转入 LLM，模型返回答案，微软 TTS 成功生成三段 PCM，但用户听不到回答。播放器日志显示：包装器因仅允许 boot1 而 bypass；普通 aplay 内的原厂 ALSA 音效插件仍尝试加载不存在的 `/usr/lib/diracmobile.config`，连续出现 `Dirac_create`、`Dirac_prepareToPlay`、`Dirac_processBlock` 错误。播放器退出码为 0 并不能证明实际有声。

两套系统共用 TTS 程序与配置，不代表播放适配已覆盖两套系统。本次确认问题在 boot0 播放初始化，未重新更换音色或修改 LLM/TTS 云端配置。

## 修复与部署

`device/dirac/dirac_aplay.sh` 增加已验证 boot0 的独立 ALSA 配置指纹；boot1 原有指纹保持。两边的 ALSA 库、Dirac 库和 S12A 音效配置摘要一致，继续使用同一个已部署的初始化 SO，在实际 aplay 进程中加载 `/data/etc/diracmobile.config`。

本次只原子替换 `/data/dirac_aplay.sh`，不用重启客户端或音箱。配置仍为设备端微软 TTS、云健男声、GEC v2；轻量 Mac TTS 关闭。新包装器 SHA256：`7eb044eb514b6b77f94a46563c7932dfcd0f2571ea0fc2a67b4bf6eb179bef27`。

## 验证结果

- 包装器专项 7 项、流式管线 3 项、并行播放 1 项，共 11 项通过；Shell 语法和 diff 检查通过。
- boot0 实机一秒静音 PCM 经默认声卡路径播放：初始化 `rc=0`，播放器返回 0，无 Dirac 错误；部署后的包装器同样通过。
- 用户重新发起 LLM 问答后明确反馈“有，男声正常”；对应实际播放日志初始化成功且无处理错误。
- 本次未切回 boot1 重做真人听觉测试，boot1 原有校验分支保留且主机回归通过。长播报、连续追问和并行唤醒仍需按下面步骤复验。
- boot0 启动时还出现了系统与客户端各拉起一个 mipns 的竞争，测试前已按 PID/启动身份核对后停止额外实例，仅保留一个活跃系统实例。这是独立的启动问题，本次包装器补丁没有宣称永久解决它。

## 人工测试

1. 说“小爱同学，问问 DeepSeek，一加一等于几？请用一句话回答”：应为云健男声，整句清晰播放。此项已由用户确认。
2. 再问一个需要约一分钟回答的问题：检查开头、句间和结尾，无长时间无声或截断。
3. 回答结束后接着追问，随后分别测试“换个话题”和“结束对话”：检查换会话与退出收听。这两个指令只用于追问窗口，不是播放中打断。
4. 用较低和日常音量各试一次，再让原生小爱报时：检查两种播放路径的音量均正常。
5. 如之后重启或切换系统，再检查唤醒与短回答；记录异常时间、是否亮灯、是否有声，不公开私人对话日志或配置。

## 备份与恢复

设备旧包装器：`/data/boot0-tts-dirac-backup-20261031/dirac_aplay.sh`。电脑本地保存于 `backups/boot0-tts-dirac-20261031/`，包含修复前后脚本和说明；这是本次小修复的增量备份，不是新的全盘镜像。

若要撤回本补丁，在音箱 SSH 中确认客户端空闲并核验旧文件后执行：

```sh
test ! -e /tmp/native_first_busy || exit 1
test "$(sha256sum /data/boot0-tts-dirac-backup-20261031/dirac_aplay.sh | awk '{print $1}')" = e9b240aee6008d979c7a5c7b07496c5222451bbcf61033893bd0636d80d8226f || exit 1
cp -p /data/boot0-tts-dirac-backup-20261031/dirac_aplay.sh /data/dirac_aplay.sh.restore && mv /data/dirac_aplay.sh.restore /data/dirac_aplay.sh && sync
```

恢复只撤回本包装器适配，会重新带回 boot0 的原播放限制；不改变私有配置、TTS 二进制、音量或原生服务。
