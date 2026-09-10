# LLM 播放的 Dirac 初始化

适用范围：已验证的 S12A boot1 固件。`dirac_aplay.sh` 核验根分区、ALSA 配置、音效库及 S12A 配置的 SHA-256。其他固件或缺少组件时保留普通 aplay，并记录 bypass。

原生 mediaplayer 会在进程内调用 `Dirac_initialize("/data/etc/diracmobile.config")`；独立 aplay 不会，导致查找不存在的 `/usr/lib/diracmobile.config`，音效实例创建失败。此模块只补上同进程初始化，DSP 实例、音量、连续处理和释放仍由固件 ALSA 插件负责。

## 构建和接入

```sh
sh device/dirac/build.sh /tmp/native-first-dirac-build
```

部署以下文件，并设为仅 root 可执行：

- 构建的 `native_first_dirac.so` → `/data/native_first_dirac.so`
- `dirac_aplay.sh` → `/data/dirac_aplay.sh`
- 更新后的 `device/native_first_client.sh` → `/data/native_first_client.sh`

客户端 `llm_aplay` 为各个 LLM PCM/WAV 播放入口调用此包装器；`LD_PRELOAD` 仅传给该 aplay，不配置全局预加载，不修改 rootfs、原生播放器、麦克风、AEC 或唤醒转交逻辑。单独运行初始化程序再启动 aplay 无效，因为进程内状态不会跨 exec 保存。

`LLM_DIRAC_ENABLED=0` 可选择普通播放。若初始化运行时失败，会记录非零返回码，保留原播放行为，不能将其视为音效已生效。数字增益仍为 2.0，Master 默认沿用原生实际值，旧的 +10（+5 dB）补偿改为默认关闭；显式配置仍可覆盖。校准和后续实测见[音量与失败提示记录](../../docs/history/2026-09-10-volume-failure-gate.md)。

## 日志

`/tmp/native_first_dirac.log` 保存最近一次 LLM 播放进程的 stderr，每次新播放器覆盖，不保存音频或写入持久日志。初始化成功应出现：

```text
[DIRAC] initialize rc=0 config=/data/etc/diracmobile.config
... Prepared with conf: 'speaker'
```

同时检查没有 `Dirac_create`、`Dirac_prepareToPlay`、`Dirac_setVolume`、`Dirac_processBlock` 错误。主客户端启动日志只表明配置已加载，不足以代替一次实际播放的检查。

## 验证与回滚

- 本地测试覆盖固件/配置不匹配、组件缺失、关闭音效、继承已有 preload、带空格的参数、退出码和播放错误日志；现有句级重试、PCM 排空、原生兜底、并行唤醒测试继续执行。
- 部署前用设备原版 ALSA 的 plug/softvol/route 链处理相同合成 PCM，输出到 file/null，不向扬声器发声。原路径出现 47 条错误，修复后 0 条，两份输出帧数相同、数据不同，确认实际执行 DSP。
- 部署时先确认客户端空闲，备份旧客户端，核验新文件指纹，再原子替换文件并重启客户端。保留设备上的部署专属 `restore.sh`，恢复旧客户端并移除新增的两个 Dirac 文件。
- 回滚必须在客户端空闲时执行；原生 ASR、AEC、配置文件和 ettsc 不随本次回滚变化。

## 用户实测

1. 用日常偏小音量询问一个短问题：人声清晰，开头结尾完整，无爆音、异常突然增大或过小。
2. 让 LLM 连续讲约一分钟：句间衔接正常，不丢句、不重复、不截尾。
3. 播放期间反复喊“小爱同学”，分别开灯、关灯，共 3 次：唤醒成功、灯实际动作，LLM 始终连续播放。
4. 播放结束直接追问，再静默等待退出：追问能识别，退出后原生小爱仍可唤醒。
5. 分别以较小和日常音量测试，再播放原生音乐或询问天气：音量变化合理，切换回原生功能后的音量正常。

如有问题，反馈大致时间、场景及具体现象，便于对齐客户端和音效日志。
