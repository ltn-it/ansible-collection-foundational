"""Bind configured account metadata to the actual authenticated desktop user."""

import copy
import unittest

from plugins.module_utils import onepassword_boundary as boundary


ACCOUNT = "A" * 26
USER = "U" * 26
UNSET = object()


class DesktopIdentityTests(unittest.TestCase):
    def invoke(self, accounts=UNSET, user=UNSET):
        self.calls = []
        if accounts is UNSET:
            accounts = [{"account_uuid": ACCOUNT, "user_uuid": USER,
                         "url": "example.1password.com"}]
        if user is UNSET:
            user = {"id": USER}

        def metadata(arguments):
            self.calls.append(arguments)
            if arguments == ["account", "list", "--format", "json"]:
                return accounts
            if arguments == ["user", "get", "--me", "--account", ACCOUNT,
                             "--format", "json"]:
                return user
            # Reproduce desktop mode: whoami is not an authentication probe.
            raise AssertionError("Unexpected command, including unsupported whoami")

        return boundary.native_desktop_identity(metadata, ACCOUNT)

    def test_desktop_current_user_succeeds_without_whoami(self):
        self.assertEqual(self.invoke(), {"account_uuid": ACCOUNT, "user_uuid": USER,
                                       "url": "https://example.1password.com"})
        self.assertEqual(len(self.calls), 2)

    def test_https_case_and_single_trailing_slash_normalize(self):
        rows = [{"account_uuid": ACCOUNT, "user_uuid": USER,
                 "url": "https://EXAMPLE.1password.com/"}]
        self.assertEqual(self.invoke(rows)["url"], "https://example.1password.com")

    def test_other_registered_account_is_not_selected(self):
        rows = [{"account_uuid": "X" * 26, "user_uuid": "Y" * 26,
                 "url": "other.1password.com"},
                {"account_uuid": ACCOUNT, "user_uuid": USER,
                 "url": "example.1password.com"}]
        self.assertEqual(self.invoke(rows)["account_uuid"], ACCOUNT)

    def test_missing_duplicate_malformed_accounts_fail_before_current_user(self):
        good = {"account_uuid": ACCOUNT, "user_uuid": USER,
                "url": "example.1password.com"}
        cases = [None, [], {}, [None], [good, copy.deepcopy(good)],
                 [{**good, "account_uuid": "X" * 26}],
                 [{**good, "user_uuid": []}], [{**good, "user_uuid": "short"}]]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.invoke(rows)
            self.assertEqual(len(self.calls), 1)

    def test_unsafe_account_url_fails_before_current_user(self):
        for url in (None, [], "http://example.1password.com", "https://user@example.1password.com",
                    "example.1password.com/path", "example.1password.com:443",
                    "example.1password.com?query", " example.1password.com", "example.1password.com//"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.invoke([{"account_uuid": ACCOUNT, "user_uuid": USER, "url": url}])
            self.assertEqual(len(self.calls), 1)

    def test_authenticated_user_must_match_registered_user(self):
        for user in ({}, [], None, {"id": "X" * 26}, {"id": []}, {"id": "short"}):
            with self.subTest(user=user), self.assertRaises(ValueError):
                self.invoke(user=user)
            self.assertEqual(len(self.calls), 2)


if __name__ == "__main__":
    unittest.main()
