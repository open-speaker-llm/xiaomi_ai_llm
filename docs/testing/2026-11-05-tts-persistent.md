# TTS 会话内连接复用实际测试

适用版本：基于 `eb76353`，本地分支 `codex/S20-tts-persistent` 的 S20 第二部分提交。`DEVICE_TTS_PERSISTENT=0` 默认关闭，`ETTSC_IDLE_SECS=20` 默认空闲秒数。支持同会话多句及连续追问复用；LLM 连接池、切句阈值、并发预取和生产启用不在本步骤。真人与声学验收均为**未执行**。

## 准备

使用现有虚拟环境、Rust 和 ARM 交叉工具链；不安装依赖、crate 或新设备组件。确认设备 SSH 地址与架构；不 source、读取或修改私有 env，不使用真实 LLM key。验证仅上传候选 ettsc 和隔离脚本到自己创建的私有 `/tmp` 目录，播放器用写文件替身，不接管生产。

生产启用另需匹配版本的客户端、支持 `serve` 的 ettsc 与安装包清单，按既有维护流程成组升级及备份。默认不开启；`DEVICE_TTS_PERSISTENT=1` 优先于 `DEVICE_TTS_PREWARM`，不需要同时开启后者。配置、空闲与失败语义见[配置参考](../reference/configuration.md#tts-会话内连接复用实验)。

## 开发机步骤和预期

在仓库根目录执行：

```sh
./scripts/run_tests.sh
.venv/bin/python -m unittest tests.test_tts_persistent tests.test_native_session tests.test_tts_prewarm -v
export PATH="$HOME/.rustup/toolchains/stable-aarch64-apple-darwin/bin:$HOME/.cargo/bin:$PATH"
(cd device/ettsc && CARGO_TARGET_DIR=/tmp/tts-prewarm-host cargo test --locked --offline)
(cd device/ettsc && CARGO_TARGET_DIR=/tmp/tts-prewarm-arm cargo zigbuild --release --locked --offline --target arm-unknown-linux-musleabihf)
python3 scripts/embed_native_web.py --check
python3 scripts/embed_native_protocol.py --check
git diff --check
```

预期：关闭时保留旧 PCM、顺序与历史；开启后同会话的多句/追问只启动一个 worker，切换 session、音色等配置时回收并重建。新唤醒、换话题、对话结束及 cleanup 关闭自己持有的进程并删除任务目录。worker 失败、坏/残缺 PCM、单句等待超时回退原链路，失败不写完整历史。前导零及非法配置安全处理，复用不依赖设备没有的 `cksum`。

Rust 本机 WebSocket 用例检查三次 turn 的前两次共用一条连接、第三次在服务端关闭连接后只重新建链一次；取消和超大文本不能发起连接或发布结果，未发布任务忽略且空闲等待有界。

## 独立设备复现（不播放）

开发机替换当前目标地址，仅上传到临时目录：

```sh
SPEAKER_HOST='root@替换为当前音箱地址'
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa "$SPEAKER_HOST" 'umask 077; mkdir -p /tmp/tts-persistent-review; chmod 700 /tmp/tts-persistent-review'
scp -O -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa /tmp/tts-prewarm-arm/arm-unknown-linux-musleabihf/release/ettsc "$SPEAKER_HOST":/tmp/tts-persistent-review/ettsc
```

在音箱独立 shell 中执行。每次只用固定测试句，不读取真实历史：

```sh
umask 077
work=$(mktemp -d /tmp/tts-persistent.XXXXXX)
ETTSC_TIMING=1 ETTSC_IDLE_SECS=20 /tmp/tts-persistent-review/ettsc serve "$work" > "$work/startup.log" 2>&1 &
pid=$!
trap "kill '$pid' 2>/dev/null; wait '$pid' 2>/dev/null; rm -rf '$work'" EXIT
trap 'exit 1' INT TERM
i=0
while [ ! -f "$work/ready" ] && [ ! -f "$work/exited" ] && [ "$i" -lt 240 ]; do
    sleep 0.05; i=$((i+1))
done
for n in 1 2 3; do
    [ -f "$work/ready" ] && [ ! -f "$work/exited" ] || break
    job="$work/job.Demo$n"; mkdir "$job"
    printf '同一连接第%s句测试。' "$n" > "$job/request"
    printf zh-CN-YunjianNeural > "$job/voice"
    : > "$job/queued"
    i=0
    while [ ! -f "$job/done" ] && [ ! -f "$work/exited" ] && [ "$i" -lt 240 ]; do
        sleep 0.05; i=$((i+1))
    done
    [ -f "$job/done" ] || break
    cat "$job/done"
    wc -c < "$job/audio.pcm"
    cat "$job/worker.log"
done
kill "$pid" 2>/dev/null
wait "$pid" 2>/dev/null
```

预期三次 `done=0`，PCM 非空、16 位对齐；第 2/3 次 `tcp_ms=- tls_ws_ms=-`、`reused=1 reconnects=0`。任务文本和音色先写好才发布 `queued`，每句独立目录且只消费一次，不使用 FIFO，不把文本放进进程参数。手动退出独立 shell 后只清理自己的目录；不播放这些音频。

## 已执行记录（2026-11-05）

基线：独立的未修改 `eb76353` 工作树，使用仓库既有 `.venv/bin/python`，499 项、491 通过、8 跳过；嵌入和 Shell 语法通过。日志 `/tmp/tts_persistent_baseline.log`。

最终代码全量回归：510 项，501 通过、9 跳过，新增失败为 0；Shell 语法、两个嵌入检查及 `git diff --check` 通过。新复用/既有会话专项 36 项、35 通过、1 跳过；Rust 18 项全部通过（11 单元、7 解码），ARM 静态构建成功，无新增依赖。日志 `/tmp/tts_persistent_final_tests.log`、`/tmp/tts_persistent_targeted_final.log`、`/tmp/tts_persistent_rust.log`。

主机跳过单列：协议 BusyBox Unicode、搜索 BusyBox 重试、doctor ash、S3 汇总与百分位、C3 缓存、首段预连接、会话复用共八项 BusyBox 用例，以及 macOS 上不适用的一项 Linux CPU-signal 用例。设备独立验证只覆盖本轮列出的路径，不能将所有跳过项标为通过。

服务端协议验证：真实 S12A 上同一 WebSocket 连续三次合成全部成功，PCM 字节数为 122112、122112、127872。首句 TLS/WebSocket 1223 ms，第 2/3 次均为 `-`，`reused=1 reconnects=0`；空闲后正常退出。日志 `/tmp/tts_persistent_multiturn3.log`。

最终客户端函数在真实 BusyBox 中的隔离记录（固定模型输出、假 LLM key、写文件播放器，未调用 LLM 或播放）：

| 用例 | 结果 |
|---|---|
| 首轮两句 | rc=0；首句 TLS 1462 ms，第 2 句无握手且 reuse=1 |
| 同会话追问两句 | rc=0；worker 非空且与首轮相同，两句均无握手、reuse=1 |
| 生成期间超过空闲阈值 | 空闲 1 秒后释放连接，待文本时 reconnects=1，后续句又 reuse=1 |
| 换会话 | 旧 worker 回收，新 worker 启动，后续句复用 |
| 注入 serve 不可用 | 普通合成回退 rc=0、历史提交替身被调用 |
| 显式停止 | 自有 worker 和所有私有任务目录均清理 |

各组两句 PCM 均为 246528 字节。日志 `/tmp/tts_persistent_device_client_final.log`。只有非空 worker、单句命中记录与握手字段共同成立才计为复用通过；不能只凭 rc=0 或两个空 PID 相等判断。

早期 FIFO/线程探测未完成首任务；本机 FIFO 用例通过、设备空闲计时正常，原因未确定，该结果不作为服务端不支持多 turn 的证据。最终沿用已验证的私有目录队列。另一次客户端试验因设备没有 `cksum` 而走普通合成回退，未计为复用通过；已移除此依赖并补兼容回归。上述失败探测没有修改生产程序或配置。最终确认当前设备 kernel 4.9.61，生产客户端和 `/data/ettsc` 前后 SHA-256 一致；本轮所有自建验证目录及音频已清理，记录 `/tmp/tts_persistent_device_cleanup.log`。

## 真人和长期验收（全部未执行）

1. 配套升级并保持开关 0，记录原播放与首声；再在空闲时开启 `DEVICE_TTS_PERSISTENT=1`，用同类问题 A/B。
2. 长回答至少 5 句、同 session 连续追问、搜索垫话和 PCM 缓存开/关，核对不漏句、不重复、不混入上一句音频，来源和历史保持正确。
3. 原生家控、天气、报时以及新唤醒、明确退出、换话题、失败与中断分别复验，确认旧 worker 及时回收、原生路由正常。
4. 对照 S3、单句 `[T]` 与录音波形，分别记录 boot0/boot1 的声学首声 P50/P90、RSS/FD、失败率和长时间追问。握手省略、PCM 出现及 FIFO 提交均不等于已经听到声音，不能从隔离合成推断实际首声或耐久通过。

## 失败记录与恢复

记录提交、boot/固件、用例和开关，保留脱敏计时、长度、退出码、命中/重建状态及实际声音顺序；不记录完整问答、URL query、token、设备标识或私有配置。失败保持未通过，并复验下一轮正常问题。

设 `DEVICE_TTS_PERSISTENT=0`，空闲时重启客户端。若只想保留首段预连接，可另设 `DEVICE_TTS_PREWARM=1`；两者都为 0 则完全使用原一次性合成。需要回退代码时按匹配备份成组恢复客户端、ettsc 和安装清单。本轮只做临时隔离验证，生产启用、真人播放与生产回滚均未执行。
