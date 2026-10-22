# Copyright: (c) 2026, Lightning IT
# SPDX-License-Identifier: MIT
"""Managed-side metadata or payload capture with autonomous scratch cleanup."""

import signal
from ansible.module_utils.basic import AnsibleModule
from ansible_collections.lit.foundational.plugins.module_utils.luks_header_snapshot import (
    SnapshotInterrupted,
    snapshot,
)

DOCUMENTATION = r"""
---
module: luks_header_snapshot
short_description: Capture a bounded LUKS2 header revision on the managed host
version_added: "1.38.0"
description:
  - Uses a protected tmpfs directory and removes it before returning any result.
  - Defaults to metadata only; no provider or controller plaintext is used.
  - Payload mode is for protected Ansible escrow memory and requires no_log at the caller.
options:
  device:
    type: path
    required: true
    description: Canonical installed block device below /dev.
  expected_uuid:
    type: str
    required: true
    description: Exact canonical LUKS UUID checked before and after capture.
  expected_sha256:
    type: str
    default: ""
    description: Optional exact planned header digest, checked before any payload transfer.
  temporary_root:
    type: path
    default: /run
    description: Existing canonical tmpfs directory owned by the effective user.
  include_payload:
    type: bool
    default: false
    description: Return protected base64 header bytes only for escrow capture.
  allow_regular_file_device:
    type: bool
    default: false
    description: Explicit test-only regular-file source opt-in.
  max_raw_bytes:
    type: int
    default: 20971520
    description: Positive raw byte ceiling, at most 20 MiB.
  cryptsetup_path:
    type: path
    default: /usr/sbin/cryptsetup
    description: Absolute trusted cryptsetup executable.
  timeout_seconds:
    type: int
    default: 30
    description: Command timeout from 1 to 60 seconds.
  expected_machine_id:
    type: str
    default: ""
    description: Optional exact source machine ID; day-2 planning requires it.
  machine_id_path:
    type: path
    default: /etc/machine-id
    description: Canonical installed source identity file.
author:
  - Lightning IT (@lightning-it)
"""
EXAMPLES = r"""
- name: Inspect a previously identified source without transferring header bytes
  lit.foundational.luks_header_snapshot:
    device: /dev/example
    expected_uuid: 11111111-2222-4333-8444-555555555555
    expected_machine_id: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
"""
RETURN = r"""
raw_sha256:
  type: str
  returned: success
  description: SHA-256 of the exact raw snapshot.
raw_size_bytes:
  type: int
  returned: success
  description: Verified bounded header size.
luks_uuid:
  type: str
  returned: success
  description: Verified source and snapshot UUID.
scratch_removed:
  type: bool
  returned: success
  description: True after all owned raw scratch has been removed.
luks_header_b64:
  type: str
  returned: only when include_payload=true
  description: Sensitive raw header, only for no_log escrow processing.
"""


def main():
    module = AnsibleModule(
        argument_spec=dict(
            device=dict(type="path", required=True), expected_uuid=dict(type="str", required=True),
            expected_sha256=dict(type="str", default=""),
            temporary_root=dict(type="path", default="/run"), include_payload=dict(type="bool", default=False),
            allow_regular_file_device=dict(type="bool", default=False), max_raw_bytes=dict(type="int", default=20971520),
            cryptsetup_path=dict(type="path", default="/usr/sbin/cryptsetup"), timeout_seconds=dict(type="int", default=30),
            expected_machine_id=dict(type="str", default=""), machine_id_path=dict(type="path", default="/etc/machine-id"),
        ), supports_check_mode=True,
    )
    if module.check_mode:
        module.exit_json(changed=False, skipped=True, msg="Snapshot requires normal bounded execution.")

    def interrupted(signum, frame):
        raise SnapshotInterrupted("Snapshot interrupted.")

    for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(signum, interrupted)
    try:
        result = snapshot(**module.params)
    except Exception:
        module.fail_json(msg="Bounded LUKS2 snapshot failed; no raw payload is disclosed.")
    module.exit_json(changed=False, **result)


if __name__ == "__main__":
    main()
