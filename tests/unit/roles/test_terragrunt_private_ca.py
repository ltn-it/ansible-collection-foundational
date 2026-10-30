from pathlib import Path

from ansible.plugins.filter.core import combine
from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]


def test_terragrunt_private_ca_is_optional_and_used_everywhere():
    defaults = yaml.safe_load(
        (ROOT / "roles/terragrunt/defaults/main.yml").read_text(encoding="utf-8")
    )
    tasks = (ROOT / "roles/terragrunt/tasks/main.yml").read_text(encoding="utf-8")

    assert defaults["terragrunt_vault_ca_path"] == ""
    assert tasks.count("ca_path: \"{{ terragrunt_vault_ca_path | default(omit, true) }}\"") == 3


@pytest.mark.parametrize("optional_values", [None, "", "configured"])
def test_terragrunt_commands_only_receive_configured_vault_environment(optional_values):
    tasks = yaml.safe_load(
        (ROOT / "roles/terragrunt/tasks/main.yml").read_text(encoding="utf-8")
    )
    commands = [task for task in tasks if "ansible.builtin.command" in task]
    assert commands
    variables = {
        "terragrunt_http_username": "fixture-user",
        "terragrunt_http_password": "fixture-password",
        "omit": "__omit_place_holder_fixture__",
    }
    expected = {"TF_HTTP_USERNAME": "fixture-user", "TF_HTTP_PASSWORD": "fixture-password"}
    optional = {
        "terragrunt_vault_addr": ("VAULT_ADDR", "https://vault.example.test"),
        "terragrunt_vault_token": ("VAULT_TOKEN", "fixture-token"),
        "terragrunt_vault_ca_path": ("VAULT_CACERT", "/fixture/ca.pem"),
    }
    for variable, (name, value) in optional.items():
        if optional_values is not None:
            variables[variable] = value if optional_values == "configured" else ""
        if optional_values == "configured":
            expected[name] = value
    environment = NativeEnvironment(undefined=StrictUndefined)
    environment.filters["combine"] = combine
    for task in commands:
        template = task["environment"]
        if isinstance(template, dict):
            observed = {name: environment.from_string(value).render(variables)
                        for name, value in template.items()}
        else:
            observed = environment.from_string(template).render(variables)
        assert observed == expected, task["name"]


def test_terragrunt_import_accepts_guarded_extra_arguments():
    tasks = (ROOT / "roles/terragrunt/tasks/main.yml").read_text(encoding="utf-8")

    assert "item.extra_args | default([]) is sequence" in tasks
    assert "item.extra_args | default([]) is not string" in tasks
    assert "+ (item.extra_args | default([]))" in tasks
    assert "register: _terragrunt_import_result" in tasks
    assert "and _terragrunt_import_result.rc != 0" in tasks


def test_terragrunt_state_migrations_are_explicit_and_non_destructive():
    defaults = yaml.safe_load(
        (ROOT / "roles/terragrunt/defaults/main.yml").read_text(encoding="utf-8")
    )
    tasks = (ROOT / "roles/terragrunt/tasks/main.yml").read_text(encoding="utf-8")

    assert defaults["terragrunt_state_moves"] == []
    assert defaults["terragrunt_state_removals"] == []
    assert defaults["terragrunt_state_migration_strict"] is False
    assert "argv: [terragrunt, state, mv" in tasks
    assert "argv: [terragrunt, state, rm" in tasks
    assert "register: _terragrunt_state_move_result" in tasks
    assert "and _terragrunt_state_move_result.rc != 0" in tasks
    assert "register: _terragrunt_state_removal_result" in tasks
    assert "and _terragrunt_state_removal_result.rc != 0" in tasks
    assert "item.remote_resource_preserved | default(false) | bool" in tasks
    assert tasks.count("no_log: true") >= 6


def test_terragrunt_provider_lock_upgrade_is_explicitly_opt_in():
    defaults = yaml.safe_load(
        (ROOT / "roles/terragrunt/defaults/main.yml").read_text(encoding="utf-8")
    )
    tasks = (ROOT / "roles/terragrunt/tasks/main.yml").read_text(encoding="utf-8")

    assert defaults["terragrunt_init_upgrade"] is False
    assert "(['-upgrade'] if terragrunt_init_upgrade | bool else [])" in tasks
