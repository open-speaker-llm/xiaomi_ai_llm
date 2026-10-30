"""Offline release format and publication failures; synthetic ARM headers, no device."""
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools/speaker-maintenance"
sys.path.insert(0, str(TOOLS))
import native_endpoint_release as release

spec = importlib.util.spec_from_file_location("endpoint_builder", ROOT / "device/native_endpoint/build_package.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def elf():
    value = bytearray(52)
    value[:7] = b"\x7fELF\x01\x01\x01"
    struct.pack_into("<HH", value, 16, 3, 40)
    return bytes(value) + b"synthetic-test-not-executable"


def assets_content():
    return {name: (b"synthetic-model" if name.endswith(".onnx") else elf() + name.encode()) for name in release.ASSETS}


def manifest(content):
    return release.manifest_bytes({name: release.digest(value) for name, value in content.items()})


def runtime_content():
    model = {**assets_content(), "neural_pool": elf(), "run_neural_pool.sh": b"#!/bin/sh\nexit 0\n"}
    content = {"xiaomi_neural_shadow/" + name: value for name, value in model.items()}
    content["xiaomi_neural_shadow/runtime.sha256"] = manifest(model)
    content.update({"xiaomi_native_wake_probe/" + name: elf() for name in ("native_wake_pool", "native_resident_session")})
    content["runtime-files.sha256"] = manifest(content)
    return content


def archive_bytes(content, extra=()):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, value in sorted(content.items()):
            info = tarfile.TarInfo(name)
            info.size = len(value)
            info.mode = 0o755 if name in release.EXECUTABLE_MEMBERS else 0o644
            archive.addfile(info, io.BytesIO(value))
        for info, value in extra:
            archive.addfile(info, io.BytesIO(value) if info.isfile() else None)
    return gzip.compress(raw.getvalue(), mtime=0)


def reseal(directory):
    (directory / "package.sha256").write_bytes(manifest({name: (directory / name).read_bytes() for name in release.PAYLOADS}))


def make_package(directory, metadata=True):
    directory.mkdir(exist_ok=True)
    content = {"runtime.tar.gz": archive_bytes(runtime_content()), "native_asr.so": elf(), "lifecycle": elf(),
               "native_first_client.sh": b"#!/bin/sh\nexit 0\n", "manager.sh": b"#!/bin/sh\nexit 0\n"}
    for name, value in content.items():
        (directory / name).write_bytes(value)
    reseal(directory)
    if metadata:
        checked = release.validate_package(directory)
        meta = release.make_metadata(checked["package_manifest_sha256"], checked["runtime"], {"revision": "a" * 40, "dirty": False})
        (directory / "release.json").write_text(json.dumps(meta))


def snapshot(directory):
    return {str(path.relative_to(directory)): (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
            for path in directory.rglob("*") if path.is_file() and not path.is_symlink()}


class OfflineReleaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / "package"
        make_package(self.package)

    def check(self):
        return release.inspect_release(self.package)

    def test_valid_package_is_read_only_and_does_not_authorize_deployment(self):
        before = snapshot(self.package)
        report, code = self.check()
        self.assertEqual(code, 2)
        self.assertEqual(report["package"]["status"], "PASS")
        self.assertEqual(report["release"]["status"], "PASS")
        self.assertEqual(report["deployment"]["status"], "UNKNOWN")
        self.assertFalse(report["deployment"]["allowed"])
        self.assertEqual(snapshot(self.package), before)

    def test_legacy_package_missing_metadata_remains_unknown(self):
        (self.package / "release.json").unlink()
        report, code = self.check()
        self.assertEqual(code, 2)
        self.assertEqual(report["package"]["status"], "PASS")
        self.assertEqual(report["release"]["code"], "LEGACY_METADATA_MISSING")

    def test_payload_corruption_and_missing_file_block(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                path = self.package / "manager.sh"
                if missing:
                    path.unlink()
                else:
                    path.write_bytes(path.read_bytes() + b"damage")
                report, code = self.check()
                self.assertEqual(code, 1)
                self.assertEqual(report["package"]["status"], "FAIL")
                self.assertFalse(report["deployment"]["allowed"])

    def test_manifest_rejects_traversal_extra_duplicates_and_missing(self):
        original = (self.package / "package.sha256").read_bytes()
        first = original.splitlines(keepends=True)[0]
        for value in (original + b"0" * 64 + b"  ../outside\n", original + first,
                      original.replace(b"  manager.sh", b"  /manager.sh"), original[len(first):],
                      original.replace(b"  manager.sh", b" *manager.sh"), original.replace(b"\n", b"\r\n")):
            with self.subTest(value=value[:20]):
                (self.package / "package.sha256").write_bytes(value)
                self.assertEqual(self.check()[1], 1)

    def test_symlinked_package_payload_manifest_or_metadata_is_rejected(self):
        for name in ("manager.sh", "package.sha256", "release.json"):
            with self.subTest(name=name):
                path = self.package / name
                data = path.read_bytes()
                target = self.root / "outside"
                target.write_bytes(data)
                path.unlink()
                path.symlink_to(target)
                self.assertEqual(self.check()[1], 1)
                path.unlink()
                path.write_bytes(data)
        linked = self.root / "linked"
        linked.symlink_to(self.package, target_is_directory=True)
        self.assertEqual(release.inspect_release(linked)[1], 1)

    def test_archive_path_types_duplicates_and_extra_members_are_rejected(self):
        for name, kind in (("../outside", tarfile.REGTYPE), ("/absolute", tarfile.REGTYPE),
                           ("xiaomi_neural_shadow/extra", tarfile.REGTYPE),
                           ("xiaomi_neural_shadow/neural_pool", tarfile.SYMTYPE),
                           ("xiaomi_neural_shadow/neural_pool", tarfile.LNKTYPE),
                           ("xiaomi_neural_shadow/neural_pool", tarfile.FIFOTYPE),
                           ("xiaomi_neural_shadow/neural_pool", tarfile.DIRTYPE),
                           ("xiaomi_neural_shadow/neural_pool", tarfile.REGTYPE)):
            with self.subTest(name=name, kind=kind):
                info = tarfile.TarInfo(name)
                info.type = kind
                if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                    info.linkname = "../../outside"
                (self.package / "runtime.tar.gz").write_bytes(archive_bytes(runtime_content(), ((info, b""),)))
                reseal(self.package)
                report, code = self.check()
                self.assertEqual(code, 1)
                self.assertEqual(report["package"]["code"], "ARCHIVE_MEMBER")
        self.assertFalse((self.root / "outside").exists())

    def test_missing_truncated_and_trailing_archive_is_rejected(self):
        missing = runtime_content()
        del missing["xiaomi_neural_shadow/neural_pool"]
        good = archive_bytes(runtime_content())
        for data in (archive_bytes(missing), good[:-12], gzip.compress(gzip.decompress(good) + b"hidden data")):
            with self.subTest(size=len(data)):
                (self.package / "runtime.tar.gz").write_bytes(data)
                reseal(self.package)
                self.assertEqual(self.check()[1], 1)

    def test_runtime_without_execute_permission_is_rejected(self):
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, value in sorted(runtime_content().items()):
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(value), 0o644
                archive.addfile(info, io.BytesIO(value))
        (self.package / "runtime.tar.gz").write_bytes(gzip.compress(raw.getvalue(), mtime=0))
        reseal(self.package)
        report, code = self.check()
        self.assertEqual((code, report["package"]["code"]), (1, "ARCHIVE_EXECUTABLE"))

    def test_gnu_extension_header_cannot_hide_as_a_whitelisted_file(self):
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w", format=tarfile.GNU_FORMAT) as archive:
            extension = tarfile.TarInfo("././@LongLink")
            extension.type = tarfile.GNUTYPE_LONGNAME
            name = b"xiaomi_neural_shadow/neural_pool\x00"
            extension.size = len(name)
            archive.addfile(extension, io.BytesIO(name))
            info = tarfile.TarInfo("ignored-short-name")
            info.size, info.mode = len(elf()), 0o755
            archive.addfile(info, io.BytesIO(elf()))
        (self.package / "runtime.tar.gz").write_bytes(gzip.compress(raw.getvalue(), mtime=0))
        reseal(self.package)
        report, code = self.check()
        self.assertEqual((code, report["package"]["code"]), (1, "ARCHIVE_MEMBER"))

    def test_cli_rejects_raw_extension_headers_without_overflow_recursion_or_hidden_members(self):
        normal = gzip.decompress((self.package / "runtime.tar.gz").read_bytes())
        (self.package / "release.json").unlink()
        cases = [(kind, 2 ** 63, 1) for kind in
                 (tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK)]
        cases += [(tarfile.XGLTYPE, 0, 1), (tarfile.XGLTYPE, 0, 400)]
        for kind, size, count in cases:
            with self.subTest(kind=kind, size=size, count=count):
                info = tarfile.TarInfo("extension")
                info.type, info.size = kind, size
                prefix = info.tobuf(format=tarfile.GNU_FORMAT) * count
                (self.package / "runtime.tar.gz").write_bytes(gzip.compress(prefix + normal, mtime=0))
                reseal(self.package)
                result = subprocess.run(
                    [sys.executable, str(TOOLS / "check_native_endpoint_package.py"), "--package", str(self.package)],
                    capture_output=True, text=True, timeout=5,
                    env={**os.environ, "PATH": "/nonexistent", "PYTHONDONTWRITEBYTECODE": "1"})
                self.assertFalse("Traceback" in result.stderr, result.stderr[-240:])
                self.assertEqual(result.returncode, 1, result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(report["package"]["code"], "ARCHIVE_MEMBER")
                self.assertEqual(report["deployment"]["status"], "BLOCKED")

    def test_raw_scan_accepts_current_layout_and_parser_sees_every_member(self):
        raw = gzip.decompress((self.package / "runtime.tar.gz").read_bytes())
        layout = release.scan_tar_headers(raw)
        self.assertEqual(len(layout), len(release.ARCHIVE_FILES))
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            parsed = [(member.offset, member.size) for member in archive]
        self.assertEqual(layout, parsed)
        self.assertEqual(self.check()[0]["package"]["status"], "PASS")

    def test_raw_scan_rejects_sizes_spans_padding_and_tails_before_tarfile(self):
        def header(size, kind=tarfile.REGTYPE):
            info = tarfile.TarInfo("runtime-files.sha256")
            info.size, info.type = size, kind
            return info.tobuf(format=tarfile.GNU_FORMAT)
        cases = [
            (header(2 ** 63) + bytes(1024), "ARCHIVE_SIZE"),
            (header(-1) + bytes(1024), "ARCHIVE_SIZE"),
            (header(release.MAX_FILE_BYTES + 1) + bytes(1024), "ARCHIVE_LIMIT"),
            (header(release.MAX_FILE_BYTES) + bytes(1024), "ARCHIVE_TRUNCATED"),
            (header(1) + b"x" + bytes(510) + b"!" + bytes(1024), "ARCHIVE_PADDING"),
            (header(0) + bytes(512), "ARCHIVE_TRAILING"),
            (header(0) + bytes(1024) + header(0), "ARCHIVE_TRAILING"),
            (header(0)[:-1], "ARCHIVE_TRAILING"),
            (header(0) * (len(release.ARCHIVE_FILES) + 1) + bytes(1024), "ARCHIVE_MEMBER"),
            (header(0, tarfile.XGLTYPE) + bytes(1024), "ARCHIVE_MEMBER"),
        ]
        for raw, code in cases:
            with self.subTest(code=code, length=len(raw)):
                with mock.patch.object(release.tarfile, "open") as parser:
                    with self.assertRaises(release.InvalidPackage) as caught:
                        release.check_runtime(gzip.compress(raw, mtime=0))
                    self.assertEqual(caught.exception.code, code)
                    parser.assert_not_called()

    def test_header_checksum_still_reaches_and_is_rejected_by_tarfile(self):
        raw = bytearray(gzip.decompress((self.package / "runtime.tar.gz").read_bytes()))
        raw[148:156] = b"0000000\x00"
        with mock.patch.object(release.tarfile, "open", wraps=tarfile.open) as parser:
            with self.assertRaises(release.InvalidPackage) as caught:
                release.check_runtime(gzip.compress(raw, mtime=0))
            self.assertEqual(caught.exception.code, "ARCHIVE_FORMAT")
            parser.assert_called_once()

    def test_internal_manifest_catches_corruption_even_if_outer_hash_is_updated(self):
        content = runtime_content()
        content["xiaomi_neural_shadow/neural_pool"] += b"corrupt"
        (self.package / "runtime.tar.gz").write_bytes(archive_bytes(content))
        reseal(self.package)
        report, code = self.check()
        self.assertEqual(code, 1)
        self.assertEqual(report["package"]["code"], "HASH_MISMATCH")

    def test_model_manifest_cannot_hide_extra_or_mismatched_input(self):
        content = runtime_content()
        content["xiaomi_neural_shadow/runtime.sha256"] += b"0" * 64 + b"  ../outside\n"
        content["runtime-files.sha256"] = manifest({k: v for k, v in content.items() if k != "runtime-files.sha256"})
        (self.package / "runtime.tar.gz").write_bytes(archive_bytes(content))
        reseal(self.package)
        self.assertEqual(self.check()[1], 1)

    def test_wrong_elf_architecture_is_rejected_after_valid_hash(self):
        path = self.package / "native_asr.so"
        value = bytearray(path.read_bytes())
        struct.pack_into("<H", value, 18, 62)
        path.write_bytes(value)
        reseal(self.package)
        report, code = self.check()
        self.assertEqual((code, report["package"]["code"]), (1, "ELF_TARGET"))

    def test_size_limits_stop_compressed_expansion_and_large_files(self):
        with mock.patch.object(release, "MAX_RUNTIME_BYTES", 64):
            report, code = self.check()
        self.assertEqual((code, report["package"]["code"]), (1, "ARCHIVE_LIMIT"))
        with self.assertRaises(release.InvalidPackage):
            release.read_regular(self.package / "manager.sh", 2)

    def test_invalid_metadata_binding_inputs_claims_and_types_block(self):
        original = json.loads((self.package / "release.json").read_text())
        mutations = [lambda m: m.update(schema_version=True), lambda m: m.update(release_id="sha256:" + "0" * 64),
                     lambda m: m["inputs"].update(assets_manifest_sha256="0" * 64),
                     lambda m: m["inputs"]["assets"].update({"libc.so.6": "0" * 64}),
                     lambda m: m["validation"].update(device="passed"),
                     lambda m: m["upgrade"].update(supported=True),
                     lambda m: m["upgrade"].update(supported=0),
                     lambda m: m["target"].update(root_partition="boot0"),
                     lambda m: m["source"].update(dirty="false"), lambda m: m.update(unknown="ignored")]
        for change in mutations:
            with self.subTest(change=change):
                meta = json.loads(json.dumps(original))
                change(meta)
                (self.package / "release.json").write_text(json.dumps(meta))
                self.assertEqual(self.check()[1], 1)

    def test_duplicate_json_keys_and_invalid_json_block(self):
        for value in ('{"schema_version":1,"schema_version":1}', '[]', '{', '{"x":NaN}', '{"x":' + '[' * 1100):
            with self.subTest(value=value[:25]):
                (self.package / "release.json").write_text(value)
                self.assertEqual(self.check()[1], 1)

    def test_missing_source_revision_or_dirty_source_is_never_clean(self):
        path = self.package / "release.json"
        meta = json.loads(path.read_text())
        for source in ({"revision": None, "dirty": None}, {"revision": "b" * 40, "dirty": True}):
            meta["source"] = source
            path.write_text(json.dumps(meta))
            report, code = self.check()
            self.assertEqual(code, 2)
            self.assertEqual(report["release"]["source"], source)
            self.assertTrue(any("未提交" in msg for msg in report["messages"]))

    def test_device_evidence_never_invents_an_allowed_upgrade_source(self):
        path = self.root / "evidence.json"
        for model, partition, code, reason in (("S12A", "boot1", 1, "UPGRADE_RULE_UNAVAILABLE"),
                                              ("S12A", "boot0", 1, "DEVICE_TARGET_MISMATCH"),
                                              ("other", "boot1", 1, "DEVICE_TARGET_MISMATCH"),
                                              ("S12A", "unknown", 2, "DEVICE_PARTITION_UNKNOWN")):
            path.write_text(json.dumps({"schema_version": 1, "device_model": model, "root_partition": partition,
                                        "installed_package_sha256": "0" * 64}))
            report, actual = release.inspect_release(self.package, path)
            self.assertEqual(actual, code)
            self.assertEqual(report["deployment"]["code"], reason)
            self.assertFalse(report["deployment"]["allowed"])
        path.write_text('{"device_model":"S12A"}')
        self.assertEqual(release.inspect_release(self.package, path)[1], 1)

    def test_cli_json_and_chinese_summary_work_without_external_commands(self):
        env = {**os.environ, "PATH": "/nonexistent", "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run([sys.executable, str(TOOLS / "check_native_endpoint_package.py"), "--package", str(self.package)],
                                capture_output=True, text=True, timeout=5, env=env)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stdout)["exit_code"], 2)
        self.assertIn("不允许部署", result.stderr)
        invalid = subprocess.run([sys.executable, str(TOOLS / "check_native_endpoint_package.py")],
                                 capture_output=True, text=True, timeout=5, env=env)
        self.assertEqual(invalid.returncode, 64)

    def test_invalid_deflate_returns_structured_rejection_without_traceback(self):
        compressed = bytearray(gzip.compress(b"candidate", mtime=0))
        compressed[10] = 0xff  # Reserved DEFLATE block type after a valid gzip header.
        (self.package / "runtime.tar.gz").write_bytes(compressed)
        reseal(self.package)
        result = subprocess.run([sys.executable, str(TOOLS / "check_native_endpoint_package.py"),
                                 "--package", str(self.package)], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report["package"]["code"], "ARCHIVE_FORMAT")
        self.assertEqual(report["deployment"]["status"], "BLOCKED")
        self.assertFalse(report["deployment"]["allowed"])
        self.assertNotIn("Traceback", result.stderr)


class CleanBuildTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assets, self.header = self.root / "assets", self.root / "header"
        self.assets.mkdir()
        self.header.mkdir()
        for name, value in assets_content().items():
            (self.assets / name).write_bytes(value)
            if name == "ld-linux-armhf.so.3":
                (self.assets / name).chmod(0o755)
        (self.assets / "runtime.sha256").write_bytes(manifest(assets_content()))
        header = b"synthetic test header"
        (self.header / "c-api-1.10.36.h").write_bytes(header)
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(release, "HEADER_SHA256", release.digest(header)).start()
        mock.patch.object(builder, "source_record", return_value={"revision": "c" * 40, "dirty": False}).start()

    def fake_compiler(self, command, **kwargs):
        if command[0] == "sh":
            folder = Path(command[-1])
            folder.mkdir(exist_ok=True)
            names = ("native_wake_pool", "native_resident_session", "native_wake_probe.so") if "build_native_wake" in command[1] else ("neural_pool",)
            for name in names:
                (folder / name).write_bytes(elf())
                (folder / name).chmod(0o755)
        elif command[0] == "zig":
            Path(command[-1]).write_bytes(elf())
        elif command == [sys.executable, str(ROOT / "scripts/embed_native_protocol.py"), "--check"]:
            pass  # Drift rejection is separately exercised with the real embedding CLI.
        else:
            self.fail("Unexpected external command")
        return subprocess.CompletedProcess(command, 0)

    def build(self, output):
        with mock.patch.object(builder.subprocess, "run", side_effect=self.fake_compiler):
            return builder.build_package(self.assets, self.header, output)

    def test_nonempty_output_is_refused_without_changing_existing_package(self):
        output = self.root / "existing"
        make_package(output)
        before = snapshot(output)
        with mock.patch.object(builder, "compile_payload") as compile_call:
            with self.assertRaises(ValueError):
                builder.build_package(self.assets, self.header, output)
            compile_call.assert_not_called()
        self.assertEqual(snapshot(output), before)

    def test_output_symlink_file_and_stale_runtime_are_refused(self):
        target = self.root / "target"
        target.mkdir()
        link = self.root / "link"
        link.symlink_to(target, target_is_directory=True)
        file = self.root / "file"
        file.write_text("keep")
        stale = self.root / "stale"
        (stale / "runtime").mkdir(parents=True)
        for output in (link, file, stale):
            with self.subTest(output=output), self.assertRaises(ValueError):
                self.build(output)
        self.assertEqual(file.read_text(), "keep")
        self.assertEqual(list(target.iterdir()), [])

    def test_stale_protocol_blocks_build_before_compilation_or_output_creation(self):
        source = self.root / "source"
        (source / "scripts").mkdir(parents=True)
        (source / "device/lib").mkdir(parents=True)
        (source / "scripts/embed_native_protocol.py").write_bytes((ROOT / "scripts/embed_native_protocol.py").read_bytes())
        (source / "device/lib/native_protocol.sh").write_text("# new protocol\n")
        (source / "device/native_first_client.sh").write_text(
            "# BEGIN GENERATED NATIVE PROTOCOL\n# stale protocol\n# END GENERATED NATIVE PROTOCOL\n")
        output = self.root / "output"
        with mock.patch.object(builder, "ROOT", source), mock.patch.object(builder, "compile_payload") as compile_call:
            with self.assertRaisesRegex(ValueError, "协议模块"):
                builder.build_package(self.assets, self.header, output)
            compile_call.assert_not_called()
        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.glob(".endpoint-build-*")), [])

    def test_failed_build_cleans_stage_and_preserves_empty_or_absent_output(self):
        for exists in (False, True):
            output = self.root / ("empty" if exists else "absent")
            if exists:
                output.mkdir()
            def broken(*args):
                (args[-1] / "partial").write_text("partial")
                raise subprocess.CalledProcessError(1, ["synthetic compiler"])
            with mock.patch.object(builder, "compile_payload", side_effect=broken), self.assertRaises(subprocess.CalledProcessError):
                builder.build_package(self.assets, self.header, output)
            self.assertEqual(output.exists(), exists)
            if exists:
                self.assertEqual(list(output.iterdir()), [])
            self.assertEqual(list(self.root.glob(".endpoint-build-*")), [])

    def test_success_publishes_bound_metadata_and_preserves_five_payload_contract(self):
        output = self.root / "output"
        output.mkdir()
        self.build(output)
        checked = release.validate_package(output)
        self.assertEqual(checked["metadata"]["validation"]["device"], "not_run")
        self.assertEqual(checked["metadata"]["source"]["revision"], "c" * 40)
        self.assertEqual(set(release.parse_manifest((output / "package.sha256").read_bytes(), release.PAYLOADS)), release.PAYLOADS)
        self.assertEqual(list(self.root.glob(".endpoint-build-*")), [])

    def test_same_inputs_produce_identical_payload_and_metadata(self):
        first, second = self.root / "first", self.root / "second"
        self.build(first)
        self.build(second)
        for name in release.PAYLOADS | {"package.sha256", "release.json"}:
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes(), name)

    def test_invalid_input_header_or_asset_fails_before_compiler(self):
        with mock.patch.object(builder, "compile_payload") as compile_call:
            (self.header / "c-api-1.10.36.h").write_bytes(b"wrong version")
            with self.assertRaises(ValueError):
                builder.build_package(self.assets, self.header, self.root / "output")
            compile_call.assert_not_called()
            (self.header / "c-api-1.10.36.h").write_bytes(b"synthetic test header")
            (self.assets / "silero_vad_v5.onnx").write_bytes(b"wrong model")
            with self.assertRaises(ValueError):
                builder.build_package(self.assets, self.header, self.root / "output")
            compile_call.assert_not_called()
        self.assertFalse((self.root / "output").exists())

    def test_bad_candidate_never_publishes(self):
        def wrong(assets, header, stage):
            make_package(stage, metadata=False)
            (stage / "native_asr.so").write_bytes(b"wrong")
        with mock.patch.object(builder, "compile_payload", side_effect=wrong), self.assertRaises(ValueError):
            builder.build_package(self.assets, self.header, self.root / "output")
        self.assertFalse((self.root / "output").exists())
        self.assertEqual(list(self.root.glob(".endpoint-build-*")), [])

    def test_output_filled_during_build_is_not_overwritten(self):
        output = self.root / "output"
        def appeared(assets, header, stage):
            make_package(stage, metadata=False)
            output.mkdir()
            (output / "keep").write_text("other build")
        with mock.patch.object(builder, "compile_payload", side_effect=appeared), self.assertRaises(ValueError):
            builder.build_package(self.assets, self.header, output)
        self.assertEqual((output / "keep").read_text(), "other build")
        self.assertEqual(list(self.root.glob(".endpoint-build-*")), [])


if __name__ == "__main__":
    unittest.main()
