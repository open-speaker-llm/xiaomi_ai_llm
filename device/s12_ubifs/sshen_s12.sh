#!/bin/sh /etc/rc.common
START=45

start() {
    local keyfile=/etc/dropbear/authorized_keys.s12-local
    local hostkey=/etc/dropbear/s12-host-key
    local target=/etc/dropbear/authorized_keys
    local data_key=/data/etc/dropbear/dropbear_rsa_host_key

    grep -qs ' /data ' /proc/mounts || return 1
    [ -s "$keyfile" ] && [ -s "$hostkey" ] && [ -f "$target" ] || return 1
    grep -qs ' /etc/dropbear/authorized_keys ' /proc/mounts && return 1

    if [ ! -s "$data_key" ]; then
        umask 077
        mkdir -p /data/etc/dropbear || return 1
        cp "$hostkey" "$data_key.tmp" || return 1
        chmod 600 "$data_key.tmp" || return 1
        mv "$data_key.tmp" "$data_key" || return 1
    fi
    mount --bind "$keyfile" "$target" || return 1
    printf '1\n' > /tmp/ssh_en
}
