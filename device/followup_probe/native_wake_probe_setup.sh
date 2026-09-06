#!/bin/sh
# Temporary NONWAKEUP research; restores the existing PCM tap overlay.
set -eu
D=/tmp/boot1-native-wake
: "${EXPECTED_PROBE_SHA256:?set the locally built wake.so SHA-256}"
[ "${#EXPECTED_PROBE_SHA256}" -eq 64 ]
case "$EXPECTED_PROBE_SHA256" in *[!0-9a-f]*) exit 2;; esac
umask 077
mkdir -p "$D"
[ "$(awk '$2 == "/" {print $1;exit}' /proc/mounts)" = /dev/mtdblock5 ]
[ "$(sha256sum /usr/bin/mipns-xiaomi | awk '{print $1}')" = a02071a39f3509d3a90dac638e323039a24de784a907f076a0a91f81cd5fbb9d ]
[ "$(sha256sum /usr/lib/libxaudio_engine.so | awk '{print $1}')" = 79f1a33d9683cd6940c8d23e3dd4e992f1958fe220c0dfff8d230f9f8a1b5e73 ]
[ "$(sha256sum "$D/wake.so" | awk '{print $1}')" = "$EXPECTED_PROBE_SHA256" ]
[ "$(sha256sum /usr/lib/libaivs-message-util.so | awk '{print $1}')" = c0fc1b551e20962e6dceeb4b1a24b3d8a454e19bec8fd692f2229241691a0c31 ]
[ "$(sha256sum /usr/bin/mico_aivs_lab | awk '{print $1}')" = 7063b44fbe779c04c8bfc89e2870e1716eeb62765ba0025f8e8b68ea8026d18c ]
[ "$(sha256sum /etc/init.d/pns | awk '{print $1}')" = 5eb54e917c4d28b11eb25779601df5c1e92ca7824312631967813228715d71af ]
grep -q NATIVE_PCM_TAP_MANAGED_V1 /etc/init.d/pns
! grep -q BOOT1_NATIVE_WAKE_PROBE /etc/init.d/pns
[ ! -e /tmp/native_first_busy ]
cp /etc/init.d/pns "$D/pns.before"
sed 's|procd_set_param env LD_PRELOAD=/data/xaudio_pcm_tap.so|procd_set_param env "LD_PRELOAD=/tmp/boot1-native-wake/wake.so /data/xaudio_pcm_tap.so" # BOOT1_NATIVE_WAKE_PROBE|' "$D/pns.before" > "$D/pns.probe"
grep -q BOOT1_NATIVE_WAKE_PROBE "$D/pns.probe"
sh -n "$D/pns.probe"
cat > "$D/restore.sh" <<'EOF'
#!/bin/sh
if grep -q BOOT1_NATIVE_WAKE_PROBE /etc/init.d/pns; then
 umount /etc/init.d/pns || exit 1
 /etc/init.d/pns restart
 echo "restored at $(date)" >> /tmp/boot1-native-wake/restore.log
fi
EOF
chmod 700 "$D/restore.sh" "$D/pns.probe"
touch "$D/rollback.armed"
sh -c 'trap "" HUP; (sleep 480; [ ! -e /tmp/boot1-native-wake/rollback.armed ] || sh /tmp/boot1-native-wake/restore.sh) > /tmp/boot1-native-wake/rollback.log 2>&1 </dev/null & echo $! > /tmp/boot1-native-wake/rollback.pid'
trap 'sh "$D/restore.sh" >/dev/null 2>&1 || true' 0
mount --bind "$D/pns.probe" /etc/init.d/pns
/etc/init.d/pns restart
sleep 4
sh /data/native_pcm_tap.sh status
trap - 0
tail -n 8 "$D/probe.log"
