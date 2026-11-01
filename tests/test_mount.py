import unittest
from pathlib import Path

from watcher_operator.mount import is_mountpoint


class MountTests(unittest.TestCase):
    def test_is_mountpoint_detects_matching_mount_point(self):
        root = Path(__file__).parent / ".test_mount_data"
        root.mkdir(exist_ok=True)
        mountinfo = root / "mountinfo"
        target = root / "volumes"
        target.mkdir(exist_ok=True)
        try:
            mountinfo.write_text(
                f"24 22 0:21 / {target.resolve()} rw,relatime - ext4 /dev/sda1 rw\n",
                encoding="utf-8",
            )

            self.assertTrue(is_mountpoint(target, mountinfo))
        finally:
            mountinfo.unlink(missing_ok=True)
            target.rmdir()
            root.rmdir()

    def test_is_mountpoint_returns_false_for_missing_mountinfo(self):
        root = Path(__file__).parent / ".test_mount_data"
        root.mkdir(exist_ok=True)
        try:
            self.assertFalse(is_mountpoint(root / "volumes", root / "missing"))
        finally:
            root.rmdir()


if __name__ == "__main__":
    unittest.main()
