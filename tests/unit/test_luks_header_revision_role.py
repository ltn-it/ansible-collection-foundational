"""Exercise real revision-role discovery and bounded cryptsetup failures."""

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest


UUID = "11111111-2222-4333-8444-555555555555"
HEADER = b"SYNTHETIC_REVISION_HEADER"


class HeaderRevisionRoleTests(unittest.TestCase):
    def test_revision_uses_bounded_snapshot_for_uuid_and_metadata_discovery(self):
        source = Path(__file__).resolve().parents[2]
        for stalled in ("luksUUID", "luksDump", ""):
            with self.subTest(stalled=stalled), tempfile.TemporaryDirectory(
                dir=os.environ["HOME"], prefix="revision-role-"
            ) as directory, tempfile.TemporaryDirectory(
                dir="/dev/shm", prefix="revision-role-"
            ) as runtime_directory:
                root, runtime = Path(directory), Path(runtime_directory)
                root.chmod(0o700)
                runtime.chmod(0o700)
                scratch = runtime / "scratch"
                scratch.mkdir(mode=0o700)
                device = runtime / "device.img"
                device.write_bytes(b"SYNTHETIC_DEVICE")
                machine = root / "machine-id"
                machine.write_text("a" * 32 + "\n")
                crypttab = root / "crypttab"
                crypttab.write_text(f"root UUID={UUID} none luks\n")
                findfs = root / "findfs"
                findfs.write_text(f"#!{sys.executable}\nprint({str(device)!r})\n")
                findfs.chmod(0o700)
                marker = root / "stalled-pid"
                cryptsetup = root / "cryptsetup"
                cryptsetup.write_text(
                    f"#!{sys.executable}\n"
                    "import os, pathlib, sys, time\n"
                    f"if sys.argv[1] == {stalled!r}:\n"
                    f" pathlib.Path({str(marker)!r}).write_text(str(os.getpid()))\n"
                    " time.sleep(60)\n"
                    f"if sys.argv[1] == 'luksUUID': print({UUID!r})\n"
                    "elif sys.argv[1] == 'luksDump': print('{}')\n"
                    "elif sys.argv[1] == 'luksHeaderBackup':\n"
                    f" path=pathlib.Path(sys.argv[-1]);path.write_bytes({HEADER!r});path.chmod(0o400)\n"
                    "else: raise SystemExit(8)\n"
                )
                cryptsetup.chmod(0o700)
                collection = root / "collections/ansible_collections/lit"
                collection.mkdir(parents=True)
                (collection / "foundational").symlink_to(source, target_is_directory=True)
                variables = {
                    "luks_header_escrow_revision_enabled": True,
                    "luks_header_escrow_subject": "synthetic-source",
                    "luks_header_escrow_expected_uuid": UUID,
                    "luks_header_escrow_expected_machine_id": "a" * 32,
                    "luks_header_escrow_machine_id_path": str(machine),
                    "luks_header_escrow_crypttab_path": str(crypttab),
                    "luks_header_escrow_findfs_path": str(findfs),
                    "luks_header_escrow_cryptsetup_path": str(cryptsetup),
                    "luks_header_escrow_remote_temporary_root": str(scratch),
                    "luks_header_escrow_allow_regular_file_device": True,
                    "luks_header_escrow_timeout_seconds": 1,
                }
                assertions = ["_luks_header_escrow_snapshot is none"]
                if stalled:
                    assertions += [
                        "revision_failure_task == 'Inspect exact header bytes without transferring them'",
                        "luks_header_escrow_revision_result is none",
                    ]
                else:
                    assertions += [
                        "revision_failure_task is not defined",
                        "luks_header_escrow_revision_result.scratch_removed is sameas true",
                        f"luks_header_escrow_revision_result.luks_uuid == '{UUID}'",
                        "luks_header_escrow_revision_result.raw_size_bytes | type_debug == 'int'",
                        "luks_header_escrow_revision_result.raw_size_bytes == " + str(len(HEADER)),
                        "luks_header_escrow_revision_result.header_sha256 == '"
                        + hashlib.sha256(HEADER).hexdigest() + "'",
                        "'luks_header_b64' not in luks_header_escrow_revision_result",
                    ]
                play = [{
                    "hosts": "localhost", "gather_facts": False,
                    "vars": variables,
                    "tasks": [{
                        "block": [{"ansible.builtin.include_role": {
                            "name": "lit.foundational.luks_header_escrow",
                            "tasks_from": "revision",
                        }}],
                        "rescue": [{"ansible.builtin.set_fact": {
                            "revision_failure_task": "{{ ansible_failed_task.name }}",
                        }}],
                    }, {"ansible.builtin.assert": {"that": assertions, "quiet": True}}],
                }]
                (root / "play.json").write_text(json.dumps(play))
                (root / "ansible.cfg").write_text("[defaults]\nretry_files_enabled=False\n")
                env = {
                    **os.environ,
                    "HOME": str(root),
                    "ANSIBLE_CONFIG": str(root / "ansible.cfg"),
                    "ANSIBLE_COLLECTIONS_PATH": str(root / "collections"),
                    "ANSIBLE_COLLECTIONS_SCAN_SYS_PATH": "false",
                    "ANSIBLE_LOCAL_TEMP": str(root / "local"),
                    "ANSIBLE_REMOTE_TEMP": str(root / "remote"),
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
                child = subprocess.Popen(
                    [sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,",
                     "-c", "local", str(root / "play.json")],
                    env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    start_new_session=True,
                )
                try:
                    output, errors = child.communicate(timeout=25)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.communicate()
                    raise
                self.assertEqual(child.returncode, 0, (output + errors).decode(errors="replace"))
                self.assertEqual(list(scratch.iterdir()), [])
                self.assertEqual(device.read_bytes(), b"SYNTHETIC_DEVICE")
                self.assertEqual(marker.exists(), bool(stalled))
                if stalled:
                    with self.assertRaises(ProcessLookupError):
                        os.kill(int(marker.read_text()), 0)


if __name__ == "__main__":
    unittest.main()
