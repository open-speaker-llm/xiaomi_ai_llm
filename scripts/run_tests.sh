#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
    if [ -x ".venv/bin/python" ]; then
        PYTHON=".venv/bin/python"
    else
        PYTHON="python3"
    fi
fi

echo "== Python unit tests =="
"$PYTHON" -m unittest discover -s tests -p 'test_*.py'

echo "== Shell syntax =="
for script in \
    device/native_first_client.sh \
    device/vad_record.sh \
    device/native_result_timing_probe.sh \
    device/stream_client.sh \
    device/wake_monitor.sh
do
    sh -n "$script"
done

echo "OK"
