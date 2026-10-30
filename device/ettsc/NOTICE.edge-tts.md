# EdgeTTS v2 算法来源与许可

`src/gec_v2.rs` 是 [rany2/edge-tts 的 DRM 实现](https://github.com/rany2/edge-tts/blob/bd44c1d1aaebdc1db7f47456ee12431b42ec7cac/src/edge_tts/drm.py) 的 Rust 适配，固定上游提交为 `bd44c1d1aaebdc1db7f47456ee12431b42ec7cac`。该文件遵循 **LGPL-3.0-only**；仓库根目录的 MIT 许可证不覆盖这一衍生文件。

上游作者和贡献者的许可声明保留在 [vendor/edge-tts/LICENSE](vendor/edge-tts/LICENSE)，其 LGPLv3 条款引用的 GPLv3 全文保留在 [vendor/edge-tts/COPYING.GPL-3.0](vendor/edge-tts/COPYING.GPL-3.0)。上游 LICENSE 中仅适用于 `srt_composer.py` 的 MIT 条款不适用于 DRM 算法。

保留的上游原始源码与 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `vendor/edge-tts/drm.py` | `b29c37e2a0c11284adb2a1ffc04f0f231e1ba2d921494a912797218b05d64c4a` |
| `vendor/edge-tts/constants.py` | `6c987fafa0a10aad81d8d5fc3447a14f2bca2eb86b4f97296c384253d3906c94` |

Rust 适配使用显式 32 位回绕运算、整数时间窗口和普通 SHA 轮循环，不包含 Python 缓存、异步网络或时钟校正类。测试向量由保留的 Python 算术函数独立生成，覆盖时间窗口、2038/32 位边界、SHA 填充与 CS64 字对边界。

分发静态 `ettsc` 二进制时，应同时提供本目录的完整对应源码、许可证、`Cargo.toml`、`Cargo.lock`、`build.sh`、本地补丁及其他必要构建材料，使接收者能够修改该模块并重新构建。只发布二进制不能替代这些材料。保留的 Python 源码和向量生成器仅供开发核对，音箱运行时不依赖 Python。
