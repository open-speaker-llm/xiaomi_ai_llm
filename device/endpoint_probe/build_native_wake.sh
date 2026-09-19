#!/bin/sh
set -eu
[ "$#" -eq 1 ] || { echo 'usage: build_native_wake.sh output_directory' >&2; exit 2; }
src=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
mkdir -p "$1"
zig cc -target arm-linux-gnueabihf.2.25 -Os -Wall -Wextra -Werror -shared -fPIC \
    "$src/native_wake_probe.c" -ldl -lpthread -o "$1/native_wake_probe.so"
zig cc -target arm-linux-gnueabihf.2.25 -Os -Wall -Wextra -Werror \
    "$src/native_wake_watch.c" -o "$1/native_wake_watch"
zig cc -target arm-linux-gnueabihf.2.25 -Os -Wall -Wextra -Werror \
    "$src/native_wake_session.c" -o "$1/native_wake_session"
zig cc -target arm-linux-gnueabihf.2.25 -Os -UNDEBUG -Wall -Wextra -Werror -Wl,--export-dynamic \
    "$src/test_first_endpoint.c" -ldl -lpthread -o "$1/test_first_endpoint"
zig cc -target arm-linux-gnueabihf.2.25 -Os -UNDEBUG -Wall -Wextra -Werror \
    '-DNW_DIR="/tmp/native_recovery_unit"' \
    "$src/test_native_recovery.c" -o "$1/test_native_recovery"
zig cc -target arm-linux-gnueabihf.2.25 -Os -UNDEBUG -Wall -Wextra -Werror \
    '-DNW_DIR="/tmp/native_retention_unit"' \
    "$src/test_native_route_retention.c" -o "$1/test_native_route_retention"
cp "$src/run_native_wake.sh" "$1/"
cp "$src/run_native_wake_session.sh" "$1/"
zig cc -target arm-linux-gnueabihf.2.25 -Os -Wall -Wextra -Werror \
    "$src/native_wake_pool.c" -o "$1/native_wake_pool"

zig cc -target arm-linux-gnueabihf.2.25 -Os -Wall -Wextra -Werror \
    "$src/native_restore_guard.c" -o "$1/native_restore_guard"
cp "$src/native_route_restore.sh" "$src/run_route_client.sh" "$1/"

zig cc -target arm-linux-gnueabihf.2.25 -Os -Wall -Wextra -Werror \
    "$src/native_resident_session.c" -o "$1/native_resident_session"

cp "$src/native_resident_lease.sh" "$1/"
