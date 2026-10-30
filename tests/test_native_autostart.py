"""Autostart chooses dependencies from the real config without contacting a speaker."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NativeAutostartTest(unittest.TestCase):
    def run_init(self, config, *, reachable=True, without='1', running=False, environment=None):
        with tempfile.TemporaryDirectory() as temp:
            config_path = Path(temp, 'actual.env')
            if config is not None:
                config_path.write_text(config)
            client = Path(temp, 'client.sh')
            client.write_text('''#!/bin/sh
[ ! -f "$CONFIG_FILE" ] || . "$CONFIG_FILE"
printf '%s|%s|%s' "${LLM_PIPELINE:-native}" "${TTS_ENGINE:-server}" "${BACKEND:-deepseek}" > "$TEST_DIR/started"
''')
            client.chmod(0o700)
            source = (ROOT / 'device/data_init_native_first.sh').read_text()
            source = source.rsplit('\nmain "$@"', 1)[0].replace('/tmp/native_first_client.log', temp + '/client.log')
            source += r'''
sleep() { printf '%s\n' "$1" >> "$TEST_DIR/sleeps"; }
is_client_running() { [ "$ALREADY_RUNNING" = 1 ]; }
curl() {
    for arg in "$@"; do url=$arg; done
    printf '%s\n' "$url" >> "$TEST_DIR/probes"
    [ "$REACHABLE" = 1 ]
}
main
wait
'''
            base_env = {key: value for key, value in os.environ.items()
                        if key not in ('LLM_PIPELINE', 'TTS_ENGINE', 'TTS_SERVER', 'SERVER', 'BACKEND')}
            env = {**base_env, 'TEST_DIR': temp, 'CONFIG_FILE': str(config_path), 'CLIENT': str(client),
                   'LOG_FILE': temp + '/autostart.log', 'START_DELAY': '0', 'SERVER_WAIT_SECONDS': '5',
                   'START_WITHOUT_SERVER': without, 'REACHABLE': str(int(reachable)),
                   'ALREADY_RUNNING': str(int(running)), **(environment or {})}
            run = subprocess.run(['sh', '-c', source], capture_output=True, text=True, timeout=5, env=env)
            def read(name):
                path = Path(temp, name)
                return path.read_text() if path.exists() else ''
            return run, read('autostart.log'), read('probes').splitlines(), read('started'), read('sleeps').splitlines()

    def test_native_device_skips_unrelated_server_and_optional_mac_asr(self):
        run, log, probes, started, sleeps = self.run_init(
            'LLM_PIPELINE=native\nTTS_ENGINE=device\nFOLLOWUP_ASR_ENGINE=mac\n',
            reachable=False, without='0')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(probes, [])
        self.assertEqual(started, 'native|device|deepseek')
        self.assertEqual(sleeps, ['0'])
        self.assertIn('startup dependency=none', log)

    def test_native_server_probes_configured_tts_address(self):
        run, _, probes, started, _ = self.run_init(
            "LLM_PIPELINE=native\nTTS_ENGINE=server\nSERVER=http://unused\nTTS_SERVER='http://actual-tts:8081'\n")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(probes, ['http://actual-tts:8081/'])
        self.assertTrue(started)

    def test_server_pipeline_uses_server_even_with_device_tts(self):
        run, _, probes, _, _ = self.run_init(
            'LLM_PIPELINE=server\nTTS_ENGINE=device\nSERVER=http://actual-server\nTTS_SERVER=http://unused\n')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(probes, ['http://actual-server/'])

    def test_real_file_overrides_conflicting_environment_and_log_file_is_isolated(self):
        run, log, probes, started, _ = self.run_init(
            'LLM_PIPELINE=native\nTTS_ENGINE=device\nBACKEND=kimi\nLOG_FILE="$TEST_DIR/config-client.log"\n',
            environment={'LLM_PIPELINE': 'server', 'TTS_ENGINE': 'server', 'BACKEND': 'glm'})
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(probes, [])
        self.assertEqual(started, 'native|device|kimi')
        self.assertIn('starting native-first client', log)

    def test_shell_config_expansion_selects_the_same_effective_value(self):
        run, _, probes, _, _ = self.run_init(
            'LLM_PIPELINE=native\nTTS_ENGINE=server\nSERVICE_HOST=http://configured\nTTS_SERVER="$SERVICE_HOST:9000"\n')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(probes, ['http://configured:9000/'])

    def test_tts_address_falls_back_to_server_and_missing_config_uses_client_defaults(self):
        for config, expected in [('SERVER=http://fallback\n', 'http://fallback/'),
                                 (None, 'http://192.168.8.150:8080/')]:
            with self.subTest(config=config):
                run, _, probes, started, _ = self.run_init(config)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(probes, [expected])
                self.assertEqual(started, 'native|server|deepseek')

    def test_unreachable_dependency_preserves_existing_wait_and_start_policy(self):
        for without in ('0', '1'):
            with self.subTest(without=without):
                run, log, probes, started, sleeps = self.run_init('LLM_PIPELINE=server\n',
                                                                               reachable=False, without=without)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(len(probes), 2)
                self.assertEqual(sleeps, ['0', '3', '3'])
                self.assertEqual(bool(started), without == '1')
                self.assertIn('server not reachable after 5s', log)

    def test_config_errors_are_explained_without_start_or_secret_output(self):
        run, log, probes, started, _ = self.run_init('API_KEY=private-fixture\nTTS_SERVER="unterminated\n')
        self.assertNotEqual(run.returncode, 0)
        self.assertIn('configuration load failed; client not started', log)
        self.assertEqual(probes, [])
        self.assertEqual(started, '')
        self.assertNotIn('private-fixture', log + run.stdout + run.stderr)

    def test_urls_and_config_output_do_not_leak_to_autostart_log(self):
        run, log, probes, _, _ = self.run_init(
            'API_KEY=private-fixture\nSERVER=http://user:credential@local-service\n'
            'echo private-config-output\n')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(probes, ['http://user:credential@local-service/'])
        for secret in ('private-fixture', 'credential', 'private-config-output', 'local-service'):
            self.assertNotIn(secret, log + run.stdout + run.stderr)

    def test_existing_client_is_not_started_or_probed_again(self):
        run, log, probes, started, _ = self.run_init('LLM_PIPELINE=server\n', running=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('client already running', log)
        self.assertEqual(probes, [])
        self.assertEqual(started, '')
