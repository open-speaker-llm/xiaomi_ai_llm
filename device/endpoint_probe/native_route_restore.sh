#!/bin/sh
# Sourced by the temporary client runner. Old daily clients have no endpoint
# journal reader, so rollback crosses a fully stopped native-process boundary.
route_native_pids() {
    pidof mipns-xiaomi mico_aivs_lab 2>/dev/null || :
}
route_native_status() { sh /data/native_asr.sh status; }
route_wait_native() {
    local wanted="$1" attempt=0
    while [ "$attempt" -lt 50 ]; do
        case "$wanted" in
            stopped) [ -z "$(route_native_pids)" ] && return 0;;
            healthy) route_native_status >/dev/null 2>&1 && return 0;;
            *) return 1;;
        esac
        attempt=$((attempt+1))
        sleep 0.2
    done
    echo "Native service did not become $wanted within 10 seconds" >&2
    return 1
}
route_stop_native() {
    /etc/init.d/mico_aivs_lab stop || return 1
    /etc/init.d/pns stop || return 1
    route_wait_native stopped
}
route_start_native() {
    /etc/init.d/mico_aivs_lab start || return 1
    /etc/init.d/pns start || return 1
    route_wait_native healthy
}
route_restore_overlays_stopped() {
    sh /tmp/xiaomi_native_wake_probe/run_native_wake.sh restore-stopped
}
route_stop_session() {
    NATIVE_WAKE_SESSION_DIR=/tmp/xiaomi_native_wake_probe \
        sh /tmp/xiaomi_native_wake_probe/run_native_wake_session.sh stop
}
route_archive_log() {
    # Must run only after both native writers and the experimental client stop.
    # A failed copy/move never grants permission to restart the old reader.
    local source="$1" archive="$2"
    [ -d "$archive" ] && [ ! -L "$archive" ] || return 1
    if [ -e "$source" ] || [ -L "$source" ]; then
        [ -f "$source" ] && [ ! -L "$source" ] || return 1
        [ ! -e "$archive/instruction.log" ] && [ ! -L "$archive/instruction.log" ] || return 1
        mv "$source" "$archive/instruction.log" || return 1
        [ ! -e "$source" ] && [ ! -L "$source" ] || return 1
    fi
}
route_restore_legacy() {
    [ -e "$D/armed" ] || return 0
    [ "$(hash "$original")" = "$ORIGINAL_ROUTE_SHA256" ] || return 1
    route_stop_session || return 1
    stop_route_client || return 1
    route_stop_native || return 1
    route_restore_overlays_stopped || return 1
    [ -z "$(route_native_pids)" ] || return 1
    # Every attempt gets a separate archive; retry never overwrites evidence.
    local archive
    archive=$(mktemp -d "$D/rollback.XXXXXX") || return 1
    route_archive_log "$ROUTE_INSTRUCTION_LOG" "$archive" || return 1
    printf 'native-writers-stopped\n' > "$archive/boundary" || return 1
    route_start_native || return 1
    launch_client "$original" /tmp/native_first_client.log || return 1
    rm -f "$D/armed" "$D/timer.armed" || return 1
    echo ORIGINAL_CLIENT_RESTORED
}
