import tempfile
import unittest
from pathlib import Path

from watcher_operator.mount import is_mountpoint


class MountTests(unittest.TestCase):
    def test_is_mountpoint_detects_matching_mount_point(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mountinfo = root / "mountinfo"
            target = root / "volumes"
            target.mkdir()
            mountinfo.write_text(
                f"24 22 0:21 / {target} rw,relatime - ext4 /dev/sda1 rw\n",
                encoding="utf-8",
            )

            self.assertTrue(is_mountpoint(target, mountinfo))

    def test_is_mountpoint_returns_false_for_missing_mountinfo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            self.assertFalse(is_mountpoint(root / "volumes", root / "missing"))


if __name__ == "__main__":
    unittest.main()
