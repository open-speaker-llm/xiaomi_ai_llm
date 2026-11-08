#!/bin/sh
# Valid only for the examined S12 system1 build and its audio components.
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
S12_DIRAC_SO=${S12_DIRAC_SO:-/data/s12_dirac_init.so}
hash_is() { [ "$(md5sum "$1" 2>/dev/null | awk '{print $1}')" = "$2" ]; }
supported() {
    local root ubi mtd label
    command -v usleep >/dev/null 2>&1 || return 1
    root=$(awk '$2=="/" && $1!="rootfs" {r=$1} END {print r}' /proc/mounts)
    case "$root" in /dev/ubi[0-9]*_*) ubi=${root#/dev/}; ubi=${ubi%%_*};; *) return 1;; esac
    mtd=$(cat "/sys/class/ubi/$ubi/mtd_num" 2>/dev/null)
    case "$mtd" in ''|*[!0-9]*) return 1;; esac
    label=$(awk -v n="mtd$mtd:" '$1==n {gsub(/"/,"",$4); print $4; exit}' /proc/mtd)
    [ "$label" = system1 ] &&
    hash_is /usr/bin/aplay 27b41d6fab670be9b77aa8fb0bbcb2ac &&
    hash_is /usr/lib/libasound.so.2.0.0 667200e6eb82a2a6ae9dcd4a900b84eb &&
    hash_is /usr/lib/libDiracAPI_SHARED.so de533d5a7fbd923e5c3e9d8d299a1cd6 &&
    hash_is /etc/asound.conf 6dff90f00b50d30b5cac67d4733ca4c9 &&
    hash_is /data/etc/diracmobile.config 3fb63badb5eefb6617b5505271a19185 &&
    hash_is "$S12_DIRAC_SO" efc81eb9cb915013c2d70c934bccb661
}
if [ "${1:-}" = --verify ]; then supported; exit $?; fi
supported || { echo '[S12-DIRAC] unsupported audio baseline' >&2; exit 1; }
export NATIVE_FIRST_DIRAC=1
export LD_PRELOAD="$S12_DIRAC_SO${LD_PRELOAD:+:$LD_PRELOAD}"
exec aplay "$@"
