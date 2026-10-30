"""Version-bound low-space transaction; fake /data, firmware and service helpers."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/speaker-maintenance"))
import native_endpoint_release as release
import prepare_native_endpoint_upgrade as upgrade

spec = importlib.util.spec_from_file_location("release_fixtures", ROOT / "tests/test_native_endpoint_release.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


def control_elf():
    value = bytearray(64)
    value[:7] = b"\x7fELF\x02\x01\x01"
    struct.pack_into("<HH", value, 16, 2, 183)
    return bytes(value) + b"synthetic-aarch64-controller"


class EndpointUpgradeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.backup, self.candidate, self.extras = [self.root / name for name in ("backup", "candidate", "extras")]
        self.backup.mkdir()
        self.extras.mkdir()
        fixtures.make_package(self.backup / "native_endpoint", metadata=False)
        for name in ("native_first_client.sh", "native_asr.so"):
            shutil.copy2(self.backup / "native_endpoint" / name, self.backup / name)
        values = {"native_asr.sh": b"#!/bin/sh\nexit 0\n", "native_asr_ctl": control_elf(),
                  "init.sh": b"#!/bin/sh\nprintf 'OLD_INIT\\n'\n", "native_first.env": b"TTS_ENGINE=device\nPRIVATE_KEY=fixture-secret\n",
                  "ettsc": b"unchanged-v2-tool"}
        for name, value in values.items():
            (self.backup / name).write_bytes(value)
        self.before = {name: upgrade.file_hash(self.backup / name) for name in upgrade.BACKUP_FILES}
        (self.backup / "data-full.tar.gz").write_bytes(b"synthetic private full backup")
        record = {"device_root": "boot1", "files": self.before,
                  "data_archive_sha256": upgrade.file_hash(self.backup / "data-full.tar.gz")}
        (self.backup / "verified-manifest.json").write_text(json.dumps(record))
        fixtures.make_package(self.candidate, metadata=False)
        (self.candidate / "native_first_client.sh").write_bytes(b"#!/bin/sh\n# candidate\nexit 0\n")
        (self.candidate / "native_asr.so").write_bytes(fixtures.elf() + b"new library")
        runtime = fixtures.runtime_content()
        runtime["xiaomi_native_wake_probe/native_wake_pool"] += b"new runtime"
        runtime["runtime-files.sha256"] = fixtures.manifest({k: v for k, v in runtime.items() if k != "runtime-files.sha256"})
        (self.candidate / "runtime.tar.gz").write_bytes(fixtures.archive_bytes(runtime))
        fixtures.reseal(self.candidate)
        checked = release.validate_package(self.candidate)
        metadata = release.make_metadata(checked["package_manifest_sha256"], checked["runtime"], {"revision": "a" * 40, "dirty": False})
        (self.candidate / "release.json").write_text(json.dumps(metadata))
        (self.extras / "native_asr_ctl").write_bytes(control_elf() + b"new control")
        (self.extras / "init.sh").write_bytes(b"#!/bin/sh\nprintf 'NEW_INIT\\n'\n")
        (self.extras / "speaker_doctor.sh").write_bytes(b"#!/bin/sh\nexit 2\n")
        for path in (self.root / "data", self.root / "tmp", self.root / "proc", self.root / "usr/bin", self.root / "bin"):
            path.mkdir(parents=True)
        for name in upgrade.BACKUP_FILES:
            target = self.root / "data" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.backup / name, target)
        (self.root / "proc/mounts").write_text("/dev/mtdblock5 / squashfs ro 0 0\n")
        (self.root / "proc/meminfo").write_text("MemAvailable: 200000 kB\n")
        for pid, command in ((1, b"/sbin/init\0"), (2, b"/sbin/unrelated\0")):
            path = self.root / "proc" / str(pid)
            path.mkdir()
            (path / "cmdline").write_bytes(command)
        (self.root / "usr/bin/firmware").write_bytes(b"known firmware")
        self.firmware = {"/usr/bin/firmware": upgrade.file_hash(self.root / "usr/bin/firmware")}
        self.ident = "0123456789abcdef"
        self.stage = self.root / "tmp" / ("endpoint-upgrade-stage-" + self.ident)
        self.txn = self.root / "data" / ("endpoint-upgrade-" + self.ident)
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(upgrade, "SOURCE_PINS", {name: self.before[name] for name in upgrade.SOURCE_PINS}).start()
        mock.patch.object(upgrade, "FIRMWARE_PINS", self.firmware).start()
        old_client_hash = self.before["native_first_client.sh"]
        functions = f'''stop_route_client() {{ printf 'stop-client\\n' >> "$TMP/calls"; }}
route_stop_native() {{ printf 'stop-native\\n' >> "$TMP/calls"; }}
route_archive_log() {{ [ ! -e "$1" ] || mv "$1" "$2/instruction.log"; }}
launch_client() {{
 printf 'start-client\\n' >> "$TMP/calls"
 if [ -f "$TMP/fail-start" ] && [ "$(hash "$DATA/native_first_client.sh")" != {old_client_hash} ]; then return 1; fi
 return 0
}}
ROUTE_INSTRUCTION_LOG="$TMP/instruction.log"
'''
        mock.patch.object(upgrade, "route_helpers", return_value=(functions, "# fixture helper\n")).start()
        bin_dir = self.root / "bin"
        wrappers = {
            "uname": "#!/bin/sh\nprintf 'aarch64\\n'\n",
            "df": '''#!/bin/sh
for path in "$@"; do :; done
available=200000
[ "$path" != "$TEST_ROOT/data" ] || available=${TEST_DATA_FREE:-5000}
printf 'Filesystem 1024-blocks Used Available Capacity Mounted\\nfixture 300000 0 %s 0%% %s\\n' "$available" "$path"
''',
            "sync": "#!/bin/sh\nexit 0\n",
            "cp": f'''#!/bin/sh
for target in "$@"; do :; done
if [ "$target" = "$TEST_ROOT/data/native_endpoint/runtime.tar.gz" ] && [ -n "${{INJECT:-}}" ] && [ ! -e "$TEST_ROOT/tmp/injected" ]; then
 touch "$TEST_ROOT/tmp/injected"
 [ "$(cat "$TEST_ROOT/data/endpoint-upgrade-{self.ident}/state")" = APPLYING ] || exit 97
 : > "$target"
 if [ "$INJECT" = kill ]; then kill -KILL "$PPID"; exit 1; fi
 exit 1
fi
exec {shlex.quote(shutil.which('cp'))} "$@"
''',
            "mv": f'''#!/bin/sh
for target in "$@"; do :; done
if [ "${{FAIL_AFTER_RESTORE:-}}" = 1 ] && [ "$target" = "$TEST_ROOT/data/init.sh" ] && grep -q OLD_INIT "$1" && [ ! -e "$TEST_ROOT/tmp/restore-injected" ]; then
 touch "$TEST_ROOT/tmp/restore-injected"
 {shlex.quote(shutil.which('mv'))} "$@" || exit 1
 printf 'damaged active client\\n' > "$TEST_ROOT/data/native_first_client.sh"
 exit 0
fi
if [ "$target" = "$TEST_ROOT/data/init.sh" ] && [ "$(cat "$TEST_ROOT/data/endpoint-upgrade-{self.ident}/state" 2>/dev/null)" = COMMITTED ] && [ ! -e "$TEST_ROOT/tmp/init-injected" ]; then
 if [ "${{FAIL_INIT_PUBLISH:-}}" = 1 ]; then touch "$TEST_ROOT/tmp/init-injected"; exit 1; fi
 if [ "${{FAIL_AFTER_INIT:-}}" = 1 ]; then
  touch "$TEST_ROOT/tmp/init-injected"
  {shlex.quote(shutil.which('mv'))} "$@" || exit 1
  printf 'owner changed config\\n' > "$TEST_ROOT/data/native_first.env"
  [ "${{BREAK_GUARD:-}}" != 1 ] || printf 'damaged guard\\n' > "$TEST_ROOT/data/endpoint-upgrade-{self.ident}/guard.sh"
  exit 0
 fi
fi
if [ "${{FAIL_RENAME:-}}" = 1 ] && [ "$target" = "$TEST_ROOT/data/native_asr.so" ] && [ ! -e "$TEST_ROOT/tmp/rename-injected" ]; then
 touch "$TEST_ROOT/tmp/rename-injected"; exit 1
fi
exec {shlex.quote(shutil.which('mv'))} "$@"
''',
        }
        for name, text in wrappers.items():
            (bin_dir / name).write_text(text)
            (bin_dir / name).chmod(0o755)
        self.env = {**os.environ, "TEST_ROOT": str(self.root), "PATH": str(bin_dir) + ":" + os.environ["PATH"]}

    def prepare(self, enable_followup_controls=False):
        self.plan = upgrade.prepare_bundle(self.backup, self.candidate, self.extras, self.stage,
                                           upgrade.file_hash(self.candidate / "package.sha256"),
                                           test_root=self.root, transaction_id=self.ident,
                                           enable_followup_controls=enable_followup_controls)
        return self.plan

    def run_transaction(self, command, *args, persistent=False, **env):
        script = self.txn / "restore.sh" if persistent else self.stage / "transaction.sh"
        return subprocess.run(["sh", str(script), command, *map(str, args)], text=True,
                              capture_output=True, timeout=15, env={**self.env, **env})

    def assert_old(self):
        for name, expected in self.before.items():
            self.assertEqual(upgrade.file_hash(self.root / "data" / name), expected, name)
        self.assertFalse((self.root / "data/speaker_doctor.sh").exists())

    def test_preflight_does_not_modify_data_and_rejects_no_space_busy_or_wrong_firmware(self):
        self.prepare()
        before = fixtures.snapshot(self.root / "data")
        result = self.run_transaction("preflight")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fixtures.snapshot(self.root / "data"), before)
        self.assertNotEqual(self.run_transaction("apply", TEST_DATA_FREE="1").returncode, 0)
        (self.root / "tmp/native_first_busy").write_text("busy")
        self.assertNotEqual(self.run_transaction("apply").returncode, 0)
        (self.root / "tmp/native_first_busy").unlink()
        (self.root / "usr/bin/firmware").write_bytes(b"other firmware")
        self.assertNotEqual(self.run_transaction("apply").returncode, 0)
        self.assertFalse(self.txn.exists())
        self.assertEqual(fixtures.snapshot(self.root / "data"), before)

    def test_success_preserves_config_and_v2_tts_and_manual_rollback_restores_absence(self):
        self.prepare()
        result = self.run_transaction("apply")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual((self.txn / "state").read_text().strip(), "COMMITTED")
        for name, expected in self.plan["after_files"].items():
            self.assertEqual(upgrade.file_hash(self.root / "data" / name), expected, name)
        self.assertEqual(upgrade.file_hash(self.root / "data/native_first.env"), self.before["native_first.env"])
        self.assertEqual(upgrade.file_hash(self.root / "data/ettsc"), self.before["ettsc"])
        rollback = self.run_transaction("restore", self.stage / "old-runtime.tar.gz", persistent=True)
        self.assertEqual(rollback.returncode, 0, rollback.stderr + rollback.stdout)
        self.assert_old()
        self.assertEqual((self.txn / "state").read_text().strip(), "ROLLED_BACK")

    def test_explicit_controls_append_only_private_env_and_restore_original(self):
        before_env = (self.backup / "native_first.env").read_bytes()
        self.prepare(enable_followup_controls=True)
        expected = before_env + b"\nexport FOLLOWUP_EXIT_ENABLED=1\nexport FOLLOWUP_RESET_ENABLED=1\n"
        staged = self.stage / "extras/native_first.env"
        self.assertEqual(staged.read_bytes(), expected)
        self.assertEqual(staged.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.plan["after_files"]["native_first.env"], release.digest(expected))
        result = self.run_transaction("apply")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertNotIn("fixture-secret", result.stdout + result.stderr)
        self.assertEqual((self.root / "data/native_first.env").read_bytes(), expected)
        result = self.run_transaction("restore", self.stage / "old-runtime.tar.gz", persistent=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assert_old()

    def test_enabled_controls_failed_start_restores_original_env(self):
        self.prepare(enable_followup_controls=True)
        (self.root / "tmp/fail-start").write_text("new candidate only")
        result = self.run_transaction("apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("UPGRADE_ROLLED_BACK", result.stdout)
        self.assert_old()

    def test_enabled_controls_restore_accepts_original_hash_but_rejects_other_edits(self):
        self.prepare(enable_followup_controls=True)
        self.assertEqual(self.run_transaction("apply").returncode, 0)
        (self.root / "data/native_first.env").write_text("unrelated owner edit\n")
        self.assertNotEqual(self.run_transaction("restore", self.stage / "old-runtime.tar.gz", persistent=True).returncode, 0)
        shutil.copy2(self.backup / "native_first.env", self.root / "data/native_first.env")
        result = self.run_transaction("restore", self.stage / "old-runtime.tar.gz", persistent=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assert_old()

    def test_partial_large_file_copy_failure_rolls_back(self):
        self.prepare()
        result = self.run_transaction("apply", INJECT="copy-failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("UPGRADE_ROLLED_BACK", result.stdout)
        self.assert_old()

    def test_committed_init_publish_failure_restores_old_state(self):
        self.prepare()
        result = self.run_transaction("apply", FAIL_INIT_PUBLISH="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("UPGRADE_ROLLED_BACK", result.stdout)
        self.assertEqual((self.txn / "state").read_text().strip(), "ROLLED_BACK")
        self.assert_old()

    def test_failure_after_new_init_with_restore_refusal_reinstalls_guard(self):
        self.prepare()
        result = self.run_transaction("apply", FAIL_AFTER_INIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("UPGRADE_RECOVERY_REQUIRED", result.stderr)
        self.assertEqual((self.txn / "state").read_text().strip(), "RECOVERY_REQUIRED")
        self.assertEqual((self.root / "data/init.sh").read_bytes(), (self.txn / "guard.sh").read_bytes())
        boot = subprocess.run(["sh", str(self.root / "data/init.sh")], capture_output=True, text=True, env=self.env)
        self.assertEqual((boot.returncode, boot.stdout), (0, ""))
        self.assertEqual((self.root / "data/native_first.env").read_text(), "owner changed config\n")

    def test_uninstallable_guard_reports_no_boot_safety_guarantee(self):
        self.prepare()
        result = self.run_transaction("apply", FAIL_AFTER_INIT="1", BREAK_GUARD="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("UPGRADE_BOOT_GUARD_UNCONFIRMED", result.stderr)
        self.assertNotIn("boot guard retained", result.stderr)

    def test_manual_restore_final_failure_reinstalls_guard_without_recursive_restore(self):
        self.prepare(enable_followup_controls=True)
        self.assertEqual(self.run_transaction("apply").returncode, 0)
        result = self.run_transaction("restore", self.stage / "old-runtime.tar.gz", persistent=True, FAIL_AFTER_RESTORE="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("UPGRADE_RECOVERY_REQUIRED", result.stderr)
        self.assertEqual((self.txn / "state").read_text().strip(), "RECOVERY_REQUIRED")
        self.assertEqual((self.root / "data/init.sh").read_bytes(), (self.txn / "guard.sh").read_bytes())
        self.assertEqual((self.root / "data/native_first_client.sh").read_text(), "damaged active client\n")
        boot = subprocess.run(["sh", str(self.root / "data/init.sh")], capture_output=True, text=True, env=self.env)
        self.assertEqual((boot.returncode, boot.stdout), (0, ""))
        retry = self.run_transaction("restore", self.stage / "old-runtime.tar.gz", persistent=True)
        self.assertEqual(retry.returncode, 0, retry.stderr + retry.stdout)
        self.assert_old()

    def test_small_file_rename_failure_and_new_client_failure_roll_back(self):
        self.prepare()
        result = self.run_transaction("apply", FAIL_RENAME="1")
        self.assertNotEqual(result.returncode, 0)
        self.assert_old()
        # Separate identity is required for every new maintenance attempt.
        shutil.rmtree(self.txn)
        (self.stage / "old-runtime.tar.gz").unlink()
        (self.root / "tmp/fail-start").write_text("new candidate only")
        result = self.run_transaction("apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("UPGRADE_ROLLED_BACK", result.stdout)
        self.assert_old()

    def test_power_loss_with_tmp_loss_keeps_original_boot_then_restores_from_host_copy(self):
        self.prepare()
        result = self.run_transaction("apply", INJECT="kill")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.txn / "state").read_text().strip(), "APPLYING")
        shutil.rmtree(self.root / "tmp")
        (self.root / "tmp").mkdir()
        boot = subprocess.run(["sh", str(self.root / "data/init.sh")], capture_output=True, text=True, env=self.env)
        self.assertEqual((boot.returncode, boot.stdout), (0, ""))
        self.assertFalse((self.root / "tmp/calls").exists())
        replacement = self.root / "tmp/verified-old-runtime.tar.gz"
        shutil.copy2(self.backup / "native_endpoint/runtime.tar.gz", replacement)
        result = self.run_transaction("restore", replacement, persistent=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assert_old()

    def test_bad_restore_archive_or_changed_private_config_never_overwrites(self):
        self.prepare()
        self.assertEqual(self.run_transaction("apply").returncode, 0)
        wrong = self.root / "wrong-runtime"
        wrong.write_bytes(b"damaged")
        before = fixtures.snapshot(self.root / "data")
        self.assertNotEqual(self.run_transaction("restore", wrong, persistent=True).returncode, 0)
        self.assertEqual(fixtures.snapshot(self.root / "data"), before)
        (self.root / "data/native_first.env").write_text("owner changed config\n")
        before = fixtures.snapshot(self.root / "data")
        result = self.run_transaction("restore", self.stage / "old-runtime.tar.gz", persistent=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(fixtures.snapshot(self.root / "data"), before)

    def test_symlink_target_tampered_stage_or_changed_source_blocks_before_backup(self):
        self.prepare()
        (self.root / "data/speaker_doctor.sh").symlink_to(self.root / "absent")
        self.assertNotEqual(self.run_transaction("apply").returncode, 0)
        (self.root / "data/speaker_doctor.sh").unlink()
        (self.stage / "extras/init.sh").write_text("changed")
        self.assertNotEqual(self.run_transaction("apply").returncode, 0)
        self.assertFalse(self.txn.exists())
        self.assert_old()

    def test_generator_rejects_source_candidate_backup_tampering_and_arm32_control(self):
        (self.extras / "native_asr_ctl").write_bytes(fixtures.elf())
        with self.assertRaises(ValueError):
            self.prepare()
        (self.extras / "native_asr_ctl").write_bytes(control_elf())
        with self.assertRaises(ValueError):
            upgrade.prepare_bundle(self.backup, self.candidate, self.extras, self.stage, "0" * 64)
        (self.backup / "native_first.env").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.stage.exists())

    def run_old_client(self, leave_watchdog=False, keep_fifo=False, changed_start=False):
        script = self.root / "old-parent.sh"
        script.write_text('''#!/bin/sh
mkdir "$TEST_ROOT/proc/$$"
printf 'sh %s/data/native_first_client.sh\\000' "$TEST_ROOT" > "$TEST_ROOT/proc/$$/cmdline"
printf 'State:\\tS\\n' > "$TEST_ROOT/proc/$$/status"
printf '%s (sh) S 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 12345 0\\n' "$$" > "$TEST_ROOT/proc/$$/stat"
echo $$ > "$TEST_ROOT/tmp/native_first_client.pid"
(while :; do printf 'writer\\n' >> "$TEST_ROOT/tmp/watchdog-writes"; sleep 0.1; done) &
child=$!
echo "$child" > "$TEST_ROOT/tmp/watchdog-pid"
mkdir "$TEST_ROOT/proc/$child"
printf 'sh %s/data/native_first_client.sh\\000' "$TEST_ROOT" > "$TEST_ROOT/proc/$child/cmdline"
printf 'State:\\tS\\n' > "$TEST_ROOT/proc/$child/status"
cleanup() {
 sleep 1.3
 if [ "$LEAVE_WATCHDOG" = 0 ]; then kill "$child"; wait "$child" 2>/dev/null; rm -rf "$TEST_ROOT/proc/$child"; fi
 # Publish a simulated replacement identity before opening the cleanup gate.
 # A real process cannot change starttime while retaining its own identity.
 if [ "$CHANGE_START" = 1 ]; then sed 's/12345/54321/' "$TEST_ROOT/proc/$$/stat" > "$TEST_ROOT/proc/$$/stat.next"; mv "$TEST_ROOT/proc/$$/stat.next" "$TEST_ROOT/proc/$$/stat"; fi
 [ "$KEEP_FIFO" = 1 ] || rm -f "$TEST_ROOT/tmp/native_first_event.fifo"
 touch "$TEST_ROOT/tmp/cleanup-done"
 # Match the legacy cleanup: the PID file is its final completion signal.
 rm -f "$TEST_ROOT/tmp/native_first_client.pid"
}
trap cleanup INT TERM EXIT
mkfifo "$TEST_ROOT/tmp/native_first_event.fifo"
exec 3<>"$TEST_ROOT/tmp/native_first_event.fifo"
touch "$TEST_ROOT/tmp/client-ready"
while true; do
 if ! read event ts <&3; then sleep 0.2; continue; fi
done
''')
        parent = subprocess.Popen(["sh", str(script)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  start_new_session=True, env={**self.env, "LEAVE_WATCHDOG": str(int(leave_watchdog)),
                                  "KEEP_FIFO": str(int(keep_fifo)), "CHANGE_START": str(int(changed_start))})
        # Fake /proc mirrors the host-owned fixture parent's actual lifetime.
        def reap_parent():
            parent.wait()
            shutil.rmtree(self.root / "proc" / str(parent.pid), ignore_errors=True)
        reaper = threading.Thread(target=reap_parent, daemon=True)
        reaper.start()
        def finish():
            try:
                os.killpg(parent.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            parent.wait(timeout=3)
            reaper.join(timeout=3)
        self.addCleanup(finish)
        deadline = time.monotonic() + 3
        while not (self.root / "tmp/client-ready").exists():
            if time.monotonic() > deadline:
                self.fail("fixture parent did not start")
            time.sleep(0.01)
        return parent

    def test_graceful_stop_waits_for_delayed_cleanup_and_old_watchdog(self):
        self.prepare()
        parent = self.run_old_client()
        definitions = (self.stage / "transaction.sh").read_text().split('case "${1:-}" in', 1)[0]
        result = subprocess.run(["sh"], input=definitions + "\nstop_owned_clients\n", text=True,
                                capture_output=True, timeout=8, env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(parent.wait(timeout=2), -signal.SIGKILL)
        self.assertTrue((self.root / "tmp/cleanup-done").exists())
        self.assertGreater(len((self.root / "tmp/watchdog-writes").read_text().splitlines()), 5)
        self.assertEqual({p.name for p in (self.root / "proc").glob("[0-9]*")}, {"1", "2"})

    def test_surviving_old_watchdog_blocks_without_killing_parent_early(self):
        self.prepare()
        parent = self.run_old_client(leave_watchdog=True)
        definitions = (self.stage / "transaction.sh").read_text().split('case "${1:-}" in', 1)[0]
        code = definitions + "\nsleep() { command sleep 0.04; }\nstop_owned_clients\n"
        result = subprocess.run(["sh"], input=code, text=True, capture_output=True, timeout=8, env=self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("watchdog did not exit", result.stderr)
        self.assertIsNone(parent.poll())
        self.assertTrue((self.root / "tmp/cleanup-done").exists())
        self.assertTrue((self.root / "proc" / (self.root / "tmp/watchdog-pid").read_text().strip()).exists())
        self.assert_old()

    def test_uncleared_fifo_blocks_final_parent_kill(self):
        self.prepare()
        parent = self.run_old_client(keep_fifo=True)
        definitions = (self.stage / "transaction.sh").read_text().split('case "${1:-}" in', 1)[0]
        code = definitions + "\nsleep() { command sleep 0.04; }\nstop_owned_clients\n"
        result = subprocess.run(["sh"], input=code, text=True, capture_output=True, timeout=8, env=self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.root / "tmp/cleanup-done").exists())
        self.assertIsNone(parent.poll())

    def test_changed_parent_start_identity_blocks_final_kill(self):
        self.prepare()
        parent = self.run_old_client(changed_start=True)
        definitions = (self.stage / "transaction.sh").read_text().split('case "${1:-}" in', 1)[0]
        result = subprocess.run(["sh"], input=definitions + "\nstop_owned_clients\n", text=True,
                                capture_output=True, timeout=8, env=self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.root / "tmp/cleanup-done").exists())
        self.assertIsNone(parent.poll())

    def test_proc_scan_tolerates_disappearance_but_not_unreadable_live_process(self):
        self.prepare()
        definitions = (self.stage / "transaction.sh").read_text().split('case "${1:-}" in', 1)[0]
        process = self.root / "proc/55555"
        for point in ("cmdline", "tr", "status", "awk-error", "awk-empty"):
            for vanished in (True, False):
                with self.subTest(point=point, vanished=vanished):
                    process.mkdir(exist_ok=True)
                    (process / "cmdline").write_bytes(f"sh\0{self.root}/data/native_first_client.sh\0".encode())
                    (process / "status").write_text("State:\tS\n")
                    remove = 'rm -rf "$PROC/55555";' if vanished else ":;"
                    if point in ("cmdline", "status"):
                        injected = f'''regular() {{
 if [ "$1" = "$PROC/55555/{point}" ]; then {remove} return 1; fi
 [ -f "$1" ] && [ ! -L "$1" ]
}}
'''
                    elif point == "tr":
                        injected = f'''tr() {{
 local value
 value=$(command tr "$@") || return 1
 case "$value" in *native_first_client.sh*) {remove} return 1;; *) printf '%s' "$value";; esac
}}
'''
                    else:
                        injected = f'''awk() {{
 for arg in "$@"; do :; done
 if [ "$arg" = "$PROC/55555/status" ]; then {remove} return {1 if point == 'awk-error' else 0}; fi
 command awk "$@"
}}
'''
                    result = subprocess.run(["sh"], input=definitions + injected + "\nmatching_client_pids\n",
                                            text=True, capture_output=True, timeout=4, env=self.env)
                    self.assertEqual(result.returncode == 0, vanished, result.stderr)
                    self.assertEqual(result.stdout, "")
                    shutil.rmtree(process, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
