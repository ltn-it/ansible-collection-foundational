"""Keep generated-unit boot policy in the Quadlet source rather than systemctl enable."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from jinja2 import Environment, StrictUndefined
import yaml

ROOT = Path(__file__).resolve().parents[2]
ROLE = ROOT / 'roles/podman_systemd'


class QuadletBootPolicyTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ansible-playbook'), 'requires the prescribed Ansible EE')
    def test_retained_source_requires_read_and_write_access_before_a_following_stop(self):
        main = yaml.safe_load((ROLE / 'tasks/main.yml').read_text())
        names = ['Inspect the original Quadlet when retaining its disabled source',
                 'Require a regular single-link retained Quadlet before teardown',
                 'Check effective access to disable a retained Quadlet before teardown']
        for mode, accepted in [(0o600, True), (0o200, False), (0o400, False)]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source, stop = root / 'original.kube', root / 'following-stop'
                source.write_text('[Install]\nWantedBy=default.target\n')
                source.chmod(mode)
                tasks = [next(t for t in main if t['name'] == name) for name in names]
                tasks.append(dict(name='Following service stop boundary',
                                  **{'ansible.builtin.command': dict(argv=['/usr/bin/touch', str(stop)])}))
                play = root / 'play.yml'
                play.write_text(yaml.safe_dump([dict(hosts='localhost', gather_facts=False, vars=dict(
                    podman_systemd_action='absent', podman_systemd_remove_quadlet=False,
                    podman_systemd_quadlet_path=str(source)), tasks=tasks)], sort_keys=False))
                config = root / 'ansible.cfg'
                config.write_text('[defaults]\nstdout_callback=default\n')
                try:
                    outcome = subprocess.run(  # noqa: S603 -- shipped preflight and isolated real permission fixture.
                        [shutil.which('ansible-playbook'), '-i', 'localhost,', '-c', 'local', str(play)],
                        capture_output=True, text=True, timeout=60, check=False,
                        env=os.environ | {'ANSIBLE_CONFIG': str(config), 'ANSIBLE_LOCAL_TEMP': str(root / 'local'),
                                          'ANSIBLE_REMOTE_TEMP': str(root / 'remote')})
                finally:
                    source.chmod(0o600)
                self.assertEqual(outcome.returncode == 0, accepted, outcome.stdout + outcome.stderr)
                self.assertEqual(stop.exists(), accepted)

    @unittest.skipUnless(shutil.which('ansible-playbook'), 'requires the prescribed Ansible EE')
    def test_install_removal_recognizes_indented_headers_and_preserves_other_sections(self):
        main = yaml.safe_load((ROLE / 'tasks/main.yml').read_text())
        task = next(t for t in main if t['name'] ==
                    'Disable boot policy in the retained original Quadlet after confirmed teardown')
        for install_indent, kube_indent in [('  ', ''), ('', ' \t')]:
            with self.subTest(install=install_indent, kube=kube_indent), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / 'original.kube'
                prefix = '[Unit]\nDescription=Keep exact application bytes\n'
                application = kube_indent + '[Kube]\nYaml=/private/original.yml\n'
                source.write_text(prefix + install_indent + '[Install]\nWantedBy=default.target\n' + application)
                source.chmod(0o600)
                play = root / 'play.yml'
                play.write_text(yaml.safe_dump([dict(hosts='localhost', gather_facts=False, vars=dict(
                    podman_systemd_action='absent', podman_systemd_remove_quadlet=False,
                    podman_systemd_retained_quadlet=dict(stat=dict(exists=True)),
                    podman_systemd_quadlet_path=str(source)), tasks=[task])], sort_keys=False))
                config = root / 'ansible.cfg'
                config.write_text('[defaults]\nstdout_callback=default\n')
                outcome = subprocess.run(  # noqa: S603 -- shipped file edit and private valid section layouts.
                    [shutil.which('ansible-playbook'), '-i', 'localhost,', '-c', 'local', str(play)],
                    capture_output=True, text=True, timeout=60, check=False,
                    env=os.environ | {'ANSIBLE_CONFIG': str(config), 'ANSIBLE_LOCAL_TEMP': str(root / 'local'),
                                      'ANSIBLE_REMOTE_TEMP': str(root / 'remote')})
                self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
                self.assertEqual(source.read_text(), prefix + application)
                self.assertEqual(source.stat().st_mode & 0o777, 0o600)

    def test_disabled_quadlet_has_no_install_target(self):
        template = Environment(undefined=StrictUndefined).from_string(
            (ROLE / 'templates/kube.quadlet.j2').read_text())
        for enabled in [False, True]:
            with self.subTest(enabled=enabled):
                result = template.render(
                    podman_systemd_description='Synthetic fixture', podman_systemd_manifest_path='/private/pod.yml',
                    podman_systemd_after=[], podman_systemd_wants=[], podman_systemd_networks=[],
                    podman_systemd_log_path='', podman_systemd_enabled=enabled,
                    podman_systemd_install_wanted_by='default.target')
                self.assertEqual('WantedBy=default.target' in result, enabled)

    def test_generated_service_state_never_calls_enable_or_disable(self):
        tasks = yaml.safe_load((ROLE / 'tasks/main.yml').read_text())
        for task in tasks:
            if 'ansible.builtin.systemd' in task:
                with self.subTest(task=task['name']):
                    self.assertNotIn('enabled', task['ansible.builtin.systemd'])

    @unittest.skipUnless(shutil.which('ansible-playbook'), 'requires the prescribed Ansible EE')
    def test_absent_removes_boot_policy_even_when_the_quadlet_is_retained(self):
        for remove in [True, False]:
            with self.subTest(remove=remove), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                quadlet = root / 'original.kube'
                source = '[Unit]\nDescription=Preserve original\n[Kube]\nYaml=/private/original.yml\n'
                quadlet.write_text(source + '[Install]\nWantedBy=default.target\n')
                quadlet.chmod(0o600)
                main = yaml.safe_load((ROLE / 'tasks/main.yml').read_text())
                index = next(i for i, t in enumerate(main) if t['name'] ==
                             'Stop the loaded Podman kube service before disabling or removing it')
                tasks = main[index:]
                for task in tasks:
                    # Model only external manager calls. File mutations and the
                    # shipped teardown assertions run against real source bytes.
                    if 'ansible.builtin.systemd' in task:
                        task.pop('ansible.builtin.systemd')
                        task['ansible.builtin.command'] = dict(argv=[sys.executable, '-c', 'pass'])
                        task['changed_when'] = False
                    elif task['name'] == 'Verify the Podman kube service state after teardown':
                        task['ansible.builtin.command']['argv'] = [sys.executable, '-c',
                            "print('LoadState=loaded\\nActiveState=inactive\\nResult=success')"]
                play = root / 'play.yml'
                play.write_text(yaml.safe_dump([dict(hosts='localhost', gather_facts=False, vars=dict(
                    podman_systemd_action='absent', podman_systemd_scope='user',
                    podman_systemd_service_name='original.service', podman_systemd_quadlet_path=str(quadlet),
                    podman_systemd_remove_quadlet=remove, podman_systemd_removal_load=dict(stdout='loaded'),
                    podman_systemd_teardown_already_successful=True,
                    podman_systemd_retained_quadlet=dict(stat=dict(exists=True))), tasks=tasks)], sort_keys=False))
                config = root / 'ansible.cfg'
                config.write_text('[defaults]\nstdout_callback=default\n')
                outcome = subprocess.run(  # noqa: S603 -- trusted EE Ansible with private synthetic source.
                    [shutil.which('ansible-playbook'), '-i', 'localhost,', '-c', 'local', str(play)],
                    capture_output=True, text=True, timeout=60, check=False,
                    env=os.environ | {'ANSIBLE_CONFIG': str(config), 'ANSIBLE_LOCAL_TEMP': str(root / 'local'),
                                      'ANSIBLE_REMOTE_TEMP': str(root / 'remote')})
                self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
                self.assertEqual(quadlet.exists(), not remove)
                if not remove:
                    self.assertEqual(quadlet.read_text(), source)
                    self.assertEqual(quadlet.stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
