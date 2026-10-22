"""Real cryptsetup snapshot tests and bounded managed-side failure cleanup."""

import base64
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from plugins.module_utils.luks_header_snapshot import snapshot


UUID = "11111111-2222-4333-8444-555555555555"


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="snapshot-unit-", dir="/dev/shm")
        self.executable_root = tempfile.TemporaryDirectory(prefix="snapshot-cli-", dir=os.environ["HOME"])
        self.root = Path(self.scratch.name)
        self.runtime = self.root / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.device = self.root / "disk.img"
        with self.device.open("wb") as stream:
            stream.truncate(32 * 1024 * 1024)
        self.identity = Path(self.executable_root.name) / "machine-id"
        self.identity.write_text("a" * 32 + "\n")
        self.options = dict(device=str(self.device), expected_uuid=UUID, temporary_root=str(self.runtime),
                            allow_regular_file_device=True, expected_machine_id="a" * 32,
                            machine_id_path=str(self.identity))

    def tearDown(self):
        self.scratch.cleanup()
        self.executable_root.cleanup()

    def no_raw_scratch(self):
        self.assertEqual(list(self.runtime.iterdir()), [])

    def fake_cli(self, mode):
        binary = Path(self.executable_root.name) / "cryptsetup"
        marker = Path(self.executable_root.name) / "started"
        source = '''import json, os, pathlib, sys, time
args=sys.argv[1:]
if args[0]=='luksUUID':print(EXPECTED_UUID)
elif args[0]=='luksDump':print('{}')
elif args[0]=='luksHeaderBackup':
 path=pathlib.Path(args[-1]);path.write_bytes(b'SYNTHETIC_RAW_HEADER'*64);path.chmod(0o400)
 pathlib.Path(MARKER).write_text(str(os.getpid()))
 if MODE=='fail':raise SystemExit(7)
 if MODE=='sleep':time.sleep(60)
 if MODE=='permissions':path.chmod(0o600)
 if MODE=='hardlink':os.link(path,path.parent/'another-link')
else:raise SystemExit(8)
'''.replace("EXPECTED_UUID", repr(UUID)).replace("MARKER", repr(str(marker))).replace("MODE", repr(mode))
        binary.write_text("#!" + sys.executable + "\n" + source)
        binary.chmod(0o700)
        return str(binary), marker

    def test_real_metadata_matches_payload_and_device_remains_unchanged(self):
        subprocess.run(
            ["/usr/sbin/cryptsetup", "luksFormat", "--batch-mode", "--type", "luks2", "--uuid", UUID,
             "--key-file", "-", "--pbkdf", "pbkdf2", "--pbkdf-force-iterations", "1000", str(self.device)],
            input=b"SYNTHETIC_DISK_KEY_FOR_UNIT_ONLY", check=True, capture_output=True, timeout=30,
        )
        before = hashlib.sha256(self.device.read_bytes()).hexdigest()
        metadata = snapshot(**self.options)
        self.assertEqual(set(metadata), {"luks_uuid", "raw_size_bytes", "raw_sha256", "scratch_removed"})
        self.no_raw_scratch()
        payload = snapshot(**self.options, include_payload=True, expected_sha256=metadata["raw_sha256"])
        raw = base64.b64decode(payload.pop("luks_header_b64"), validate=True)
        self.assertEqual(payload, metadata)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), metadata["raw_sha256"])
        self.assertEqual(len(raw), metadata["raw_size_bytes"])
        self.assertEqual(hashlib.sha256(self.device.read_bytes()).hexdigest(), before)
        self.no_raw_scratch()

    def test_changed_planned_hash_is_rejected_before_payload_return_and_cleaned(self):
        binary, marker = self.fake_cli("valid")
        with self.assertRaisesRegex(ValueError, "revision changed before payload transfer"):
            snapshot(**self.options, cryptsetup_path=binary, include_payload=True, expected_sha256="e" * 64)
        self.assertTrue(marker.exists())
        self.no_raw_scratch()

    def test_wrong_machine_is_rejected_before_snapshot_commands(self):
        binary, marker = self.fake_cli("fail")
        with self.assertRaisesRegex(ValueError, "Wrong source machine"):
            snapshot(**{**self.options, "expected_machine_id": "b" * 32}, cryptsetup_path=binary)
        self.assertFalse(marker.exists())
        self.no_raw_scratch()

    def test_wrong_uuid_is_rejected_before_temporary_capture(self):
        binary, marker = self.fake_cli("fail")
        with self.assertRaisesRegex(ValueError, "Wrong source LUKS UUID"):
            snapshot(**{**self.options, "expected_uuid": "22222222-2222-4333-8444-555555555555"},
                     cryptsetup_path=binary)
        self.assertFalse(marker.exists())
        self.no_raw_scratch()

    def test_regular_file_without_opt_in_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "explicit test opt-in"):
            snapshot(**{**self.options, "allow_regular_file_device": False})
        self.no_raw_scratch()

    def test_symlink_source_is_rejected(self):
        alias = self.root / "alias.img"
        alias.symlink_to(self.device)
        with self.assertRaisesRegex(ValueError, "canonical installed device"):
            snapshot(**{**self.options, "device": str(alias)})
        self.no_raw_scratch()

    def test_unsafe_or_symlinked_runtime_is_rejected(self):
        binary, marker = self.fake_cli("fail")
        self.runtime.chmod(0o777)
        with self.assertRaises(ValueError):
            snapshot(**self.options, cryptsetup_path=binary)
        self.runtime.chmod(0o700)
        alias = self.root / "runtime-alias"
        alias.symlink_to(self.runtime)
        with self.assertRaises(ValueError):
            snapshot(**{**self.options, "temporary_root": str(alias)}, cryptsetup_path=binary)
        self.assertFalse(marker.exists())
        self.no_raw_scratch()

    def test_partial_failure_oversize_permissions_and_hardlinks_are_cleaned(self):
        for mode in ("fail", "permissions", "hardlink", "oversize"):
            with self.subTest(mode=mode):
                binary, marker = self.fake_cli(mode)
                bound = 1 if mode == "oversize" else 20971520
                with self.assertRaises(ValueError):
                    snapshot(**self.options, cryptsetup_path=binary, max_raw_bytes=bound)
                self.assertTrue(marker.exists())
                self.no_raw_scratch()

    def test_timeout_kills_only_owned_child_and_cleans_partial_header(self):
        binary, marker = self.fake_cli("sleep")
        with self.assertRaises(subprocess.TimeoutExpired):
            snapshot(**self.options, cryptsetup_path=binary, timeout_seconds=1)
        self.no_raw_scratch()
        with self.assertRaises(ProcessLookupError):
            os.kill(int(marker.read_text()), 0)

    def test_managed_process_sigterm_cleans_header_and_reaps_crypto_child(self):
        binary, marker = self.fake_cli("sleep")
        options = {**self.options, "cryptsetup_path": binary}
        program = '''import json,signal,sys
sys.path.insert(0,sys.argv[1])
from plugins.module_utils.luks_header_snapshot import SnapshotInterrupted,snapshot
def interrupted(signum,frame):raise SnapshotInterrupted('test termination')
signal.signal(signal.SIGTERM,interrupted)
try:snapshot(**json.load(sys.stdin))
except SnapshotInterrupted:sys.exit(19)
'''
        root = str(Path(__file__).resolve().parents[2])
        child = subprocess.Popen([sys.executable, "-I", "-S", "-c", program, root],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            child.stdin.write(json.dumps(options).encode())
            child.stdin.close()
            for _attempt in range(100):
                if marker.exists() or child.poll() is not None:
                    break
                time.sleep(0.02)
            self.assertTrue(marker.exists())
            child.send_signal(signal.SIGTERM)
            self.assertEqual(child.wait(timeout=10), 19)
            self.no_raw_scratch()
            with self.assertRaises(ProcessLookupError):
                os.kill(int(marker.read_text()), 0)
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()
            child.stdout.close()
            child.stderr.close()


if __name__ == "__main__":
    unittest.main()
