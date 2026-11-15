"""Run the shipped dynamic preflight with a real Ansible tag filter."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
ANSIBLE = shutil.which('ansible-playbook')


@unittest.skipUnless(ANSIBLE, 'requires the prescribed Ansible EE')
class TaggedTeardownTests(unittest.TestCase):
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
