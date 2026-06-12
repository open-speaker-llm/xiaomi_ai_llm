#!/bin/sh
# v2: inject ExpectSpeech EARLY (at StartAnswer / first Speak), while the dialog
# is still in "answering" state, to test if mipns then keeps the mic open
# through Dialog.Finish.
ILOG=/tmp/mico_aivs_lab/instruction.log
SOCK=/tmp/mipns/usock/speech.usock
SENDER=/data/followup_probe/usock_send
PREFIX=08011a24080212    # outer \x08\x01 + \x1a\x24 + inner \x08\x02 (ExpectSpeech)
                          # full = PREFIX + "20" + hex(dialog_id)

hexid() { printf '%s' "$1" | hexdump -v -e '/1 "%02x"'; }

CURDID=""
INJECTED=""
echo "[inj2] watching $ILOG (fire on StartAnswer)"
tail -n0 -f "$ILOG" 2>/dev/null | while IFS= read -r line; do
    did=$(printf '%s' "$line" | sed -nE 's/.*"dialog_id":"([0-9a-f]+)".*/\1/p')
    [ -n "$did" ] && CURDID="$did"
    case "$line" in
        *StartAnswer*|*\"Speak\"*)
            if [ -n "$CURDID" ] && [ "$INJECTED" != "$CURDID" ]; then
                idh=$(hexid "$CURDID")
                payload="${PREFIX}20${idh}"
                ts=$(date '+%H:%M:%S')
                echo "[inj2 $ts] trigger dialog=$CURDID -> inject ExpectSpeech ($payload)"
                $SENDER "$SOCK" "$payload"
                INJECTED="$CURDID"
            fi
            ;;
        *FinishSpeakStream*) echo "[inj2] FinishSpeakStream dialog=$CURDID" ;;
        *\"Finish\"*Dialog*|*Dialog*\"Finish\"*) echo "[inj2] Dialog.Finish dialog=$CURDID" ;;
        *RecognizeResult*) t=$(printf '%s' "$line" | sed -nE 's/.*"text":"([^"]*)".*/\1/p'); [ -n "$t" ] && echo "[inj2] ASR: $t" ;;
    esac
done
