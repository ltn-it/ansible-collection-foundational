# Copyright: (c) 2026, Lightning IT
# SPDX-License-Identifier: MIT
"""Controller-only Ansible adapter for the shared native Password item boundary."""

from ansible.plugins.action import ActionBase
from ..module_utils.onepassword_secret_item import (
    _EXPECTED_ARGS,
    _OnePasswordCLI,
    _OnePasswordSecretItemStore,
    _fail,
    _normalize_arguments,
    _normalize_sign_in_address,
    execute_native,
)

DOCUMENTATION = r"""
---
module: onepassword_secret_item
short_description: Plan or create one exact 1Password Password item
version_added: "1.34.0"
description:
  - Validates one exact 1Password account, vault, item, and field on the Ansible controller.
  - Creates an absent Password item only through 1Password-internal password generation.
  - Never reads or returns the generated password; secret-consuming actions must use a dedicated descriptor-to-process
    boundary that does not expose the value to Ansible variables or facts.
  - Rejects service-account, Connect, and shell-session token environments so desktop CLI integration is explicit.
options:
  operation:
    description:
      - C(plan) performs metadata-only inspection.
      - C(apply) creates an absent item and returns its non-sensitive item ID without reading the password.
    type: str
    choices:
      - plan
      - apply
    required: true
  cli_path:
    description: Absolute path to the approved 1Password CLI binary.
    type: path
    required: true
  cli_sha256:
    description: Complete lowercase SHA-256 digest of the approved CLI executable.
    type: str
    required: true
  cli_version:
    description: Exact approved 1Password CLI version.
    type: str
    required: true
  account_id:
    description: Exact 1Password account ID.
    type: str
    required: true
  account_sign_in_address:
    description: Exact expected account sign-in address.
    type: str
    required: true
  authorized_user_uuids:
    description: Exact allowlist of 1Password operator user UUIDs.
    type: list
    elements: str
    required: true
  vault_id:
    description: Exact 1Password vault ID.
    type: str
    required: true
  item_id:
    description: Exact item ID; it must be empty for initial creation and pinned for later validation.
    type: str
    default: ""
  item_version:
    description:
      - Exact immutable 1Password item version.
      - Use C(0) only for discovery or initial creation, then pin the positive version returned by the action.
    type: int
    default: 0
  item_title:
    description: Exact unique item title within the selected vault.
    type: str
    required: true
  field_id:
    description: Built-in Password item field ID.
    type: str
    default: password
  category:
    description: Exact item category.
    type: str
    choices:
      - Password
    default: Password
  tags:
    description: Exact non-sensitive item tags, each containing at most 64 safe characters.
    type: list
    elements: str
    required: true
  subject:
    description: Exact non-sensitive subject recorded in the item.
    type: str
    required: true
  schema_version:
    description: Exact schema version recorded in the item.
    type: int
    default: 1
  password_recipe:
    description: Exact 1Password internal-generation recipe.
    type: str
    required: true
  password_length:
    description: Exact expected password length.
    type: int
    required: true
  allow_create:
    description: Explicitly permit creation during C(apply).
    type: bool
    default: false
  approval_authority:
    description:
      - Independently configured Approval Authority for C(apply).
      - Pins one Ed25519 signer, the allowed-signers file, and the C(ssh-keygen) verifier by full SHA-256 digest.
      - The fixed signature namespace is C(lit-onepassword-approval-v1).
      - Pins one canonical controller-only replay directory that C(approval.replay_directory) must match exactly.
    type: dict
    default: {}
  approval:
    description:
      - Expiring, signed, one-time approval for C(apply).
      - The signature covers the authority, execution ID, repository commits, operation, target, and complete
        normalized non-secret action contract.
    type: dict
    default: {}
attributes:
  action:
    description: The action executes entirely on the controller.
    support: full
  check_mode:
    description: C(apply) is reduced to metadata-only planning; no item is created.
    support: full
  connection:
    description: No managed-host connection is used.
    support: none
  diff_mode:
    description: Secret material and item content are never returned as diff data.
    support: none
notes:
  - C(plan) and C(apply) return non-sensitive identity metadata only.
  - The action does not update, rotate, archive, or delete an existing item.
  - Creation has no cross-controller transaction primitive. Use one serialized controller and pin the returned item
    ID and positive item version before any secret-consuming operation.
  - The controller must already have an unlocked 1Password desktop CLI integration for the exact account.
author:
  - Lightning IT (@lightning-it)
"""

EXAMPLES = r"""
---
- name: Plan one independently escrowed recovery item
  lit.foundational.onepassword_secret_item:
    operation: plan
    cli_path: /usr/local/bin/op
    cli_sha256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    cli_version: 2.38.1
    account_id: AAAAAAAAAAAAAAAAAAAAAAAAAA
    account_sign_in_address: example.1password.com
    authorized_user_uuids: [UUUUUUUUUUUUUUUUUUUUUUUUUU]
    vault_id: vvvvvvvvvvvvvvvvvvvvvvvvvv
    item_id: ""
    item_title: host01.example.test LUKS recovery
    field_id: password
    category: Password
    tags:
      - recovery
    subject: host01.example.test
    schema_version: 1
    password_recipe: letters,digits,symbols,64
    password_length: 64
"""

RETURN = r"""
created:
  description: Whether C(apply) created the absent item.
  returned: always
  type: bool
exists:
  description: Whether the exact item exists after the operation.
  returned: always
  type: bool
item_id:
  description: Exact non-sensitive item ID, or null when absent during C(plan).
  returned: always
  type: str
item_version:
  description: Exact non-sensitive item version, or null when absent during C(plan).
  returned: always
  type: int
planned:
  description: Whether creation remains pending after metadata-only planning.
  returned: always
  type: bool
operator_user_uuid:
  description: Allowlisted 1Password operator observed during validation.
  returned: always
  type: str
"""


class ActionModule(ActionBase):
    """Ansible controller-only action-plugin entry point."""

    TRANSFERS_FILES = False
    _requires_connection = False
    _supports_check_mode = True
    _VALID_ARGS = _EXPECTED_ARGS

    def run(self, tmp=None, task_vars=None):
        if task_vars is None:
            task_vars = {}
        self._task.no_log = True
        super(ActionModule, self).run(tmp, task_vars)
        return execute_native(
            dict(self._task.args), check_mode=bool(self._task.check_mode)
        )
