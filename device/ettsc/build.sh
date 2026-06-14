#!/bin/bash
# 交叉编译 ettsc（音箱端直连 EdgeTTS 客户端）到小米音箱。
# 目标：32 位 armhf 全静态 musl（音箱是 aarch64 内核 + armhf 用户态）。
#
# 依赖（一次性）：
#   brew install rustup zig
#   rustup default stable && rustup target add arm-unknown-linux-musleabihf
#   cargo install cargo-zigbuild
set -e
cd "$(dirname "$0")"

TARGET=arm-unknown-linux-musleabihf
command -v cargo-zigbuild >/dev/null || { echo "缺 cargo-zigbuild：cargo install cargo-zigbuild"; exit 1; }
command -v zig >/dev/null || { echo "缺 zig：brew install zig"; exit 1; }

echo "[build] cargo zigbuild --release --target $TARGET"
cargo zigbuild --release --target "$TARGET"

OUT="target/$TARGET/release/ettsc"
mkdir -p dist
cp "$OUT" dist/ettsc
echo "[build] -> $(pwd)/dist/ettsc"
file dist/ettsc 2>/dev/null || true
