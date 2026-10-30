#!/usr/bin/python3
# Copyright: (c) 2026, Lightning IT
# SPDX-License-Identifier: MIT
"""Private bounded identity precheck shared by the role and snapshot."""

import os
from pathlib import Path
import re
import stat
import sys


def require_machine_identity(path, expected):
    if (not isinstance(path, str) or not os.path.isabs(path) or os.path.realpath(path) != path
            or not isinstance(expected, str) or not re.fullmatch("[0-9a-f]{32}", expected)):
        raise ValueError("Wrong source machine.")
    for parent in (Path(path).parent, *Path(path).parent.parents):
        info = parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.geteuid())
                or (info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX))):
            raise ValueError("Unprotected source identity ancestry.")
    observed = os.lstat(path)
    if (not stat.S_ISREG(observed.st_mode) or not 0 < observed.st_size <= 33
            or observed.st_uid not in (0, os.geteuid()) or observed.st_mode & 0o022):
        raise ValueError("Wrong source machine.")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        stable = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_uid", "st_gid", "st_mode")
        if any(getattr(observed, key) != getattr(before, key) for key in stable):
            raise ValueError("Wrong source machine.")
        identity = os.read(fd, 34)
        after = os.fstat(fd)
        if (any(getattr(before, key) != getattr(after, key) for key in stable)
                or len(identity) != before.st_size or identity.decode("ascii").strip() != expected):
            raise ValueError("Wrong source machine.")
    finally:
        os.close(fd)


if __name__ == "__main__":
    try:
        if len(sys.argv) != 3:
            raise ValueError("Exact identity arguments required.")
        require_machine_identity(sys.argv[1], sys.argv[2])
    except (OSError, ValueError):
        sys.exit("Source machine identity precheck failed.")
    print("Pinned source machine identity verified.")
