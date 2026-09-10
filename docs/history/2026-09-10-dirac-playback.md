# 2026-09-10：Dirac 播放初始化与 boot1 部署

用户明确要求将 Dirac 修复部署到音箱，并提供真人验证场景。

## 修改

- 在现有隔离 worktree 从 main `ef513b6` 建立 `codex/fix-dirac-playback`。
- 增加 2.7 KB ARM 共享库，在实际 aplay 进程中调用设备原生 `Dirac_initialize`，选用现存 S12A 配置。
- 包装器核验 boot1 及 ALSA/Dirac/配置指纹；不匹配、关闭或缺少组件时保留普通播放并标明 bypass。
- 客户端所有 LLM aplay 入口经统一适配器调用，保留原参数、退出码、同一 FIFO 连播和原生兜底规则。最近一次播放错误输出保存为 `/tmp/native_first_dirac.log`。
- 未修改原生播放器、ettsc、音量配置、麦克风/AEC 或并行唤醒逻辑。

## 验证

- 本地 101 项测试通过，shell 语法和 diff 检查通过。新增 6 项覆盖不匹配/缺失/关闭、preload 继承、参数、返回码及错误日志，已有句级重试和原生兜底测试继续通过。
- 真机相同合成 PCM 经原版 ALSA plug/softvol/route 到 file/null：原路径 47 条错误，修复后 0 条；前后均输出 816000 字节，数据不同，均未发生整数削顶。此测试不向扬声器播放，也不能代表实际语音听感。
- 部署后实际默认声卡路径连续播放两段一秒静音 PCM：播放器返回 0，Dirac 只初始化一次，speaker 配置准备成功，错误 0，释放返回 0。
- 原生 ASR healthy，Loopback Enable=Enable；Master=145、mysoftvol=105/105，和部署前一致。
- 尚待真人确认实际音色、音量、长播报、追问及并行唤醒；未执行整机重启或切换 boot0。

## 部署与回滚

- 正式文件：`/data/native_first_client.sh`、`/data/dirac_aplay.sh`、`/data/native_first_dirac.so`。
- 生效客户端 PID=1065，07:38:34 进入 IDLE。持久文件沿用已有开机启动入口；本轮只重启客户端。
- 备份及回滚：`/data/dirac-backup-20260910-073825/restore.sh`，须在客户端空闲时运行。
- 首次部署遇到既有 TERM 陷阱只清理不退出，以及精简固件没有 nohup：旧文件已恢复，确认旧客户端 PID 后结束残留进程，用忽略 HUP 的后台 shell 启动并核验恢复。随后使用修正部署步骤成功更新，回滚脚本也使用相同兼容启动方式。没有因此改动原生小爱服务文件。
- 调试临时文件及首次失败的重复备份已清理，保留最终可用回滚目录。详细测试输出位于本机 `/tmp/xiaomi-dirac-audit-20260910/`。

SHA-256：

```text
native_first_client.sh d1a3dd3a3ac4b62e16aeab8643830761b23a5195548996f31ff011f085460a9b
dirac_aplay.sh e9b240aee6008d979c7a5c7b07496c5222451bbcf61033893bd0636d80d8226f
native_first_dirac.so d57c628a809d8764530a3260a844774be24b3eac48bf3dd0dcbad80b5a1b79bd
```

真人验证清单见 `device/dirac/README.md`。
