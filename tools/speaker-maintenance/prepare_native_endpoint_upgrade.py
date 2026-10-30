#!/usr/bin/env python3
"""生成固定旧版到指定候选的低空间维护事务；仅本机生成，不连接或操作音箱。"""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import struct
import subprocess
import sys
import uuid

import native_endpoint_release as release

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools/speaker-maintenance"
SOURCE_PINS = {
    "native_endpoint/package.sha256": "43d832ee500ff2058216ad004830657022cb05c31f0cdf271238c15abd2822a3",
    "native_endpoint/runtime.tar.gz": "6536152774d894ecd11a74a45cc3603ac76bbc5d2811494dfa819a24f49150f4",
    "native_first_client.sh": "4666623b8b85643eb28bc21b370ed52f227f9f333c9399d7e50752dfbac98fc9",
    "native_asr.so": "71f96c915b89795a721cfc0e701f88907435e25f59bf131f10295ab7bc3be611",
    "native_asr.sh": "ecf34e250505d488eaa2b41fbe1280f46d91d56abc0a1b7482ff185d4fd5b93f",
    "native_asr_ctl": "993a96982aee36482d83d9dab06b49ea0bc3f969a0e1fc57bc464432c21e79dc",
    "init.sh": "9aefae73a82c923fa7ce31ec79e8ab482111bf2a2a06b69be6ed9953a9c0e807",
}
FIRMWARE_PINS = {
    "/usr/bin/mipns-xiaomi": "a02071a39f3509d3a90dac638e323039a24de784a907f076a0a91f81cd5fbb9d",
    "/usr/lib/libxaudio_engine.so": "79f1a33d9683cd6940c8d23e3dd4e992f1958fe220c0dfff8d230f9f8a1b5e73",
    "/usr/bin/mico_aivs_lab": "7063b44fbe779c04c8bfc89e2870e1716eeb62765ba0025f8e8b68ea8026d18c",
    "/usr/lib/libaivs-message-util.so": "c0fc1b551e20962e6dceeb4b1a24b3d8a454e19bec8fd692f2229241691a0c31",
    "/usr/lib/libaivs_sdk.so": "21656da7ab6029e046e378270d7841629babc4d5b941ed27774bc25266678eda",
}
PACKAGE_FILES = release.PAYLOADS | {"package.sha256"}
BACKUP_FILES = {"native_endpoint/" + name for name in PACKAGE_FILES} | {
    "native_first_client.sh", "native_asr.so", "native_asr.sh", "native_asr_ctl", "init.sh", "native_first.env", "ettsc"}
SMALL_FILES = BACKUP_FILES - {"native_endpoint/runtime.tar.gz", "ettsc"}
EXTRAS = {"init.sh", "native_asr_ctl", "speaker_doctor.sh"}


def file_hash(path):
    return release.digest(release.read_regular(Path(path)))


def check_control_elf(data):
    # The speaker runs an aarch64 kernel. This standalone controller is ELF64;
    # the injected Xiaomi SO and isolated model runtime remain ELF32 ARM.
    if (len(data) < 64 or data[:7] != b"\x7fELF\x02\x01\x01"
            or struct.unpack_from("<H", data, 16)[0] != 2
            or struct.unpack_from("<H", data, 18)[0] != 183):
        raise ValueError("native_asr_ctl 必须为已验证路线的 ELF64 小端 AArch64 可执行文件。")


def route_helpers():
    functions = (ROOT / "device/endpoint_probe/run_route_client.sh").read_text().split('case "${1:-}" in', 1)[0]
    functions = functions.replace('. "$D/native_route_restore.sh"', '. "$UPGRADE_HOME/native_route_restore.sh"')
    return functions, (ROOT / "device/endpoint_probe/native_route_restore.sh").read_text()


def private_write(path, value):
    path.write_bytes(value if isinstance(value, bytes) else value.encode())
    path.chmod(0o600)


def validate_backup(backup):
    record = release.read_json(backup / "verified-manifest.json")
    if record.keys() != {"device_root", "files", "data_archive_sha256"} or record["device_root"] != "boot1":
        raise ValueError("备份记录结构或设备分区不符。")
    hashes = record["files"]
    if not isinstance(hashes, dict) or hashes.keys() != BACKUP_FILES:
        raise ValueError("备份必须包含完整的 13 项应用文件。")
    release.validate_package(backup / "native_endpoint")
    for name in sorted(BACKUP_FILES):
        if file_hash(backup / name) != hashes[name]:
            raise ValueError("本机备份文件与已核验的清单不一致。")
    if any(hashes[name] != expected for name, expected in SOURCE_PINS.items()):
        raise ValueError("仅支持已核验的固定旧日常版，拒绝其它升级来源。")
    if (hashes["native_first_client.sh"] != hashes["native_endpoint/native_first_client.sh"]
            or hashes["native_asr.so"] != hashes["native_endpoint/native_asr.so"]):
        raise ValueError("备份活动副本与安装包不一致。")
    if file_hash(backup / "data-full.tar.gz") != record["data_archive_sha256"]:
        raise ValueError("完整 data 私有备份归档校验失败。")
    return hashes


def render_runner(values, firmware_root=""):
    template = (TOOLS / "native_endpoint_upgrade.sh.in").read_text()
    constants = "\n".join(f"{key}={shlex.quote(str(value))}" for key, value in values.items())
    checks = " &&\n".join(f"    matches {shlex.quote(firmware_root + path)} {shlex.quote(value)}" for path, value in FIRMWARE_PINS.items())
    return template.replace("@CONSTANTS@", constants).replace("@FIRMWARE_CHECKS@", checks)


def prepare_bundle(backup, candidate, extras, output, expected_candidate, *, enable_followup_controls=False,
                   test_root=None, transaction_id=None):
    backup, candidate, extras, output = map(Path, (backup, candidate, extras, output))
    if os.path.lexists(output):
        raise ValueError("事务输出必须为全新目录，不覆盖已有内容。")
    before = validate_backup(backup)
    checked = release.validate_package(candidate)
    if not release.HEX.fullmatch(expected_candidate) or checked["package_manifest_sha256"] != expected_candidate:
        raise ValueError("候选清单与明确指定的摘要不符。")
    if checked["metadata"] is None:
        raise ValueError("新候选必须附带经过校验的 release.json；该文件仅保存在主机。")
    extra_data = {name: release.read_regular(extras / name) for name in EXTRAS}
    check_control_elf(extra_data["native_asr_ctl"])
    for name in ("init.sh", "speaker_doctor.sh"):
        if subprocess.run(["sh", "-n", str(extras / name)], capture_output=True).returncode:
            raise ValueError("额外设备脚本语法检查失败。")
    if enable_followup_controls:
        extra_data["native_first.env"] = release.read_regular(backup / "native_first.env") + (
            b"\nexport FOLLOWUP_EXIT_ENABLED=1\nexport FOLLOWUP_RESET_ENABLED=1\n")
    ident = transaction_id or uuid.uuid4().hex[:16]
    if len(ident) != 16 or any(char not in "0123456789abcdef" for char in ident):
        raise ValueError("事务标识必须是 16 位小写十六进制。")
    prefix = str(Path(test_root).resolve()) if test_root else ""
    data, temporary, proc = prefix + "/data", prefix + "/tmp", prefix + "/proc"
    stage, txn = temporary + "/endpoint-upgrade-stage-" + ident, data + "/endpoint-upgrade-" + ident
    functions, restore = route_helpers()
    if prefix:
        pattern = r"/(?:data|tmp|proc|etc)(?=/|[\s\"'])"
        functions = re.sub(pattern, lambda match: prefix + match[0], functions)
        restore = re.sub(pattern, lambda match: prefix + match[0], restore)
    output.mkdir(mode=0o700)
    try:
        (output / "package").mkdir(mode=0o700)
        (output / "extras").mkdir(mode=0o700)
        for name in sorted(PACKAGE_FILES):
            private_write(output / "package" / name, release.read_regular(candidate / name))
        for name, value in extra_data.items():
            private_write(output / "extras" / name, value)
        if enable_followup_controls and subprocess.run(
                ["sh", "-n", str(output / "extras/native_first.env")], capture_output=True).returncode:
            raise ValueError("新增开关后的私有配置语法检查失败；未执行或打印配置。")
        after = dict(before)
        for name in PACKAGE_FILES:
            after["native_endpoint/" + name] = file_hash(output / "package" / name)
        after["native_first_client.sh"] = after["native_endpoint/native_first_client.sh"]
        after["native_asr.so"] = after["native_endpoint/native_asr.so"]
        after.update({name: release.digest(value) for name, value in extra_data.items()})
        manifests = {"before.sha256": before, "old-small.sha256": {name: before[name] for name in SMALL_FILES},
                     "after.sha256": after, "committed.sha256": {name: value for name, value in after.items() if name != "init.sh"},
                     "rollback-current.sha256": {name: value for name, value in after.items() if name not in ("init.sh", "native_first.env")}}
        for name, mapping in manifests.items():
            private_write(output / name, release.manifest_bytes(mapping))
        private_write(output / "client-functions.sh", functions)
        private_write(output / "native_route_restore.sh", restore)
        committed_hash = file_hash(output / "committed.sha256")
        guard = f'''#!/bin/sh
# A pending or damaged transaction must leave original Xiaomi services alone.
TXN={shlex.quote(txn)}
DATA={shlex.quote(data)}
[ -d "$TXN" ] && [ ! -L "$TXN" ] || exit 0
[ "$(cat "$TXN/state" 2>/dev/null)" = COMMITTED ] || exit 0
[ ! -L "$TXN/committed.sha256" ] && [ ! -L "$TXN/new-init.sh" ] || exit 0
[ "$(sha256sum "$TXN/committed.sha256" | awk '{{print $1}}')" = {committed_hash} ] || exit 0
[ "$(sha256sum "$TXN/new-init.sh" | awk '{{print $1}}')" = {after['init.sh']} ] || exit 0
(cd "$DATA" && sha256sum -c "$TXN/committed.sha256" >/dev/null 2>&1) || exit 0
exec sh "$TXN/new-init.sh" "$@"
'''
        private_write(output / "guard.sh", guard)
        stage_hashes = {str(path.relative_to(output)): file_hash(path) for path in output.rglob("*") if path.is_file()}
        private_write(output / "stage.sha256", release.manifest_bytes(stage_hashes))
        allocated = lambda size: ((size + 4095) // 4096) * 4096
        old_small_bytes = sum(allocated((backup / name).stat().st_size) for name in SMALL_FILES)
        new_small_bytes = sum(allocated((output / "package" / name).stat().st_size) for name in PACKAGE_FILES - {"runtime.tar.gz"})
        new_small_bytes += sum(allocated(len(value)) for value in extra_data.values())
        new_small_bytes += allocated((candidate / "native_first_client.sh").stat().st_size) + allocated((candidate / "native_asr.so").stat().st_size)
        growth = max(0, (candidate / "runtime.tar.gz").stat().st_size - (backup / "native_endpoint/runtime.tar.gz").stat().st_size)
        data_required = (old_small_bytes + new_small_bytes + allocated(growth) + 256 * 1024 + 1024 * 1024 + 1023) // 1024
        tmp_required = ((backup / "native_endpoint/runtime.tar.gz").stat().st_size + checked["runtime"]["runtime_unpacked_bytes"] + 8 * 1024 * 1024 + 1023) // 1024
        values = {"ID": ident, "DATA": data, "TMP": temporary, "PROC": proc, "STAGE": stage, "TXN": txn,
                  "LOCK": temporary + "/endpoint-upgrade.lock", "OLD_RUNTIME": stage + "/old-runtime.tar.gz",
                  "DATA_REQUIRED_KIB": data_required, "TMP_REQUIRED_KIB": tmp_required, "MEMORY_REQUIRED_KIB": tmp_required + 32768,
                  "STAGE_MANIFEST_HASH": file_hash(output / "stage.sha256"),
                  "BEFORE_HASH": file_hash(output / "before.sha256"), "OLD_SMALL_HASH": file_hash(output / "old-small.sha256"),
                  "AFTER_HASH": file_hash(output / "after.sha256"), "COMMITTED_HASH": committed_hash,
                  "ROLLBACK_CURRENT_HASH": file_hash(output / "rollback-current.sha256"),
                  "CLIENT_FUNCTIONS_HASH": file_hash(output / "client-functions.sh"), "RESTORE_HELPER_HASH": file_hash(output / "native_route_restore.sh"),
                  "GUARD_HASH": file_hash(output / "guard.sh"), "ENV_HASH": before["native_first.env"], "AFTER_ENV_HASH": after["native_first.env"],
                  "ENABLE_FOLLOWUP_CONTROLS": int(enable_followup_controls), "ETTSC_HASH": before["ettsc"],
                  "OLD_INIT_HASH": before["init.sh"], "NEW_INIT_HASH": after["init.sh"], "DOCTOR_HASH": after["speaker_doctor.sh"],
                  "OLD_RUNTIME_HASH": before["native_endpoint/runtime.tar.gz"], "NEW_RUNTIME_HASH": after["native_endpoint/runtime.tar.gz"]}
        private_write(output / "transaction.sh", render_runner(values, prefix))
        if subprocess.run(["sh", "-n", str(output / "transaction.sh")], capture_output=True).returncode:
            raise ValueError("生成事务脚本未通过语法检查。")
        plan = {"schema_version": 1, "source_package_sha256": before["native_endpoint/package.sha256"],
                "candidate_package_sha256": expected_candidate, "transaction_id": ident, "device_stage": stage, "device_backup": txn,
                "runner_sha256": file_hash(output / "transaction.sh"), "data_required_kib": data_required,
                "tmp_extra_required_kib": tmp_required, "memory_available_required_kib": tmp_required + 32768,
                "after_files": after, "originally_absent": ["speaker_doctor.sh"],
                "enable_followup_controls": bool(enable_followup_controls),
                "power_loss": "original_xiaomi_only_until_verified_recovery_or_commit", "device_acceptance": "not_run"}
        private_write(output / "plan.json", json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        return plan
    except BaseException:
        shutil.rmtree(output)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--extras", type=Path, required=True)
    parser.add_argument("--expected-candidate", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--enable-followup-controls", action="store_true",
                        help="显式开启结束追问与换话题；默认保持原配置，启用时私有配置纳入事务")
    args = parser.parse_args(argv)
    try:
        plan = prepare_bundle(args.backup, args.package, args.extras, args.output, args.expected_candidate,
                              enable_followup_controls=args.enable_followup_controls)
    except (OSError, ValueError) as exc:
        print("事务未生成：" + (str(exc) if isinstance(exc, ValueError) else "文件读取或输出失败。"), file=sys.stderr)
        return 1
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
