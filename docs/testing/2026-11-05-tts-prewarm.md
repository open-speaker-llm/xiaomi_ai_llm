# TTS 首段预连接实际测试

适用版本：`codex/S20-tts-prewarm` 的本地提交，父提交为 `24b3308`。实现对应 01 §3.4 / §8 D2 的首段预连接实验：握手后保留连接供一次真实合成使用。默认 `DEVICE_TTS_PREWARM=0`；只作用于 native + device 句级流式。单连接多句、LLM 连接池和原生路由不在此步。

## 准备

- 使用已有 Python 虚拟环境、Rust 和 ARM 交叉工具链，不安装新包或 crate。测试使用假 LLM key，不读取任何真实 env 或密钥文件。
- 设备独立测试先核对当前 SSH 地址、固件与 ARM 用户态；`ssh xiaomi` 只是操作手册中的既有别名，不能假定本机已配置。候选程序只放入自己的私有 `/tmp` 目录，播放器用写文件替身，不替换生产组件。
- 生产启用另需维护者按匹配来源的升级流程同时核对客户端、ettsc 和安装包清单，保留可恢复备份；不能只改开关后继续使用不支持 `prewarm` 的旧 ettsc。本轮未部署生产、未更改私有配置。

## 开发机步骤

仓库根目录执行：

```sh
./scripts/run_tests.sh
# 本次 Mac 使用的现有 Rust 工具链；其它开发机按已有安装位置调整。
export PATH="$HOME/.rustup/toolchains/stable-aarch64-apple-darwin/bin:$HOME/.cargo/bin:$PATH"
.venv/bin/python -m unittest tests.test_tts_prewarm tests.test_latency_trace tests.test_tts_sentence_recovery tests.test_web_filler_cache -v
(cd device/ettsc && CARGO_TARGET_DIR=/tmp/tts-prewarm-host cargo test --locked --offline)
(cd device/ettsc && CARGO_TARGET_DIR=/tmp/tts-prewarm-arm cargo zigbuild --release --locked --offline --target arm-unknown-linux-musleabihf)
python3 scripts/embed_native_web.py --check
python3 scripts/embed_native_protocol.py --check
git diff --check
```

预期：默认关闭时 PCM、顺序和历史与原链路一致；开启时先启动预连接，首段交给同一进程/连接，后续段走一次性合成；握手失败、半截音频、等待超时回退到普通合成，原重试预算仍生效；无文本、轮末及退出时回收自己的子进程及私有任务目录。server、非流式路径不启动预连接。非法开关只警告一次并使用 0。Rust 回归使用本机 WebSocket 检查真实连接先于文本、单 turn 及残缺结果拒收，不调用云端。

## 音箱独立步骤

先将 `SPEAKER_HOST` 替换为当前已核对的 SSH 目标，在开发机只上传候选 ettsc 到临时目录：

```sh
SPEAKER_HOST='root@替换为当前音箱地址'
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa "$SPEAKER_HOST" 'umask 077; mkdir -p /tmp/tts-prewarm-review; chmod 700 /tmp/tts-prewarm-review'
scp -O -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa /tmp/tts-prewarm-arm/arm-unknown-linux-musleabihf/release/ettsc "$SPEAKER_HOST":/tmp/tts-prewarm-review/ettsc
```

以下在音箱独立 shell 中执行，不 source 私有配置、不播放：

```sh
umask 077
work=$(mktemp -d /tmp/tts-prewarm.XXXXXX)
ETTSC_TIMING=1 /tmp/tts-prewarm-review/ettsc prewarm "$work" zh-CN-YunjianNeural > "$work/worker.log" 2>&1 &
pid=$!
# 等 ready；应加 12 秒上限，未 ready 或已有 done 时记录失败并退出本例。
i=0
while [ ! -f "$work/ready" ] && [ ! -f "$work/done" ] && [ "$i" -lt 240 ]; do
    sleep 0.05; i=$((i+1))
done
# 仅 ready 且没有 done 时，继续交付固定测试句。
if [ -f "$work/ready" ] && [ ! -f "$work/done" ]; then
    printf '预连接首句测试。' > "$work/request.part"
    mv "$work/request.part" "$work/request"
    i=0
    while [ ! -f "$work/done" ] && [ "$i" -lt 240 ]; do
        sleep 0.05; i=$((i+1))
    done
fi
[ -f "$work/done" ] || kill "$pid" 2>/dev/null
wait "$pid"
cat "$work/done"
wc -c < "$work/audio.pcm"
grep '^\[T\] ' "$work/worker.log"
rm -rf "$work"
```

预期 `done=0`，PCM 非空、16 位对齐；音箱不出声。增加 1 秒等待后再交文本，仍应复用握手后的原连接。若不交文本，握手成功后空闲 20 秒以非零状态退出，`done=1` 且没有 PCM。出现错误/超时时只处理自己的 PID 和临时目录，不能 `killall`。重复普通合成和预连接各至少 5 次，记录“交文本到完整 PCM”；预连接的握手准备时间已提前，不能从两组差值直接推断真实对话首声。

## 已执行记录（2026-11-05）

修改前同一已有 `.venv` 基线：491 项，484 通过、7 跳过，嵌入和 Shell 语法检查通过；日志 `/tmp/tts_prewarm_baseline.log`。

最终代码全量回归：499 项，491 通过、8 跳过，新增失败为 0；Shell 语法和两个嵌入检查通过。新预连接专项 8 项，7 通过、1 跳过；原有延迟/逐句恢复/缓存专项 38 项，35 通过、3 跳过，并全部包含于最终全量回归。Rust 14 项全部通过（7 单元、7 解码），ARM 交叉构建成功，无新增依赖。最终全量日志为开发机 `/tmp/tts_prewarm_final_cleanup_tests.log`。

主机跳过单列：协议 BusyBox Unicode、搜索 BusyBox 重试、doctor ash、S3 汇总、S3 百分位、C3 PCM 缓存、TTS 预连接共七项 BusyBox 用例，以及一项 Linux CPU-signal 用例。主机未安装 BusyBox、平台为 macOS；设备独立 BusyBox 证据只覆盖下述本轮路径，不能替代所有被跳过用例。

设备为当前可连接的 S12A、kernel 4.9.61。先用已安装 ettsc 做 20 次只握手、不合成的测量：20/20 成功，TCP P50 5 ms / P90 7 ms；TLS/WebSocket P50 **785 ms**、P90 **1165 ms**、max **1489 ms**，高于方案的 150 ms 搁置门槛。脱敏计时保存于开发机 `/tmp/tts_prewarm_probe.log`。

ARM 候选为静态链接 32 位 ARM EABI5。私有 `/tmp` 中固定句、固定音色，普通模式与预连接模式各 5 次全部成功，每次 PCM 112896 字节。预连接模式先等 ready，再保留 1 秒才交文本：

| 样本 | 普通模式交文本到 PCM（ms） | 已握手模式交文本到 PCM（ms） |
|---|---:|---:|
| 1 | 2140 | 390 |
| 2 | 1120 | 390 |
| 3 | 2470 | 340 |
| 4 | 2320 | 390 |
| 5 | 1110 | 880 |

样本量小、云端耗时有波动，且已握手模式不包含前置准备时间；只证明连接能保留并用于首段，不能当作整轮或声学首声改善比例。空闲 20 秒退出为 rc=2 / done=1，无 PCM。

另在真实 BusyBox 中加载候选客户端的预连接、合成和队列函数，以固定模型输出和写文件播放器隔离验证：首段命中及后续普通合成 rc=0、合计 PCM 231552 字节，历史提交替身被调用；注入预连接失败后普通合成 rc=0、相同 PCM 字节数；空模型结果 rc=1、无完整历史。三种路径均回收自己的 worker。日志为开发机 `/tmp/tts_prewarm_device_ab.log`、`/tmp/tts_prewarm_device_shell.log`；生产客户端及 `/data/ettsc` 前后 SHA-256 保持一致。最后补齐的轮末 IPC 删除也在真实 BusyBox 独立验证通过；本轮自建的设备验证目录及音频已删除。

## 真人与生产验收（全部未执行）

1. 配套升级后先保持 `DEVICE_TTS_PREWARM=0`，记录至少 20 轮首声基线，覆盖原生家控、报时、天气和 LLM 问答。
2. 空闲时将唯一有效开关设为 1 并重启。观察 `[TTS] prewarm started/hit` 和 S3 计时，录音测唤醒/转 LLM 到首个语音波形；FIFO 提交及 PCM 文件出现都不是声学首声。
3. 分别验证普通问答、搜索垫话（PCM 缓存关闭/开启）、连续追问、短答、长答、网络失败、无答案与中断。预期每轮只预连接一次，不重复或漏播，不写入残缺历史，结束后无 worker 残留。
4. 对照开关 0/1 的 P50/P90、失败率和资源使用，boot0/boot1 分别记录；不能把独立 shell 或主机测试算作真人通过。

## 失败记录与恢复

记录提交、固件/boot、用例、开关、脱敏时间与字节数、退出码、实际声音顺序和 worker 回收情况；不保存问答原文、URL query、设备标识、token 或私有配置。失败保持未通过，正常下一轮也需复验。

设 `DEVICE_TTS_PREWARM=0`，在空闲时按既有方式重启客户端，恢复一次性合成。需要退回代码时成组恢复已核对的客户端、ettsc 和安装清单。独立验证结束只删除自己创建的 `/tmp/tts-prewarm.*` 目录和候选上传目录，不删除其它音频或进程。本轮未执行生产启用、真人播放或生产回滚。
