"""Read-only speaker diagnostics against synthetic files, never a real speaker."""
import hashlib
import os
from pathlib import Path
import shutil
import shlex
import stat
import struct
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOCTOR = ROOT / 'device/speaker_doctor.sh'
SECRET = 'doctor-test-secret-NOT-A-REAL-KEY'
PRIVATE_TEXT = 'doctor-private-dialog-do-not-print'


class SpeakerDoctorTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='speaker-doctor-test-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.marker = self.root / 'unexpected-execution'
        self.env = os.environ.copy()
        self.env['LC_ALL'] = 'C'
        for command in ('curl', 'wget', 'ssh', 'scp', 'ubus', 'amixer', 'ps', 'df', 'reboot', 'fw_env'):
            self.put('/doctor/bin/' + command,
                     '#!/bin/sh\nprintf called >> ' + str(self.marker) + '\nexit 99\n', executable=True)
        self.env['PATH'] = str(self.root / 'doctor/bin') + os.pathsep + self.env['PATH']
        self.configure()
        self.put('/usr/share/mico/version', "option HARDWARE 'S12A'\noption ROM '1.54.8'\n")
        self.put('/proc/mounts', '/dev/mtdblock4 / squashfs ro 0 0\n/dev/mtdblock7 /data jffs2 rw 0 0\ntmpfs /tmp tmpfs rw 0 0\n')
        self.put('/proc/uptime', '123.45 100.00\n')
        self.put('/doctor/df-k.txt',
                 'Filesystem 1024-blocks Used Available Capacity Mounted on\n'
                 '/dev/mtdblock7 65536 40000 25536 61% /data\n'
                 'tmpfs 131072 10000 121072 7% /tmp\n')
        self.executable('/data/native_first_client.sh')
        self.executable('/data/ettsc')
        self.executable('/data/vad_record.sh')
        self.put('/tmp/native_first_client.pid', '111\n')
        self.process(111, ['sh', '/data/native_first_client.sh'])
        self.process(201, ['/usr/bin/mipns-xiaomi'])
        self.process(202, ['/usr/bin/mico_aivs_lab'])
        self.put('/tmp/native_first_client.log', PRIVATE_TEXT)
        self.put('/tmp/native_first_events.log', PRIVATE_TEXT)

    def put(self, name, content, executable=False):
        path = self.root / name.lstrip('/')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode() if isinstance(content, str) else content)
        path.chmod(0o700 if executable else 0o600)
        return path

    def executable(self, name):
        return self.put(name, '#!/bin/sh\nprintf executed >> ' + str(self.marker) + '\nexit 99\n', executable=True)

    def configure(self, pipeline='native', tts='device', extra=''):
        self.put('/data/native_first.env',
                 f'LLM_PIPELINE={pipeline}\nTTS_ENGINE={tts}\nBACKEND=deepseek\n'
                 f'DEEPSEEK_API_KEY="{SECRET}"\nFOLLOWUP_ENABLED=0\n'
                 'SYSTEM1_FOLLOWUP_ENABLED=0\nNATIVE_ENDPOINT_ENABLED=0\n' + extra)

    def process(self, pid, argv, state='S', asr=False):
        self.put(f'/proc/{pid}/cmdline', b'\0'.join(s.encode() for s in argv) + b'\0')
        self.put(f'/proc/{pid}/status', f'Name:\tfixture\nState:\t{state} (fixture)\n')
        if asr:
            self.put(f'/proc/{pid}/maps', '1000-2000 r-xp 00000000 00:00 1 /data/native_asr.so\n')

    def boot1(self, endpoint=False):
        self.configure(extra='SYSTEM1_FOLLOWUP_ENABLED=1\nSYSTEM1_FOLLOWUP_RECORD_MODE=native_live\n'
                             'SYSTEM1_FOLLOWUP_ASR_ENGINE=native_live\n' +
                             ('NATIVE_ENDPOINT_ENABLED=1\n' if endpoint else ''))
        # Keep one assignment per setting, as recommended by the operator guide.
        config = self.root / 'data/native_first.env'
        lines = config.read_text().splitlines()
        final = {line.split('=', 1)[0]: line for line in lines}
        config.write_text('\n'.join(final.values()) + '\n')
        self.put('/proc/mounts', '/dev/mtdblock5 / squashfs ro 0 0\n')
        self.put('/usr/share/mico/version', "option HARDWARE 'S12A'\noption ROM '1.76.54'\n")
        self.executable('/data/native_asr.sh')
        self.executable('/data/native_asr_ctl')
        self.put('/data/native_asr.so', 'synthetic shared library')
        self.process(201, ['/usr/bin/mipns-xiaomi'], asr=True)
        self.process(202, ['/usr/bin/mico_aivs_lab'], asr=True)
        state = bytearray(4224)
        struct.pack_into('<8I', state, 0, 0x4e415331, 1, 201, 202, 0, 0, 0, 0)
        state[128:128 + len(PRIVATE_TEXT)] = PRIVATE_TEXT.encode()
        self.put('/tmp/native_followup/state', state)
        if endpoint:
            self.package()
            pool = bytearray(3684)
            struct.pack_into('<13I', pool, 0, 0x4e503033, 301, 302, 200000, 4, 0, 1,
                             10000, 0, 1, 0, 1, 0)
            for index in range(4):
                offset = 52 + index * 908
                struct.pack_into('<7I', pool, offset, 0x4e573033, 301, 200000, 0, 0, 0, 0)
                struct.pack_into('<5I', pool, offset + 364, 3, index + 1, 302, 201, 202)
                pool[offset + 428:offset + 444] = bytes([index + 1]) * 16
            self.put('/tmp/xiaomi_native_wake_probe/native-pool.state', pool)
            self.process(301, ['/tmp/xiaomi_native_wake_probe/native_wake_pool', 'resident', '86400'])
            self.process(302, ['./ld-linux-armhf.so.3', '--library-path', '/tmp/xiaomi_neural_shadow',
                               '--preload', '/tmp/xiaomi_neural_shadow/libstdc++.so.6',
                               './neural_pool', './libsherpa-onnx-c-api.so', './silero_vad_v5.onnx'])
            self.put('/proc/302/cwd.txt', '/tmp/xiaomi_neural_shadow\n')

    def package(self):
        package = self.root / 'data/native_endpoint'
        package.mkdir(parents=True, exist_ok=True)
        for name in ('native_first_client.sh', 'native_asr.so'):
            shutil.copy2(self.root / 'data' / name, package / name)
        self.executable('/data/native_endpoint/manager.sh')
        self.executable('/data/native_endpoint/lifecycle')
        self.put('/data/native_endpoint/runtime.tar.gz', 'synthetic archive')
        self.put('/data/native_endpoint/package.sha256', ''.join(
            hashlib.sha256((package / name).read_bytes()).hexdigest() + '  ' + name + '\n'
            for name in ('runtime.tar.gz', 'native_asr.so', 'native_first_client.sh', 'manager.sh', 'lifecycle')))

    def run_doctor(self, shell='sh', *args):
        result = subprocess.run([shell, str(DOCTOR), '--root', str(self.root), *args],
                                env=self.env, capture_output=True, text=True, timeout=15)
        self.assertFalse(self.marker.exists(), result.stdout + result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        self.assertNotIn(PRIVATE_TEXT, result.stdout + result.stderr)
        self.assertEqual(result.stderr, '', result.stderr)
        return result

    def snapshot(self):
        return {str(p.relative_to(self.root)): (stat.S_IMODE(p.stat().st_mode), p.stat().st_mtime_ns, p.read_bytes())
                for p in self.root.rglob('*') if p.is_file() and not p.is_symlink()}

    def reader_path(self, *readers):
        """Expose only the listed byte readers, without inheriting host fallbacks."""
        directory = self.root / 'reader-bin'
        directory.mkdir()
        for command in ('sh', 'awk', 'cat', 'tr', 'wc', 'readlink', 'sha256sum', *readers):
            source = shutil.which(command)
            if source is None:
                self.skipTest(command + ' unavailable on this host')
            (directory / command).symlink_to(source)
        self.env['PATH'] = str(directory)
        return directory

    def test_boot0_device_baseline_is_read_only_and_does_not_need_optional_components(self):
        before = self.snapshot()
        result = self.run_doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('native-device', result.stdout)
        self.assertIn('[SKIP] ENDPOINT', result.stdout)
        self.assertIn('human_acceptance=not_run', result.stdout)
        self.assertEqual(self.snapshot(), before)

    @unittest.skipUnless(shutil.which('dash'), 'dash unavailable')
    def test_runs_under_posix_dash(self):
        self.assertEqual(self.run_doctor('dash').returncode, 0)

    @unittest.skipUnless(shutil.which('busybox'), 'BusyBox unavailable on this host')
    def test_runs_under_busybox_ash(self):
        result = subprocess.run(['busybox', 'sh', str(DOCTOR), '--root', str(self.root)],
                                env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_modes_do_not_require_unused_components_or_credentials(self):
        (self.root / 'data/ettsc').unlink()
        for mode, pipeline, tts in [('native-server', 'native', 'server'), ('server', 'server', 'device')]:
            with self.subTest(mode=mode):
                self.configure(pipeline, tts, extra='SERVER="https://user:URL_SECRET@example.invalid/path?token=URL_TOKEN"\n')
                if pipeline == 'server':
                    path = self.root / 'data/native_first.env'
                    path.write_text(path.read_text().replace(f'DEEPSEEK_API_KEY="{SECRET}"', 'DEEPSEEK_API_KEY='))
                result = self.run_doctor()
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertIn(mode, result.stdout)
                self.assertNotIn('URL_SECRET', result.stdout)
                self.assertNotIn('URL_TOKEN', result.stdout)
                self.assertIn('[SKIP] DEVICE_TTS', result.stdout)

    def test_missing_selected_key_is_an_error(self):
        self.configure(extra='DEEPSEEK_API_KEY=\n')
        result = self.run_doctor()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('[FAIL] LLM_KEY', result.stdout)

    def test_shell_expressions_and_control_flow_are_unknown_and_never_executed(self):
        for payload in (f'DEEPSEEK_API_KEY=$(touch {self.marker})\n',
                        f'TTS_ENGINE=`touch {self.marker}`\n',
                        f'if touch {self.marker}; then\nTTS_ENGINE=device\nfi\n',
                        'TTS_ENGINE=${OTHER_VALUE}\n'):
            with self.subTest(payload=payload):
                self.configure(extra=payload)
                result = self.run_doctor()
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn('[UNKNOWN] CONFIG', result.stdout)
                self.assertIn('[UNKNOWN] MODE', result.stdout)

    def test_quoted_literals_and_comments_are_parsed_without_evaluation(self):
        self.configure(extra="export LLM_PIPELINE='native' # note\nTTS_ENGINE=\"device\" # note\n"
                             "LLM_API_KEY='$(literal-secret-not-executed)'\n")
        result = self.run_doctor()
        self.assertEqual(result.returncode, 2, result.stdout)  # duplicates need review
        self.assertIn('[PASS] CONFIG', result.stdout)
        self.assertIn('native-device', result.stdout)
        self.assertNotIn('literal-secret', result.stdout)

    def test_template_configuration_is_parseable(self):
        self.put('/data/native_first.env', (ROOT / 'device/native_first.env.example').read_bytes())
        result = self.run_doctor()
        self.assertIn('[PASS] CONFIG', result.stdout)

    def test_missing_offline_process_and_space_evidence_stays_unknown(self):
        shutil.rmtree(self.root / 'proc/111')
        (self.root / 'doctor/df-k.txt').unlink()
        result = self.run_doctor()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('[UNKNOWN] CLIENT_PROCESS', result.stdout)
        self.assertIn('[UNKNOWN] DATA_SPACE', result.stdout)
        self.assertIn('[UNKNOWN] TMP_SPACE', result.stdout)

    def test_missing_offline_root_does_not_use_host_state(self):
        shutil.rmtree(self.root / 'proc')
        result = self.run_doctor()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('[UNKNOWN] PARTITION', result.stdout)
        self.assertIn('[UNKNOWN] MIPNS', result.stdout)
        self.assertNotIn('[PASS] CLIENT_PROCESS', result.stdout)

    def test_missing_required_offline_components_and_maps_remain_unknown(self):
        self.boot1(endpoint=True)
        (self.root / 'data/ettsc').unlink()
        (self.root / 'data/native_asr.so').unlink()
        (self.root / 'proc/201/maps').unlink()
        (self.root / 'data/native_endpoint/runtime.tar.gz').unlink()
        result = self.run_doctor()
        self.assertEqual(result.returncode, 2, result.stdout)
        for label in ('DEVICE_TTS', 'ASR_LIBRARY', 'ASR_SNAPSHOT', 'ENDPOINT_HASH'):
            self.assertIn('[UNKNOWN] ' + label, result.stdout)

    def test_missing_manifest_or_active_files_are_unknown_but_known_mismatches_stay_failures(self):
        self.boot1(endpoint=True)
        manifest = self.root / 'data/native_endpoint/package.sha256'
        saved = manifest.read_bytes()
        manifest.unlink()
        result = self.run_doctor()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('[UNKNOWN] ENDPOINT_HASH', result.stdout)
        manifest.write_bytes(saved)
        (self.root / 'data/native_asr.so').unlink()
        result = self.run_doctor()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('[UNKNOWN] ENDPOINT_ACTIVE_HASH', result.stdout)
        self.put('/data/native_first_client.sh', 'wrong active client', executable=True)
        result = self.run_doctor()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('[FAIL] ENDPOINT_ACTIVE_HASH', result.stdout)
        (self.root / 'data/native_endpoint/runtime.tar.gz').unlink()
        self.put('/data/native_endpoint/native_asr.so', 'corrupt package library')
        result = self.run_doctor()
        self.assertIn('[FAIL] ENDPOINT_HASH', result.stdout)

    def test_experimental_followup_is_not_mistaken_for_local_recorder(self):
        self.configure(extra='FOLLOWUP_ENABLED=1\nFOLLOWUP_MODE=native_multirounds\n')
        (self.root / 'data/vad_record.sh').unlink()
        result = self.run_doctor()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('[UNKNOWN] FOLLOWUP', result.stdout)
        self.assertNotIn('FOLLOWUP_RECORDER', result.stdout)

    def test_mismatched_and_zombie_client_are_not_reported_running(self):
        for argv, state in [(['sh', '/data/not-the-client.sh', '/data/native_first_client.sh'], 'S'),
                            (['sh', '/data/native_first_client.sh'], 'Z')]:
            with self.subTest(argv=argv, state=state):
                self.process(111, argv, state)
                result = self.run_doctor()
                self.assertEqual(result.returncode, 1)
                self.assertIn('[FAIL] CLIENT_PROCESS', result.stdout)

    def test_nonexecutable_required_component_is_a_defect(self):
        (self.root / 'data/ettsc').chmod(0o600)
        result = self.run_doctor()
        self.assertEqual(result.returncode, 1)
        self.assertIn('[FAIL] DEVICE_TTS', result.stdout)

    def test_low_space_is_a_warning_and_does_not_trigger_cleanup(self):
        self.put('/doctor/df-k.txt', 'disk 1000 999 1 99% /data\ntmpfs 1000 999 1 99% /tmp\n')
        before = self.snapshot()
        result = self.run_doctor()
        self.assertEqual(result.returncode, 2)
        self.assertIn('[WARN] DATA_SPACE', result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_boot1_reports_snapshot_evidence_without_claiming_product_acceptance(self):
        self.boot1(endpoint=True)
        before = self.snapshot()
        result = self.run_doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('[INFO] ASR_SNAPSHOT', result.stdout)
        self.assertIn('[INFO] ENDPOINT_SNAPSHOT', result.stdout)
        self.assertIn('仅为快照就绪迹象', result.stdout)
        self.assertIn('[PASS] ENDPOINT_ACTIVE_HASH', result.stdout)
        self.assertIn('不宣称正式 ENDPOINT_READY', result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_boot1_works_with_hexdump_and_no_od(self):
        self.boot1(endpoint=True)
        self.reader_path('hexdump')
        before = self.snapshot()
        result = self.run_doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('[INFO] ASR_SNAPSHOT', result.stdout)
        self.assertIn('[INFO] ENDPOINT_SNAPSHOT', result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_boot1_retains_od_fallback(self):
        self.boot1(endpoint=True)
        self.reader_path('od')
        result = self.run_doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('[INFO] ASR_SNAPSHOT', result.stdout)
        self.assertIn('[INFO] ENDPOINT_SNAPSHOT', result.stdout)

    def test_missing_byte_readers_leave_snapshots_unknown(self):
        self.boot1(endpoint=True)
        self.reader_path()
        result = self.run_doctor()
        self.assertEqual(result.returncode, 2, result.stdout)
        for label in ('ASR_SNAPSHOT', 'ENDPOINT_SNAPSHOT'):
            self.assertIn('[UNKNOWN] ' + label, result.stdout)
            self.assertNotIn('[INFO] ' + label, result.stdout)
        self.assertNotIn('[FAIL]', result.stdout)

    def test_failed_reader_output_cannot_claim_readiness(self):
        self.boot1(endpoint=True)
        reader = shutil.which('hexdump')
        directory = self.reader_path('hexdump')
        (directory / 'hexdump').unlink()
        # Even a full, valid prefix is untrusted when the reader reports failure.
        self.put('/reader-bin/hexdump', '#!/bin/sh\n' + shlex.quote(reader) +
                 ' "$@"\nexit 1\n', executable=True)
        result = self.run_doctor()
        self.assertEqual(result.returncode, 2, result.stdout)
        for label in ('ASR_SNAPSHOT', 'ENDPOINT_SNAPSHOT'):
            self.assertIn('[UNKNOWN] ' + label, result.stdout)
            self.assertNotIn('[INFO] ' + label, result.stdout)
        self.assertNotIn('[FAIL]', result.stdout)

    def test_incomplete_or_invalid_byte_output_stays_unknown(self):
        self.boot1(endpoint=True)
        reader = shutil.which('hexdump')
        directory = self.reader_path('hexdump')
        (directory / 'hexdump').unlink()
        for transform in ('NR>1 {print}', 'NR==1 {$0=256} {print}',
                          'NR==1 {$0="invalid"} {print}', '{print} END {print 0}'):
            with self.subTest(transform=transform):
                self.put('/reader-bin/hexdump', '#!/bin/sh\n' + shlex.quote(reader) +
                         ' "$@" | awk ' + shlex.quote(transform) + '\n', executable=True)
                result = self.run_doctor()
                self.assertEqual(result.returncode, 2, result.stdout)
                for label in ('ASR_SNAPSHOT', 'ENDPOINT_SNAPSHOT'):
                    self.assertIn('[UNKNOWN] ' + label, result.stdout)
                    self.assertNotIn('[INFO] ' + label, result.stdout)
                self.assertNotIn('[FAIL]', result.stdout)

    def test_failed_plan_reads_are_unknown_not_invalid_state(self):
        self.boot1(endpoint=True)
        reader = shutil.which('hexdump')
        directory = self.reader_path('hexdump')
        (directory / 'hexdump').unlink()
        self.put('/reader-bin/hexdump', '#!/bin/sh\n' + shlex.quote(reader) +
                 ' "$@"\n[ "$3" = 0 ]\n', executable=True)
        result = self.run_doctor()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('[INFO] ASR_SNAPSHOT', result.stdout)
        self.assertIn('[UNKNOWN] ENDPOINT_SNAPSHOT', result.stdout)
        self.assertNotIn('[INFO] ENDPOINT_SNAPSHOT', result.stdout)
        self.assertNotIn('[FAIL]', result.stdout)

    def test_unreadable_asr_prefix_does_not_turn_endpoint_unknown_into_failure(self):
        self.boot1(endpoint=True)
        reader = shutil.which('hexdump')
        directory = self.reader_path('hexdump')
        (directory / 'hexdump').unlink()
        self.put('/reader-bin/hexdump', '#!/bin/sh\nfor file do :; done\n' + shlex.quote(reader) +
                 ' "$@"\ncase "$file" in */native_followup/state) exit 1;; esac\n', executable=True)
        result = self.run_doctor()
        self.assertEqual(result.returncode, 2, result.stdout)
        for label in ('ASR_SNAPSHOT', 'ENDPOINT_SNAPSHOT'):
            self.assertIn('[UNKNOWN] ' + label, result.stdout)
            self.assertNotIn('[INFO] ' + label, result.stdout)
        self.assertNotIn('[FAIL]', result.stdout)

    def test_endpoint_manifest_cannot_escape_directory_or_repeat_entries(self):
        self.boot1(endpoint=True)
        manifest = self.root / 'data/native_endpoint/package.sha256'
        original = manifest.read_text()
        for content in (original + '0' * 64 + '  ../../private-secret\n',
                        original + original.splitlines()[0] + '\n',
                        '\n'.join(original.splitlines()[:-1]) + '\n'):
            with self.subTest(content=content[-80:]):
                manifest.write_text(content)
                result = self.run_doctor()
                self.assertEqual(result.returncode, 1)
                self.assertIn('[FAIL] ENDPOINT_HASH', result.stdout)

    def test_endpoint_hash_and_active_copy_mismatches_are_defects(self):
        self.boot1(endpoint=True)
        self.put('/data/native_asr.so', 'wrong active library')
        result = self.run_doctor()
        self.assertEqual(result.returncode, 1)
        self.assertIn('[FAIL] ENDPOINT_ACTIVE_HASH', result.stdout)
        self.put('/data/native_endpoint/runtime.tar.gz', 'corrupt package')
        result = self.run_doctor()
        self.assertIn('[FAIL] ENDPOINT_HASH', result.stdout)

    def test_old_package_does_not_require_active_hash_match_when_disabled(self):
        self.boot1()
        self.package()
        self.put('/data/native_first_client.sh', 'restored earlier client', executable=True)
        result = self.run_doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('ENDPOINT_ACTIVE_HASH', result.stdout)

    def test_symlinked_configuration_and_package_are_not_followed(self):
        outside = self.root / 'private-config'
        outside.write_text(f'LLM_PIPELINE=server\nTTS_ENGINE=server\nDEEPSEEK_API_KEY={SECRET}\n')
        config = self.root / 'data/native_first.env'
        config.unlink()
        config.symlink_to(outside)
        result = self.run_doctor()
        self.assertEqual(result.returncode, 1)
        self.assertIn('[FAIL] CONFIG', result.stdout)
        config.unlink()
        self.boot1(endpoint=True)
        artifact = self.root / 'data/native_endpoint/runtime.tar.gz'
        artifact.unlink()
        artifact.symlink_to(outside)
        result = self.run_doctor()
        self.assertIn('[FAIL] ENDPOINT_HASH', result.stdout)

    def test_truncated_and_foreign_asr_state_are_unknown(self):
        self.boot1()
        state = self.root / 'tmp/native_followup/state'
        original = state.read_bytes()
        for content in (original[:20], bytes(4224)):
            with self.subTest(size=len(content)):
                state.write_bytes(content)
                result = self.run_doctor()
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn('[UNKNOWN] ASR_SNAPSHOT', result.stdout)

    def test_expired_endpoint_lease_and_wrong_native_epoch_are_defects(self):
        self.boot1(endpoint=True)
        state = self.root / 'tmp/xiaomi_native_wake_probe/native-pool.state'
        original = state.read_bytes()
        for offset, value in ((12, 100000), (52 + 376, 999)):
            with self.subTest(offset=offset):
                changed = bytearray(original)
                struct.pack_into('<I', changed, offset, value)
                state.write_bytes(changed)
                result = self.run_doctor()
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn('[FAIL] ENDPOINT_SNAPSHOT', result.stdout)

    def test_active_plan_numeric_identity_must_match_pool(self):
        self.boot1(endpoint=True)
        state = self.root / 'tmp/xiaomi_native_wake_probe/native-pool.state'
        original = state.read_bytes()
        for offset, value in ((0, 0), (4, 999), (8, 100000), (12, 1), (364, 0), (372, 999)):
            with self.subTest(offset=offset):
                changed = bytearray(original)
                struct.pack_into('<I', changed, 52 + offset, value)
                state.write_bytes(changed)
                result = self.run_doctor()
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn('[FAIL] ENDPOINT_SNAPSHOT', result.stdout)
                self.assertIn('活动计划', result.stdout)

    def test_missing_endpoint_uptime_is_unknown(self):
        self.boot1(endpoint=True)
        (self.root / 'proc/uptime').unlink()
        result = self.run_doctor()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('[UNKNOWN] ENDPOINT_SNAPSHOT', result.stdout)

    def test_model_identity_requires_loader_arguments_and_controlled_cwd(self):
        self.boot1(endpoint=True)
        result = self.run_doctor()
        self.assertEqual(result.returncode, 0, result.stdout)
        (self.root / 'proc/302/cwd.txt').unlink()
        result = self.run_doctor()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('[UNKNOWN] ENDPOINT_SNAPSHOT', result.stdout)
        self.put('/proc/302/cwd.txt', '/tmp/unrelated\n')
        result = self.run_doctor()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.process(302, ['/bin/cat', '/tmp/xiaomi_neural_shadow/neural_pool'])
        result = self.run_doctor()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('[FAIL] ENDPOINT_SNAPSHOT', result.stdout)

    def test_absolute_model_loader_needs_no_cwd_but_keeps_argument_order(self):
        self.boot1(endpoint=True)
        directory = '/tmp/xiaomi_neural_shadow'
        args = [directory + '/ld-linux-armhf.so.3', '--library-path', directory,
                '--preload', directory + '/libstdc++.so.6', directory + '/neural_pool',
                directory + '/libsherpa-onnx-c-api.so', directory + '/silero_vad_v5.onnx']
        self.process(302, args)
        (self.root / 'proc/302/cwd.txt').unlink()
        self.assertEqual(self.run_doctor().returncode, 0)
        self.process(302, [args[0], 'not-a-loader-option', *args[2:]])
        result = self.run_doctor()
        self.assertEqual(result.returncode, 1, result.stdout)

    def test_old_or_deleted_asr_mappings_are_not_valid_library_evidence(self):
        self.boot1()
        for mapping in ('/data/native_asr.so.OLD', '/data/native_asr.so (deleted)',
                        '/other/native_asr.so', '/data/native_asr.so.extra'):
            with self.subTest(mapping=mapping):
                self.put('/proc/201/maps', '1000-2000 r-xp 00000000 00:00 1 ' + mapping + '\n')
                result = self.run_doctor()
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn('[FAIL] ASR_SNAPSHOT', result.stdout)

    @unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
    def test_numeric_snapshot_layout_matches_current_c_structures(self):
        output = self.root / 'layout'
        source = ('#include <stddef.h>\n#include "native_pool.h"\n'
                  'int main(int argc, char **argv) { if(argc==2) { struct np_pool p; '
                  'FILE *f=fopen(argv[1],"rb"); if(!f) return 2; '
                  'int ok=fread(&p,1,sizeof(p),f)==sizeof(p); fclose(f); '
                  'if(!ok || !np_valid(&p))return 1; puts("valid=1");return 0; } '
                  'printf("%zu %zu %zu %zu\\n", sizeof(struct control), '
                  'sizeof(struct np_pool), sizeof(struct np_slot), '
                  'offsetof(struct nw_state, expected_producer)); return 0; }\n')
        subprocess.run(['cc', '-x', 'c', '-I' + str(ROOT / 'device/endpoint_probe'),
                        '-', '-o', str(output)], input=source, text=True, capture_output=True, check=True)
        result = subprocess.run([str(output)], text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout.strip(), '4224 3684 908 376')
        self.boot1(endpoint=True)
        result = subprocess.run([str(output), str(self.root / 'tmp/xiaomi_native_wake_probe/native-pool.state')],
                                text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout.strip(), 'valid=1')

    def test_usage_errors_have_stable_exit_code(self):
        for args in (['--root'], ['--root', 'relative'], ['--root', '/'], ['--repair']):
            with self.subTest(args=args):
                result = subprocess.run(['sh', str(DOCTOR), *args], capture_output=True, text=True)
                self.assertEqual(result.returncode, 64)
