# boot1 首轮本地判停组件

适用：S12A / MDZ-25-DA，boot1/system1，ROM 1.76.54，以及安装器校验的原生 ASR 基线。已在实机启用并完成现场验收；其他固件、不同已安装版本不能直接套用。项目级[原理](../../docs/concepts/native-first.md#首轮收音与结果提交)、[日常操作](../../docs/runbooks/operations.md#boot1-首轮本地判停)、[排障](../../docs/runbooks/troubleshooting.md#首轮提前截断或启用判停后没有回答)分别维护在现有文档层级；本页负责组件构建、安装与维护边界。

## 行为和配置

音箱内运行一个 Silero VAD 模型，观察原生处理后的 PCM，并控制真实唤醒首轮的收音结束。小米云继续识别文字和处理原生指令；本机不做文字识别，不需要 Mac ASR 或新网络服务。免唤醒追问仍用原生 VAD。

| 规则 | 当前值和处理 |
|---|---|
| 未开口 | 首帧起 6 秒未检测到语音，no-speech 退出 |
| 句末 | 检测到语音后约 2 秒静音，正常 quiet 结束；已实测容纳约 1.5 秒停顿 |
| 单轮上限 | 唤醒后约 20 秒；残句不请求 LLM、不写历史 |
| 瞬时积压 | 最多 50 帧 / 500 ms 可追平，不跳帧；结束前必须消费全部已发布音频且提议新鲜 |
| 异常或取消 | 拒绝本轮残句，保留拒绝记录，避免迟到结果重放 |

这些是编译后的当前策略，不是全部可通过 env 调节的参数。它不判断语义是否完整；超过约 2 秒的长停顿仍可能被当作句末。改变阈值需要重新构建并复验轻声、噪声、超长与恢复场景。

```sh
# device/native_first.env.example 默认关闭；安装成功后才启用。
NATIVE_ENDPOINT_ENABLED=1
NATIVE_ENDPOINT_MANAGER=/data/native_endpoint/manager.sh
```

`NATIVE_DIALOG_INPUT_GUARD` 是既有识别后短句补全，`NATIVE_ASR_LISTEN_TIMEOUT` 是追问保护超时，都不是首轮判停开关或句末阈值。

## 构建输入

需要 Python 3、Zig，以及自行准备并校验的 ARM32 依赖。构建器不下载资源，也不把模型、第三方二进制或原厂固件提交进仓库。运行时依赖沿用已验证组合：

- sherpa-onnx v1.10.36 ARM32 C API，内含 ONNX Runtime 1.17.1。
- 同版头文件 `c-api-1.10.36.h`，SHA256 `90e4c96fc0c24c7cbedb24918bacc82c6bd896e35f992bf593e8c70fc54b01b4`；构建脚本强制校验。
- Silero v5 双采样率模型，文件名 `silero_vad_v5.onnx`，SHA256 `6b99cbfd39246b6706f98ec13c7c50c6b299181f2474fa05cbc8046acc274396`。不能替换成接口不同的精简模型。
- Debian ARMHF glibc `2.36-9+deb12u7` 与 libstdc++ `12.2.0-14+deb12u1`，仅由模型进程的独立加载器使用，不覆盖系统 `/lib`。

来源与选型证据见[模型实验记录](../../docs/history/first-turn-endpoint/neural-vad-20260919.md)。依赖目录应含以下文件及 `runtime.sha256`：

```text
ld-linux-armhf.so.3  libc.so.6  libdl.so.2  libm.so.6
libonnxruntime.so    libpthread.so.0       librt.so.1
libsherpa-onnx-c-api.so  libstdc++.so.6     silero_vad_v5.onnx
```

清单每行格式为 `SHA256  文件名`，覆盖上述十项。构建器将输入文件与提供的清单比对；**这项检查不替代来源核验，也不会自动证明任意输入清单可信**。构建和部署可在开发 Mac 完成，运行不依赖它。若另行分发第三方运行包，还需保留对应许可证及履行各依赖的分发义务；本仓库 MIT 仅覆盖自有代码。

仓库根目录执行，先把三个路径替换为自己的目录，输出使用新的空目录：

```sh
python3 device/native_endpoint/build_package.py \
  --assets /path/to/verified-arm32-assets \
  --header /path/to/pinned-header-directory \
  --output /path/to/new-endpoint-package
```

构建目标为 ARM32/glibc 2.25 接口。`neural_pool` 单独链接 `neural_clock.c`，在旧内核上直接走已验证的取时 ABI，避免新版 glibc 探测不支持的系统调用造成寄存器日志。它不修改系统 libc、内核日志级别或原生进程的时钟实现。

输出 `runtime.tar.gz`、组合版 `native_asr.so`、`native_first_client.sh`、`manager.sh`、`lifecycle` 和 `package.sha256`。`runtime/`、`build/` 是本机中间目录，不是需要逐项上传的安装入口。底层代码及独立测试入口见[实现目录](../endpoint_probe/README.md)。

## 安装

先确认基础[原生 ASR 组件](../native_asr/README.md)健康、设备空闲、`/data` 空间足够。运行库原始文件约 19.34 MiB，安装占用以构建输出和 `df -k` 为准，运行还需 `/tmp` 解压空间及模型内存。安装器要求可用空间大于暂存文件占用加 1 MiB，不能用这项空间检查代替实际运行验证；不要自动删除旧功能腾空间。

首次安装分两步，在开发机仓库根目录执行：

```sh
python3 tools/speaker-maintenance/install_native_endpoint.py \
  --host 192.168.8.152 --package /path/to/new-endpoint-package
```

该步只暂存到音箱 `/tmp/endpoint-install-时间戳`，校验文件并输出 `STAGE=…`。准备好维护窗口后，使用实际返回路径激活：

```sh
python3 tools/speaker-maintenance/install_native_endpoint.py \
  --host 192.168.8.152 --package /path/to/new-endpoint-package \
  --activate-stage /tmp/endpoint-install-实际时间戳
```

激活会核对已知客户端、native_asr 库/管理器及固件 ABI，检查空闲和空间，备份原客户端、私有配置与 SO，停止原有客户端和原生服务，归档旧 `instruction.log`，部署并启用，再检查 READY/healthy。它不修改 rootfs init 文件。原始配置备份留在设备，输出 `BACKUP=/data/endpoint-backup-时间`；妥善保存该路径，配置中可能含密钥。

安装器要求安装前的客户端 SHA256 为 `70a7012f2c68c7ebc8e545d9481845068406a476dc4cff7e68808fe671f8f184`，SO 为 `8a7d11ac76c90b60d7e42de48c02b3390205ce440650f0ef524a0c929091b0d6`，管理器为 `ecf34e250505d488eaa2b41fbe1280f46d91d56abc0a1b7482ff185d4fd5b93f`。这些是本次实机安装前核验的基线，不代表用任意版本基础安装器安装后都会得到相同文件。新设备或版本不一致时，应先完成适配和回滚验证，再更新安装器允许的基线，不能跳过校验。

安装器是**基线受限的首次安装工具，不是任意版本通用升级器**：

- `/data/native_endpoint` 已存在时，默认暂存拒绝；当前激活版的客户端/SO 也不同于旧基线，直接再次激活会拒绝。
- `--reuse-installed-package` 仅用于已完整回滚到旧基线、仍有有效暂存目录、且磁盘中整包清单完全相同的重新启用，不支持替换不同版本。
- 不同版本升级需准备专门核验、备份和替换流程，不能通过删包目录或跳过哈希校验冒充首次安装。
- 不要仅覆盖客户端、单独重装旧 native_asr，或同时加载实验 `run_*.sh`。生产 SO 包含首轮判停和原有追问，两者共用管理入口。

## 启动、恢复与验收

现有 `rc.local → /data/init.sh → native_first_client.sh` 自动调用管理器。包存放 `/data/native_endpoint/`，启动校验后展开到 `/tmp/xiaomi_native_wake_probe/` 与 `/tmp/xiaomi_neural_shadow/`，模型预加载成功后才接管新唤醒。

```sh
# 音箱上，只读检查
sh /data/native_endpoint/manager.sh verify
sh /data/native_endpoint/manager.sh status
sh /data/native_asr.sh status
```

预期 `ENDPOINT_READY owner=… model=… turns=…` 及 native_asr `healthy`。`manager.sh start|stop` 由内核锁串行化；重复 start 复用就绪实例。客户端退出请求 stop。不要自行运行内部 `_start/_stop`。

服务以最长一天的有限运行段循环，临近期限只在空闲时排空并重新加载；未就绪的新轮保留原生收音。原生进程身份变化触发重新关联，旧拒绝证据保留。三次相邻故障后停止重试，间隔一分钟以上的运行故障重新计数；此时 status 报不可用，不能将原生回退描述为判停已恢复。专属管理日志约 1 MiB 后轮换。

停用、重新启用与日常日志按[运维手册](../../docs/runbooks/operations.md#boot1-首轮本地判停)。完整回滚须在空闲时执行**本次安装实际输出**的 `BACKUP/restore.sh`，恢复原客户端、配置、SO，归档指令日志再重启，以免重复回答旧问题；安装包会保留，配置恢复为安装前状态。

验收采用[EP1–EP7](../../tests/manual_native_first_cases.md#ep-首轮本地判停)。截至 2026-09-20 已完成静默、超长拒绝与恢复、停顿轻声续说、连续轮、再次唤醒、免唤醒交接及实际回滚/启用；模型现场 RSS 约 27.7 MiB。2026-09-20 已完成整机重启及重启后的静默/停顿续说验收，自动恢复为单模型实例；全天稳定性仍未验收；200 轮耐久属于较早常驻包的文件输入，不能冒充最终包全部现场测试。版本哈希、反例和最终结果见[日常验收记录](../../docs/history/first-turn-endpoint/native-daily-20260919.md)。
