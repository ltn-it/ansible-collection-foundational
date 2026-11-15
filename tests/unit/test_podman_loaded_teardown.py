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
              bad_signature=False, multiple=False, optimize=0, separate=False, ignored_stop=False,
              multiple_sources=False, trailing_flags=False, ignored_start=False, unsupported_flag=False,
              default_logging=False, wrapped_start=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        source = pathlib.Path(temporary.name) / 'pod.yml'
        if not missing:
            source.write_text('synthetic manifest\n')
        executable = '/usr/bin/podman' if native else '/usr/bin/sleep'
        start = [executable, 'kube', 'play', '--log-driver=k8s-file',
                 '--log-opt=path=/private/application.log', str(source)]
        if default_logging:
            start = [executable, 'kube', 'play', str(source)]
        if separate:
            start = [executable, 'kube', 'play', '--log-driver', 'k8s-file',
                     '--log-opt', 'path=/private/application.log', str(source)]
        stop = ['/usr/bin/podman', 'kube', 'down',
                str(source.with_name('different.yml')) if other_stop else str(source)]
        if multiple_sources:
            start.insert(-1, str(source.with_name('missing-first.yml')))
            stop.insert(-1, str(source.with_name('missing-first.yml')))
        if trailing_flags:
            start.append('--replace')
            stop.append('--force')
        if unsupported_flag:
            start.insert(3, '--unsupported-fixture')
        if wrapped_start:
            executable = '/usr/bin/env'
            start.insert(0, executable)
        calls = []

        def row(binary, argv):
            ignored = (ignored_stop and 'down' in argv) or (ignored_start and 'play' in argv)
            return [binary, argv, ignored, 0, 0, 0, 0, 0, 0, 0]

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

    def test_separate_native_options_still_require_the_loaded_manifest(self):
        result, _ = self.probe(separate=True, missing=True)
        self.assertFalse(result['ok'])

    def test_accepts_separate_native_options_with_a_readable_loaded_manifest(self):
        result, calls = self.probe(separate=True)
        self.assertEqual(result, {'ok': True, 'native': True})
        self.assertEqual(calls, ['ExecStart', 'ExecStop', 'ExecStopPost'])

    def test_rejects_disagreeing_loaded_play_and_teardown_sources(self):
        result, _ = self.probe(other_stop=True)
        self.assertFalse(result['ok'])

    def test_rejects_native_service_without_a_loaded_down_command(self):
        result, _ = self.probe(no_stop=True)
        self.assertFalse(result['ok'])

    def test_rejects_an_ignored_native_down_failure_before_teardown(self):
        result, _ = self.probe(ignored_stop=True)
        self.assertFalse(result['ok'])

    def test_rejects_multiple_loaded_sources_instead_of_checking_only_the_last_file(self):
        result, _ = self.probe(multiple_sources=True)
        self.assertFalse(result['ok'])

    def test_resolves_the_manifest_before_valid_trailing_boolean_options(self):
        result, _ = self.probe(trailing_flags=True)
        self.assertEqual(result, {'ok': True, 'native': True})

    def test_rejects_unrecognized_loaded_options_before_teardown(self):
        result, _ = self.probe(unsupported_flag=True)
        self.assertFalse(result['ok'])

    def test_rejects_an_ignored_native_start_failure(self):
        result, _ = self.probe(ignored_start=True)
        self.assertFalse(result['ok'])

    def test_default_logging_still_requires_the_actual_loaded_manifest(self):
        result, _ = self.probe(default_logging=True, missing=True)
        self.assertFalse(result['ok'])

    def test_default_logging_cannot_hide_an_ignored_native_down_failure(self):
        result, _ = self.probe(default_logging=True, ignored_stop=True)
        self.assertFalse(result['ok'])

    def test_default_logging_accepts_a_verified_loaded_native_source(self):
        result, _ = self.probe(default_logging=True)
        self.assertEqual(result, {'ok': True, 'native': True})

    def test_unrecognized_loaded_start_cannot_bypass_teardown_validation(self):
        result, calls = self.probe(native=False, missing=True)
        self.assertFalse(result['ok'])
        self.assertEqual(calls, ['ExecStart'])

    def test_wrapped_start_cannot_hide_a_missing_loaded_manifest(self):
        result, calls = self.probe(wrapped_start=True, missing=True)
        self.assertFalse(result['ok'])
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
