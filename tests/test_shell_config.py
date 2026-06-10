import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ShellConfigTest(unittest.TestCase):
    def run_shell(self, script: str):
        return subprocess.run(
            ["sh", "-c", script],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_device_shell_scripts_parse(self):
        scripts = [
            "device/native_first_client.sh",
            "device/vad_record.sh",
            "device/native_result_timing_probe.sh",
            "device/stream_client.sh",
            "device/wake_monitor.sh",
        ]
        for script in scripts:
            with self.subTest(script=script):
                result = subprocess.run(
                    ["sh", "-n", script],
                    cwd=ROOT,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_native_first_env_example_is_sourceable(self):
        result = self.run_shell(
            ". device/native_first.env.example; "
            'printf "%s\\n" "$BACKEND $FOLLOWUP_START_HITS $NATIVE_REPLAY_SUCCESS_DELAY"'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "deepseek 1 0")

    def test_env_example_tracks_key_client_defaults(self):
        env_text = (ROOT / "device/native_first.env.example").read_text()
        client_text = (ROOT / "device/native_first_client.sh").read_text()
        expected_pairs = {
            "FOLLOWUP_ARM_DELAY": "0.2",
            "FOLLOWUP_START_HITS": "1",
            "FOLLOWUP_MIN_RAW_BYTES": "16000",
            "NATIVE_REPLAY_SUCCESS_DELAY": "0",
            "NATIVE_REPLAY_SUCCESS_SPEAK": "1",
            "FREEZE_NATIVE_PLAYER_ON_THINK": "1",
            "LLM_PIPELINE": "server",
            "LLM_MODEL": "deepseek-v4-flash",
            "LLM_THINKING": "disabled",
            "TTS_FALLBACK_NATIVE": "1",
        }
        for key, value in expected_pairs.items():
            with self.subTest(key=key):
                self.assertIn(f"{key}={value}", env_text)
                self.assertIn(f'{key}="${{{key}:-{value}}}"', client_text)


if __name__ == "__main__":
    unittest.main()
