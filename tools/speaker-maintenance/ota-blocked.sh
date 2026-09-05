#!/bin/sh
# owner-maintenance-v1: native OTA is disabled; use reviewed patched images.
# Do not log arguments: an update URL may contain credentials.
logger -t owner-ota "Blocked native update entry: ${0##*/}" 2>/dev/null || :
echo 'Native firmware updates are disabled by the owner. Use a reviewed SSH-patched image.' >&2
exit 126
