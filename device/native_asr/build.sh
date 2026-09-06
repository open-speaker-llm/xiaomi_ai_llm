#!/bin/sh
set -eu
cd "$(dirname "$0")"
out="${1:-/tmp/native-asr-build}"
mkdir -p "$out"
zig cc -target arm-linux-gnueabihf.2.25 -shared -fPIC -Os -Wall -Wextra -Werror \
    native_asr.c -ldl -lpthread -o "$out/native_asr.so"
zig cc -target aarch64-linux-musl -static -Os -Wall -Wextra -Werror \
    native_asr_ctl.c -o "$out/native_asr_ctl"
