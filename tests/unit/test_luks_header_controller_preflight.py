"""Exercise controller-only escrow validation with an unreachable SSH source."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class HeaderControllerPreflightTests(unittest.TestCase):
    def test_private_local_tmp_and_execution_identity_are_scoped_to_controller(self):
        source = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            escrow = root / "escrow"
            escrow.mkdir(mode=0o700)
            collection = root / "collections/ansible_collections/lit"
            collection.mkdir(parents=True)
            (collection / "foundational").symlink_to(source, target_is_directory=True)
            inventory = {
                "all": {
                    "hosts": {
                        "localhost": {
                            "ansible_connection": "local",
                            "ansible_become": False,
                        },
                        "unreachable-source": {
                            "ansible_connection": "ssh",
                            "ansible_host": "127.0.0.1",
                            "ansible_port": 1,
                            "ansible_user": "nobody",
                            "ansible_become": True,
                            "ansible_remote_tmp": "/run/source-only-unwritable-from-controller",
                        },
                    }
                }
            }
            (root / "inventory.json").write_text(json.dumps(inventory))
            play = [
                {
                    "name": "Validate only controller state without contacting a source",
                    "hosts": "unreachable-source",
                    "gather_facts": False,
                    "tasks": [
                        {
                            "name": "Exercise the actual controller preflight taskset",
                            "ansible.builtin.include_role": {
                                "name": "lit.foundational.luks_header_escrow",
                                "tasks_from": "preflight",
                            },
                            "vars": {
                                "luks_header_escrow_enabled": True,
                                "luks_header_escrow_controller_root_path": str(escrow),
                                "luks_header_escrow_path": str(
                                    escrow / "header.vault.yml"
                                ),
                            },
                        },
                        {
                            "name": "Preserve source connection and privilege settings",
                            "ansible.builtin.assert": {
                                "that": [
                                    "ansible_connection == 'ssh'",
                                    "ansible_user == 'nobody'",
                                    "ansible_become is sameas true",
                                    "ansible_remote_tmp == '/run/source-only-unwritable-from-controller'",
                                ],
                                "quiet": True,
                            },
                        },
                    ],
                }
            ]
            (root / "play.json").write_text(json.dumps(play))
            (root / "ansible.cfg").write_text("[defaults]\nretry_files_enabled=False\n")
            env = {
                **os.environ,
                "HOME": str(root),
                "ANSIBLE_CONFIG": str(root / "ansible.cfg"),
                "ANSIBLE_COLLECTIONS_PATH": str(root / "collections"),
                "ANSIBLE_COLLECTIONS_SCAN_SYS_PATH": "false",
                "ANSIBLE_LOCAL_TEMP": str(root / "controller-local"),
                "ANSIBLE_REMOTE_TEMP": "/nonexistent/target-only-temporary-root",
                "ANSIBLE_REMOTE_TMP": "/nonexistent/target-only-temporary-root",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ansible.cli.playbook",
                    "-i",
                    str(root / "inventory.json"),
                    str(root / "play.json"),
                ],
                env=env,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(
                result.returncode,
                0,
                (result.stdout + result.stderr).decode(errors="replace"),
            )
            self.assertFalse((escrow / "header.vault.yml").exists())


if __name__ == "__main__":
    unittest.main()
