#!/bin/sh
set -eu
[ "$#" -eq 0 ] || exit 2
D=/tmp/xiaomi_neural_shadow
: "${EXPECTED_NEURAL_MANIFEST_SHA256:?}"
cd "$D"
actual=$(sha256sum runtime.sha256)
[ "${actual%% *}" = "$EXPECTED_NEURAL_MANIFEST_SHA256" ]
sha256sum -c runtime.sha256 >/dev/null
ulimit -c 0
ulimit -v 98304
ulimit -S -t 15
exec ./ld-linux-armhf.so.3 --library-path "$D" --preload "$D/libstdc++.so.6" \
    ./neural_pool ./libsherpa-onnx-c-api.so ./silero_vad_v5.onnx
