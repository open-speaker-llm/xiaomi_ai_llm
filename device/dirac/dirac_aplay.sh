#!/bin/sh
# Only the verified boot1 S12A playback ABI is enabled. Other devices retain aplay.
DIRAC_SO=/data/native_first_dirac.so
dirac_hash_is() {
    [ "$(sha256sum "$1" 2>/dev/null | awk '{print $1}')" = "$2" ]
}
dirac_supported() {
    [ "$(awk '$2 == "/" {print $1;exit}' /proc/mounts)" = /dev/mtdblock5 ] &&
    dirac_hash_is /etc/asound.conf 373b3ad8876e203e782490f1b22da97cc6fd065b0ff81eebeb2ed37b8317b7c6 &&
    dirac_hash_is /usr/lib/libasound.so.2.0.0 01409adf05754a4581d93ae90eda5d0541fac780aec02927d1d7fd5325c9e08b &&
    dirac_hash_is /usr/lib/libDiracAPI_SHARED.so f8beaef8ae0f9481f50510e0ecd541dcc23a023dbb2f693a278fe672a3940692 &&
    dirac_hash_is /data/etc/diracmobile.config 01a0d394c992b1f9f96031c26a8cde486403695b8a55bfb12ee6c915d1226a74
}
dirac_aplay_main() {
    if [ "${LLM_DIRAC_ENABLED:-1}" = 1 ] && [ -r "$DIRAC_SO" ] && dirac_supported; then
        # exec preserves player exit status and PID; preload is private to aplay.
        export NATIVE_FIRST_DIRAC=1
        export LD_PRELOAD="$DIRAC_SO${LD_PRELOAD:+:$LD_PRELOAD}"
    else
        echo '[DIRAC] bypass: disabled, helper missing or firmware/config unsupported' >&2
    fi
    exec aplay "$@"
}

dirac_aplay_main "$@"
