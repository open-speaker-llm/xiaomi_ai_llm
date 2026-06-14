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
            "FOLLOWUP_ARM_DELAY": "0",
            "FOLLOWUP_ARM_POLL_SECONDS": "0.03",
            "FOLLOWUP_START_HITS": "1",
            "FOLLOWUP_MIN_RAW_BYTES": "16000",
            "FOLLOWUP_WINDOW_MIN_PEAK": "180",
            "FOLLOWUP_WINDOW_MIN_RMS_THRESHOLD": "25",
            "FOLLOWUP_WINDOW_MIN_ACTIVE_PERMILLE": "2",
            "NATIVE_REPLAY_SUCCESS_DELAY": "0",
            "NATIVE_REPLAY_SUCCESS_SPEAK": "1",
            "FREEZE_NATIVE_PLAYER_ON_THINK": "1",
            "SUPPRESS_NATIVE_THINK_LED": "1",
            "LLM_VOLUME": "1.1",
            "LLM_MASTER_SCALE": "100",
            "LLM_MASTER_CURRENT_SCALE": "100",
            "LLM_MASTER_MAX": "160",
            "LLM_PIPELINE": "native",
            "LLM_MODEL": "deepseek-v4-flash",
            "LLM_THINKING": "disabled",
            "TTS_FALLBACK_NATIVE": "1",
            "TTS_NATIVE_WAIT_ENABLED": "1",
            "TTS_NATIVE_WAIT_MIN_SECONDS": "2",
            "TTS_NATIVE_WAIT_MAX_SECONDS": "30",
            "TTS_NATIVE_WAIT_BYTES_PER_SECOND": "24",
            "TTS_NATIVE_WAIT_EXTRA_SECONDS": "1",
            "TTS_NATIVE_STATUS_WAIT_ENABLED": "1",
            "TTS_NATIVE_STATUS_START_TIMEOUT_SECONDS": "4",
            "TTS_NATIVE_STATUS_MAX_SECONDS": "120",
            "TTS_NATIVE_STATUS_IDLE_HITS": "2",
            "TTS_NATIVE_STATUS_POLL_SECONDS": "0.2",
            "TTS_NATIVE_LED_SUPPRESS_INTERVAL_SECONDS": "0.3",
            "LED_FEEDBACK_ENABLED": "1",
            "LED_LLM_ACCEPT_BLINKS": "3",
            "LED_FOLLOWUP_ASR_OK_BLINKS": "3",
            "LED_ERROR_BLINKS": "3",
            "LED_BLINK_ON_SECONDS": "0.12",
            "LED_BLINK_OFF_SECONDS": "0.12",
            "LED_CHASE_DELAY_SECONDS": "0.08",
            "LED_SOLID_REFRESH_SECONDS": "0.3",
            "LED_WAKE_HOLD_SECONDS": "4",
            "LED_WAKE_HOLD_REFRESH_SECONDS": "0.1",
        }
        for key, value in expected_pairs.items():
            with self.subTest(key=key):
                self.assertIn(f"{key}={value}", env_text)
                self.assertIn(f'{key}="${{{key}:-{value}}}"', client_text)


if __name__ == "__main__":
    unittest.main()
