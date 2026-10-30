"""Primary-first key admission, immutable records and metadata-only public output."""

import copy
import json
import pickle
import unittest

from plugins.module_utils.luks_header_key_custody import (
    _load_primary_key,
    manage_key,
    validate_contract,
)

PASSWORD = "SYNTHETIC_WRAPPING_KEY_ONLY_" + "a" * 36
assert len(PASSWORD) == 64
OTHER = "SYNTHETIC_DIFFERENT_KEY_ONLY_" + "b" * 35
assert len(OTHER) == 64


def contract(secondary=True, pending=False):
    value = {"schema_version": 1, "subject": "source.example.test", "source_machine_id": "a" * 32,
             "luks_uuid": "11111111-2222-4333-8444-555555555555", "header_sha256": "c" * 64,
             "mount": "fixture-kv", "prefix": "fixtures/header-key-v1",
             "onepassword_required": secondary, "onepassword": {}}
    if secondary:
        value["onepassword"] = {"account_id": "A" * 26, "user_uuid": "B" * 26, "vault_id": "v" * 26,
                                "item_id": "" if pending else "i" * 26, "item_version": 0 if pending else 1,
                                "item_title": value["subject"] + " LUKS Header Key " + value["header_sha256"]}
    return value


class MemoryKV:
    def __init__(self):
        self.stored = None
        self.calls = []
        self.lose_response = False
        self.drop_write = False

    def read(self, mount, path):
        self.calls.append(("read", mount, path))
        return copy.deepcopy(self.stored)

    def create(self, mount, path, record):
        self.calls.append(("create", mount, path))
        if self.stored is not None:
            raise ValueError("synthetic CAS conflict")
        if not self.drop_write:
            self.stored = {"version": 1, "data": copy.deepcopy(record)}
        if self.lose_response:
            raise ValueError("synthetic response lost")


class KeyCustodyTests(unittest.TestCase):
    def setUp(self):
        self.client = MemoryKV()
        self.generated = 0
        self.reads = 0

    def factory(self):
        self.assertIsNone(self.client.stored)
        self.assertEqual(self.client.calls[0][0], "read")
        self.generated += 1
        return {"password": PASSWORD, "onepassword": contract()["onepassword"]}

    def secondary(self, pins):
        self.assertEqual(pins, contract()["onepassword"])
        self.reads += 1
        return PASSWORD

    def apply(self, **overrides):
        options = {"operation": "apply", "allow_create": True, "candidate_factory": self.factory,
                   "secondary_reader": self.secondary}
        options.update(overrides)
        return manage_key(self.client, contract(pending=True), **options)

    def test_missing_plan_never_generates_or_reads_secondary(self):
        result = manage_key(self.client, contract(pending=True), candidate_factory=self.factory,
                            secondary_reader=self.secondary)
        self.assertFalse(result["exists"])
        self.assertFalse(result["primary_verified"])
        self.assertEqual((self.generated, self.reads), (0, 0))
        self.assertEqual(len(self.client.calls), 1)

    def test_create_primary_readback_and_independent_copy_without_secret_output(self):
        result = self.apply()
        self.assertEqual((self.generated, self.reads), (1, 2))
        self.assertTrue(result["created"] and result["primary_verified"] and result["secondary_verified"])
        self.assertEqual(set(result), {
            "schema_version", "subject", "source_machine_id", "luks_uuid", "header_sha256",
            "mount", "path", "exists", "created", "primary_verified", "primary_version",
            "onepassword", "secondary_required", "secondary_verified", "reconciled_unknown_write",
        })
        self.assertNotIn("key_sha256", result)
        self.assertEqual(result["onepassword"], contract()["onepassword"])
        self.assertNotIn(PASSWORD, json.dumps(result))
        self.assertEqual([x[0] for x in self.client.calls], ["read", "read", "create", "read"])

    def test_matching_repeat_uses_primary_without_regeneration_or_write(self):
        self.apply()
        before = copy.deepcopy(self.client.stored)
        self.client.calls.clear()
        result = manage_key(self.client, contract(), operation="apply", allow_create=True,
                            candidate_factory=lambda: self.fail("must not regenerate"), secondary_reader=self.secondary)
        self.assertFalse(result["created"])
        self.assertTrue(result["secondary_verified"])
        self.assertEqual(self.client.stored, before)
        self.assertEqual([x[0] for x in self.client.calls], ["read"])

    def test_existing_plan_returns_positive_pins_but_no_secondary_acceptance(self):
        self.apply()
        result = manage_key(self.client, contract(pending=True))
        self.assertEqual(result["onepassword"]["item_version"], 1)
        self.assertFalse(result["secondary_verified"])
        self.assertNotIn(PASSWORD, json.dumps(result))

    def test_consumption_requires_pins_but_not_an_awake_desktop(self):
        self.apply()
        with self.assertRaises(ValueError):
            _load_primary_key(self.client, contract(pending=True))
        handle = _load_primary_key(self.client, contract())
        self.assertEqual(handle._bytes(), PASSWORD.encode())
        self.assertNotIn(PASSWORD, repr(handle))
        with self.assertRaises(TypeError):
            json.dumps(handle)
        with self.assertRaises(TypeError):
            pickle.dumps(handle)
        handle.close()
        with self.assertRaises(ValueError):
            handle._bytes()

    def test_missing_verify_and_unadmitted_creation_do_not_generate(self):
        for values in ({"operation": "verify"}, {"operation": "apply"},
                       {"operation": "apply", "allow_create": True}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                manage_key(self.client, contract(), **values)
        self.assertIsNone(self.client.stored)

    def test_missing_secondary_reader_prevents_even_candidate_creation(self):
        with self.assertRaises(ValueError):
            self.apply(secondary_reader=None)
        self.assertEqual(self.generated, 0)

    def test_wrong_secondary_before_primary_commit_leaves_primary_absent(self):
        with self.assertRaisesRegex(ValueError, "keys conflict"):
            self.apply(secondary_reader=lambda pins: OTHER)
        self.assertIsNone(self.client.stored)
        self.assertFalse(any(x[0] == "create" for x in self.client.calls))

    def test_wrong_secondary_after_commit_does_not_claim_success_or_overwrite(self):
        calls = 0

        def changed(pins):
            nonlocal calls
            calls += 1
            return PASSWORD if calls == 1 else OTHER

        with self.assertRaisesRegex(ValueError, "keys conflict"):
            self.apply(secondary_reader=changed)
        self.assertIsNotNone(self.client.stored)
        self.assertEqual(sum(x[0] == "create" for x in self.client.calls), 1)

    def test_changed_source_revision_backend_or_pins_rejects_before_write(self):
        self.apply()
        cases = [{"subject": "other.example.test"}, {"source_machine_id": "b" * 32},
                 {"luks_uuid": "22222222-2222-4333-8444-555555555555"}, {"header_sha256": "d" * 64},
                 {"onepassword_required": False, "onepassword": {}},
                 {"onepassword": {**contract()["onepassword"], "item_id": "j" * 26}}]
        original = copy.deepcopy(self.client.stored)
        for changes in cases:
            self.client.calls.clear()
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                manage_key(self.client, {**contract(), **changes}, operation="verify", secondary_reader=self.secondary)
            self.assertFalse(any(x[0] == "create" for x in self.client.calls))
            self.assertEqual(self.client.stored, original)

    def test_nonfirst_version_and_malformed_record_never_regenerate(self):
        self.apply()
        original = copy.deepcopy(self.client.stored)
        for mutation in (lambda x: x.update(version=2), lambda x: x["data"].update(extra="bad"),
                         lambda x: x["data"].update(password="short"),
                         lambda x: x["data"].update(kind="disk-unlock")):
            self.client.stored = copy.deepcopy(original)
            mutation(self.client.stored)
            with self.assertRaises(ValueError):
                manage_key(self.client, contract(), operation="apply", allow_create=True,
                           candidate_factory=lambda: self.fail("must not regenerate"), secondary_reader=self.secondary)

    def test_lost_response_reconciles_exact_readback_without_retry_or_false_attribution(self):
        self.client.lose_response = True
        result = self.apply()
        self.assertTrue(result["reconciled_unknown_write"])
        self.assertIsNone(result["created"])
        self.assertTrue(result["primary_verified"] and result["secondary_verified"])
        self.assertEqual(sum(x[0] == "create" for x in self.client.calls), 1)

    def test_unknown_uncommitted_write_is_not_retried(self):
        self.client.lose_response = self.client.drop_write = True
        with self.assertRaisesRegex(ValueError, "creation is unverified"):
            self.apply()
        self.assertEqual(sum(x[0] == "create" for x in self.client.calls), 1)

    def test_race_during_generation_refuses_primary_overwrite(self):
        def racing():
            candidate = self.factory()
            self.client.stored = {"version": 1, "data": {"unrelated": True}}
            return candidate

        with self.assertRaisesRegex(ValueError, "changed during admission"):
            self.apply(candidate_factory=racing)
        self.assertFalse(any(x[0] == "create" for x in self.client.calls))

    def test_hc_only_policy_needs_no_native_provider(self):
        key = contract(secondary=False)
        result = manage_key(self.client, key, operation="apply", allow_create=True,
                            candidate_factory=lambda: {"password": PASSWORD, "onepassword": {}})
        self.assertFalse(result["secondary_required"] or result["secondary_verified"])
        handle = _load_primary_key(self.client, key)
        self.assertEqual(handle._bytes(), PASSWORD.encode())
        handle.close()

    def test_generator_failure_does_not_leak_error_material_or_write_primary(self):
        def failed():
            raise ValueError(PASSWORD)

        with self.assertRaisesRegex(ValueError, "generation outcome requires inspection") as error:
            self.apply(candidate_factory=failed)
        self.assertNotIn(PASSWORD, str(error.exception))
        self.assertFalse(any(x[0] == "create" for x in self.client.calls))

    def test_invalid_candidate_and_secondary_pin_mutation_never_commit(self):
        candidates = [{"password": "short", "onepassword": contract()["onepassword"]},
                      {"password": PASSWORD, "onepassword": {}},
                      {"password": PASSWORD, "onepassword": {**contract()["onepassword"], "item_version": True}},
                      {"password": PASSWORD, "onepassword": {**contract()["onepassword"], "vault_id": "q" * 26}},
                      {"password": PASSWORD, "onepassword": contract()["onepassword"], "root_token": "forbidden"}]
        for value in candidates:
            with self.subTest(candidate_fields=set(value)), self.assertRaises(ValueError):
                self.apply(candidate_factory=lambda: value)
        self.assertIsNone(self.client.stored)

    def test_readonly_modes_reject_create_authority_before_provider_reads(self):
        for operation in ("plan", "verify", "delete", "rotate"):
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                manage_key(self.client, contract(), operation=operation, allow_create=True)
        self.assertEqual(self.client.calls, [])

    def test_invalid_closed_contracts_fail_before_provider_calls(self):
        for change in ({"extra": True}, {"schema_version": True}, {"mount": "a/b"},
                       {"prefix": "../escape"}, {"subject": "a..b"}, {"header_sha256": "x"},
                       {"onepassword_required": "true"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                manage_key(self.client, {**contract(), **change})
        self.assertEqual(self.client.calls, [])


if __name__ == "__main__":
    unittest.main()
