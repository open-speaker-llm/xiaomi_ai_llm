#!/bin/sh
# Execute over an already authenticated SSH connection after booting a patch.
# The only executable probes are made AFTER verifying the deny-script hashes.
set -eu
expected_root=${1:?Pass /dev/mtdblock4 or /dev/mtdblock5}
case "$expected_root" in
    /dev/mtdblock4|/dev/mtdblock5) ;;
    *) exit 2 ;;
esac
test "$(awk '$2 == "/" { print $1 }' /proc/mounts)" = "$expected_root"
test "$(cat /tmp/ssh_en)" = 1
test "$(readlink /etc/rc.d/S45sshen)" = ../init.d/sshen
test -s /data/dropbear/authorized_keys
grep -q ' /etc/dropbear/authorized_keys ' /proc/mounts
cmp -s /etc/dropbear/authorized_keys /data/dropbear/authorized_keys
test "$(uci -q get 'dropbear.@dropbear[0].PasswordAuth')" = 0
test "$(uci -q get 'dropbear.@dropbear[0].RootPasswordAuth')" = 0
pidof dropbear >/dev/null
echo 'PASS: correct rootfs, SSH hook, owner keys and public-key-only login'

guard_sha=d4f1b71fa30356b44871a10922fc80f07510976dcf8660fc1d83fed29533603d
for entry in /bin/ota /bin/flash.sh; do
    test "$(sha256sum "$entry" | cut -d ' ' -f 1)" = "$guard_sha"
done
if grep -Ev '^[[:space:]]*(#|$)' /etc/crontabs/root | grep -q '/bin/ota'; then
    echo 'FAIL: OTA cron is still active' >&2
    exit 1
fi
boot_before=$(fw_env -g boot_part)
for mode in check slient upgrade ble test success; do
    status=0
    /bin/ota "$mode" http://127.0.0.1/owner-maintenance-probe 2>/dev/null || status=$?
    test "$status" = 126
done
status=0
/bin/flash.sh /tmp/owner-maintenance-nonexistent.img 2>/dev/null || status=$?
test "$status" = 126
test "$(fw_env -g boot_part)" = "$boot_before"
echo 'PASS: native OTA/flash entries denied, cron disabled, boot selection unchanged'
