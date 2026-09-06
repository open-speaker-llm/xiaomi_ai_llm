#!/bin/sh
# Build both ABIs: native audio is ARM32, the recorder runs on the ARM64 kernel.
set -eu
[ "$#" -eq 1 ] || { echo "usage: $0 output_directory" >&2; exit 2; }
src=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
mkdir -p "$1"
zig cc -target arm-linux-gnueabihf.2.25 -shared -fPIC -Os -Wall -Wextra -Werror \
    "$src/xaudio_pcm_tap.c" -ldl -o "$1/xaudio_pcm_tap.so"
zig cc -target aarch64-linux-musl -static -Os -Wall -Wextra -Werror \
    "$src/capture_pcm.c" -o "$1/capture_pcm"
