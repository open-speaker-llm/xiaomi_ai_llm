# minimp3 本地缓冲区补丁

用于修复项目 Issue #7 中的 `RUSTSEC-2025-0044` / `GHSA-7mcq-f592-pf7v`。
`ettsc` 在 `ETTSC_PCM=1` 时使用该解码器。

## 来源与范围

- 上游：[germangb/minimp3-rs](https://github.com/germangb/minimp3-rs)，crates.io `minimp3 0.5.2`。
- 发布包 SHA-256：`9a3ed9d34ed1a9190336a2b165bf09ac447693dfd9a61684597aaae2ee12df53`。
- 发布包记录的上游提交：`11194c1112f3263b9ada7a71ee1f5327e90138d9`。
- `src/lib.rs`、`src/error.rs`、`LICENSE` 从校验过的发布包复制；MIT 许可保留。
- 本地版本通过父项目的 `[patch.crates-io]` 引用，不连接第三方 fork，不引入新的构建脚本，不发布到 registry。

`src/lib.rs` 相对上游只有以下变动：

1. `SliceRingBuffer<u8>` 替换为标准库 `VecDeque<u8>`。
2. 调用 C 解码器前执行 `make_contiguous()`，保证完整 MP3 输入连续，且借用在 FFI 调用期间有效。
3. 使用 `drain(..frame_bytes)` 移除已消费字节，保留未完成的帧。
4. 删除缓冲库导致的手写 `unsafe impl Send`，使用成员类型自动推导。

`src/error.rs` 未改动。清单移除了 `slice-ring-buffer`、上游仓库内部的
`minimp3-sys` 路径及上游开发依赖；保留原有 registry 版本要求和可选 `async_tokio`
接口。项目仍只启用同步解码，`minimp3-sys 0.3.2` 和 C 解码算法均保持不变。

## 验证与维护

在 `device/ettsc` 运行：

```sh
cargo test --locked --offline
cargo zigbuild --release --target arm-unknown-linux-musleabihf --locked --offline
```

旧版设备上若标准 libtest 运行器超时，可构建不使用测试工作线程的检查程序：

```sh
cargo zigbuild --release --example decoder_device_check \
  --target arm-unknown-linux-musleabihf --locked --offline
```

将 `target/arm-unknown-linux-musleabihf/release/examples/decoder_device_check`
复制到已授权设备的临时目录后执行。它按顺序复用相同的 7 项断言，任何失败均返回非零；
不连接网络、不播放音频、不修改设备配置。2026-09-09 真机验证时，libtest 运行器超时，
而该顺序检查程序全部通过；底层 libtest 兼容性原因尚未进一步定位。

`tests/decoder_regression.rs` 验证重复补充缓冲、跨环绕边界的错位帧、短读、截断帧、空/无效输入、IO 错误和
锁文件禁止重新引入漏洞依赖。合成音频重复 32 次后，原版解码得到 1408 帧、811008
个采样；补丁需保持该结果。在 aarch64 macOS 上还检查修复前记录的 PCM SHA-256，
其他 CPU 的解码舍入可能不同，不能跨架构假定逐字节相同。
错位帧测试已通过反向验证：临时把 `make_contiguous()` 改成只传第一个切片时，
测试因 PCM 改变而失败，恢复正确实现后通过。

本补丁只消除这项缓冲库依赖风险，不宣称修复所有 C 解码器或 TLS 问题。
2026-09-09 的 OSV 锁文件查询中，此项告警已消失，但原有 `rustls-webpki 0.102.8`
仍有其他告警，需独立评估；不能将本次结果称为全依赖审计无告警。

`VecDeque::make_contiguous()` 可能移动缓冲数据；部署前需验证真机解码延迟、内存、
音量和句间连续播放。保留旧 `ettsc` 以便回滚。修改源码或锁文件不会更新设备上的旧二进制。
上游发布经过验证、移除该依赖的版本后，应优先评估升级并删除此本地副本。
