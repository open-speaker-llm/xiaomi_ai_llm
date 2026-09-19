#!/bin/sh
# Never let a long-running worker outlive the existing temporary restore timers.
resident_timer_covers() {
    local dir="$1" seconds="$2" now="$3" expires value
    [ -f "$dir/timer.armed" ] && [ ! -L "$dir/timer.armed" ] || return 1
    [ -f "$dir/timer.deadline" ] && [ ! -L "$dir/timer.deadline" ] || return 1
    expires=$(cat "$dir/timer.deadline") || return 1
    case "$expires:$seconds:$now" in *[!0-9:]*|:*|*:|*::*) return 1;; esac
    for value in "$expires" "$seconds" "$now"; do case "$value" in 0[0-9]*) return 1;; esac; done
    [ "${#expires}" -le 10 ] && [ "${#seconds}" -le 5 ] && [ "${#now}" -le 10 ] || return 1
    [ "$seconds" -ge 37 ] && [ "$seconds" -le 86400 ] || return 1
    [ "$expires" -ge "$((now + seconds + 30))" ]
}
