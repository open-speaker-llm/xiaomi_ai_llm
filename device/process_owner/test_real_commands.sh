#!/bin/sh
# Exercises real ALSA programs against the null device, plus a controlled HTTP
# endpoint that holds the connection open. No physical microphone is opened.
set -eu
OWNER=${1:?owner binary}; URL=${2:?controlled slow URL}
D=$(mktemp -d /tmp/native-owner-real.XXXXXX)
cleanup(){ [ ! -f "$D/pid.owner" ] || "$D/owner" stop "$D/pid" "$D/client.sh" >/dev/null 2>&1 || :; rm -rf "$D"; }
trap cleanup EXIT INT TERM
cp "$OWNER" "$D/owner"; chmod 700 "$D/owner"
cat > "$D/client.sh" <<'SH'
#!/bin/sh
D=${0%/*}
"$D/owner" check "$D/pid" "$D/client.sh" || exit 1
trap 'exit 0' TERM INT
arecord -D null -t raw -f S16_LE -r 16000 -c 1 >/dev/null 2>"$D/record.err" & echo $! >"$D/record.pid"
tail -f /dev/null | aplay -D null -t raw -f S16_LE -r 16000 -c 1 >/dev/null 2>"$D/play.err" & echo $! >"$D/play.pid"
curl -sS -m 40 "$TEST_URL" >/dev/null 2>"$D/network.err" & echo $! >"$D/network.pid"
echo ready > "$D/ready"
wait
SH
chmod 700 "$D/client.sh"
TEST_URL="$URL"; export TEST_URL
"$D/owner" run "$D/pid" /bin/sh "$D/client.sh" >"$D/log" 2>&1 </dev/null &
i=0; while [ ! -e "$D/ready" ]; do i=$((i+1)); [ "$i" -lt 20 ] || exit 1; sleep 1; done
sleep 1
for pair in 'record arecord' 'play aplay' 'network curl'; do
    set -- $pair; pid=$(cat "$D/$1.pid"); [ "$(cat /proc/$pid/comm)" = "$2" ] || { echo "FAIL: $2 not running"; exit 1; }
done
for name in mipns-xiaomi mico_aivs_lab mediaplayer; do pidof "$name" > "$D/native.$name" || exit 1; done
"$D/owner" stop "$D/pid" "$D/client.sh"
for name in record play network; do pid=$(cat "$D/$name.pid"); [ ! -d "/proc/$pid" ] || { echo "FAIL: $name survived"; exit 1; }; done
for name in mipns-xiaomi mico_aivs_lab mediaplayer; do [ "$(pidof "$name")" = "$(cat "$D/native.$name")" ] || { echo "FAIL: native $name changed"; exit 1; }; done
echo 'real arecord/aplay/curl stopped; native service PIDs unchanged'
