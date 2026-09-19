"""Actual watcher + supervisor; private fake model, no audio or cloud."""
from pathlib import Path
import os
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'device/endpoint_probe'


class NativeLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.p = Path(self.temp.name)
        self.children = []
        self.handles = []
        self.env = {**os.environ, 'NATIVE_WAKE_SESSION_DIR': str(self.p),
                    'EXPECTED_NEURAL_MANIFEST_SHA256': 'fixture', 'LIFECYCLE_STAGE': 'stream'}
        definitions = ['-DNW_DIR="' + str(self.p) + '"', '-DCONTROL_DIR="' + str(self.p) + '"',
                       '-DNW_HELPER_SCRIPT="' + str(self.p / 'helper.sh') + '"',
                       '-DNW_READY_IDLE_MS=500']
        for source, name in [('native_wake_watch.c', 'native_wake_watch'),
                             ('native_wake_session.c', 'native_wake_session'),
                             ('test_native_lifecycle.c', 'fixture')]:
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', *definitions,
                            str(SRC / source), '-o', str(self.p / name)], check=True, capture_output=True)
        (self.p / 'helper.sh').write_text('#!/bin/sh\nexec "' + str(self.p / 'fixture') + '" helper "$@"\n')
        self.fixture('init', str(os.getpid()))

    def tearDown(self):
        for proc in reversed(self.children):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
        for handle in self.handles:
            handle.close()
        self.temp.cleanup()

    def fixture(self, *args):
        subprocess.run([str(self.p / 'fixture'), *args], check=True, capture_output=True, timeout=3)

    def launch(self, name, *args, stage='stream'):
        log = self.p / ('run-' + str(len(self.children)) + '.log')
        handle = log.open('wb')
        self.handles.append(handle)
        proc = subprocess.Popen([str(self.p / name), *args], env={**self.env, 'LIFECYCLE_STAGE': stage},
                                stdout=handle, stderr=subprocess.STDOUT)
        self.children.append(proc)
        return proc, log

    def wait_for(self, predicate, message):
        until = time.monotonic() + 4
        while time.monotonic() < until:
            if predicate():
                return
            time.sleep(.02)
        self.fail(message() if callable(message) else message)

    def ready(self, log):
        self.wait_for(lambda: 'FIRST_ENDPOINT_READY' in log.read_text(), log.read_text())

    def test_kill_during_preload_reclaims_only_that_generation(self):
        for stage, marker in [('before', 'FIXTURE_HELPER'), ('stream', 'FIXTURE_STREAM_WRITTEN')]:
            first, log = self.launch('native_wake_watch', 'endpoint-tagged', stage=stage)
            self.wait_for(lambda: marker in log.read_text(), 'helper did not reach ' + stage)
            self.assertNotIn('FIRST_ENDPOINT_READY', log.read_text())
            # Non-live staged state cannot claim a wake while the model loads.
            self.assertTrue((self.p / 'native-wake.state').exists())
            self.fixture('assert-unarmed')
            first.kill()
            first.wait(timeout=3)
            # Session retries while the dead owner's helper is still exiting.
            next_session, next_log = self.launch('native_wake_session', '1', '10', stage='ready')
            self.ready(next_log)
            self.assertIn('FIRST_RECOVERED', next_log.read_text())
            self.fixture('complete')
            self.assertEqual(next_session.wait(timeout=3), 0, next_log.read_text())
            self.assertFalse((self.p / 'native-wake.state').exists())
            self.assertFalse(list(self.p.glob('shadow.*')))

    def test_kill_supervisor_stops_preloading_worker_and_restart_succeeds(self):
        first, log = self.launch('native_wake_session', '1', '10')
        self.wait_for(lambda: 'FIXTURE_STREAM_WRITTEN' in log.read_text(), 'helper never started')
        first.kill()
        first.wait(timeout=3)
        self.wait_for(lambda: not (self.p / 'native-wake.state').exists(), 'orphan watcher did not clean')
        self.assertFalse(list(self.p.glob('shadow.*')))
        second, second_log = self.launch('native_wake_session', '1', '10', stage='ready')
        self.ready(second_log)
        # Competing supervisors are denied by a kernel lock, not pid text.
        competing = subprocess.run([str(self.p / 'native_wake_session'), '1', '1'],
                                   env=self.env, capture_output=True, timeout=3)
        self.assertEqual(competing.returncode, 2)
        self.fixture('complete')
        self.assertEqual(second.wait(timeout=3), 0, second_log.read_text())
        self.assertEqual((self.p / 'session.guard').read_text(), '')

    def test_term_during_preload_cleans_and_never_arms(self):
        proc, log = self.launch('native_wake_watch', 'endpoint-tagged')
        self.wait_for(lambda: 'FIXTURE_STREAM_WRITTEN' in log.read_text(), 'helper never started')
        proc.terminate()
        self.assertNotEqual(proc.wait(timeout=3), 0)
        self.assertNotIn('FIRST_ENDPOINT_READY', log.read_text())
        self.assertFalse((self.p / 'native-wake.state').exists())
        self.assertFalse(list(self.p.glob('shadow.*')))

    def test_protected_journal_full_refuses_before_loading_or_arming(self):
        routes = self.p / 'routes'
        routes.mkdir(mode=0o700)
        for i in range(256):
            (routes / str(i)).write_text('unknown\n')
        proc, log = self.launch('native_wake_session', '1', '10', stage='ready')
        self.assertNotEqual(proc.wait(timeout=3), 0)
        self.assertIn('FIRST_ROUTE_CAPACITY protected-full action=no-arm', log.read_text())
        self.assertNotIn('FIRST_PRELOAD', log.read_text())
        self.assertNotIn('FIXTURE_HELPER', log.read_text())
        self.assertFalse((self.p / 'native-wake.state').exists())
        self.assertEqual(len(list(routes.iterdir())), 256)

    def test_busy_after_real_preload_keeps_retry_code_and_cleans(self):
        proc, log = self.launch('native_wake_watch', 'endpoint-tagged', stage='busy')
        self.assertEqual(proc.wait(timeout=3), 3, log.read_text())
        self.assertIn('FIXTURE_MAPPINGS_READY', log.read_text())
        self.assertNotIn('FIRST_ENDPOINT_READY', log.read_text())
        self.assertFalse((self.p / 'native-wake.state').exists())
        self.assertFalse(list(self.p.glob('shadow.*')))

    def test_idle_expiry_is_distinct_from_a_failed_request(self):
        proc, log = self.launch('native_wake_watch', 'endpoint-ready', stage='ready')
        self.assertEqual(proc.wait(timeout=3), 4, log.read_text())
        self.assertIn('FIRST_ENDPOINT_READY', log.read_text())
        self.assertIn('modified=0 ended=0 final=0 finished=0 failed=0 frames=0', log.read_text())
        self.assertFalse((self.p / 'native-wake.state').exists())
        self.assertFalse(list(self.p.glob('shadow.*')))

    def test_second_wake_cancels_without_promoting_old_pending_result(self):
        proc, log = self.launch('native_wake_watch', 'endpoint-tagged', stage='ready')
        self.ready(log)
        self.fixture('begin')
        self.fixture('cancel')
        self.assertEqual(proc.wait(timeout=3), 5, log.read_text())
        records = list((self.p / 'routes').iterdir())
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].read_text().endswith(' pending\n'))
        self.assertFalse((self.p / 'native-wake.state').exists())
        self.assertFalse(list(self.p.glob('shadow.*')))

    def test_two_user_cancellations_keep_supervisor_ready_for_next_question(self):
        proc, log = self.launch('native_wake_session', '3', '15', stage='ready')
        for round_number in range(1, 6):
            self.wait_for(lambda: log.read_text().count('FIRST_ENDPOINT_READY') >= round_number,
                          lambda: 'missing next READY after cancellation: ' + log.read_text())
            if round_number < 3:
                self.fixture('begin')
                self.fixture('cancel')
            else:
                self.fixture('complete')
        self.assertEqual(proc.wait(timeout=3), 0, log.read_text())
        self.assertEqual(log.read_text().count('FIRST_SESSION_WAIT reason=replaced'), 2)
        self.assertIn('attempted=3 passed=3 consecutive_failed=0', log.read_text())
        records = [p.read_text() for p in (self.p / 'routes').iterdir()]
        self.assertEqual(sum(r.endswith(' pending\n') for r in records), 2)
        self.assertEqual(sum(r.endswith(' quiet\n') for r in records), 3)

    def test_protocol_revocation_still_counts_as_failure(self):
        proc, log = self.launch('native_wake_watch', 'endpoint-tagged', stage='ready')
        self.ready(log)
        self.fixture('begin')
        self.fixture('revoke')
        self.assertEqual(proc.wait(timeout=3), 1, log.read_text())
        records = list((self.p / 'routes').iterdir())
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].read_text().endswith(' pending\n'))
