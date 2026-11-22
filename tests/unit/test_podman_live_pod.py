"""Run the shipped Pod-binding program against typed native-engine responses."""

import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar
import yaml

ROOT = Path(__file__).resolve().parents[2]
APP, POD, INFRA, OTHER = ('a' * 64, 'b' * 64, 'c' * 64, 'd' * 64)


class LivePodTests(unittest.TestCase):
    def invoke(self, *, pod=None, present=True, mode='live', expected=POD,
               expected_infra=INFRA, remaining=(), engine_error=False, name='app-pod'):
        if pod is None:
            pod = dict(Id=POD, Name='app-pod', InfraContainerID=INFRA,
                       Containers=[dict(Id=APP, State='running'), dict(Id=INFRA, State='running')])
        task = yaml.safe_load((ROOT / 'roles/podman_systemd/tasks/log_handoff/live_pod.yml').read_text())[0]
        values = dict(podman_systemd_h_pod_container=APP, podman_systemd_h_pod_name=name,
                      podman_systemd_h_pod_expected=expected, podman_systemd_h_infra_expected=expected_infra,
                      podman_systemd_h_pod_mode=mode, podman_systemd_h_python=dict(ansible_facts=dict(
                          ansible_python=dict(executable=sys.executable))))
        argv = Templar(loader=DataLoader(), variables=values).template(task['ansible.builtin.command']['argv'])
        calls = []

        def engine(args, **kwargs):
            calls.append(args)
            self.assertEqual(args[0], '/usr/bin/podman')
            if args[1:3] == ['container', 'exists']:
                return SimpleNamespace(returncode=125 if engine_error else int(not present), stdout='')
            if args[1] == 'inspect':
                self.assertEqual(args[2:], [APP, '--format', '{{.Pod}}'])
                return SimpleNamespace(returncode=0, stdout=POD)
            if args[1:3] == ['pod', 'inspect']:
                self.assertEqual(args[3:], [POD])
                return SimpleNamespace(returncode=0, stdout=json.dumps([pod]))
            if args[1:3] == ['pod', 'exists']:
                return SimpleNamespace(returncode=0 if args[3] in remaining else 1, stdout='')
            self.fail('Unexpected engine operation')

        output = io.StringIO()
        error = None
        try:
            with mock.patch.object(subprocess, 'run', side_effect=engine), \
                    mock.patch.object(sys, 'argv', ['shipped'] + argv[3:]), contextlib.redirect_stdout(output):
                exec(compile(argv[2], 'shipped-live-pod', 'exec'), {})  # noqa: S102 -- shipped code, mock engine.
        except RuntimeError as exc:
            error = str(exc)
        except SystemExit as exc:
            self.assertEqual(exc.code, 0)
        return error, json.loads(output.getvalue()) if output.getvalue() else None, calls

    def test_exact_application_with_optional_native_infrastructure_is_supported(self):
        for infra in [INFRA, '']:
            with self.subTest(infra=bool(infra)):
                pod = dict(Id=POD, Name='app-pod', InfraContainerID=infra,
                           Containers=[dict(Id=APP, State='running')])
                if infra:
                    pod['Containers'].append(dict(Id=infra, State='running'))
                error, value, _ = self.invoke(pod=pod, expected_infra=infra)
                self.assertIsNone(error)
                self.assertEqual(value, dict(absent=False, pod_id=POD, pod_name='app-pod', infra_id=infra))

    def test_unlisted_stopped_or_duplicate_members_are_rejected(self):
        base = dict(Id=POD, Name='app-pod', InfraContainerID=INFRA,
                    Containers=[dict(Id=APP, State='running'), dict(Id=INFRA, State='running')])
        for change in ['extra', 'stopped', 'duplicate', 'missing-application']:
            with self.subTest(change=change):
                pod = copy.deepcopy(base)
                if change == 'extra':
                    pod['Containers'].append(dict(Id=OTHER, State='running'))
                elif change == 'stopped':
                    pod['Containers'][1]['State'] = 'exited'
                elif change == 'duplicate':
                    pod['Containers'].append(dict(Id=APP, State='running'))
                else:
                    pod['Containers'][0]['Id'] = OTHER
                self.assertEqual(self.invoke(pod=pod)[0], 'UNSUPPORTED_LIVE_POD_MEMBERS')

    def test_original_pod_name_identity_and_infrastructure_cannot_drift(self):
        for expected, infra, name in [(OTHER, INFRA, 'app-pod'), (POD, OTHER, 'app-pod'),
                                       (POD, INFRA, 'foreign-pod')]:
            with self.subTest(expected=expected, infra=infra, name=name):
                self.assertIsNotNone(self.invoke(expected=expected, expected_infra=infra, name=name)[0])

    def test_resume_and_start_require_both_old_identity_and_name_to_be_absent(self):
        for mode in ['resume', 'absent']:
            with self.subTest(mode=mode):
                error, value, calls = self.invoke(present=False, mode=mode)
                self.assertIsNone(error)
                self.assertEqual(value, dict(absent=True))
                self.assertEqual([c[3] for c in calls if c[1:3] == ['pod', 'exists']], [POD, 'app-pod'])
                for remaining in [(POD,), ('app-pod',)]:
                    self.assertEqual(self.invoke(present=False, mode=mode, remaining=remaining)[0],
                                     'ORIGINAL_POD_STILL_EXISTS')
        self.assertEqual(self.invoke(present=True, mode='absent')[0], 'OLD_CONTAINER_STILL_PRESENT')
        self.assertEqual(self.invoke(present=False)[0], 'LIVE_CONTAINER_NOT_FOUND')

    def test_engine_failures_and_missing_identity_are_never_absence_proof(self):
        self.assertEqual(self.invoke(present=False, mode='resume', engine_error=True)[0], 'LIVE_POD_QUERY_FAILED')
        self.assertEqual(self.invoke(present=False, mode='resume', expected='')[0], 'MISSING_ORIGINAL_POD_BINDING')
        for name in ['app-pod\n', '-foreign', '../elsewhere']:
            with self.subTest(name=name):
                error, _, calls = self.invoke(name=name)
                self.assertEqual(error, 'INVALID_LIVE_POD_BINDING')
                self.assertEqual(calls, [])
