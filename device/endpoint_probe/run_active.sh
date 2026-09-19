#!/bin/sh
# Temporary ASR-only trials. No persistent installation or LLM/history writes.
set -eu
export XIAOMI_ENDPOINT_ACTIVE=1
exec sh "$(dirname "$0")/run_protocol.sh" "$@"
