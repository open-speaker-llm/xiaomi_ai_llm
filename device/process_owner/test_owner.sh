#!/bin/sh
# Isolated Linux test. Does not touch the real assistant, sound devices or network.
set -eu
OWNER=${1:?absolute path to test binary}
D=$(mktemp -d /tmp/native-owner-test.XXXXXX)
cleanup() {
    if [ -f "$D/client.pid.owner" ]; then
        "$OWNER" stop "$D/client.pid" "$D/client.sh" >/dev/null 2>&1 ||
            "$OWNER" stop "$D/client.pid" "$D/stubborn.sh" >/dev/null 2>&1 || {
                echo "test session still active; preserving $D for inspection" >&2
                return 1
            }
    fi
    for file in "$D"/native*.pid "$D"/sentinel.pid; do
        [ -f "$file" ] || continue
        pid=$(cat "$file"); [ -n "$pid" ] && kill "$pid" 2>/dev/null || :
    done
    rm -rf "$D"
}
trap cleanup EXIT INT TERM
cat > "$D/client.sh" <<'SH'
#!/bin/sh
D=${0%/*}; OWNER="$D/owner"
"$OWNER" check "$D/client.pid" "$D/client.sh" || exit 1
trap 'exit 0' TERM INT
trap 'echo cleaned >> "$D/cleanup"' EXIT
sleep 120 & echo $! > "$D/record.pid"
sleep 120 & echo $! > "$D/audio.pid"
(sleep 120 & echo $! > "$D/network.pid"; wait) &
"$OWNER" detach /bin/sleep 120 & echo $! > "$D/native.pid"
echo ready > "$D/ready"
wait
SH
cp "$OWNER" "$D/owner"; chmod 700 "$D/owner" "$D/client.sh"
run(){ rm -f "$D/ready"; "$D/owner" run "$D/client.pid" /bin/sh "$D/client.sh" >"$D/out" 2>&1 </dev/null &
    i=0; while [ ! -e "$D/ready" ]; do i=$((i+1)); [ "$i" -lt 50 ] || { cat "$D/out"; exit 1; }; sleep 1; done; }
assert_gone(){ [ ! -d "/proc/$1" ] || { echo "FAIL: owned PID $1 survived"; exit 1; }; }
assert_alive(){ kill -0 "$1" 2>/dev/null || { echo "FAIL: unrelated PID $1 stopped"; exit 1; }; }
run
rec=$(cat "$D/record.pid"); audio=$(cat "$D/audio.pid"); net=$(cat "$D/network.pid"); native=$(cat "$D/native.pid")
if "$D/owner" stop "$D/client.pid" "$D/not-client.sh" 2>/dev/null; then echo 'FAIL: wrong script accepted'; exit 1; fi
assert_alive "$rec"; assert_alive "$audio"; assert_alive "$net"
owner_pid=$(cat "$D/client.pid"); printf '%s\n' "$native" > "$D/client.pid"
if "$D/owner" stop "$D/client.pid" "$D/client.sh" 2>/dev/null; then echo 'FAIL: mismatched PID file accepted'; exit 1; fi
assert_alive "$rec"; assert_alive "$native"; printf '%s\n' "$owner_pid" > "$D/client.pid"
"$D/owner" stop "$D/client.pid" "$D/client.sh"
assert_gone "$rec"; assert_gone "$audio"; assert_gone "$net"; assert_alive "$native"
[ -f "$D/cleanup" ]; echo 'stop: owned children gone, detached native survives'
cp "$D/native.pid" "$D/native1.pid"
run
rec=$(cat "$D/record.pid"); audio=$(cat "$D/audio.pid"); net=$(cat "$D/network.pid"); native=$(cat "$D/native.pid")
cp "$D/native.pid" "$D/native2.pid"
run
assert_gone "$rec"; assert_gone "$audio"; assert_gone "$net"; assert_alive "$native"
"$D/owner" stop "$D/client.pid" "$D/client.sh"
echo 'restart: prior children gone, detached native survives'
sleep 120 & sentinel=$!; echo "$sentinel" > "$D/sentinel.pid"
printf '%s\n' "$sentinel" > "$D/client.pid"
if "$D/owner" stop "$D/client.pid" "$D/client.sh" 2>/dev/null; then echo 'FAIL: unmanaged live PID accepted'; exit 1; fi
assert_alive "$sentinel"; rm "$D/client.pid"
echo 'unmanaged PID: rejected without signal'

# A worker that ignores TERM must not survive escalation. The detached
# native sentinel must still be alive after the same stop.
cat > "$D/stubborn.sh" <<'SH'
#!/bin/sh
D=${0%/*}; "$D/owner" check "$D/client.pid" "$D/stubborn.sh" || exit 1
trap 'exit 0' TERM INT
sh -c 'trap "" TERM; exec sleep 120' & echo $! > "$D/stubborn.pid"
"$D/owner" detach /bin/sleep 120 & echo $! > "$D/native3.pid"
echo ready > "$D/stubborn.ready"
wait
SH
chmod 700 "$D/stubborn.sh"
"$D/owner" run "$D/client.pid" /bin/sh "$D/stubborn.sh" > "$D/out" 2>&1 </dev/null &
i=0; while [ ! -f "$D/stubborn.ready" ]; do i=$((i+1)); [ "$i" -lt 30 ] || exit 1; sleep 1; done
stubborn=$(cat "$D/stubborn.pid"); native=$(cat "$D/native3.pid")
sleep 1
"$D/owner" stop "$D/client.pid" "$D/stubborn.sh"
assert_gone "$stubborn"; assert_alive "$native"
echo 'TERM-resistant worker: escalated inside owned session only'
