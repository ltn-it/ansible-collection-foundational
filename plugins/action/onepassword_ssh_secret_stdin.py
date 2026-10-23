# Copyright: (c) 2026, Lightning IT
# SPDX-License-Identifier: MIT
"""Controller-only Ansible adapter for the shared signed SSH stdin boundary."""

from ansible.plugins.action import ActionBase
from ..module_utils.onepassword_ssh_secret_stdin import (
    _EXPECTED_ARGS,
    execute_native,
)

DOCUMENTATION = r"""
---
module: onepassword_ssh_secret_stdin
short_description: Stream one pinned 1Password secret into one pinned SSH session
version_added: "1.34.0"
description:
  - Validates exact Password and SSH Key items inside one exact 1Password account and vault.
  - Requires an externally pinned SSH-key fingerprint and an exact, protected SSH Agent socket.
  - Reads the Password value only inside the controller action and sends it directly to SSH standard input.
  - Never returns the secret to Ansible variables, facts, stdout, stderr, logs, or a plaintext file.
options:
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
  password_item_id:
    type: str
    required: true
  password_item_version:
    type: int
    required: true
  password_item_title:
    type: str
    required: true
  password_field_id:
    type: str
    default: password
  password_tags:
    type: list
    elements: str
    required: true
  password_length:
    type: int
    required: true
  ssh_item_id:
    type: str
    required: true
  ssh_item_version:
    type: int
    required: true
  ssh_item_title:
    type: str
    required: true
  ssh_tags:
    type: list
    elements: str
    required: true
  ssh_expected_fingerprint:
    type: str
    required: true
  subject:
    type: str
    required: true
  schema_version:
    type: int
    default: 1
  ssh_path:
    type: path
    required: true
  ssh_sha256:
    type: str
    required: true
  ssh_add_path:
    type: path
    required: true
  ssh_add_sha256:
    type: str
    required: true
  ssh_keygen_path:
    type: path
    required: true
  ssh_keygen_sha256:
    type: str
    required: true
  agent_socket_path:
    type: path
    required: true
  known_hosts_path:
    type: path
    required: true
  known_hosts_sha256:
    description: Complete lowercase SHA-256 digest of the exact known-hosts file.
    type: str
    required: true
  destination_host:
    type: str
    required: true
  destination_user:
    type: str
    default: root
  destination_port:
    type: int
    required: true
  destination_host_fingerprint:
    type: str
    required: true
  remote_command:
    type: str
    choices: [/bin/cryptroot-unlock]
    required: true
  approval_authority:
    description:
      - Independently configured Ed25519 Approval Authority.
      - Pins the exact signer, allowed-signers file, and C(ssh-keygen) verifier by full SHA-256 digest.
      - The fixed signature namespace is C(lit-onepassword-approval-v1).
      - Pins one canonical controller-only replay directory that C(approval.replay_directory) must match exactly.
    type: dict
    required: true
  approval:
    description:
      - Expiring asymmetric signature over the authority, execution ID, repository commits, operation, target, and
        complete normalized non-secret unlock contract.
      - Replay is claimed globally for the Authority, execution ID, and nonce, independent of target and payload.
    type: dict
    required: true
notes:
  - The action supports only SSH public-key authentication through the exact approved Agent socket.
  - The destination user is always C(root), and C(subject) must equal C(destination_host).
  - The protected known-hosts file must contain exactly one Ed25519 key for the exact host and port, matching the
    independently pinned host fingerprint.
  - The action always disables PTY allocation, executes C(/bin/cryptroot-unlock) explicitly, sends the passphrase
    without a newline, and closes SSH standard input. Debian cryptroot-unlock uses EOF-delimited C(cat) input in its
    non-interactive path.
  - Check mode validates item identities, public fingerprints, files, and Agent availability but does not read the
    password or open an SSH connection.
  - This action does not reboot, create, edit, rotate, export, archive, or delete any 1Password item.
  - The controller worker soft core-dump limit is set to zero before reading. The trusted operating system, kernel,
    process memory, swap configuration, approved executable owners, and the 1Password/SSH child processes remain
    explicit trust boundaries.
author:
  - Lightning IT (@lightning-it)
"""

EXAMPLES = r"""
---
- name: Unlock one encrypted host without exposing the passphrase to Ansible
  lit.foundational.onepassword_ssh_secret_stdin:
    cli_path: /usr/local/bin/op
    cli_sha256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    cli_version: 2.38.1
    account_id: AAAAAAAAAAAAAAAAAAAAAAAAAA
    account_sign_in_address: example.1password.com
    authorized_user_uuids: [UUUUUUUUUUUUUUUUUUUUUUUUUU]
    vault_id: vvvvvvvvvvvvvvvvvvvvvvvvvv
    password_item_id: pppppppppppppppppppppppppp
    password_item_version: 1
    password_item_title: host01.example.test LUKS recovery
    password_tags: [breakglass, recovery]
    password_length: 64
    ssh_item_id: iiiiiiiiiiiiiiiiiiiiiiiiii
    ssh_item_version: 1
    ssh_item_title: host01.example.test Dropbear recovery
    ssh_tags: [breakglass, recovery]
    ssh_expected_fingerprint: SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
    subject: host01.example.test
    ssh_path: /usr/bin/ssh
    ssh_sha256: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
    ssh_add_path: /usr/bin/ssh-add
    ssh_add_sha256: cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
    ssh_keygen_path: /usr/bin/ssh-keygen
    ssh_keygen_sha256: dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
    agent_socket_path: /absolute/path/to/1password/agent.sock
    known_hosts_path: /absolute/path/to/dropbear-known-hosts
    known_hosts_sha256: eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee
    destination_host: host01.example.test
    destination_port: 2222
    destination_host_fingerprint: SHA256:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB
    remote_command: /bin/cryptroot-unlock
    approval_authority:
      schema_version: 1
      identity: approval-authority@example.test
      namespace: lit-onepassword-approval-v1
      fingerprint: SHA256:CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC
      allowed_signers_path: /absolute/controller-only/approval_allowed_signers
      allowed_signers_sha256: ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
      ssh_keygen_path: /usr/bin/ssh-keygen
      ssh_keygen_sha256: dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
      replay_directory: /absolute/controller-only/approval-replay
    approval:
      schema_version: 1
      execution_id: unlock-20260809-001
      commit_shas:
        foundational: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
      nonce: cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      issued_at: "2026-08-09T10:00:00Z"
      expires_at: "2026-08-09T10:05:00Z"
      replay_directory: /absolute/controller-only/approval-replay
      signature: |
        -----BEGIN SSH SIGNATURE-----
        <base64-signature>
        -----END SSH SIGNATURE-----
"""

RETURN = r"""
unlocked:
  type: bool
  returned: always
  description: Whether the guarded SSH stdin operation completed successfully.
password_item_id:
  type: str
  returned: always
  description: Validated non-sensitive Password item ID.
password_item_version:
  type: int
  returned: always
  description: Validated non-sensitive Password item version.
ssh_item_id:
  type: str
  returned: always
  description: Validated non-sensitive SSH Key item ID.
ssh_item_version:
  type: int
  returned: always
  description: Validated non-sensitive SSH Key item version.
ssh_fingerprint:
  type: str
  returned: always
  description: Externally pinned and revalidated public-key fingerprint.
destination:
  type: str
  returned: always
  description: Non-sensitive SSH destination identity.
operator_user_uuid:
  type: str
  returned: always
  description: Allowlisted 1Password operator observed during validation.
core_dumps_disabled:
  type: bool
  returned: always
  description: Whether the controller worker soft core-dump limit was set to zero before secret retrieval.
"""


class ActionModule(ActionBase):
    """Controller-only exact-item SSH secret-consumer action."""

    TRANSFERS_FILES = False
    _requires_connection = False
    _supports_check_mode = True
    _VALID_ARGS = _EXPECTED_ARGS

    def run(self, tmp=None, task_vars=None):
        self._task.no_log = True
        super(ActionModule, self).run(tmp, task_vars or {})
        return execute_native(dict(self._task.args), check_mode=bool(self._task.check_mode))
