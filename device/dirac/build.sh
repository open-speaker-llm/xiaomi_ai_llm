#!/bin/sh
set -eu
cd "$(dirname "$0")"
out="${1:-/tmp/native-first-dirac-build}"
mkdir -p "$out"
zig cc -target arm-linux-gnueabihf.2.25 -shared -fPIC -Os -Wall -Wextra -Werror \
    dirac_init.c -ldl -o "$out/native_first_dirac.so"
