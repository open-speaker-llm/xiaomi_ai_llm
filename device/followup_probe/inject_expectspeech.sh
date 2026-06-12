#!/bin/sh
# Watch instruction.log; when a dialog's TTS finishes, inject ExpectSpeech for
# that dialog_id BEFORE Dialog.Finish, to test if mipns reopens the mic.
ILOG=/tmp/mico_aivs_lab/instruction.log
SOCK=/tmp/mipns/usock/speech.usock
SENDER=/tmp/usock_send
PREFIX=08011a24080212    # outer + inner type=0x02 (ExpectSpeech), then 20<id>
                          # full = PREFIX + "20" + hex(dialog_id)

hexid() { printf '%s' "$1" | hexdump -v -e '/1 "%02x"'; }

CURDID=""
INJECTED=""
echo "[inj] watching $ILOG ..."
tail -n0 -f "$ILOG" 2>/dev/null | while IFS= read -r line; do
    did=$(printf '%s' "$line" | sed -nE 's/.*"dialog_id":"([0-9a-f]+)".*/\1/p')
    [ -n "$did" ] && CURDID="$did"
    case "$line" in
        *FinishSpeakStream*)
            if [ -n "$CURDID" ] && [ "$INJECTED" != "$CURDID" ]; then
                idh=$(hexid "$CURDID")
                payload="${PREFIX}20${idh}"
                ts=$(date '+%H:%M:%S')
                echo "[inj $ts] FinishSpeakStream dialog=$CURDID -> inject ExpectSpeech"
                $SENDER "$SOCK" "$payload"
                INJECTED="$CURDID"
            fi
            ;;
        *\"Finish\"*Dialog*|*Dialog*\"Finish\"*)
            echo "[inj] Dialog.Finish dialog=$CURDID"
            ;;
    esac
done
