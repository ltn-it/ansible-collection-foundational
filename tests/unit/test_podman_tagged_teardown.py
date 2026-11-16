"""Run the shipped dynamic preflight with a real Ansible tag filter."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
ANSIBLE = shutil.which('ansible-playbook')


@unittest.skipUnless(ANSIBLE, 'requires the prescribed Ansible EE')
class TaggedTeardownTests(unittest.TestCase):
    def test_successfully_inactive_loaded_service_needs_no_new_teardown(self):
        for action in ['stopped', 'absent']:
            for active, result, inspected in [
                ('inactive', 'success', False),
                ('active', 'success', True),
                ('inactive', 'exit-code', True),
                ('inactive', None, True),
            ]:
                with self.subTest(action=action, active=active, result=result), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    guard = root / 'guard-called'
                    stopped = root / 'stop-called'
                    main = yaml.safe_load((ROOT / 'roles/podman_systemd/tasks/main.yml').read_text())
                    tasks = [next(t for t in main if t['name'] ==
                                  'Classify an already successful inactive loaded service')]
                    for name, marker, module in [
                        ('Validate the actual loaded native teardown configuration', guard, 'ansible.builtin.include_tasks'),
                        ('Manage Podman kube service state', stopped, 'ansible.builtin.systemd'),
                        ('Stop the loaded Podman kube service before disabling or removing it',
                         stopped, 'ansible.builtin.systemd'),
                    ]:
                        task = next(t for t in main if t['name'] == name).copy()
                        task.pop(module)
                        task['ansible.builtin.command'] = {'argv': ['/usr/bin/touch', str(marker)]}
                        tasks.append(task)
                    status = ['LoadState=loaded', 'ActiveState=' + active]
                    if result is not None:
                        status.append('Result=' + result)
                    play = root / 'play.yml'
                    play.write_text(yaml.safe_dump([dict(
                        name='Already successful inactive service', hosts='localhost', gather_facts=False,
                        vars=dict(podman_systemd_action=action,
                                  podman_systemd_removal_load={'stdout': 'loaded'},
                                  podman_systemd_teardown_initial={'stdout_lines': status}),
                        tasks=tasks,
                    )], sort_keys=False))
                    config = root / 'ansible.cfg'
                    config.write_text('[defaults]\nstdout_callback=default\n')
                    outcome = subprocess.run(  # noqa: S603 -- trusted EE Ansible and private fixture.
                        [ANSIBLE, '-i', 'localhost,', '-c', 'local', str(play)],
                        env=os.environ | {'ANSIBLE_CONFIG': str(config), 'ANSIBLE_LOCAL_TEMP': str(root / 'local'),
                                          'ANSIBLE_REMOTE_TEMP': str(root / 'remote')},
                        capture_output=True, text=True, timeout=60, check=False,
                    )
                    self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
                    self.assertEqual(guard.exists(), inspected)
                    self.assertEqual(stopped.exists(), inspected)

    def test_missing_inactive_stop_skips_service_management_and_accepts_not_found_status(self):
        for load, active, expected, managed in [
            ('not-found', 'inactive', 0, False),
            ('not-found', 'active', 2, False),
            ('loaded', 'inactive', 0, True),
        ]:
            with self.subTest(load=load, active=active), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                marker = root / 'service-management'
                main = yaml.safe_load((ROOT / 'roles/podman_systemd/tasks/main.yml').read_text())
                names = [
                    'Require an inactive service when its loaded fragment is unavailable',
                    'Manage Podman kube service state',
                    'Verify the Podman kube service state after teardown',
                    'Require successful Podman kube service teardown before Quadlet removal',
                ]
                tasks = [next(t for t in main if t['name'] == name) for name in names]
                tasks[1].pop('ansible.builtin.systemd')
                tasks[1]['ansible.builtin.command'] = {'argv': ['/usr/bin/touch', str(marker)]}
                status = '\n'.join(['LoadState=' + load, 'ActiveState=' + active] +
                                   ([] if load == 'not-found' else ['Result=success']))
                tasks[2]['ansible.builtin.command'] = {'argv': [sys.executable, '-c',
                    'import sys; print(' + repr(status) + '); sys.exit(' +
                    ('4' if load == 'not-found' else '0') + ')']}
                play = root / 'play.yml'
                play.write_text(yaml.safe_dump([dict(
                    name='Already missing stop contract', hosts='localhost', gather_facts=False,
                    vars=dict(podman_systemd_action='stopped',
                              podman_systemd_removal_load={'stdout': load},
                              podman_systemd_missing_fragment_state={'stdout_lines': status.splitlines()}),
                    tasks=tasks,
                )], sort_keys=False))
                config = root / 'ansible.cfg'
                config.write_text('[defaults]\nstdout_callback=default\n')
                outcome = subprocess.run(  # noqa: S603 -- trusted EE Ansible and private fixture.
                    [ANSIBLE, '-i', 'localhost,', '-c', 'local', str(play)],
                    env=os.environ | {'ANSIBLE_CONFIG': str(config), 'ANSIBLE_LOCAL_TEMP': str(root / 'local'),
                                      'ANSIBLE_REMOTE_TEMP': str(root / 'remote')},
                    capture_output=True, text=True, timeout=60, check=False,
                )
                self.assertEqual(outcome.returncode, expected, outcome.stdout + outcome.stderr)
                self.assertEqual(marker.exists(), managed)

    def test_missing_fragment_after_stop_still_requires_inactive_state(self):
        main = yaml.safe_load((ROOT / 'roles/podman_systemd/tasks/main.yml').read_text())
        task = next(t for t in main if t['name'] ==
                    'Require successful Podman kube service teardown before Quadlet removal')
        for load, active, result, expected in [
            ('not-found', 'active', 'success', 2),
            ('not-found', 'inactive', 'success', 0),
            ('not-found', 'inactive', 'exit-code', 2),
            ('not-found', 'inactive', None, 2),
            ('loaded', 'active', 'success', 2),
            ('loaded', 'inactive', 'exit-code', 2),
            ('loaded', 'inactive', None, 2),
            ('loaded', 'inactive', 'success', 0),
        ]:
            with self.subTest(load=load, active=active, result=result), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                play = root / 'play.yml'
                play.write_text(yaml.safe_dump([dict(
                    name='Post-stop state proof', hosts='localhost', gather_facts=False,
                    vars=dict(podman_systemd_action='absent',
                              podman_systemd_removal_load={'stdout': 'loaded'},
                              podman_systemd_removal_result={'stdout_lines': [
                                  'LoadState=' + load, 'ActiveState=' + active] +
                                  ([] if result is None else ['Result=' + result])}),
                    tasks=[task],
                )], sort_keys=False))
                config = root / 'ansible.cfg'
                config.write_text('[defaults]\nstdout_callback=default\n')
                outcome = subprocess.run(  # noqa: S603 -- trusted EE Ansible and private fixture.
                    [ANSIBLE, '-i', 'localhost,', '-c', 'local', str(play)],
                    env=os.environ | {'ANSIBLE_CONFIG': str(config), 'ANSIBLE_LOCAL_TEMP': str(root / 'local'),
                                      'ANSIBLE_REMOTE_TEMP': str(root / 'remote')},
                    capture_output=True, text=True, timeout=60, check=False,
                )
                self.assertEqual(outcome.returncode, expected, outcome.stdout + outcome.stderr)

    def test_tag_filtered_missing_manifest_fails_before_the_following_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / 'bin'
            binary.mkdir()
            bus = binary / 'busctl'
            bus.write_text(
                '#!/usr/bin/env python3\nimport json,sys\n'
                "if 'call' in sys.argv:\n"
                " value={'type':'o','data':['/org/freedesktop/systemd1/unit/fixture']}\n"
                'else:\n'
                " argv=(['/usr/bin/podman','kube','play','--log-driver=k8s-file',"
                "'--log-opt=path=/private/app.log'," + repr(str(root / 'missing.yml')) + "]\n"
                "       if sys.argv[-1]=='ExecStart' else [])\n"
                " value={'type':'a(sasbttttuii)','data':"
                "[['/usr/bin/podman',argv,False,0,0,0,0,0,0,0]] if argv else []}\n"
                'print(json.dumps(value))\n'
            )
            bus.chmod(0o700)
            main = yaml.safe_load((ROOT / 'roles/podman_systemd/tasks/main.yml').read_text())
            task = next(t for t in main if t['name'] == 'Validate the actual loaded native teardown configuration')
            include = task['ansible.builtin.include_tasks']
            target = str(ROOT / 'roles/podman_systemd/tasks/teardown_preflight.yml')
            if isinstance(include, str):
                task['ansible.builtin.include_tasks'] = target
            else:
                include['file'] = target
            marker = root / 'mutation'
            play = root / 'play.yml'
            play.write_text(yaml.safe_dump([dict(
                name='Tagged loaded teardown fixture', hosts='localhost', gather_facts=False,
                environment={'PATH': str(binary) + os.pathsep + os.environ['PATH']},
                vars=dict(podman_systemd_action='stopped', podman_systemd_scope='user',
                          podman_systemd_service_name='fixture.service',
                          podman_systemd_removal_load={'stdout': 'loaded'}),
                tasks=[task, {'name': 'Following service mutation', 'ansible.builtin.command':
                             {'argv': ['/usr/bin/touch', str(marker)]}, 'tags': 'podman_systemd'}],
            )], sort_keys=False))
            config = root / 'ansible.cfg'
            config.write_text('[defaults]\nstdout_callback=default\n')
            result = subprocess.run(  # noqa: S603 -- trusted EE Ansible and private generated fixture.
                [ANSIBLE, '-i', 'localhost,', '-c', 'local', '--tags', 'podman_systemd', str(play)],
                env=os.environ | {'ANSIBLE_CONFIG': str(config), 'ANSIBLE_LOCAL_TEMP': str(root / 'local'),
                                  'ANSIBLE_REMOTE_TEMP': str(root / 'remote')},
                capture_output=True, text=True, timeout=60, check=False,
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn('Require the loaded native teardown source before any service mutation', result.stdout)
            self.assertFalse(marker.exists())
