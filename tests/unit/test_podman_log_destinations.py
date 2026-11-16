"""Exercise the shipped destination argv with real files and effective permissions."""

import contextlib
import io
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar
import yaml

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / 'roles/podman_systemd/tasks'


class LogDestinationTests(unittest.TestCase):
    def test_log_cannot_overwrite_its_manifest_or_quadlet(self):
        tasks = yaml.safe_load((TASKS / 'assert.yml').read_text())
        task = next(t for t in tasks if t['name'] ==
                    'Require trusted directory ancestry for the native log destination')
        for case in ['separate', 'manifest', 'quadlet', 'manifest-alias']:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                log, manifest, quadlet = root / 'app.log', root / 'pod.yml', root / 'app.kube'
                for path in [log, manifest, quadlet]:
                    path.write_text('synthetic definition\n')
                    path.chmod(0o600)
                if case == 'manifest':
                    log = manifest
                elif case == 'quadlet':
                    log = quadlet
                elif case == 'manifest-alias':
                    manifest.unlink()
                    manifest.symlink_to(log)
                values = dict(podman_systemd_log_path=str(log),
                              podman_systemd_manifest_path=str(manifest),
                              podman_systemd_quadlet_path=str(quadlet),
                              podman_systemd_log_python=dict(ansible_facts=dict(
                                  ansible_python=dict(executable=sys.executable))))
                argv = Templar(loader=DataLoader(), variables=values).template(
                    task['ansible.builtin.command']['argv'])
                original = Path.lstat

                def trusted_fixture_parent(path):
                    info = original(path)
                    # The EE's shared /tmp is not a deployment directory. Only
                    # model its ancestor mode; real file identities stay intact.
                    if str(path) in ['/tmp', tempfile.gettempdir()]:
                        fields = list(info)
                        fields[0] = stat.S_IFDIR | 0o755
                        return os.stat_result(fields)
                    return info

                accepted = True
                try:
                    with mock.patch.object(sys, 'argv', ['shipped'] + argv[3:]), \
                            mock.patch.object(Path, 'lstat', trusted_fixture_parent), \
                            contextlib.redirect_stdout(io.StringIO()):
                        exec(compile(argv[2], 'shipped-log-ancestry', 'exec'), {})  # noqa: S102 -- shipped code and isolated files.
                except (RuntimeError, SystemExit):
                    accepted = False
                self.assertEqual(accepted, case == 'separate')

    def test_atomic_copy_requires_write_and_search_access_to_the_target_parent(self):
        import hashlib

        tasks = yaml.safe_load((TASKS / 'log_handoff/copy_guard_one.yml').read_text())
        task = next(t for t in tasks if t['name'] ==
                    'Verify immutable manifest and definition hashes and acceptable prior destination bytes')
        for mode, accepted in [(0o700, True), (0o500, False)]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                parent = root / 'destination'
                parent.mkdir()
                target = parent / 'app.log'
                target.write_bytes(b'')
                manifest, quadlet, held = root / 'pod.yml', root / 'app.kube', root / 'held.log'
                for path in [manifest, quadlet, held]:
                    path.write_bytes(b'original\n')
                stage = root / 'stage'
                stage.mkdir()
                held.rename(stage / 'held.log')
                values = dict(podman_systemd_h_name='app', podman_systemd_h_stage=str(stage),
                              podman_systemd_h_log=str(target), podman_systemd_h_activity=dict(stdout='active'),
                              podman_systemd_h_spec=dict(manifest=str(manifest), quadlet=str(quadlet)),
                              podman_systemd_h_saved=dict(app=dict(
                                  manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                                  quadlet_sha256=hashlib.sha256(quadlet.read_bytes()).hexdigest())),
                              podman_systemd_h_python=dict(ansible_facts=dict(
                                  ansible_python=dict(executable=sys.executable))))
                argv = Templar(loader=DataLoader(), variables=values).template(
                    task['ansible.builtin.command']['argv'])
                parent.chmod(mode)
                try:
                    outcome = subprocess.run(argv, capture_output=True, text=True,  # noqa: S603 -- shipped argv in private EE fixture.
                                             timeout=10, check=False)
                finally:
                    parent.chmod(0o700)
                self.assertEqual(outcome.returncode == 0, accepted, outcome.stderr)


if __name__ == '__main__':
    unittest.main()
