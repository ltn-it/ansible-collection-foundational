"""Shared native SSH APIs retain approval and no-secret check-mode boundaries."""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from ansible.errors import AnsibleActionFail
from ansible.plugins.action import ActionBase

from plugins.action import onepassword_ssh_key_item as key_action
from plugins.action import onepassword_ssh_secret_stdin as unlock_action
from plugins.module_utils import onepassword_ssh_key_item as key_native
from plugins.module_utils import onepassword_ssh_secret_stdin as unlock_native
from tests.unit.plugins.action.test_onepassword_ssh_secret_stdin import (
    _arguments,
    _write_valid_known_hosts,
)


def test_native_ssh_import_and_input_rejection_need_no_ansible_runtime():
    root = Path(__file__).resolve().parents[4]
    code = """import json,sys
sys.path.insert(0,sys.argv[1])
from plugins.module_utils import onepassword_ssh_key_item as key
from plugins.module_utils import onepassword_ssh_secret_stdin as unlock
assert not any(n == 'ansible' or n.startswith('ansible.') for n in sys.modules)
rejected = 0
for boundary in [key,unlock]:
    try:
        boundary.execute_native([],check_mode=True)
    except ValueError:
        rejected += 1
assert rejected == 2
assert not any(n == 'ansible' or n.startswith('ansible.') for n in sys.modules)
print(json.dumps({'no_ansible_runtime':True,'rejected_before_io':rejected}))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", code, str(root)],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"no_ansible_runtime": True, "rejected_before_io": 2}


@pytest.mark.parametrize("boundary", [key_native, unlock_native])
@pytest.mark.parametrize("mode", ["false", 0, 1, None, []])
def test_native_mode_is_a_boolean_before_any_normalization_or_io(boundary, mode):
    with pytest.raises(AnsibleActionFail, match="boolean check_mode"):
        boundary.execute_native({}, check_mode=mode)


def test_native_unlock_contract_mutation_fails_before_cli_or_secret_access(tmp_path, monkeypatch):
    _write_valid_known_hosts(tmp_path)
    arguments = _arguments(tmp_path)
    arguments["password_tags"] = ["different-approved-payload"]
    monkeypatch.setattr(
        unlock_native, "_inspect_boundaries",
        lambda *_unused: pytest.fail("mutated approval reached provider access"),
    )
    with pytest.raises(AnsibleActionFail):
        unlock_native.execute_native(arguments)


@pytest.mark.parametrize("adapter", [key_action, unlock_action])
def test_ansible_adapter_enforces_no_log_before_shared_boundary(adapter, monkeypatch):
    task = SimpleNamespace(args={"public_test_marker": "no-provider-data"}, check_mode=True, no_log=False)
    action = adapter.ActionModule.__new__(adapter.ActionModule)
    action._task = task
    monkeypatch.setattr(ActionBase, "run", lambda *_args, **_kwargs: {})
    result = {"changed": False}

    def native(arguments, *, check_mode):
        assert task.no_log is True
        assert arguments == task.args and check_mode is True
        return result

    monkeypatch.setattr(adapter, "execute_native", native)
    assert action.run() is result
