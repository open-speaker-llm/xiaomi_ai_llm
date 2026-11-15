"""Exercise the client and generated hook's actual root-slot detection bodies."""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

CLIENT = Path(__file__).resolve().parents[1] / 'device/native_first_client.sh'


def detection_bodies():
    text = CLIENT.read_text()
    pattern = r'root_device\(\) \{\n.*?\n\}\n\nis_system1_root\(\) \{\n.*?\n\}'
    bodies = re.findall(pattern, text, re.S)
    if len(bodies) != 2:
        raise AssertionError(f'expected client and hook detectors, found {len(bodies)}')
    return bodies


class System1Detection(unittest.TestCase):
    def run_detector(self, body, mounts, mtd, number):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'mounts').write_text(mounts)
            (root / 'mtd').write_text(mtd)
            if number is not None:
                (root / 'ubi0').mkdir()
                (root / 'ubi0' / 'mtd_num').write_text(number)
            body = body.replace('/proc/mounts', str(root / 'mounts'))
            body = body.replace('/proc/mtd', str(root / 'mtd'))
            body = body.replace('/sys/class/ubi/', str(root) + '/')
            return subprocess.run(['sh', '-c', body + '\nis_system1_root'],
                                  capture_output=True, check=False).returncode == 0

    def test_client_and_hook(self):
        mtd = 'dev: size erasesize name\nmtd3: 06000000 00020000 "system0"\nmtd4: 06000000 00020000 "system1"\n'
        cases = [
            ('old S12A', '/dev/mtdblock5 / squashfs ro 0 0\n', '', None, True),
            ('UBIFS system1', 'rootfs / rootfs rw 0 0\n/dev/ubi0_0 / ubifs rw 0 0\n', mtd, '4\n', True),
            ('UBIFS system0', '/dev/ubi0_0 / ubifs rw 0 0\n', mtd, '3\n', False),
            ('missing root', '', mtd, '4\n', False),
            ('missing mtd number', '/dev/ubi0_0 / ubifs rw 0 0\n', mtd, None, False),
            ('invalid mtd number', '/dev/ubi0_0 / ubifs rw 0 0\n', mtd, 'bad\n', False),
            ('missing label', '/dev/ubi0_0 / ubifs rw 0 0\n', '', '4\n', False),
        ]
        for kind, body in zip(('client', 'hook'), detection_bodies()):
            for name, mounts, mtd_data, number, expected in cases:
                with self.subTest(kind=kind, case=name):
                    self.assertEqual(self.run_detector(body, mounts, mtd_data, number), expected)


if __name__ == '__main__':
    unittest.main()
