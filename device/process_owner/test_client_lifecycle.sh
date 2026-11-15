#!/bin/sh
# Run only a generated fixture and a controlled slow HTTP endpoint.
set -eu
OWNER=${1:?owner binary}; FIXTURE=${2:?generated fixture}; URL=${3:?controlled slow HTTP URL}
D=/tmp/native-owner-ci
[ ! -e "$D/client.pid.owner" ] || { echo 'fixture already active'; exit 1; }
mkdir -p "$D"
cleanup() { sh "$D/client.sh" stop >/dev/null 2>&1 || :; }
trap cleanup EXIT INT TERM
cp "$FIXTURE" "$D/client.sh"; chmod 700 "$D/client.sh"
CONFIG_FILE="$D/no-config"; NATIVE_PROCESS_OWNER="$OWNER"; PID_FILE="$D/client.pid"; LOG_FILE="$D/client.log"
TTS_ENGINE=device; FOLLOWUP_ASR_ENGINE=none; TEST_URL="$URL"
export CONFIG_FILE NATIVE_PROCESS_OWNER PID_FILE LOG_FILE TTS_ENGINE FOLLOWUP_ASR_ENGINE TEST_URL
for n in mipns-xiaomi mico_aivs_lab mediaplayer; do pidof "$n" > "$D/native.$n" || exit 1; done
start() {
    rm -f "$D/record.pid" "$D/play.pid" "$D/curl.pid"
    sh "$D/client.sh" >"$D/outer.log" 2>&1 </dev/null &
    i=0; while [ ! -f "$D/curl.pid" ]; do i=$((i+1)); [ "$i" -lt 30 ] || { cat "$D/outer.log"; exit 1; }; sleep 1; done
    for pair in 'record arecord' 'play aplay' 'curl curl'; do
        set -- $pair; pid=$(cat "$D/$1.pid"); [ "$(cat /proc/$pid/comm)" = "$2" ] || exit 1
    done
}
remember() { for n in record play curl; do cp "$D/$n.pid" "$D/$n.old"; done; }
check_old() { for n in record play curl; do pid=$(cat "$D/$n.old"); [ ! -d "/proc/$pid" ] || { echo "$n survived"; exit 1; }; done; }
check_native() { for n in mipns-xiaomi mico_aivs_lab mediaplayer; do [ "$(pidof "$n")" = "$(cat "$D/native.$n")" ] || { echo "$n changed"; exit 1; }; done; }
start; remember; start; check_old; check_native
echo 'client restart: old arecord/aplay/curl gone; native PIDs unchanged'
remember; sh "$D/client.sh" stop; check_old; check_native
echo 'client stop: arecord/aplay/curl gone; native PIDs unchanged'
