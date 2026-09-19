"""Bounded persistent-model controller; no device, microphone or cloud."""
from pathlib import Path
import os
import subprocess
import tempfile
import time
import unittest
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'device/endpoint_probe'

class NativePoolTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.p = Path(self.temp.name)
        self.children = []
        self.logs = []
        self.env = {**os.environ, 'EXPECTED_NEURAL_MANIFEST_SHA256': 'fixture'}
        definitions = ['-DNW_DIR="'+str(self.p)+'"', '-DCONTROL_DIR="'+str(self.p)+'"',
                       '-DNP_HELPER_SCRIPT="'+str(self.p/'helper.sh')+'"',
                       '-DNATIVE_BUSY_FILE="'+str(self.p/'busy')+'"', '-DNP_DRAIN_MS=2000', '-DNRS_MIN_SECONDS=8', '-DNRS_SERVICE_SECONDS=8', '-DNRS_POOL_PATH="'+str(self.p/'pool')+'"']
        for source, name in [('native_wake_pool.c', 'pool'), ('test_native_pool.c', 'fixture'), ('native_resident_session.c', 'manager')]:
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', *definitions,
                            str(SRC/source), '-o', str(self.p/name)], check=True, capture_output=True)
        (self.p/'helper.sh').write_text('#!/bin/sh\nexec "'+str(self.p/'fixture')+'" helper\n')
        self.fixture('init', str(os.getpid()))

    def tearDown(self):
        for proc in reversed(self.children):
            if proc.poll() is None:
                proc.terminate()
                try: proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait(timeout=3)
        for log in self.logs: log.close()
        self.temp.cleanup()

    def fixture(self, *args):
        return subprocess.run([str(self.p/'fixture'), *args], check=True, capture_output=True, text=True, timeout=3).stdout

    def launch(self, stage='ready', turns=None, resident=None):
        path = self.p/('run-'+str(len(self.children))+'.log')
        log = path.open('wb'); self.logs.append(log)
        args = ['resident', str(resident)] if resident else ['20'] + ([str(turns)] if turns else [])
        proc = subprocess.Popen([str(self.p/'pool'), *args], env={**self.env, 'POOL_STAGE':stage}, stdout=log, stderr=subprocess.STDOUT)
        self.children.append(proc)
        return proc, path

    def wait_for(self, predicate, message):
        until = time.monotonic()+4
        while time.monotonic()<until:
            if predicate(): return
            time.sleep(.01)
        self.fail(message() if callable(message) else message)

    def ready(self, path):
        self.wait_for(lambda:'FIRST_POOL_READY' in path.read_text(), path.read_text)

    def clean(self):
        self.assertFalse((self.p/'native-wake.state').exists())
        self.assertFalse((self.p/'native-pool.state').exists())
        self.assertFalse(list(self.p.glob('shadow.*')))
        self.assertFalse((self.p/'session.sock').exists())

    def test_four_generations_share_child_and_preserve_cancel_denials(self):
        proc, log = self.launch(); self.ready(log)
        ids = []
        for i in range(4):
            ids.append(self.fixture('assert-ready').strip())
            self.fixture('begin')
            if i<2: self.fixture('cancel')
            else:
                self.fixture('complete')
                self.wait_for(lambda:log.read_text().count('FIRST_POOL_ROUTE')>=i-1, log.read_text)
                if i<3:
                    self.wait_for(lambda:log.read_text().count('FIRST_POOL_RETIRED')>=i+1, log.read_text)
        self.assertEqual(proc.wait(timeout=3), 0, log.read_text())
        self.assertEqual(len({x.split()[0] for x in ids}), 4)
        self.assertEqual(len({tuple(x.split()[1:]) for x in ids}), 1)
        self.assertEqual(log.read_text().count('POOL_FIXTURE_STARTED'), 1)
        records = [p.read_text() for p in (self.p/'routes').iterdir()]
        self.assertEqual(sum(x.endswith(' pending\n') for x in records), 2)
        self.assertEqual(sum(x.endswith(' quiet\n') for x in records), 2)
        self.clean()

    def test_helper_death_never_promotes_pending_and_all_slots_clean(self):
        proc, log = self.launch(); self.ready(log)
        ids = dict(x.split('=') for x in self.fixture('assert-ready').split())
        self.fixture('begin'); os.kill(int(ids['observer']), 9)
        self.assertNotEqual(proc.wait(timeout=3), 0, log.read_text())
        self.assertTrue(next((self.p/'routes').iterdir()).read_text().endswith(' pending\n'))
        self.clean()

    def test_native_identity_change_releases_old_pool_without_approving_pending(self):
        proc, log = self.launch(resident=20); self.ready(log)
        self.fixture('begin')
        replacement = subprocess.Popen(['sleep', '20']); self.children.append(replacement)
        self.fixture('init', str(replacement.pid))
        self.assertNotEqual(proc.wait(timeout=3), 0, log.read_text())
        self.assertIn('FIRST_POOL_NATIVE_CHANGED', log.read_text())
        self.assertTrue(next((self.p/'routes').iterdir()).read_text().endswith(' pending\n'))
        self.clean()

    def test_daily_service_renews_completed_lease_until_explicit_stop(self):
        path=self.p/'service.log';log=path.open('wb');self.logs.append(log)
        proc=subprocess.Popen([str(self.p/'manager'),'service'],env=self.env,stdout=log,stderr=subprocess.STDOUT)
        self.children.append(proc);self.ready(path)
        first=self.fixture('assert-ready')
        until=time.monotonic()+10
        while path.read_text().count('FIRST_POOL_READY')<2 and time.monotonic()<until:time.sleep(.05)
        self.assertEqual(path.read_text().count('FIRST_POOL_READY'),2,path.read_text())
        self.assertNotEqual(first.split()[1:],self.fixture('assert-ready').split()[1:])
        self.assertIn('FIRST_RESIDENT_RENEW',path.read_text())
        subprocess.run([str(self.p/'manager'),'stop'],check=True,timeout=5)
        self.assertEqual(proc.wait(timeout=3),0,path.read_text());self.clean()

    def test_stop_uses_existing_session_socket_and_cleans(self):
        proc, log = self.launch(); self.ready(log)
        stopped = subprocess.run([str(self.p/'pool'), 'stop'], capture_output=True, timeout=3)
        self.assertEqual(stopped.returncode, 0)
        proc.wait(timeout=3); self.clean()

    def test_killed_owner_is_recovered_without_reusing_old_generations(self):
        first, log = self.launch(); self.ready(log)
        self.fixture('begin'); first.kill(); first.wait(timeout=3)
        time.sleep(.1)
        second, next_log = self.launch(); self.ready(next_log)
        self.assertIn('FIRST_POOL_RECOVERED', next_log.read_text())
        self.assertTrue(next((self.p/'routes').iterdir()).read_text().endswith(' pending\n'))
        second.terminate(); second.wait(timeout=3); self.clean()

    def test_stop_during_preload_never_arms(self):
        proc, log = self.launch('before')
        self.wait_for(lambda:'POOL_FIXTURE_STARTED' in log.read_text(), log.read_text)
        proc.terminate(); proc.wait(timeout=3)
        self.assertNotIn('FIRST_POOL_READY', log.read_text()); self.clean()

    def test_unclaimed_native_bypass_retires_its_empty_input_slot(self):
        proc, log = self.launch(); self.ready(log)
        before = self.fixture('assert-ready')
        self.fixture('bypass')
        after = self.fixture('assert-ready')
        self.assertNotEqual(before.split()[0], after.split()[0])
        self.assertEqual(before.split()[1:], after.split()[1:])
        proc.terminate(); proc.wait(timeout=3); self.clean()

    def test_forty_turns_recycle_fresh_maps_with_one_child(self):
        proc, log = self.launch(turns=40); self.ready(log)
        ids, denials = [], []
        max_files = 0
        for i in range(40):
            current = self.fixture('assert-ready').strip(); ids.append(current)
            nonce = current.split()[0].split('=')[1]
            if i % 5 == 0:
                self.fixture('bypass')
            else:
                self.fixture('begin')
                if i % 3 == 0:
                    self.fixture('cancel'); denials.append('pool-'+nonce)
                else:
                    self.fixture('complete')
            self.wait_for(lambda:log.read_text().count('FIRST_POOL_RETIRED')>=i+1, log.read_text)
            if i<39:
                self.wait_for(lambda:log.read_text().count('FIRST_POOL_RECYCLED')>=i+1, log.read_text)
                max_files=max(max_files,len(list(self.p.glob('shadow.*'))))
        self.assertEqual(proc.wait(timeout=3),0,log.read_text())
        self.assertEqual(len({x.split()[0] for x in ids}),40)
        self.assertEqual(len({tuple(x.split()[1:]) for x in ids}),1)
        self.assertEqual(log.read_text().count('POOL_FIXTURE_STARTED'),1)
        self.assertLessEqual(max_files,12)
        archived=(self.p/'routes.denied/b_p').read_text().splitlines()[1:]
        self.assertEqual(archived,denials[:-1] if 'pool-'+nonce in denials else denials)
        self.assertLessEqual(len(list((self.p/'routes').iterdir())),33)
        self.clean()

    def test_stop_while_replacement_unprepared_cleans_both_generations(self):
        proc,log=self.launch(stage='refill',turns=12);self.ready(log)
        self.fixture('begin');self.fixture('cancel')
        self.wait_for(lambda:'POOL_FIXTURE_REFILL_PAUSED' in log.read_text(),log.read_text)
        proc.terminate();proc.wait(timeout=3)
        self.assertIn('pool-',(self.p/'routes.denied/b_p').read_text())
        self.clean()

    def test_crashed_controller_during_refill_is_recoverable(self):
        proc,log=self.launch(stage='refill',turns=12);self.ready(log)
        self.fixture('begin');self.fixture('cancel')
        self.wait_for(lambda:'POOL_FIXTURE_REFILL_PAUSED' in log.read_text(),log.read_text)
        proc.kill();proc.wait(timeout=3);time.sleep(.1)
        second,next_log=self.launch(turns=12);self.ready(next_log)
        self.assertIn('FIRST_POOL_RECOVERED',next_log.read_text())
        self.assertIn('pool-',(self.p/'routes.denied/b_p').read_text())
        second.terminate();second.wait(timeout=3);self.clean()

    def test_unprepared_replacement_exhausts_safely_without_reusing_slot(self):
        proc,log=self.launch(stage='refill',turns=12);self.ready(log)
        self.fixture('begin');self.fixture('cancel')
        self.wait_for(lambda:'POOL_FIXTURE_REFILL_PAUSED' in log.read_text(),log.read_text)
        for _ in range(3):
            self.fixture('assert-ready');self.fixture('begin');self.fixture('cancel')
        self.assertNotEqual(proc.wait(timeout=3),0,log.read_text())
        self.assertNotIn('FIRST_POOL_RECYCLED',log.read_text())
        self.assertNotIn('allowed=1',log.read_text())
        self.assertEqual(len(list((self.p/'routes').iterdir())),3)
        self.assertTrue(all(p.read_text().endswith(' pending\n') for p in (self.p/'routes').iterdir()))
        self.clean()

    def test_resident_idle_drains_without_claiming_another_request(self):
        proc,log=self.launch(resident=8);self.ready(log)
        self.fixture('begin');self.fixture('complete')
        self.wait_for(lambda:'allowed=1' in log.read_text(),log.read_text)
        self.assertEqual(proc.wait(timeout=9),0,log.read_text())
        self.assertIn('resident=1',log.read_text())
        self.assertIn('FIRST_POOL_DRAIN idle=1 saved=1',log.read_text())
        self.clean()

    def test_resident_budget_does_not_stop_an_active_turn_at_drain_boundary(self):
        proc,log=self.launch(resident=8);self.ready(log)
        self.fixture('begin');time.sleep(6.2)
        self.assertIsNone(proc.poll(),log.read_text())
        self.fixture('complete')
        self.assertEqual(proc.wait(timeout=3),0,log.read_text())
        self.assertIn('allowed=1',log.read_text())
        self.clean()

    def test_resident_manager_reloads_dead_model_without_approving_old_result(self):
        logpath=self.p/'managed.log';log=logpath.open('wb');self.logs.append(log)
        proc=subprocess.Popen([str(self.p/'manager'),'25'],env=self.env,stdout=log,stderr=subprocess.STDOUT);self.children.append(proc)
        self.ready(logpath)
        first=dict(x.split('=') for x in self.fixture('assert-ready').split())
        self.fixture('begin');os.kill(int(first['observer']),9)
        until=time.monotonic()+7
        while logpath.read_text().count('FIRST_POOL_READY')<2 and time.monotonic()<until:time.sleep(.02)
        self.assertEqual(logpath.read_text().count('FIRST_POOL_READY'),2,logpath.read_text())
        second=dict(x.split('=') for x in self.fixture('assert-ready').split())
        self.assertNotEqual(first['observer'],second['observer']);self.assertNotEqual(first['owner'],second['owner'])
        self.assertTrue(next((self.p/'routes').iterdir()).read_text().endswith(' pending\n'))
        stopped=subprocess.run([str(self.p/'manager'),'stop'],capture_output=True,timeout=5)
        self.assertEqual(stopped.returncode,0);proc.wait(timeout=3);self.clean()
        self.assertFalse((self.p/'resident.sock').exists())
