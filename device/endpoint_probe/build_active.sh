#!/bin/sh
set -eu
[ "$#" -eq 2 ] || { echo 'usage: build_active.sh libfvad_checkout output_directory' >&2; exit 2; }
src=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
vad=$(CDPATH= cd -- "$1" && pwd)
[ "$(git -C "$vad" rev-parse HEAD)" = 532ab666c20d3cfda38bca63abbb0f152706c369 ]
[ -z "$(git -C "$vad" status --porcelain --untracked-files=all)" ]
mkdir -p "$2"
for program in protocol_probe.so active_pcm filter_vad_pcm noise_vad_pcm test_endpoint_active test_active_probe; do
    case "$program" in
    protocol_probe.so) input=active_probe.c; set -- "$1" "$2" -shared -fPIC;;
    active_pcm) input=active_pcm.c; set -- "$1" "$2";;
    filter_vad_pcm) input=filter_vad_pcm.c; set -- "$1" "$2";;
    noise_vad_pcm) input=noise_vad_pcm.c; set -- "$1" "$2";;
    test_endpoint_active) input=test_endpoint_active.c; set -- "$1" "$2";;
    test_active_probe) input=test_protocol_probe.c; set -- "$1" "$2" -DPROBE_ACTIVE_ENDPOINT;;
    esac
    vad_arg=$1;out=$2;shift 2
    zig cc -target arm-linux-gnueabihf.2.25 -Os -UNDEBUG -Wall -Wextra -Werror \
        -DPROBE_DIR='"/tmp/xiaomi_endpoint_active"' \
        -I"$vad/include" -I"$vad/src" "$src/$input" "$@" \
        "$vad/src/fvad.c" "$vad"/src/signal_processing/*.c "$vad"/src/vad/*.c \
        -ldl -lpthread -o "$out/$program"
    set -- "$vad_arg" "$out"
done
for file in LICENSE PATENTS AUTHORS; do cp "$vad/$file" "$2/libfvad-$file"; done
cp "$src/run_protocol.sh" "$src/run_active.sh" "$2/"
