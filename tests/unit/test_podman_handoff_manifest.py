"""Exercise the shipped original-source inspection with real manifest files in the EE."""

import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
ANSIBLE = shutil.which('ansible-playbook')


@unittest.skipUnless(ANSIBLE, 'requires the prescribed Ansible EE')
class HandoffManifestTests(unittest.TestCase):
    def test_unsupported_manifests_fail_before_a_following_mutation(self):
        observer = subprocess.Popen([sys.executable, '-c', 'import signal; signal.pause()'])  # noqa: S603 -- isolated EE process identity fixture.
        self.addCleanup(observer.wait, timeout=10)
        self.addCleanup(observer.terminate)
        for label, kind, applications, initializers, accepted in [
            ('single', 'Pod', 1, 0, True),
            ('multiple', 'Pod', 2, 0, False),
            ('initializer', 'Pod', 1, 1, False),
            ('other-kind', 'List', 1, 0, False),
        ]:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                cid, unit = 'a' * 64, 'application'
                graph, stage = root / 'graph', root / 'stage'
                source = graph / 'overlay-containers' / cid / 'userdata/ctr.log'
                source.parent.mkdir(parents=True)
                stage.mkdir(mode=0o700)
                source.write_text('original log\n')
                source.chmod(0o600)
                target, manifest, quadlet = root / 'application.log', root / 'pod.yml', root / 'original.kube'
                target.write_text('')
                target.chmod(0o600)
                value = dict(apiVersion='v1', kind=kind, metadata=dict(name='application'), spec=dict(
                    containers=[dict(name='app' + str(i), image='example.invalid/fixture:1')
                                for i in range(applications)],
                    initContainers=[dict(name='init' + str(i), image='example.invalid/fixture:1')
                                    for i in range(initializers)],
                ))
                manifest.write_text(yaml.safe_dump(value))
                quadlet.write_text('# synthetic original definition\n')
                tasks = yaml.safe_load((ROOT / 'roles/podman_systemd/tasks/log_handoff/query.yml').read_text())
                # Stub only the external Podman response. Every shipped file/hash/shape assertion is retained.
                tasks[0]['ansible.builtin.command']['argv'] = [sys.executable, '-c',
                    'print(' + repr(' '.join([cid, 'true', str(observer.pid), str(source), unit + '.service'])) + ')']
                for task in tasks:
                    include = task.get('ansible.builtin.import_tasks')
                    if include:
                        task['ansible.builtin.import_tasks'] = str(
                            (ROOT / 'roles/podman_systemd/tasks/log_handoff' / include).resolve())
                    if task.get('ansible.builtin.include_tasks') == 'live_pod.yml':
                        # Native-engine membership is exercised separately. Keep
                        # this test focused on the original manifest/file guards.
                        live = root / 'live_pod.yml'
                        live.write_text(yaml.safe_dump([dict(name='Synthetic external Pod metadata',
                            **{'ansible.builtin.command': dict(argv=[sys.executable, '-c',
                                'print(' + repr(json.dumps(dict(pod_id='b' * 64, pod_name='application',
                                                               infra_id='c' * 64))) + ')']),
                               'register': 'podman_systemd_h_live_pod', 'changed_when': False})]))
                        task['ansible.builtin.include_tasks'] = str(live)
                inspected = root / 'query.yml'
                inspected.write_text(yaml.safe_dump(tasks, sort_keys=False))
                marker = root / 'following-mutation'
                variables = dict(
                    podman_systemd_h_graph=str(graph), podman_systemd_h_stage=str(stage),
                    podman_systemd_h_name='application', podman_systemd_h_saved={},
                    podman_systemd_h_home=str(root), podman_systemd_h_unit_dir=str(root),
                    podman_systemd_h_python=dict(ansible_facts=dict(ansible_python=dict(executable=sys.executable))),
                    podman_systemd_log_handoff_profile=dict(
                        runtime_uid=os.geteuid(), runtime_user=pwd.getpwuid(os.geteuid()).pw_name),
                    podman_systemd_h_spec=dict(container='application-app0', unit=unit, manifest=str(manifest),
                                              manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                                              quadlet=str(quadlet), destination=str(target)),
                )
                play = root / 'play.yml'
                play.write_text(yaml.safe_dump([dict(name='Original source contract', hosts='localhost',
                    gather_facts=False, vars=variables, tasks=[
                        dict(name='Inspect the original source using shipped tasks',
                             **{'ansible.builtin.include_tasks': str(inspected)}),
                        dict(name='Following mutation',
                             **{'ansible.builtin.command': dict(argv=['/usr/bin/touch', str(marker)])}),
                    ])], sort_keys=False))
                config = root / 'ansible.cfg'
                config.write_text('[defaults]\nstdout_callback=default\n')
                outcome = subprocess.run(  # noqa: S603 -- trusted EE Ansible with isolated synthetic files.
                    [ANSIBLE, '-i', 'localhost,', '-c', 'local', str(play)],
                    env=os.environ | {'ANSIBLE_CONFIG': str(config), 'ANSIBLE_LOCAL_TEMP': str(root / 'local'),
                                      'ANSIBLE_REMOTE_TEMP': str(root / 'remote')},
                    capture_output=True, text=True, timeout=60, check=False,
                )
                self.assertEqual(outcome.returncode == 0, accepted, outcome.stdout + outcome.stderr)
                self.assertEqual(marker.exists(), accepted)


if __name__ == '__main__':
    unittest.main()
