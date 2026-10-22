# Copyright: (c) 2026, Lightning IT
# SPDX-License-Identifier: MIT
"""Create-only primary KV2 custody for one revision-bound wrapping key.

Only metadata leaves the manager. Secret material is available solely through
the internal primary consumer boundary, never as an Ansible return value.
"""

import hashlib
import hmac
import re
import uuid

from .luks_header_custody import safe_path

KIND = "luks-header-wrapping-key"
REVISION = ("schema_version", "subject", "source_machine_id", "luks_uuid", "header_sha256")
CONTRACT = set(REVISION) | {"mount", "prefix", "onepassword_required", "onepassword"}
PINS = {"account_id", "user_uuid", "vault_id", "item_id", "item_version", "item_title"}
RECORD = set(REVISION) | {"kind", "vault_id", "password", "onepassword"}


def _pins(value, contract, *, pending=False):
    if not isinstance(value, dict) or set(value) != PINS:
        raise ValueError("Closed independent key pins are required.")
    for key in ("account_id", "user_uuid"):
        if not isinstance(value[key], str) or not re.fullmatch(r"[A-Z0-9]{26}", value[key]):
            raise ValueError("Invalid independent account identity.")
    if not isinstance(value["vault_id"], str) or not re.fullmatch(r"[a-z0-9]{26}", value["vault_id"]):
        raise ValueError("Invalid independent vault identity.")
    item, version = value["item_id"], value["item_version"]
    if not (pending and item == "" and type(version) is int and version == 0):
        if (
            not isinstance(item, str) or not re.fullmatch(r"[a-z0-9]{26}", item)
            or type(version) is not int or version < 1
        ):
            raise ValueError("Positive immutable independent item pins are required.")
    title = contract["subject"] + " LUKS Header Key " + contract["header_sha256"]
    if len(title) > 128 or value["item_title"] != title:
        raise ValueError("The independent key title must bind the exact revision.")
    return dict(value)


def validate_contract(contract):
    if (
        not isinstance(contract, dict) or set(contract) != CONTRACT
        or type(contract["schema_version"]) is not int or contract["schema_version"] != 1
        or type(contract["onepassword_required"]) is not bool
    ):
        raise ValueError("A closed revision-bound key custody contract is required.")
    subject = contract["subject"]
    if (
        not isinstance(subject, str) or not 1 <= len(subject) <= 253
        or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", x) for x in subject.split("."))
        or not isinstance(contract["source_machine_id"], str)
        or not re.fullmatch(r"[0-9a-f]{32}", contract["source_machine_id"])
        or not isinstance(contract["luks_uuid"], str)
        or str(uuid.UUID(contract["luks_uuid"])) != contract["luks_uuid"]
        or not isinstance(contract["header_sha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", contract["header_sha256"])
    ):
        raise ValueError("An exact source and raw-header revision are required.")
    mount = safe_path(contract["mount"])
    if "/" in mount:
        raise ValueError("One exact KV2 mount is required.")
    path = safe_path(safe_path(contract["prefix"]) + "/" + subject + "/" + contract["header_sha256"])
    if contract["onepassword_required"]:
        _pins(contract["onepassword"], contract, pending=True)
    elif contract["onepassword"] != {}:
        raise ValueError("HC-only custody must not carry a secondary provider.")
    return mount, path


def _key(value):
    if not isinstance(value, str) or len(value) != 64 or any(not 33 <= ord(x) <= 126 for x in value):
        raise ValueError("A dedicated bounded wrapping key is required.")
    return value


def _match_pins(observed, desired, *, pending=False):
    keys = PINS - ({"item_id", "item_version"} if pending and desired["item_id"] == "" else set())
    if any(observed[key] != desired[key] for key in keys):
        raise ValueError("Independent key identity conflicts with retained pins.")


def _validated_record(observed, contract, *, pending=False):
    if (
        not isinstance(observed, dict) or set(observed) != {"data", "version"}
        or type(observed["version"]) is not int or observed["version"] != 1
        or not isinstance(observed["data"], dict) or set(observed["data"]) != RECORD
    ):
        raise ValueError("Primary key custody is not one immutable live version.")
    record = observed["data"]
    if (
        record["kind"] != KIND or type(record["schema_version"]) is not int
        or any(record[key] != contract[key] for key in REVISION)
        or record["vault_id"] != "luks-header-" + contract["header_sha256"]
    ):
        raise ValueError("Primary key custody belongs to another source or revision.")
    _key(record["password"])
    if contract["onepassword_required"]:
        pins = _pins(record["onepassword"], contract)
        desired = _pins(contract["onepassword"], contract, pending=pending)
        _match_pins(pins, desired, pending=pending)
    elif record["onepassword"] != {}:
        raise ValueError("Primary key custody conflicts with HC-only policy.")
    return record


def _secondary(reader, pins, password):
    if not callable(reader):
        raise ValueError("Independent key readback is required before activation.")
    try:
        observed = reader(dict(pins))
    except Exception:
        raise ValueError("Independent key readback failed; inspect its outcome.") from None
    if not hmac.compare_digest(_key(observed).encode("ascii"), password.encode("ascii")):
        raise ValueError("Primary and independent wrapping keys conflict.")


def _receipt(contract, path, record=None, *, created=False, secondary_verified=False, reconciled=False):
    return {
        **{key: contract[key] for key in REVISION},
        "mount": contract["mount"], "path": path, "exists": record is not None,
        "created": created, "primary_verified": record is not None,
        "primary_version": 1 if record is not None else None,
        "key_sha256": hashlib.sha256(record["password"].encode("ascii")).hexdigest() if record else None,
        "onepassword": dict(record["onepassword"]) if record else dict(contract["onepassword"]),
        "secondary_required": contract["onepassword_required"],
        "secondary_verified": secondary_verified, "reconciled_unknown_write": reconciled,
    }


def manage_key(client, contract, *, operation="plan", allow_create=False,
               candidate_factory=None, secondary_reader=None):
    """Inspect HC first; generate lazily and CAS0-commit only verified new material.

    Callbacks are internal trusted integration points, not caller-provided code
    or Ansible task arguments. The native generator/reader retain their own
    signed creation and exact-item validation boundaries.
    """
    mount, path = validate_contract(contract)
    if operation not in ("plan", "apply", "verify") or type(allow_create) is not bool:
        raise ValueError("A bounded key custody operation is required.")
    if operation != "apply" and allow_create:
        raise ValueError("Read-only operations cannot permit creation.")
    observed = client.read(mount, path)
    if observed is not None:
        record = _validated_record(observed, contract, pending=operation == "plan")
        checked = False
        if operation != "plan" and contract["onepassword_required"]:
            _secondary(secondary_reader, record["onepassword"], record["password"])
            checked = True
        return _receipt(contract, path, record, secondary_verified=checked)
    if operation == "plan":
        return _receipt(contract, path)
    if operation != "apply" or not allow_create or not callable(candidate_factory):
        raise ValueError("Absent primary custody requires explicitly admitted creation.")
    if contract["onepassword_required"] and not callable(secondary_reader):
        raise ValueError("Independent key readback is required before creation.")
    try:
        candidate = candidate_factory()
    except Exception:
        raise ValueError("Key generation outcome requires inspection before retry.") from None
    if not isinstance(candidate, dict) or set(candidate) != {"password", "onepassword"}:
        raise ValueError("A closed internally generated key candidate is required.")
    password = _key(candidate["password"])
    pins = candidate["onepassword"]
    if contract["onepassword_required"]:
        pins = _pins(pins, contract)
        _match_pins(pins, contract["onepassword"], pending=True)
        _secondary(secondary_reader, pins, password)
    elif pins != {}:
        raise ValueError("HC-only creation cannot introduce a secondary backend.")
    record = {
        **{key: contract[key] for key in REVISION}, "kind": KIND,
        "vault_id": "luks-header-" + contract["header_sha256"],
        "password": password, "onepassword": dict(pins),
    }
    if client.read(mount, path) is not None:
        raise ValueError("Primary custody changed during admission; inspect before retry.")
    reconciled = False
    try:
        client.create(mount, path, record)
    except Exception:
        # One readback may reconcile a lost response. Never retry a write.
        reconciled = True
    observed = client.read(mount, path)
    if observed is None:
        raise ValueError("Primary creation is unverified; inspect before retry.")
    pinned = {**contract, "onepassword": dict(pins)}
    verified = _validated_record(observed, pinned)
    if verified != record:
        raise ValueError("Primary creation readback conflicts; no overwrite is allowed.")
    checked = False
    if contract["onepassword_required"]:
        _secondary(secondary_reader, pins, password)
        checked = True
    return _receipt(contract, path, verified, created=None if reconciled else True,
                    secondary_verified=checked, reconciled=reconciled)


class _PrimaryKey:
    """Internal non-serializable holder; callers must never return it as a fact."""

    def __init__(self, record):
        self._password = record["password"].encode("ascii")

    def __repr__(self):
        return "<primary wrapping key: redacted>"

    __str__ = __repr__

    def __reduce_ex__(self, protocol):
        raise TypeError("Internal wrapping keys cannot be serialized.")

    def _bytes(self):
        if self._password is None:
            raise ValueError("The internal key lifetime has ended.")
        return self._password

    def close(self):
        self._password = None


def _load_primary_key(client, contract):
    """Fixed consumer integration only; public operations never call this API."""
    mount, path = validate_contract(contract)
    observed = client.read(mount, path)
    if observed is None:
        raise ValueError("Primary wrapping key is absent.")
    return _PrimaryKey(_validated_record(observed, contract))
