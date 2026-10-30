#!/bin/sh
set -eu
# 配置和 .env 由 Python 解析；不执行其中的 shell 文本。
cd "$(dirname "$0")"
server_python="${PYTHON:-.venv/bin/python}"
if [ ! -x "$server_python" ]; then
    echo "Python environment missing: $server_python; create .venv and install the selected requirements first." >&2
    exit 1
fi
exec "$server_python" -m server.run "$@"
