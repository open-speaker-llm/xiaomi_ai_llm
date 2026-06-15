#!/bin/bash
# 交叉编译 micnorm（追问录音 S32→归一化 S16）到小米音箱（armhf 静态，同 ettsc）。
# 依赖: brew install zig
set -e
cd "$(dirname "$0")"
TARGET=arm-linux-musleabihf
zig cc -target "$TARGET" -static -O2 -s micnorm.c -o dist_micnorm
mkdir -p dist && mv dist_micnorm dist/micnorm
echo "[build] -> $(pwd)/dist/micnorm  ($(wc -c < dist/micnorm) bytes)"
file dist/micnorm 2>/dev/null || true
