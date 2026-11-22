"""Execute the shipped handoff input guards and closed-prefix verifier in the EE."""

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / 'roles/podman_systemd/tasks/log_handoff'
ANSIBLE = shutil.which('ansible-playbook')


@unittest.skipUnless(ANSIBLE, 'requires the prescribed Ansible EE')
class HandoffInputTests(unittest.TestCase):
    def test_public_inputs_fail_before_a_following_mutation(self):
        profile = dict(hostname='lab.example', runtime_user='container', runtime_uid=23000,
                       graphroot='/opt/podman/storage', components=dict(application=dict(
                           container='application-main', unit='application', manifest='/opt/application/pod.yml',
                           manifest_sha256='a' * 64, quadlet='/home/container/.config/containers/systemd/application.kube',
                           destination='/var/log/podman/application.log')))
        good = dict(podman_systemd_log_handoff_action='plan', podman_systemd_log_handoff_operation='migration-1',
                    podman_systemd_log_handoff_profile=profile, podman_systemd_log_handoff_stop_order=['application'],
                    podman_systemd_log_handoff_setype='', podman_systemd_h_home='/home/container')
        cases = [('valid', {}, True), ('action', {'podman_systemd_log_handoff_action': 'recover'}, False),
                 ('traversal', {'podman_systemd_log_handoff_operation': '../elsewhere'}, False),
                 ('newline', {'podman_systemd_log_handoff_operation': 'migration\n'}, False),
                 ('duplicate', {'podman_systemd_log_handoff_stop_order': ['application', 'application']}, False),
                 ('missing', {'podman_systemd_log_handoff_stop_order': ['other']}, False),
                 ('check', {'ansible_check_mode': True}, False)]
        for name, field, value in [('root', 'runtime_uid', 0), ('uid-string', 'runtime_uid', '23000'),
                                   ('unknown-field', 'environment', {'PASSWORD': 'synthetic'}),
                                   ('user', 'runtime_user', 'root;echo')]:
            changed = copy.deepcopy(profile)
            changed[field] = value
            cases.append((name, {'podman_systemd_log_handoff_profile': changed}, False))
        for name, field, value in [('foreign-unit', 'quadlet', '/etc/containers/systemd/foreign.kube'),
                                   ('live-graph', 'destination', '/opt/podman/storage/live.log'),
                                   ('bad-hash', 'manifest_sha256', 'unreviewed')]:
            changed = copy.deepcopy(profile)
            changed['components']['application'][field] = value
            cases.append((name, {'podman_systemd_log_handoff_profile': changed}, False))
        for name, change, accepted in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                marker = root / 'mutation'
                tasks = [dict(name='Public interface', **{'ansible.builtin.import_tasks': str(TASKS / 'assert.yml')}),
                         dict(name='Component interface', **{'ansible.builtin.include_tasks': str(TASKS / 'assert_component.yml')},
                              loop='{{ podman_systemd_log_handoff_stop_order }}',
                              loop_control=dict(loop_var='podman_systemd_h_item')),
                         dict(name='Following mutation', **{'ansible.builtin.command': dict(argv=['/usr/bin/touch', str(marker)])})]
                play = root / 'play.yml'
                play.write_text(yaml.safe_dump([dict(name='Handoff input boundary', hosts='localhost', gather_facts=False,
                                                     vars=good | change, tasks=tasks)], sort_keys=False))
                config = root / 'ansible.cfg'
                config.write_text('[defaults]\nstdout_callback=default\n')
                outcome = subprocess.run(  # noqa: S603 -- trusted EE Ansible and isolated synthetic fixture.
                    [ANSIBLE, '-i', 'localhost,', '-c', 'local', str(play)] + (['--check'] if name == 'check' else []),
                    capture_output=True, text=True,
                    env=os.environ | {'ANSIBLE_CONFIG': str(config), 'ANSIBLE_LOCAL_TEMP': str(root / 'local'),
                                      'ANSIBLE_REMOTE_TEMP': str(root / 'remote')}, timeout=60, check=False,
                )
                self.assertEqual(outcome.returncode == 0, accepted, outcome.stdout + outcome.stderr)
                self.assertEqual(marker.exists(), accepted)


class ClosedPrefixTests(unittest.TestCase):
    def verify(self, old, new, *, symlink=False, hardlink=False, optimize=0):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'held.log', root / 'application.log'
            source.write_bytes(old)
            target.write_bytes(new)
            if symlink:
                target.unlink()
                target.symlink_to(source)
            if hardlink:
                os.link(source, root / 'unexpected-link')
            task = next(t for t in yaml.safe_load((TASKS / 'verify_one.yml').read_text())
                        if 'ansible.builtin.command' in t)
            program = task['ansible.builtin.command']['argv'][2]
            output = io.StringIO()
            with mock.patch.object(sys, 'argv', ['fixture', str(source), str(target), str(os.geteuid()),
                                                      str(source.stat().st_ino), str(source.stat().st_dev)]), \
                    contextlib.redirect_stdout(output):
                exec(compile(program, 'shipped-closed-prefix', 'exec', optimize=optimize), {})  # noqa: S102 -- shipped code, temporary files.
            return json.loads(output.getvalue())

    def test_preserves_a_complete_multichunk_source_and_records_new_append(self):
        source = b'original\n' * 150000
        value = self.verify(source, source + b'new-writer\n')
        self.assertEqual(value['preserved_old_bytes'], len(source))
        self.assertTrue(value['new_writer_appends'])

    def test_quiet_or_empty_original_log_is_valid(self):
        self.assertFalse(self.verify(b'old', b'old')['new_writer_appends'])
        self.assertEqual(self.verify(b'', b'new')['preserved_old_bytes'], 0)

    def test_corrupt_or_truncated_prefix_is_rejected_even_with_python_optimization(self):
        for target in [b'other', b'ol']:
            with self.subTest(target=target), self.assertRaisesRegex(RuntimeError, 'PRESERVED_PREFIX_CHANGED'):
                self.verify(b'old', target, optimize=2)

    def test_symlinks_and_unexpected_hardlinks_are_rejected(self):
        for options in [dict(symlink=True), dict(hardlink=True)]:
            with self.subTest(options=options), self.assertRaisesRegex(RuntimeError, 'UNVERIFIED_SOURCE_OR_DESTINATION'):
                self.verify(b'old', b'old-new', **options)

class ShippedCommandArgumentTests(unittest.TestCase):
    """Template the shipped argv, rather than manually reproducing its argument order."""

    def run_guard(self, filename, *, wrong_inode=False, wrong_device=False, damaged=False, live_writer=False):
        from ansible.parsing.dataloader import DataLoader
        from ansible.template import Templar

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage = root / '.lit-log-handoff-regression-application'
            stage.mkdir()
            source, target = stage / 'held.log', root / 'application.log'
            source.write_bytes(b'original-record\n' * 100000)
            target.write_bytes(b'corrupt' if damaged else source.read_bytes())
            meta = source.stat()
            pid, start = '0', '0'
            if live_writer:
                pid = str(os.getpid())
                start = Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19]
            values = dict(
                item='application', podman_systemd_h_name='application', podman_systemd_h_stage=str(stage),
                podman_systemd_h_log=str(target), podman_systemd_h_graph=str(root),
                podman_systemd_log_handoff_operation='regression',
                podman_systemd_h_python=dict(ansible_facts=dict(ansible_python=dict(executable=sys.executable))),
                podman_systemd_log_handoff_profile=dict(runtime_uid=os.geteuid(),
                                                       components=dict(application=dict(destination=str(target)))),
                podman_systemd_h_saved=dict(application=dict(
                    conmon=pid, start=start, source_inode=meta.st_ino + int(wrong_inode),
                    source_dev=meta.st_dev + int(wrong_device))),
            )
            task = next(t for t in yaml.safe_load((TASKS / filename).read_text()) if 'ansible.builtin.command' in t)
            argv = Templar(loader=DataLoader(), variables=values).template(task['ansible.builtin.command']['argv'])
            return subprocess.run(argv, capture_output=True, text=True, timeout=10, check=False)  # noqa: S603 -- shipped argv with synthetic files.

    def test_actual_start_and_post_start_argv_accept_the_recorded_identity(self):
        for filename in ['authorize_start.yml', 'verify_one.yml']:
            with self.subTest(filename=filename):
                result = self.run_guard(filename)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_actual_start_and_post_start_argv_reject_either_identity_change(self):
        for filename in ['authorize_start.yml', 'verify_one.yml']:
            for change in [dict(wrong_inode=True), dict(wrong_device=True)]:
                with self.subTest(filename=filename, change=change):
                    result = self.run_guard(filename, **change)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('REPLACED_RETAINED_SOURCE', result.stderr)

    def test_actual_start_and_post_start_argv_reject_corrupt_prefixes(self):
        for filename in ['authorize_start.yml', 'verify_one.yml']:
            with self.subTest(filename=filename):
                result = self.run_guard(filename, damaged=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('PREFIX', result.stderr)

    def test_actual_start_argv_rejects_a_still_live_original_writer(self):
        result = self.run_guard('authorize_start.yml', live_writer=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('OLD_WRITER_STILL_ALIVE', result.stderr)


if __name__ == '__main__':
    unittest.main()
