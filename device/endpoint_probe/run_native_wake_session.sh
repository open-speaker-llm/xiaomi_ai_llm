#!/bin/sh
# Keep the existing entry point; the supervisor itself owns locks and children.
set -eu
D=${NATIVE_WAKE_SESSION_DIR:-/tmp/xiaomi_native_wake_probe}
[ "${1:-}" = stop ] || : "${EXPECTED_NEURAL_MANIFEST_SHA256:?}"
if [ "${1:-}" = stop ] && [ -x "$D/native_resident_session" ]; then
    "$D/native_resident_session" stop
fi
if [ "${1:-}" = resident ]; then
    [ "$#" -le 2 ] || exit 2
    . "$D/native_resident_lease.sh"
    seconds=${2:-3600}
    now=$(awk '{print int($1)}' /proc/uptime)
    resident_timer_covers "$D" "$seconds" "$now" || { echo 'RESIDENT_REFUSED wake_restore_lease' >&2; exit 2; }
    resident_timer_covers /tmp/xiaomi_native_route "$seconds" "$now" || { echo 'RESIDENT_REFUSED client_restore_lease' >&2; exit 2; }
    exec "$D/native_resident_session" "$seconds"
fi
if [ "${1:-}" = pool ]; then
    shift
    [ "$#" -le 2 ] || exit 2
    if [ "$#" -eq 2 ]; then exec "$D/native_wake_pool" "$1" "$2"; fi
    exec "$D/native_wake_pool" "${1:-180}"
fi
exec "$D/native_wake_session" "$@"
