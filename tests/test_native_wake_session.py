"""Exercise the real bounded supervisor with workers that never access audio."""
import os
import time
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / 'device/endpoint_probe/run_native_wake_session.sh'


class NativeWakeSessionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.build.name) / 'native_wake_session'
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror',
                        str(ROOT / 'device/endpoint_probe/native_wake_session.c'),
                        '-o', str(cls.binary)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def run_session(self, worker, turns='3', seconds='20', locked=False):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / 'native_wake_session').symlink_to(self.binary)
            script = p / 'native_wake_watch'
            script.write_text('#!/bin/sh\n' + worker)
            script.chmod(0o700)
            if locked:
                (p / 'session.lock').mkdir(mode=0o700)
                owner = 'not-ours'
                if locked == 'dead':
                    old = subprocess.Popen(['sh', '-c', 'exit 0'])
                    old.wait(timeout=3)
                    owner = str(old.pid)
                (p / 'session.lock/owner').write_text(owner + '\n')
                (p / 'session.lock/owner').chmod(0o600)
            proc = subprocess.run(['sh', str(RUNNER), turns, seconds],
                                  env={**os.environ, 'NATIVE_WAKE_SESSION_DIR': tmp,
                                       'EXPECTED_NEURAL_MANIFEST_SHA256': 'fixture'},
                                  text=True, capture_output=True, timeout=6)
            remains = (p / 'session.lock').exists()
            return proc, remains

    def test_rearms_three_successful_turns_and_cleans_lock(self):
        p, remains = self.run_session('test "$1" = endpoint-tagged\nexit 0\n')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.count('FIRST_SESSION_TRIAL index='), 3)
        self.assertIn('attempted=3 passed=3', p.stdout)
        self.assertFalse(remains)

    def test_configuration_failure_stops_without_repeated_restart(self):
        p, remains = self.run_session('exit 2\n')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('attempted=1 passed=0', p.stdout)
        self.assertFalse(remains)

    def test_two_failures_stop_instead_of_spinning(self):
        p, remains = self.run_session('exit 1\n')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('attempted=2 passed=0 consecutive_failed=2', p.stdout)
        self.assertFalse(remains)

    def test_busy_during_preload_waits_without_consuming_a_turn(self):
        worker = '''if [ ! -e "$NATIVE_WAKE_SESSION_DIR/once" ]; then
touch "$NATIVE_WAKE_SESSION_DIR/once"
exit 3
fi
exit 0
'''
        p, remains = self.run_session(worker, turns='1')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('attempted=1 passed=1', p.stdout)
        self.assertFalse(remains)

    def test_deadline_waits_for_worker_cleanup(self):
        # Worker trap writes to stdout; capture_output also catches orphan timer
        # processes retaining the output pipe after supervisor termination.
        worker = "trap 'echo WORKER_CLEANED; exit 1' TERM\nwhile :; do sleep 0.05; done\n"
        p, remains = self.run_session(worker, seconds='1')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('WORKER_CLEANED', p.stdout)
        self.assertIn('expired=1 interrupted=1', p.stdout)
        self.assertFalse(remains)

    def test_two_idle_windows_do_not_consume_turns_or_failure_budget(self):
        worker = '''counter="$NATIVE_WAKE_SESSION_DIR/count"
n=0
[ ! -e "$counter" ] || read n < "$counter"
n=$((n + 1))
echo "$n" > "$counter"
[ "$n" -gt 2 ] || exit 4
exit 0
'''
        p, remains = self.run_session(worker, turns='1')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(p.stdout.count('FIRST_SESSION_WAIT reason=idle'), 2)
        self.assertIn('attempted=1 passed=1 consecutive_failed=0', p.stdout)
        self.assertFalse(remains)

    def test_ready_mode_remains_bounded_and_cleans_idle_worker(self):
        worker = '''[ "$1" = endpoint-ready ] || exit 2
echo WARM_WORKER_READY
trap 'echo WORKER_CLEANED; exit 1' TERM
while :; do sleep 0.05; done
'''
        p, remains = self.run_session(worker, turns='ready', seconds='1')
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn('WARM_WORKER_READY', p.stdout)
        self.assertIn('WORKER_CLEANED', p.stdout)
        self.assertIn('expired=1 interrupted=1', p.stdout)
        self.assertFalse(remains)

    def test_another_supervisor_lock_is_preserved(self):
        p, remains = self.run_session('exit 0\n', locked=True)
        self.assertEqual(p.returncode, 2)
        self.assertTrue(remains)

    def test_verified_dead_legacy_supervisor_lock_is_reclaimed(self):
        p, remains = self.run_session('exit 0\n', locked='dead')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(remains)

    def test_deadline_kills_unresponsive_direct_worker(self):
        p, remains = self.run_session("trap '' TERM\nwhile :; do :; done\n", seconds='1')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('expired=1 interrupted=1', p.stdout)
        self.assertFalse(remains)

    def test_stop_uses_local_request_and_waits_for_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / 'native_wake_session').symlink_to(self.binary)
            worker = p / 'native_wake_watch'
            worker.write_text("#!/bin/sh\ntrap 'echo WORKER_CLEANED; exit 1' TERM\necho WORKER_READY\nwhile :; do sleep 0.05; done\n")
            worker.chmod(0o700)
            env = {**os.environ, 'NATIVE_WAKE_SESSION_DIR': tmp,
                   'EXPECTED_NEURAL_MANIFEST_SHA256': 'fixture'}
            log = p / 'run.log'
            with log.open('wb') as out:
                proc = subprocess.Popen(['sh', str(RUNNER), '1', '10'], env=env, stdout=out, stderr=out)
                try:
                    until = time.monotonic() + 3
                    while 'WORKER_READY' not in log.read_text() and time.monotonic() < until:
                        time.sleep(.02)
                    self.assertIn('WORKER_READY', log.read_text())
                    # Deliberately replace diagnostic PID text with our own PID.
                    # Stop must never signal it, nor need a model manifest.
                    (p / 'session.guard').write_text(str(os.getpid()) + '\n')
                    env.pop('EXPECTED_NEURAL_MANIFEST_SHA256')
                    stopped = subprocess.run(['sh', str(RUNNER), 'stop'], env=env,
                                             capture_output=True, text=True, timeout=6)
                    self.assertEqual(stopped.returncode, 0, stopped.stderr)
                    self.assertIn('FIRST_SESSION_STOPPED', stopped.stdout)
                    self.assertNotEqual(proc.wait(timeout=3), 0)
                    self.assertIn('WORKER_CLEANED', log.read_text())
                    self.assertFalse((p / 'session.sock').exists())
                    (p / 'session.guard').write_text(str(os.getpid()) + '\n')
                    idle = subprocess.run(['sh', str(RUNNER), 'stop'], env=env,
                                          capture_output=True, text=True, timeout=3)
                    self.assertEqual(idle.returncode, 0, idle.stderr)
                    self.assertIn('FIRST_SESSION_IDLE', idle.stdout)
                finally:
                    if proc.poll() is None:
                        proc.kill()
                    proc.wait(timeout=3)

    def test_stop_refuses_unresolved_legacy_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / 'session.lock').mkdir(mode=0o700)
            (p / 'session.lock/owner').write_text(str(os.getpid()) + '\n')
            run = subprocess.run([str(self.binary), 'stop'],
                                 env={**os.environ, 'NATIVE_WAKE_SESSION_DIR': tmp},
                                 capture_output=True, timeout=3)
            self.assertEqual(run.returncode, 2)
            self.assertTrue((p / 'session.lock/owner').exists())

    def test_unbounded_values_are_rejected(self):
        for turns, seconds in [('0', '20'), ('21', '20'), ('3', '241'), ('3', 'forever'), ('ready', '241')]:
            p, remains = self.run_session('exit 0\n', turns, seconds)
            self.assertEqual(p.returncode, 2)
            self.assertFalse(remains)
