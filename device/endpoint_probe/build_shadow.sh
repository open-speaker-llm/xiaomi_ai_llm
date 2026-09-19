#!/bin/sh
# Uses an explicitly supplied, pinned libfvad checkout. No automatic downloads.
set -eu
[ "$#" -eq 2 ] || { echo 'usage: build_shadow.sh libfvad_checkout output_directory' >&2; exit 2; }
src=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
vad=$(CDPATH= cd -- "$1" && pwd)
[ "$(git -C "$vad" rev-parse HEAD)" = 532ab666c20d3cfda38bca63abbb0f152706c369 ]
[ -z "$(git -C "$vad" status --porcelain --untracked-files=all)" ]
mkdir -p "$2"
for program in shadow_pcm shadow_capture; do
    case "$program" in
        shadow_pcm) input="$src/shadow_pcm.c";;
        shadow_capture) input="$src/../pcm_tap/capture_pcm.c";;
    esac
    zig cc -target arm-linux-gnueabihf.2.25 -Os -UNDEBUG -Wall -Wextra -Werror \
        -DPCM_ENDPOINT_SHADOW -I"$vad/include" -I"$vad/src" "$input" \
        "$vad/src/fvad.c" "$vad"/src/signal_processing/*.c "$vad"/src/vad/*.c \
        -o "$2/$program"
done
# Keep the third-party redistribution notices alongside diagnostic binaries.
cp "$vad/LICENSE" "$2/libfvad-LICENSE"
cp "$vad/PATENTS" "$2/libfvad-PATENTS"
cp "$vad/AUTHORS" "$2/libfvad-AUTHORS"
