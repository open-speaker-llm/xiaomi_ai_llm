#!/bin/sh
# Build auditable static Linux helpers for separate device architectures.
set -eu
OUT=${1:?usage: build.sh NEW_OUTPUT_DIRECTORY}
[ ! -e "$OUT" ] || { echo 'output already exists' >&2; exit 1; }
mkdir "$OUT"
SRC=$(CDPATH= cd -- "$(dirname "$0")" && pwd)/process_owner.c
zig cc -target arm-linux-musleabihf -static -Os -Wall -Wextra -Werror "$SRC" -o "$OUT/native_process_owner-arm32"
zig cc -target aarch64-linux-musl -static -Os -Wall -Wextra -Werror "$SRC" -o "$OUT/native_process_owner-aarch64"
echo "Built helper binaries in $OUT; verify firmware architecture and hashes before installation."
