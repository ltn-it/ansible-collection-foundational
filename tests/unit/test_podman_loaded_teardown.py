"""Exercise the shipped loaded-service guard without changing the controller OS."""

import contextlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]


class LoadedTeardownTests(unittest.TestCase):
    def probe(self, *, missing=False, other_stop=False, no_stop=False, native=True,
              bad_signature=False, multiple=False, optimize=0):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        source = pathlib.Path(temporary.name) / 'pod.yml'
        if not missing:
            source.write_text('synthetic manifest\n')
        executable = '/usr/bin/podman' if native else '/usr/bin/sleep'
        start = [executable, 'kube', 'play', '--log-driver=k8s-file',
                 '--log-opt=path=/private/application.log', str(source)]
        stop = ['/usr/bin/podman', 'kube', 'down',
                str(source.with_name('different.yml')) if other_stop else str(source)]
        calls = []

        def row(binary, argv):
            return [binary, argv, False, 0, 0, 0, 0, 0, 0, 0]

        def bus(arguments, **_kwargs):
            self.assertEqual(arguments[:3], ['busctl', '--user', '--json=short'])
            if 'call' in arguments:
                value = {'type': 'o', 'data': ['/org/freedesktop/systemd1/unit/fixture_2eservice']}
            else:
                property_name = arguments[-1]
                calls.append(property_name)
                if property_name == 'ExecStart':
                    rows = [row(executable, start)] * (2 if multiple else 1)
                elif property_name == 'ExecStopPost' and not no_stop:
                    rows = [row('/usr/bin/podman', stop)]
                else:
                    rows = []
                value = {'type': 'invalid' if bad_signature else 'a(sasbttttuii)', 'data': rows}
            return subprocess.CompletedProcess(arguments, 0, json.dumps(value), '')

        tasks = yaml.safe_load((ROOT / 'roles/podman_systemd/tasks/teardown_preflight.yml').read_text())
        command = next(task['ansible.builtin.command'] for task in tasks if 'ansible.builtin.command' in task)
        program = command['argv'][2]
        output = io.StringIO()
        with mock.patch.object(sys, 'argv', ['fixture', 'user', 'fixture.service']), mock.patch.object(
            subprocess, 'run', side_effect=bus
        ), contextlib.redirect_stdout(output):
            exec(compile(program, 'packaged-loaded-guard', 'exec', optimize=optimize), {})  # noqa: S102 -- mocked OS calls.
        return json.loads(output.getvalue()), calls

    def test_accepts_matching_loaded_native_commands_and_readable_source(self):
        result, calls = self.probe()
        self.assertEqual(result, {'ok': True, 'native': True})
        self.assertEqual(calls, ['ExecStart', 'ExecStop', 'ExecStopPost'])

    def test_rejects_missing_actual_source(self):
        result, _ = self.probe(missing=True)
        self.assertFalse(result['ok'])

    def test_rejects_disagreeing_loaded_play_and_teardown_sources(self):
        result, _ = self.probe(other_stop=True)
        self.assertFalse(result['ok'])

    def test_rejects_native_service_without_a_loaded_down_command(self):
        result, _ = self.probe(no_stop=True)
        self.assertFalse(result['ok'])

    def test_non_native_service_needs_no_native_teardown_manifest(self):
        result, calls = self.probe(native=False, missing=True)
        self.assertEqual(result, {'ok': True, 'native': False})
        self.assertEqual(calls, ['ExecStart'])

    def test_unrecognized_bus_schema_fails_before_service_mutation(self):
        result, _ = self.probe(bad_signature=True)
        self.assertFalse(result['ok'])

    def test_ambiguous_multiple_native_starts_fail(self):
        result, _ = self.probe(multiple=True)
        self.assertFalse(result['ok'])

    def test_runtime_guards_survive_python_optimization(self):
        result, _ = self.probe(missing=True, optimize=2)
        self.assertFalse(result['ok'])


if __name__ == '__main__':
    unittest.main()
