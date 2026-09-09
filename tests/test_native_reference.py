"""Verify the boot1 reference-channel lease and recorder startup ordering."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NativeReferenceTest(unittest.TestCase):
    def run_manager(self, body, initial='Disable', fail='0'):
        source = (ROOT / 'device/native_asr/native_asr.sh').read_text().split('\ncase "${1:-status}"')[0]
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'mixer').write_text(initial)
            code = source + r'''
DIR="$TEST_DIR"
amixer() {
    case "$*" in
        *sget*) printf "  Item0: '%s'\n" "$(cat "$DIR/mixer")" ;;
        *sset*)
            [ "$FAIL" != 1 ] || return 1
            for arg in "$@"; do value="$arg"; done
            printf '%s' "$value" > "$DIR/mixer"
            echo "mixer:$value" >> "$DIR/trace" ;;
        *) return 2 ;;
    esac
}
''' + body
            result = subprocess.run(['sh', '-c', code], capture_output=True, text=True, timeout=5,
                                    env={**os.environ, 'TEST_DIR': temp, 'FAIL': fail})
            trace = Path(temp, 'trace')
            return result, Path(temp, 'mixer').read_text(), trace.read_text() if trace.exists() else ''

    def test_enable_is_verified_and_previous_setting_is_restored(self):
        result, mixer, trace = self.run_manager('''
prepare_native_reference || exit 1
native_reference_ready || exit 2
restore_native_reference || exit 3
test ! -e "$DIR/loopback.before"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(mixer, 'Disable')
        self.assertEqual(trace.splitlines(), ['mixer:Enable', 'mixer:Disable'])

    def test_existing_enabled_setting_is_preserved_across_repeated_prepare(self):
        result, mixer, _ = self.run_manager('''
prepare_native_reference && prepare_native_reference && restore_native_reference
''', initial='Enable')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(mixer, 'Enable')

    def test_repeated_prepare_does_not_overwrite_original_disabled_setting(self):
        result, mixer, _ = self.run_manager('''
prepare_native_reference && prepare_native_reference && restore_native_reference
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(mixer, 'Disable')

    def test_missing_or_failed_control_is_not_reported_healthy(self):
        for initial, fail in [('unknown', '0'), ('Disable', '1')]:
            with self.subTest(initial=initial, fail=fail):
                result, mixer, _ = self.run_manager('''
prepare_native_reference && exit 9
native_reference_ready && exit 10
exit 0
''', initial, fail)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(mixer, initial)

    def test_stop_restores_reference_before_restarting_recorder(self):
        result, mixer, trace = self.run_manager(r'''
prepare_native_reference || exit 1
PNS="$DIR/pns"; AIVS="$DIR/aivs"
for service in pns aivs; do
    printf '#!/bin/sh\necho "restart:%s:$(cat "$TEST_DIR/mixer")" >> "$TEST_DIR/trace"\n' "$service" > "$DIR/$service"
    chmod +x "$DIR/$service"
done
mounted() { return 0; }; owned() { return 0; }; umount() { :; }
stop_native_asr
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(mixer, 'Disable')
        self.assertEqual(trace.splitlines()[-2:], ['restart:aivs:Disable', 'restart:pns:Disable'])

    def test_failed_install_restores_routing_and_does_not_report_ready(self):
        result, mixer, trace = self.run_manager(r'''
PNS="$DIR/original-pns"; AIVS="$DIR/original-aivs"
SO="$DIR/so"; CTL="$DIR/ctl"
touch "$SO"
printf '#!/bin/sh\nexit 0\n' > "$CTL"; chmod +x "$CTL"
for service in "$PNS" "$AIVS"; do
    cat > "$service" <<'SERVICE'
#!/bin/sh
procd_open_instance() { :; }
_start_mipns_xiaomi() {
    procd_open_instance
}
echo "restart:$(cat "$TEST_DIR/mixer")" >> "$TEST_DIR/trace"
SERVICE
    chmod +x "$service"
done
is_boot1() { return 0; }; verified() { return 0; }; hash_is() { return 0; }
healthy() { return 1; }; owned() { return 1; }; mounted() { return 1; }
mount() { echo failed-mount >> "$DIR/trace"; return 1; }
start_native_asr
''')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(mixer, 'Disable')
        self.assertEqual(trace.splitlines(), ['mixer:Enable', 'failed-mount', 'mixer:Disable',
                                             'restart:Disable', 'restart:Disable'])


if __name__ == '__main__':
    unittest.main()
