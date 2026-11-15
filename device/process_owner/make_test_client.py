#!/usr/bin/env python3
"""Create an isolated lifecycle fixture from the actual client; never deploy it."""
import argparse
import re
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('client', type=Path)
p.add_argument('output', type=Path)
p.add_argument('--tmp', default='/tmp/native-owner-ci')
a = p.parse_args()
if not re.fullmatch(r'/tmp/native-owner-ci(?:/[A-Za-z0-9_.-]+)*', a.tmp):
    raise SystemExit('invalid fixture root')
s = a.client.read_text().replace('/tmp/', a.tmp + '/')
needle = '\ncase "$1" in\n    stop)'
overrides = '''
# Test-only: do not touch real audio, services, LEDs, or bind mounts.
setup_audio() { :; }; led_off() { :; }; should_setup_dsnoop() { return 1; }
restore_audio_capture_overlays() { :; }; setup_native_live_asr() { :; }
setup_native_pcm_tap() { :; }; init_native_result_state() { :; }
start_aivs_speech_guard() { :; }; stop_aivs_speech_guard() { :; }
install_hook() { :; }; start_hook_watchdog() { :; }; restore_hook() { :; }
restart_mipns_single() { :; }; stop_native_endpoint() { :; }
setup_native_endpoint() { :; }; resume_native_player() { :; }; resume_native_asr() { :; }
'''
if s.count(needle) != 1:
    raise SystemExit('client entry point changed')
s = s.replace(needle, overrides + needle)
needle = 'exec 3<>"$EVENT_FIFO"'
workers = '''arecord -D null -t raw -f S16_LE -r 16000 -c 1 >/dev/null 2>/dev/null & echo $! > @ROOT@/record.pid
tail -f /dev/null | aplay -D null -t raw -f S16_LE -r 16000 -c 1 >/dev/null 2>/dev/null & echo $! > @ROOT@/play.pid
curl -sS -m 40 "$TEST_URL" >/dev/null 2>/dev/null & echo $! > @ROOT@/curl.pid
'''.replace('@ROOT@', a.tmp)
if s.count(needle) != 1:
    raise SystemExit('client FIFO entry point changed')
a.output.write_text(s.replace(needle, workers + needle))
