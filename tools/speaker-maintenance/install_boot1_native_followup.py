#!/usr/bin/env python3
"""Install boot1 native ASR followup with firmware gates and exact rollback."""
import argparse
import hashlib
import shlex
import subprocess
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='192.168.8.152')
    parser.add_argument('--build-dir', type=Path, required=True)
    root = Path(__file__).resolve().parents[2]
    parser.add_argument('--client', type=Path, default=root / 'device/native_first_client.sh')
    parser.add_argument('--manager', type=Path, default=root / 'device/native_asr/native_asr.sh')
    args = parser.parse_args()
    ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=yes',
           '-o', 'HostKeyAlgorithms=+ssh-rsa', '-o', 'PubkeyAcceptedAlgorithms=+ssh-rsa', 'root@' + args.host]

    def remote(command, data=None, timeout=90):
        result = subprocess.run(ssh + [command], input=data, capture_output=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError(result.stdout.decode(errors='replace') + result.stderr.decode(errors='replace'))
        return result.stdout.decode()

    files = {
        'native_first_client.sh': args.client,
        'native_asr.sh': args.manager,
        'native_asr.so': args.build_dir / 'native_asr.so',
        'native_asr_ctl': args.build_dir / 'native_asr_ctl',
    }
    for path in files.values():
        if not path.is_file():
            raise SystemExit(f'Missing input: {path}')
    stage = f'/tmp/native-asr-install-{int(time.time())}'
    remote('set -e; [ "$(awk \'$2=="/" {print $1;exit}\' /proc/mounts)" = /dev/mtdblock5 ]; '
           '[ ! -e /tmp/native_first_busy ]; umask 077; mkdir ' + shlex.quote(stage))
    hashes = []
    for name, path in files.items():
        data = path.read_bytes()
        target = stage + '/' + name
        remote('cat > ' + shlex.quote(target), data)
        hashes.append(f'[ "$(sha256sum {shlex.quote(target)} | awk \'{{print $1}}\')" = {hashlib.sha256(data).hexdigest()} ]')
    script = r'''set -eu
STAGE=__STAGE__
__HASHES__
[ ! -e /tmp/native_first_busy ]
[ "$(awk '$2=="/" {print $1;exit}' /proc/mounts)" = /dev/mtdblock5 ]
sh -n "$STAGE/native_first_client.sh"
sh -n "$STAGE/native_asr.sh"
# Read-only ABI validation using the staged manager's function definitions.
sed '/^case "${1:-status}"/,$d' "$STAGE/native_asr.sh" > "$STAGE/verify.sh"
sh -c '. "$1"; verified' sh "$STAGE/verify.sh"
BACKUP=/data/native-asr-backup-$(date +%Y%m%d-%H%M%S)
umask 077
mkdir "$BACKUP"
for f in native_first_client.sh native_first.env native_asr.sh native_asr.so native_asr_ctl; do
    if [ -f "/data/$f" ]; then cp -p "/data/$f" "$BACKUP/$f"; else touch "$BACKUP/$f.absent"; fi
done
cat > "$BACKUP/restore.sh" <<'RESTORE'
#!/bin/sh
set -eu
BACKUP=$(cd "$(dirname "$0")" && pwd)
[ ! -e /tmp/native_first_busy ] || { echo 'Client busy; wait for idle before restore' >&2; exit 1; }
ps | awk '$5=="sh" && $6=="/data/native_first_client.sh" {print $1}' | xargs -r kill -9 2>/dev/null || true
killall aivs_speech_guard 2>/dev/null || true
killall -CONT mediaplayer 2>/dev/null || true
if [ -f /data/native_asr.sh ]; then sh /data/native_asr.sh stop; fi
for f in native_first_client.sh native_first.env native_asr.sh native_asr.so native_asr_ctl; do
    if [ -f "$BACKUP/$f.absent" ]; then rm -f "/data/$f"; else cp -p "$BACKUP/$f" "/data/$f"; fi
done
rm -f /tmp/native_first_player_frozen /tmp/native_first_aivs_guard_armed
sh -c 'trap "" HUP; sh /data/native_first_client.sh >/tmp/native_first_autostart.log 2>&1 </dev/null &'
echo "restored $BACKUP"
RESTORE
chmod 700 "$BACKUP/restore.sh"
trap 'sh "$BACKUP/restore.sh"' 0
ps | awk '$5=="sh" && $6=="/data/native_first_client.sh" {print $1}' | xargs -r kill -9 2>/dev/null || true
killall aivs_speech_guard 2>/dev/null || true
killall -CONT mediaplayer 2>/dev/null || true
if grep -q NATIVE_PCM_TAP_MANAGED_V1 /etc/init.d/pns; then sh /data/native_pcm_tap.sh stop; fi
if [ -f /data/native_asr.sh ]; then sh /data/native_asr.sh stop; fi
for f in native_first_client.sh native_asr.sh native_asr.so native_asr_ctl; do
    cp "$STAGE/$f" "/data/$f.new"
    chmod 755 "/data/$f.new"
    mv "/data/$f.new" "/data/$f"
done
cp /data/native_first.env /data/native_first.env.new
cat >> /data/native_first.env.new <<'CONFIG'

# boot1 native live ASR-only followup; boot0 keeps its existing file-ASR path.
SYSTEM1_FOLLOWUP_ENABLED=1
SYSTEM1_FOLLOWUP_RECORD_MODE=native_live
SYSTEM1_FOLLOWUP_ASR_ENGINE=native_live
NATIVE_ASR_MANAGER=/data/native_asr.sh
NATIVE_ASR_CTL=/data/native_asr_ctl
NATIVE_ASR_LISTEN_TIMEOUT=20
PAUSE_NATIVE_ASR_DURING_LLM=0
CONFIG
chmod 600 /data/native_first.env.new
mv /data/native_first.env.new /data/native_first.env
rm -f /tmp/native_first_player_frozen /tmp/native_first_aivs_guard_armed
sh /data/native_asr.sh start
sh -c 'trap "" HUP; sh /data/native_first_client.sh >/tmp/native_first_autostart.log 2>&1 </dev/null &'
sleep 6
sh /data/native_asr.sh status
grep -q '\[IDLE\]' /tmp/native_first_client.log
trap - 0
echo "BACKUP=$BACKUP"
sha256sum /data/native_first_client.sh /data/native_asr.sh /data/native_asr.so /data/native_asr_ctl
'''.replace('__STAGE__', shlex.quote(stage)).replace('__HASHES__', '\n'.join(hashes))
    print(remote('sh -s', script.encode(), timeout=110))


if __name__ == '__main__':
    main()
