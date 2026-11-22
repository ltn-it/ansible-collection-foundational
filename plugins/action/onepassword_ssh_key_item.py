# Copyright: (c) 2026, Lightning IT
# SPDX-License-Identifier: MIT
"""Controller-only Ansible adapter for the shared native SSH Key boundary."""

from ansible.plugins.action import ActionBase
from ..module_utils.onepassword_ssh_key_item import (
    _EXPECTED_ARGS,
    _FINGERPRINT_PATTERN as _FINGERPRINT_PATTERN,
    _OnePasswordCLI as _OnePasswordCLI,
    _OnePasswordSSHKeyItemStore as _OnePasswordSSHKeyItemStore,
    _normalize_arguments as _normalize_arguments,
    _public_identity as _public_identity,
    _write_controller_file as _write_controller_file,
    execute_native,
)

DOCUMENTATION = r"""
---
module: onepassword_ssh_key_item
short_description: Plan, create, or inspect one exact 1Password SSH Key item
version_added: "1.34.0"
description:
  - Validates one exact 1Password account, vault, SSH Key item, and public identity on the Ansible controller.
  - Creates an absent Ed25519 item only through 1Password-internal SSH key generation.
  - Requests only public key, fingerprint, and non-sensitive contract fields from an existing item.
  - Never requests or returns a private key and provides no private-key export operation.
options:
  operation:
    type: str
    choices: [plan, apply, read_public, verify_agent]
    required: true
  cli_path:
    type: path
    required: true
  cli_sha256:
    type: str
    required: true
  cli_version:
    type: str
    required: true
  account_id:
    type: str
    required: true
  account_sign_in_address:
    type: str
    required: true
  authorized_user_uuids:
    type: list
    elements: str
    required: true
  vault_id:
    type: str
    required: true
  item_id:
    type: str
    default: ""
  item_version:
    description:
      - Exact immutable 1Password item version.
      - Use C(0) only for discovery or initial creation, then pin the positive version returned by the action.
    type: int
    default: 0
  item_title:
    type: str
    required: true
  category:
    type: str
    choices: [SSH Key]
    default: SSH Key
  tags:
    type: list
    elements: str
    required: true
  subject:
    type: str
    required: true
  schema_version:
    type: int
    default: 1
  key_type:
    type: str
    choices: [ed25519]
    default: ed25519
  expected_fingerprint:
    type: str
    default: ""
    description: Externally pinned SHA-256 fingerprint; required after initial discovery or creation.
  allow_create:
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
  ssh_add_path:
    type: path
    default: ""
  ssh_add_sha256:
    type: str
    default: ""
  ssh_keygen_path:
    type: path
    default: ""
  ssh_keygen_sha256:
    type: str
    default: ""
  agent_socket_path:
    type: path
    default: ""
notes:
  - Private-key use must occur through a separately verified 1Password SSH Agent boundary.
  - Public-key output is intentionally non-sensitive but remains pinned to the exact item contract.
  - The action does not update, rotate, archive, delete, or export an item.
author:
  - Lightning IT (@lightning-it)
"""

EXAMPLES = r"""
---
- name: Plan an absent externally escrowed Dropbear recovery key
  lit.foundational.onepassword_ssh_key_item:
    operation: plan
    cli_path: /usr/local/bin/op
    cli_version: 2.38.1
    account_id: AAAAAAAAAAAAAAAAAAAAAAAAAA
    account_sign_in_address: example.1password.com
    vault_id: vvvvvvvvvvvvvvvvvvvvvvvvvv
    item_title: host01.example.test Dropbear recovery
    tags: [breakglass, recovery]
    subject: host01.example.test
    key_type: ed25519
    cli_sha256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    authorized_user_uuids: [UUUUUUUUUUUUUUUUUUUUUUUUUU]
"""

RETURN = r"""
created:
  type: bool
  returned: always
  description: Whether apply created the absent item.
exists:
  type: bool
  returned: always
  description: Whether the exact SSH Key item exists.
item_id:
  type: str
  returned: always
  description: Exact non-sensitive item ID when present.
item_version:
  type: int
  returned: always
  description: Exact non-sensitive item version when present.
planned:
  type: bool
  returned: always
  description: Whether creation remains pending.
public_key:
  type: str
  returned: when the item exists
  description: Validated OpenSSH Ed25519 public key.
fingerprint:
  type: str
  returned: when the item exists
  description: Locally recomputed SHA-256 public-key fingerprint.
agent_verified:
  type: bool
  returned: when the item exists
  description:
    - Whether the exact key was uniquely available and completed a fresh signing challenge through the approved SSH
      Agent socket.
operator_user_uuid:
  type: str
  returned: always
  description: Allowlisted 1Password operator observed during validation.
"""


class ActionModule(ActionBase):
    """Ansible controller-only action-plugin entry point."""

    TRANSFERS_FILES = False
    _requires_connection = False
    _supports_check_mode = True
    _VALID_ARGS = _EXPECTED_ARGS

    def run(self, tmp=None, task_vars=None):
        self._task.no_log = True
        super(ActionModule, self).run(tmp, task_vars or {})
        return execute_native(dict(self._task.args), check_mode=bool(self._task.check_mode))
