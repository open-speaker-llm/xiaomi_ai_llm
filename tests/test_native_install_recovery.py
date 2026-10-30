"""Host-only installation boundaries and recovery after temporary-directory loss."""
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RUN = subprocess.run
RUNNER = (ROOT / 'device/endpoint_probe/run_route_client.sh').read_text()
LAUNCH = re.search(r'^launch_client\(\) \{.*?^\}', RUNNER, re.M | re.S).group()


class ClientLaunchDirectoryTest(unittest.TestCase):
    def launch(self, directory_kind='missing', failure=''):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = base / 'route'
            target = base / 'target'
            target.mkdir()
            if directory_kind == 'directory':
                runtime.mkdir(mode=0o755)
            elif directory_kind == 'file':
                runtime.write_text('keep')
            elif directory_kind == 'symlink':
                runtime.symlink_to(target, target_is_directory=True)
            elif directory_kind == 'dangling':
                runtime.symlink_to(base / 'absent')
            marker, pidfile = base / 'started', base / 'client.pid'
            client = base / 'client.sh'
            client.write_text(
                'touch ' + shlex.quote(str(marker)) + '\n'
                + ('exit 3\n' if failure == 'child' else
                   'echo $$ > ' + shlex.quote(str(pidfile)) + '\n'
                   'echo "[IDLE] 等待原生唤醒词" > "$LOG_FILE"\n'
                   'exec sleep 30\n')
            )
            code = LAUNCH.replace('/tmp/native_first_client.pid', str(pidfile)) + '\n'
            code += 'D=' + shlex.quote(str(runtime)) + '\n'
            code += 'sleep() { command sleep 0.01; }\n'
            if failure in ('mkdir', 'chmod'):
                code += failure + '() { return 1; }\n'
            code += 'launch_client ' + shlex.quote(str(client)) + ' ' + shlex.quote(str(base / 'client.log'))
            code += '''
result=$?
if [ -n "${child:-}" ]; then
    kill "$child" 2>/dev/null || :
    wait "$child" 2>/dev/null || :
fi
exit "$result"
'''
            result = RUN(['sh'], input=code, text=True, capture_output=True, timeout=5)
            mode = stat.S_IMODE(runtime.stat().st_mode) if runtime.is_dir() and not runtime.is_symlink() else None
            return result, marker.exists(), mode, list(target.iterdir())

    def test_missing_runtime_is_created_before_client_launch(self):
        result, started, mode, _ = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(started)
        self.assertEqual(mode, 0o700)
        self.assertIn('CLIENT_READY', result.stdout)

    def test_existing_runtime_is_reused_with_private_permissions(self):
        result, started, mode, _ = self.launch('directory')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(started)
        self.assertEqual(mode, 0o700)

    def test_invalid_runtime_never_starts_client(self):
        for kind in ('file', 'symlink', 'dangling'):
            with self.subTest(kind=kind):
                result, started, _, target_files = self.launch(kind)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(started)
                self.assertEqual(target_files, [])

    def test_directory_preparation_failure_never_starts_client(self):
        for kind, failure in (('missing', 'mkdir'), ('directory', 'chmod')):
            with self.subTest(failure=failure):
                result, started, _, _ = self.launch(kind, failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(started)

    def test_failed_child_does_not_report_ready(self):
        result, started, _, _ = self.launch(failure='child')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(started)
        self.assertNotIn('CLIENT_READY', result.stdout)


class NativeFollowupInstallGuardTest(unittest.TestCase):
    def invoke_installer(self, kind=None, install_package_during_upload=False):
        spec = importlib.util.spec_from_file_location(
            'followup_installer_review', ROOT / 'tools/speaker-maintenance/install_boot1_native_followup.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for name in ('data', 'tmp', 'build'):
                (base / name).mkdir()
            package = base / 'data/native_endpoint'
            if kind == 'directory':
                package.mkdir()
            elif kind == 'file':
                package.write_text('retained package')
            elif kind == 'dangling':
                package.symlink_to(base / 'absent')
            elif kind == 'symlink':
                package.symlink_to(base / 'build', target_is_directory=True)
            mounts = base / 'mounts'
            mounts.write_text('/dev/mtdblock5 / rootfs rw 0 0\n')
            client, manager = base / 'client', base / 'manager'
            for path in (client, manager, base / 'build/native_asr.so', base / 'build/native_asr_ctl'):
                path.write_text('test fixture\n')
            calls, uploads = [], []

            def fake_remote(args, input=None, **kwargs):
                command = args[-1]
                calls.append((command, input))
                self.assertEqual(args[0], 'ssh')
                if command == 'sh -s':
                    # Execute only the generated read-only activation preflight.
                    # The real service stop/install portion is never evaluated.
                    command = input.decode().split('sh -n "$STAGE/native_first_client.sh"', 1)[0]
                    input = None
                elif input is not None:
                    uploads.append(command)
                command = command.replace('/data/', str(base / 'data') + '/')
                command = command.replace('/tmp/', str(base / 'tmp') + '/')
                command = command.replace('/proc/mounts', str(mounts))
                result = RUN(['sh', '-c', command], input=input, capture_output=True, timeout=5)
                if install_package_during_upload and len(uploads) == 4 and not package.exists():
                    package.mkdir()
                return result

            args = ['install', '--host', 'example.invalid', '--build-dir', str(base / 'build'),
                    '--client', str(client), '--manager', str(manager)]
            error = None
            with mock.patch.object(sys, 'argv', args), mock.patch.object(module.subprocess, 'run', side_effect=fake_remote), redirect_stdout(io.StringIO()):
                try:
                    module.main()
                except RuntimeError as exc:
                    error = str(exc)
            return error, calls, uploads, list((base / 'tmp').iterdir())

    def test_existing_package_is_rejected_before_staging_or_upload(self):
        for kind in ('directory', 'file', 'symlink', 'dangling'):
            with self.subTest(kind=kind):
                error, calls, uploads, staged = self.invoke_installer(kind)
                self.assertIn('Existing native_endpoint package', error)
                self.assertEqual(len(calls), 1)
                self.assertEqual(uploads, [])
                self.assertEqual(staged, [])

    def test_package_appearing_after_upload_is_rejected_before_activation(self):
        error, calls, uploads, _ = self.invoke_installer(install_package_during_upload=True)
        self.assertIn('Existing native_endpoint package', error)
        self.assertEqual(len(uploads), 4)
        self.assertEqual(calls[-1][0], 'sh -s')

    def test_device_without_endpoint_package_passes_preflight(self):
        error, _, uploads, staged = self.invoke_installer()
        self.assertIsNone(error)
        self.assertEqual(len(uploads), 4)
        self.assertEqual(len(staged), 1)


class LegacyBackupPreparationTest(unittest.TestCase):
    def prepare(self, kind='missing', corrupt=False, busy=False):
        document = (ROOT / 'device/native_endpoint/README.md').read_text()
        section = document.split('### 旧备份的启动目录准备', 1)[1]
        recipe = re.search(r'```sh\n(.*?)\n```', section, re.S).group(1)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            backup, runtime = base / 'backup', base / 'route'
            backup.mkdir()
            marker = base / 'restored'
            files = ('native_first_client.sh', 'native_first.env', 'native_asr.so')
            for name in files + ('client-functions.sh', 'native_route_restore.sh'):
                (backup / name).write_text('fixture\n')
            (backup / 'before.sha256').write_text(''.join(
                hashlib.sha256((backup / name).read_bytes()).hexdigest() + '  ' + name + '\n'
                for name in files))
            # Represents the old launcher's redirection, which cannot create D.
            (backup / 'restore.sh').write_text(
                'set -eu\nprintf restored > ' + shlex.quote(str(runtime / 'launch.log')) + '\n'
                'touch ' + shlex.quote(str(marker)) + '\n')
            if kind == 'directory':
                runtime.mkdir(mode=0o755)
            elif kind == 'file':
                runtime.write_text('keep')
            elif kind == 'symlink':
                runtime.symlink_to(backup, target_is_directory=True)
            elif kind == 'dangling':
                runtime.symlink_to(base / 'absent')
            if corrupt:
                (backup / 'native_first.env').write_text('changed fixture\n')
            if busy:
                (base / 'busy').touch()
            recipe = recipe.replace('BACKUP=/data/endpoint-backup-实际时间', 'BACKUP=' + shlex.quote(str(backup)))
            recipe = recipe.replace('/tmp/xiaomi_native_route', str(runtime))
            recipe = recipe.replace('/tmp/native_first_busy', str(base / 'busy'))
            result = RUN(['sh'], input=recipe, text=True, capture_output=True, timeout=5)
            mode = stat.S_IMODE(runtime.stat().st_mode) if runtime.is_dir() and not runtime.is_symlink() else None
            return result, marker.exists(), mode, runtime.exists()

    def test_legacy_restore_prepares_or_reuses_private_directory(self):
        for kind in ('missing', 'directory'):
            with self.subTest(kind=kind):
                result, restored, mode, _ = self.prepare(kind)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(restored)
                self.assertEqual(mode, 0o700)

    def test_legacy_restore_refuses_invalid_runtime(self):
        for kind in ('file', 'symlink', 'dangling'):
            with self.subTest(kind=kind):
                result, restored, _, _ = self.prepare(kind)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(restored)

    def test_bad_backup_or_busy_device_is_rejected_before_directory_creation(self):
        for options in ({'corrupt': True}, {'busy': True}):
            with self.subTest(options=options):
                result, restored, _, directory_exists = self.prepare(**options)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(restored)
                self.assertFalse(directory_exists)
