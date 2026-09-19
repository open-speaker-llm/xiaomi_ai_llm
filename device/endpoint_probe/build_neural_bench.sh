#!/bin/sh
# Independent file benchmark and guarded helper. Supply dependencies explicitly;
# this script neither downloads packages nor changes a speaker installation.
set -eu
[ "$#" -eq 2 ] || { echo 'usage: build_neural_bench.sh header_directory output_directory' >&2; exit 2; }
src=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
header=$(CDPATH= cd -- "$1" && pwd)
test -f "$header/c-api-1.10.36.h"
actual=$(shasum -a 256 "$header/c-api-1.10.36.h")
[ "${actual%% *}" = 90e4c96fc0c24c7cbedb24918bacc82c6bd896e35f992bf593e8c70fc54b01b4 ] || {
    echo 'sherpa-onnx C API header does not match the benchmark ABI' >&2
    exit 1
}
mkdir -p "$2"
for program in neural_vad_pcm neural_shadow neural_reset_bench neural_pool; do
    if [ "$program" = neural_pool ]; then
        zig cc -target arm-linux-gnueabihf.2.25 -Os -Wall -Wextra -Werror \
            -I"$header" "$src/$program.c" "$src/neural_clock.c" \
            -rdynamic -ldl -o "$2/$program"
        continue
    fi
    zig cc -target arm-linux-gnueabihf.2.25 -Os -Wall -Wextra -Werror \
        -I"$header" "$src/$program.c" -ldl -o "$2/$program"
done
zig cc -target arm-linux-gnueabihf.2.25 -Os -Wall -Wextra -Werror \
    "$src/test_neural_clock.c" "$src/neural_clock.c" -rdynamic -o "$2/test_neural_clock"
