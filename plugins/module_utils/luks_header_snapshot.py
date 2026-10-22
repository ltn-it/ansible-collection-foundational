# Copyright: (c) 2026, Lightning IT
# SPDX-License-Identifier: MIT
"""One bounded managed-side snapshot; raw scratch never outlives the operation."""

import base64
import hashlib
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import uuid

from .luks_header_recovery import MAX_HEADER, protected_tmpfs


class SnapshotInterrupted(RuntimeError):
    """A termination exception that selectors cannot mistake for retriable EINTR."""


def _command(binary, arguments, timeout):
    child = subprocess.Popen(
        [binary, *arguments], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"},
    )
    try:
        output, _errors = child.communicate(timeout=timeout)
        if child.returncode:
            raise ValueError("LUKS snapshot command failed.")
        return output
    except BaseException:
        # This group belongs solely to this invocation, including on SIGTERM.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()
        raise
    finally:
        child.stdout.close()
        child.stderr.close()


def _ancestry(path):
    for parent in (Path(path), *Path(path).parents):
        info = parent.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid not in (0, os.geteuid())
            or (info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX))
        ):
            raise ValueError("Unprotected snapshot path ancestry.")


def snapshot(device, expected_uuid, temporary_root="/run", include_payload=False,
             allow_regular_file_device=False, max_raw_bytes=MAX_HEADER,
             cryptsetup_path="/usr/sbin/cryptsetup", timeout_seconds=30,
             expected_machine_id="", machine_id_path="/etc/machine-id"):
    """Return only revision metadata unless payload capture is explicitly requested."""
    if (
        type(include_payload) is not bool
        or type(allow_regular_file_device) is not bool
        or type(max_raw_bytes) is not int or not 0 < max_raw_bytes <= MAX_HEADER
        or type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 60
        or not isinstance(expected_uuid, str) or str(uuid.UUID(expected_uuid)) != expected_uuid
    ):
        raise ValueError("An exact bounded snapshot contract is required.")
    if not isinstance(expected_machine_id, str) or (
        expected_machine_id and not re.fullmatch("[0-9a-f]{32}", expected_machine_id)
    ):
        raise ValueError("Invalid source machine identity.")
    if expected_machine_id:
        if (
            not isinstance(machine_id_path, str) or not os.path.isabs(machine_id_path)
            or os.path.realpath(machine_id_path) != machine_id_path
            or Path(machine_id_path).read_text().strip() != expected_machine_id
        ):
            raise ValueError("Wrong source machine.")
    if (
        not isinstance(device, str) or not device.startswith("/dev/")
        or os.path.realpath(device) != device
    ):
        raise ValueError("A canonical installed device is required.")
    info = os.lstat(device)
    if not (stat.S_ISBLK(info.st_mode) or (allow_regular_file_device and stat.S_ISREG(info.st_mode))):
        raise ValueError("Regular-file sources require explicit test opt-in.")
    if not isinstance(cryptsetup_path, str) or not os.path.isabs(cryptsetup_path):
        raise ValueError("An absolute cryptsetup executable is required.")
    binary = os.path.realpath(cryptsetup_path)
    binary_info = os.stat(binary)
    _ancestry(str(Path(binary).parent))
    if (
        not stat.S_ISREG(binary_info.st_mode) or not binary_info.st_mode & 0o111
        or binary_info.st_uid not in (0, os.geteuid()) or binary_info.st_mode & 0o022
    ):
        raise ValueError("Untrusted cryptsetup executable.")
    protected_tmpfs(temporary_root)
    _ancestry(temporary_root)
    def run(*arguments):
        return _command(binary, arguments, timeout_seconds)
    if run("luksUUID", device).decode("ascii").strip() != expected_uuid:
        raise ValueError("Wrong source LUKS UUID.")
    run("luksDump", "--dump-json-metadata", device)
    root = tempfile.mkdtemp(prefix="lit-luks-header-escrow-", dir=temporary_root)
    path = str(Path(root) / "header.luks")
    try:
        # cryptsetup creates this initially absent file with mode0400 itself.
        run("luksHeaderBackup", device, "--header-backup-file", path)
        if run("luksUUID", path).decode("ascii").strip() != expected_uuid:
            raise ValueError("Snapshot LUKS UUID changed.")
        run("luksDump", "--dump-json-metadata", path)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(fd)
            if (
                not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != os.geteuid() or stat.S_IMODE(before.st_mode) != 0o400
                or not 0 < before.st_size <= max_raw_bytes
            ):
                raise ValueError("Invalid protected raw snapshot.")
            digest = hashlib.sha256()
            payload = bytearray() if include_payload else None
            read = 0
            while True:
                block = os.read(fd, min(1024 * 1024, max_raw_bytes + 1 - read))
                if not block:
                    break
                read += len(block)
                if read > max_raw_bytes:
                    raise ValueError("Snapshot exceeds its bound.")
                digest.update(block)
                if payload is not None:
                    payload.extend(block)
            after = os.fstat(fd)
            stable = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_uid", "st_gid", "st_mode", "st_nlink")
            if any(getattr(before, key) != getattr(after, key) for key in stable) or read != before.st_size:
                raise ValueError("Snapshot changed during inspection.")
            result = {"luks_uuid": expected_uuid, "raw_size_bytes": read, "raw_sha256": digest.hexdigest()}
            if payload is not None:
                result["luks_header_b64"] = base64.b64encode(payload).decode("ascii")
                payload[:] = b"\0" * len(payload)
        finally:
            os.close(fd)
    finally:
        shutil.rmtree(root)
    result["scratch_removed"] = True
    return result
