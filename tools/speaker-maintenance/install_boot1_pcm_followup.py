#!/usr/bin/env python3
"""Install verified boot1 PCM follow-up files, with a private on-device rollback.

Run only on an idle S12A ROM 1.76.54 after the ASR endpoint is ready.
No firmware partition is flashed. Existing boot0 settings are retained.
"""
import argparse
import hashlib
from pathlib import Path
import shlex
import subprocess
import time


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host', required=True)
    p.add_argument('--build-dir', type=Path, required=True)
    p.add_argument('--asr-server', required=True)
    a = p.parse_args()
    root = Path(__file__).resolve().parents[2]
    files = {
        'native_first_client.sh': root / 'device/native_first_client.sh',
        'native_pcm_tap.sh': root / 'device/pcm_tap/native_pcm_tap.sh',
        'xaudio_pcm_tap.so': a.build_dir / 'xaudio_pcm_tap.so',
        'capture_pcm': a.build_dir / 'capture_pcm',
    }
    ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=yes',
           '-o', 'HostKeyAlgorithms=+ssh-rsa', '-o', 'PubkeyAcceptedAlgorithms=+ssh-rsa', 'root@' + a.host]
    def run(script):
        return subprocess.run(ssh + ['sh -s'], input=script.encode(), check=True)
    stage = '/tmp/native-pcm-install-' + str(int(time.time()))
    run('set -e\n[ "$(awk \'$2 == "/" {print $1; exit}\' /proc/mounts)" = /dev/mtdblock5 ]\n'
        '[ ! -f /tmp/native_first_busy ]\numask 077\nmkdir ' + stage + '\n')
    for name, source in files.items():
        data = source.read_bytes()
        dest = stage + '/' + name
        subprocess.run(ssh + ['cat > ' + dest], input=data, check=True)
        run('[ "$(sha256sum ' + dest + ' | awk \'{print $1}\')" = ' + hashlib.sha256(data).hexdigest() + ' ]\n')
    rollback = '''#!/bin/sh
set -eu
backup=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
for pid in $(ps | awk '$5 == "sh" && ($6 == "/data/native_first_client.sh" || $6 == "/tmp/boot1_followup_client.sh") {print $1}'); do kill -9 "$pid" 2>/dev/null || true; done
killall aivs_speech_guard 2>/dev/null || true
killall -CONT mediaplayer 2>/dev/null || true
killall -CONT mipns-xiaomi 2>/dev/null || true
if [ -f /data/native_pcm_tap.sh ]; then sh /data/native_pcm_tap.sh stop || true; fi
rm -f /tmp/native_first_busy /tmp/native_first_player_frozen /tmp/native_first_aivs_guard_armed
for name in native_first_client.sh native_first.env native_pcm_tap.sh xaudio_pcm_tap.so capture_pcm; do
    if [ -f "$backup/$name" ]; then
        cp -p "$backup/$name" "/data/$name.restore"
        mv "/data/$name.restore" "/data/$name"
    elif [ -f "$backup/absent_$name" ]; then
        rm -f "/data/$name"
    fi
done
sh -c 'trap "" HUP; sh /data/native_first_client.sh >/tmp/native_first_autostart.log 2>&1 </dev/null &'
echo restored
'''
    subprocess.run(ssh + ['cat > ' + stage + '/restore.sh'], input=rollback.encode(), check=True)
    script = r'''set -eu
[ ! -f /tmp/native_first_busy ]
# Refuse incompatible native binaries before changing the running setup.
[ "$(sha256sum /usr/bin/mipns-xiaomi | awk '{print $1}')" = a02071a39f3509d3a90dac638e323039a24de784a907f076a0a91f81cd5fbb9d ]
[ "$(sha256sum /usr/lib/libxaudio_engine.so | awk '{print $1}')" = 79f1a33d9683cd6940c8d23e3dd4e992f1958fe220c0dfff8d230f9f8a1b5e73 ]
if awk '$2 == "/etc/init.d/pns" {found=1} END {exit !found}' /proc/mounts; then
    grep -q 'LD_PRELOAD=/tmp/xaudio_pcm_tap.so' /etc/init.d/pns || grep -q 'NATIVE_PCM_TAP_MANAGED_V1' /etc/init.d/pns
fi
backup=/data/native-pcm-backup-$(date +%Y%m%d-%H%M%S)
umask 077
mkdir "$backup"
for name in native_first_client.sh native_first.env native_pcm_tap.sh xaudio_pcm_tap.so capture_pcm; do
    if [ -f "/data/$name" ]; then cp -p "/data/$name" "$backup/$name"; else touch "$backup/absent_$name"; fi
done
cp "$stage/restore.sh" "$backup/restore.sh"
chmod 700 "$backup/restore.sh"
cp /data/native_first.env "$stage/native_first.env"
cat >> "$stage/native_first.env" <<'CONFIG'

# boot1 processed PCM followup; boot0 recorder and ASR remain as configured.
SYSTEM1_FOLLOWUP_ENABLED=1
SYSTEM1_FOLLOWUP_RECORD_MODE=native_pcm
SYSTEM1_FOLLOWUP_ASR_ENGINE=mac
PCM_CAPTURE_BIN=/data/capture_pcm
PCM_TAP_MANAGER=/data/native_pcm_tap.sh
PCM_CAPTURE_SECONDS=8
FOLLOWUP_ASR_TIMEOUT=30
PAUSE_NATIVE_ASR_DURING_LLM=0
CONFIG
printf '\nSERVER=%s\n' "$asr_quoted" >> "$stage/native_first.env"
sh -n "$stage/native_first.env"
sh -n "$stage/native_first_client.sh"
sh -n "$stage/native_pcm_tap.sh"
# Restore the backed-up client if any mutation or health check below fails.
trap 'sh "$backup/restore.sh"' EXIT
for pid in $(ps | awk '$5 == "sh" && ($6 == "/data/native_first_client.sh" || $6 == "/tmp/boot1_followup_client.sh") {print $1}'); do kill -9 "$pid" 2>/dev/null || true; done
killall aivs_speech_guard 2>/dev/null || true
killall -CONT mediaplayer 2>/dev/null || true
if grep -q 'NATIVE_PCM_TAP_MANAGED_V1' /etc/init.d/pns; then
    sh /data/native_pcm_tap.sh stop
elif grep -q 'LD_PRELOAD=/tmp/xaudio_pcm_tap.so' /etc/init.d/pns; then
    umount /etc/init.d/pns
fi
for name in native_first_client.sh native_pcm_tap.sh xaudio_pcm_tap.so capture_pcm native_first.env; do
    cp "$stage/$name" "/data/$name.new"
    case "$name" in *.env) chmod 600 "/data/$name.new";; *) chmod 755 "/data/$name.new";; esac
    mv "/data/$name.new" "/data/$name"
done
rm -f /tmp/native_first_busy /tmp/native_first_player_frozen /tmp/native_first_aivs_guard_armed
sh -c 'trap "" HUP; sh /data/native_first_client.sh >/tmp/native_first_autostart.log 2>&1 </dev/null &'
sleep 8
sh /data/native_pcm_tap.sh status
grep -q '\[IDLE\] 等待原生唤醒词' /tmp/native_first_client.log
trap - EXIT
echo "BACKUP=$backup"
sha256sum /data/native_first_client.sh /data/native_pcm_tap.sh /data/xaudio_pcm_tap.so /data/capture_pcm
'''
    # Both assignments contain shell-quoted values; no command substitution from input.
    run('stage=' + shlex.quote(stage) + '\nasr_quoted=' + shlex.quote(shlex.quote(a.asr_server)) + '\n' + script)


if __name__ == '__main__':
    main()
