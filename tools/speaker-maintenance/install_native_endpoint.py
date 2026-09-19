#!/usr/bin/env python3
"""Stage or activate the verified daily endpoint package, with exact rollback."""
import argparse,hashlib,shlex,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--host',default='192.168.8.152')
p.add_argument('--package',type=Path,required=True)
p.add_argument('--activate-stage',help='Previously prepared absolute /tmp endpoint stage')
p.add_argument('--reuse-installed-package',action='store_true',help='Re-activate an identical, verified package after rollback')
a=p.parse_args();root=Path(__file__).resolve().parents[2]
ssh=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=8','-o','HostKeyAlgorithms=+ssh-rsa','-o','PubkeyAcceptedKeyTypes=+ssh-rsa','root@'+a.host]
def remote(command,data=None,timeout=120):
 r=subprocess.run(ssh+[command],input=data,capture_output=True,timeout=timeout)
 if r.returncode:raise RuntimeError(r.stdout.decode(errors='replace')+r.stderr.decode(errors='replace'))
 return r.stdout.decode()
files=['runtime.tar.gz','native_asr.so','native_first_client.sh','manager.sh','lifecycle','package.sha256']
if not a.activate_stage:
 stage='/tmp/endpoint-install-'+str(int(time.time()))
 remote('set -eu; [ ! -e /data/native_endpoint ]; [ ! -e /tmp/native_first_busy ]; umask 077; mkdir '+shlex.quote(stage))
 for name in files:
  data=(a.package/name).read_bytes();target=shlex.quote(stage+'/'+name)
  remote('cat > '+target,data)
  remote('[ "$(sha256sum '+target+' | cut -d " " -f 1)" = '+hashlib.sha256(data).hexdigest()+' ]')
 # Reuse the previously tested stop/archive/start functions, not a killall path.
 runner=(root/'device/endpoint_probe/run_route_client.sh').read_text().split('case "${1:-}" in',1)[0]
 runner=runner.replace('. "$D/native_route_restore.sh"','. "$ENDPOINT_INSTALL_BACKUP/native_route_restore.sh"')
 remote('cat > '+shlex.quote(stage+'/client-functions.sh'),runner.encode())
 remote('cat > '+shlex.quote(stage+'/native_route_restore.sh'),(root/'device/endpoint_probe/native_route_restore.sh').read_bytes())
 print(remote('set -eu; cd '+shlex.quote(stage)+'; sha256sum -c package.sha256; sh -n manager.sh; df -k /data'))
 print('STAGE='+stage)
else:
 stage=a.activate_stage
 if not stage.startswith('/tmp/endpoint-install-') or not stage.rsplit('-',1)[1].isdigit():raise SystemExit('Invalid stage')
 # Values verified before any mutation; old configs never printed or copied off-device.
 script=r'''set -eu
STAGE=__STAGE__
cd "$STAGE"
sha256sum -c package.sha256 >/dev/null
if [ __REUSE__ = 1 ]; then
 [ -d /data/native_endpoint ] && [ ! -L /data/native_endpoint ]
 cmp "$STAGE/package.sha256" /data/native_endpoint/package.sha256
 (cd /data/native_endpoint && sha256sum -c package.sha256 >/dev/null)
else
 [ ! -e /data/native_endpoint ]
fi
[ ! -e /tmp/native_first_busy ]
[ ! -e /tmp/xiaomi_native_wake_probe/timer.armed ]
[ ! -e /tmp/xiaomi_native_route/armed ]
sh /data/native_asr.sh status
[ "$(sha256sum /data/native_first_client.sh | cut -d ' ' -f 1)" = 70a7012f2c68c7ebc8e545d9481845068406a476dc4cff7e68808fe671f8f184 ]
[ "$(sha256sum /data/native_asr.so | cut -d ' ' -f 1)" = 8a7d11ac76c90b60d7e42de48c02b3390205ce440650f0ef524a0c929091b0d6 ]
[ "$(sha256sum /data/native_asr.sh | cut -d ' ' -f 1)" = ecf34e250505d488eaa2b41fbe1280f46d91d56abc0a1b7482ff185d4fd5b93f ]
sed '/^case "${1:-status}"/,$d' /data/native_asr.sh > "$STAGE/verify-abi.sh"
sh -c '. "$1"; verified' sh "$STAGE/verify-abi.sh"
available=$(df -k /data | awk 'NR==2 {print $4}')
needed=$(du -k "$STAGE" | tail -n 1 | awk '{print $1}')
[ __REUSE__ != 1 ] || needed=0
[ "$available" -gt "$((needed+1024))" ]
BACKUP=/data/endpoint-backup-$(date +%Y%m%d-%H%M%S)
umask 077
mkdir "$BACKUP"
for name in native_first_client.sh native_first.env native_asr.so; do cp -p "/data/$name" "$BACKUP/$name"; done
cp "$STAGE/client-functions.sh" "$STAGE/native_route_restore.sh" "$BACKUP/"
(cd "$BACKUP" && sha256sum native_first_client.sh native_first.env native_asr.so > before.sha256)
cat > "$BACKUP/restore.sh" <<'RESTORE'
#!/bin/sh
set -eu
BACKUP=$(cd "$(dirname "$0")" && pwd)
export ENDPOINT_INSTALL_BACKUP="$BACKUP"
(cd "$BACKUP" && sha256sum -c before.sha256 >/dev/null)
[ ! -e /tmp/native_first_busy ] || { echo 'Wait for idle before rollback' >&2; exit 1; }
if [ -x /tmp/xiaomi_native_wake_probe/native_resident_session ]; then /tmp/xiaomi_native_wake_probe/native_resident_session stop; fi
if [ -x /tmp/xiaomi_native_wake_probe/native_wake_pool ]; then /tmp/xiaomi_native_wake_probe/native_wake_pool stop; fi
. "$BACKUP/client-functions.sh"
stop_route_client
route_stop_native
archive=$(mktemp -d /tmp/endpoint-rollback.XXXXXX)
route_archive_log "$ROUTE_INSTRUCTION_LOG" "$archive"
for name in native_first_client.sh native_first.env native_asr.so; do
 cp -p "$BACKUP/$name" "/data/$name.endpoint-restore"
 mv "/data/$name.endpoint-restore" "/data/$name"
done
route_start_native
launch_client /data/native_first_client.sh /tmp/native_first_client.log
[ ! -e /tmp/native_first_busy ]
echo "ENDPOINT_ROLLED_BACK backup=$BACKUP archive=$archive"
RESTORE
chmod 700 "$BACKUP/restore.sh"
export ENDPOINT_INSTALL_BACKUP="$BACKUP"
. "$BACKUP/client-functions.sh"
# If activation fails after this point, recover the old client and ASR library.
trap 'sh "$BACKUP/restore.sh"' EXIT
stop_route_client
route_stop_native
archive=$(mktemp -d /tmp/endpoint-activation.XXXXXX)
route_archive_log "$ROUTE_INSTRUCTION_LOG" "$archive"
if [ __REUSE__ != 1 ]; then
 mkdir /data/native_endpoint
 for name in runtime.tar.gz native_asr.so native_first_client.sh manager.sh lifecycle package.sha256; do cp "$STAGE/$name" "/data/native_endpoint/$name"; done
fi
chmod 700 /data/native_endpoint/manager.sh /data/native_endpoint/lifecycle
(cd /data/native_endpoint && sha256sum -c package.sha256 >/dev/null)
for name in native_first_client.sh native_asr.so; do
 cp "/data/native_endpoint/$name" "/data/$name.endpoint-new"
 chmod 755 "/data/$name.endpoint-new"
 mv "/data/$name.endpoint-new" "/data/$name"
done
cp /data/native_first.env /data/native_first.env.endpoint-new
printf '\n# Daily first-turn local endpoint; original Xiaomi ASR retained.\nNATIVE_ENDPOINT_ENABLED=1\nNATIVE_ENDPOINT_MANAGER=/data/native_endpoint/manager.sh\n' >> /data/native_first.env.endpoint-new
chmod 600 /data/native_first.env.endpoint-new
mv /data/native_first.env.endpoint-new /data/native_first.env
route_start_native
launch_client /data/native_first_client.sh /tmp/native_first_client.log
sh /data/native_endpoint/manager.sh status
sh /data/native_asr.sh status
trap - EXIT
printf 'BACKUP=%s\nARCHIVE=%s\n' "$BACKUP" "$archive"
df -k /data
'''.replace('__STAGE__',shlex.quote(stage)).replace('__REUSE__','1' if a.reuse_installed_package else '0')
 print(remote('sh -s',script.encode(),timeout=150))
