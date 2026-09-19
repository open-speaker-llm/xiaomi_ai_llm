#!/bin/sh
# Daily entry point; all inference and ASR remain on the speaker/Xiaomi path.
set -eu
BASE=${NATIVE_ENDPOINT_PACKAGE_DIR:-/data/native_endpoint}
WAKE=/tmp/xiaomi_native_wake_probe
MODEL=/tmp/xiaomi_neural_shadow
MANAGER=$WAKE/native_resident_session
verify_package() {
    [ -d "$BASE" ] && [ ! -L "$BASE" ] || return 1
    (cd "$BASE" && sha256sum -c package.sha256 >/dev/null)
}
status() {
    [ -x "$MANAGER" ] && "$MANAGER" status
}
stop() {
    [ ! -x "$MANAGER" ] || "$MANAGER" stop
    [ ! -x "$WAKE/native_wake_pool" ] || "$WAKE/native_wake_pool" stop
}
stage_runtime() {
    local stage path target
    verify_package || return 1
    [ ! -e "$WAKE/timer.armed" ] && [ ! -e /tmp/xiaomi_native_route/armed ] || return 1
    for path in "$WAKE" "$MODEL"; do
        [ ! -L "$path" ] || return 1
        [ ! -e "$path" ] || [ -d "$path" ] || return 1
    done
    stop || return 1
    stage=$(mktemp -d /tmp/endpoint-stage.XXXXXX) || return 1
    tar xzf "$BASE/runtime.tar.gz" -C "$stage" || return 1
    (cd "$stage" && sha256sum -c runtime-files.sha256 >/dev/null) || return 1
    # Only explicitly packaged files; routes and cancellation records survive.
    while read -r digest path; do
        case "$path" in xiaomi_neural_shadow/*|xiaomi_native_wake_probe/*) ;; *) return 1;; esac
        case "$path" in *..*|*/*/*) return 1;; esac
        target=/tmp/$path
        [ ! -L "$target" ] || return 1
        [ ! -e "$target" ] || [ -f "$target" ] || return 1
        mkdir -p "$(dirname "$target")"
        chmod 700 "$(dirname "$target")"
        mv "$stage/$path" "$target" || return 1
    done < "$stage/runtime-files.sha256"
    rm "$stage/runtime-files.sha256"
    rmdir "$stage/xiaomi_neural_shadow" "$stage/xiaomi_native_wake_probe" "$stage"
}
start() {
    local manifest count=0
    verify_package || return 1
    [ "$(sha256sum /data/native_asr.so | cut -d ' ' -f 1)" = "$(sha256sum "$BASE/native_asr.so" | cut -d ' ' -f 1)" ] || return 1
    sh /data/native_asr.sh status >/dev/null || return 1
    status && return 0
    stage_runtime || return 1
    manifest=$(sha256sum "$MODEL/runtime.sha256" | cut -d ' ' -f 1)
    (trap '' HUP; EXPECTED_NEURAL_MANIFEST_SHA256="$manifest" exec "$MANAGER" service) > "$WAKE/daily.log" 2>&1 </dev/null &
    while [ "$count" -lt 100 ]; do
        status && return 0
        count=$((count+1)); sleep 0.2
    done
    echo 'ENDPOINT_NOT_READY: original native capture remains available' >&2
    return 1
}
case "${1:-status}" in
    start|stop) exec "$BASE/lifecycle" "$1";;
    _start) [ "${NATIVE_ENDPOINT_GUARDED:-}" = 1 ]; start;;
    _stop) [ "${NATIVE_ENDPOINT_GUARDED:-}" = 1 ]; stop;;
    status) status;;
    verify) verify_package;;
    *) exit 2;;
esac
