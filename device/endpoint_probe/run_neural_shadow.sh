#!/bin/sh
# Invoked by an explicit bounded trial. No daemon or automatic microphone use.
set -eu
[ "$#" -eq 3 ] || { [ "$#" -eq 4 ] && { [ "$4" = endpoint ] || [ "$4" = first-endpoint ] || [ "$4" = first-ready ]; }; } || exit 2
D=/tmp/xiaomi_neural_shadow
: "${EXPECTED_NEURAL_MANIFEST_SHA256:?}"
cd "$D"
actual=$(sha256sum runtime.sha256)
[ "${actual%% *}" = "$EXPECTED_NEURAL_MANIFEST_SHA256" ]
sha256sum -c runtime.sha256 >/dev/null
ulimit -c 0
ulimit -v 98304
ulimit -t 20
exec ./ld-linux-armhf.so.3 --library-path "$D" --preload "$D/libstdc++.so.6" \
    ./neural_shadow ./libsherpa-onnx-c-api.so ./silero_vad_v5.onnx "$@"
