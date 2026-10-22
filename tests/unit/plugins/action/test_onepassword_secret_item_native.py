"""Real isolated native caller; no Ansible installation or live provider required."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from plugins.module_utils import onepassword_secret_item as native
from tests.unit.plugins.action.test_onepassword_secret_item import (
    ACCOUNT_ID,
    ITEM_ID,
    SUBJECT,
    USER_UUID,
    VAULT_ID,
    _apply_arguments,
    _arguments,
)


@pytest.mark.parametrize("size", [1, 63, 64])
def test_complete_header_digest_is_a_safe_tag(size):
    assert native._normalize_arguments(_arguments(tags=["a" * size]))["tags"] == ["a" * size]


@pytest.mark.parametrize("tag", ["a" * 65, "a,b", "a\nb", "a b", "-unsafe", "unsafe/"])
def test_oversized_or_unsafe_tags_are_rejected(tag):
    with pytest.raises(native.AnsibleActionFail, match="tags must"):
        native._normalize_arguments(_arguments(tags=[tag]))


def _fake_cli(tmp_path, title, tags):
    state = tmp_path / "created"
    calls = tmp_path / "calls.jsonl"
    marker = "SYNTHETIC_CREATE_OUTPUT_MUST_NOT_ESCAPE"
    config = {
        "state": str(state), "calls": str(calls), "marker": marker,
        "account": ACCOUNT_ID, "user": USER_UUID, "vault": VAULT_ID,
        "item": ITEM_ID, "title": title, "tags": tags, "subject": SUBJECT,
    }
    cli = tmp_path / "synthetic-op"
    source = '''import json, os, pathlib, sys
c = CONFIG
a = sys.argv[1:]
with open(c['calls'], 'a') as f:
    f.write(json.dumps(a) + '\\n')
assert os.environ.get('OP_BIOMETRIC_UNLOCK_ENABLED') == 'true'
assert not any(k.startswith('OP_SESSION_') or k in ('OP_SERVICE_ACCOUNT_TOKEN', 'OP_CONNECT_TOKEN', 'OP_CONNECT_HOST') for k in os.environ)
if a == ['--version']:
    print('2.38.1')
elif a[0] == 'whoami':
    raise SystemExit(1)
elif a[:2] == ['account', 'list']:
    print(json.dumps([{'account_uuid': c['account'], 'user_uuid': c['user'], 'url': 'example.1password.com'}]))
elif a[:3] == ['user', 'get', '--me']:
    assert a[3:] == ['--account', c['account'], '--format', 'json']
    print(json.dumps({'id': c['user']}))
elif a[:2] == ['vault', 'get']:
    print(json.dumps({'id': c['vault']}))
elif a[:2] == ['item', 'list']:
    assert '--cache=false' in a
    print(json.dumps([{'id': c['item'], 'version': 1, 'title': c['title'], 'category': 'PASSWORD', 'tags': c['tags']}] if pathlib.Path(c['state']).exists() else []))
elif a[:2] == ['item', 'get']:
    assert '--cache=false' in a
    assert a[a.index('--fields')+1] == 'label=subject,label=schema_version,label=expected_length'
    print(json.dumps([{'label': 'subject', 'value': c['subject']}, {'label': 'schema_version', 'value': '1'}, {'label': 'expected_length', 'value': '64'}]))
elif a[:2] == ['item', 'create']:
    assert '--generate-password=letters,digits,symbols,64' in a
    assert a[a.index('--tags')+1] == ','.join(c['tags'])
    assert not pathlib.Path(c['state']).exists()
    pathlib.Path(c['state']).write_text('synthetic metadata only')
    print(c['marker'])
    print(c['marker'], file=sys.stderr)
else:
    raise SystemExit(77)
'''.replace("CONFIG", repr(config))
    cli.write_text("#!" + sys.executable + "\n" + source)
    cli.chmod(0o700)
    return cli, state, calls, marker


def _native_child(arguments):
    root = Path(__file__).resolve().parents[4]
    program = """import json,sys
sys.path.insert(0,sys.argv[1])
from plugins.module_utils.onepassword_secret_item import execute_native
assert not any(k == 'ansible' or k.startswith('ansible.') for k in sys.modules)
try:
    result = execute_native(json.load(sys.stdin))
except ValueError:
    print('native boundary rejected input', file=sys.stderr)
    raise SystemExit(1)
assert not any(k == 'ansible' or k.startswith('ansible.') for k in sys.modules)
print(json.dumps(result))
"""
    environment = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
    return subprocess.run(
        [sys.executable, "-I", "-S", "-c", program, str(root)],
        input=json.dumps(arguments).encode(), capture_output=True, timeout=60, env=environment,
    )


def test_native_signed_create_readback_pin_and_replay_without_ansible(tmp_path):
    header = "a" * 64
    title = SUBJECT + " LUKS Header Key " + header
    tags = ["luks-header-wrapping-key", header]
    cli, state, calls, marker = _fake_cli(tmp_path, title, tags)
    common = {
        "cli_path": str(cli), "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
        "item_title": title, "tags": tags,
    }
    planned = _native_child(_arguments(**common))
    assert planned.returncode == 0, planned.stderr
    assert json.loads(planned.stdout)["planned"] is True
    assert not state.exists()
    arguments, replay = _apply_arguments(tmp_path, **common)
    created = _native_child(arguments)
    assert created.returncode == 0, created.stderr
    result = json.loads(created.stdout)
    assert result["created"] is True and result["item_id"] == ITEM_ID and result["item_version"] == 1
    assert marker.encode() not in created.stdout + created.stderr
    assert len(list(replay.glob("*.used"))) == 1
    pinned = _native_child(_arguments(**common, item_id=ITEM_ID, item_version=1))
    assert pinned.returncode == 0, pinned.stderr
    assert json.loads(pinned.stdout)["changed"] is False
    assert marker.encode() not in pinned.stdout + pinned.stderr
    # Remove only synthetic state to test the consumed approval before another create.
    state.unlink()
    repeated = _native_child(arguments)
    assert repeated.returncode != 0 and not state.exists()
    commands = [json.loads(line) for line in calls.read_text().splitlines()]
    assert sum(command[:2] == ["item", "create"] for command in commands) == 1


def test_native_apply_rejects_missing_approval_before_cli(tmp_path):
    arguments = _arguments(operation="apply", allow_create=True)
    arguments["cli_path"] = str(tmp_path / "must-not-run")
    rejected = _native_child(arguments)
    assert rejected.returncode != 0
    assert rejected.stderr == b"native boundary rejected input\n"
