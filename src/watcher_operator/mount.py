from __future__ import annotations

from pathlib import Path


def is_mountpoint(path: str | Path, mountinfo_path: str | Path = "/proc/self/mountinfo") -> bool:
    """Check whether a path is listed as a mount point in Linux mountinfo."""

    target = Path(path).resolve()
    try:
        lines = Path(mountinfo_path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return False

    for line in lines:
        parts = line.split()
        if len(parts) < 5:
            continue
        mount_point = Path(_decode_mountinfo_path(parts[4])).resolve()
        if mount_point == target:
            return True
    return False


def _decode_mountinfo_path(value: str) -> str:
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )
