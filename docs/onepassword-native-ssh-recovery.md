# Native desktop SSH recovery APIs

Ansible actions and attested native desktop callers use the same implementations:

| Native API | Purpose |
| --- | --- |
| `plugins.module_utils.onepassword_ssh_key_item.execute_native` | Validate, inspect or explicitly create one exact SSH Key item under the existing action contract. |
| `plugins.module_utils.onepassword_ssh_secret_stdin.execute_native` | Submit one exact independently held recovery password to the pinned SSH cryptroot-unlock session. |

Both entry points accept an argument dictionary and keyword-only boolean
`check_mode=False`. Their parameters and returned public metadata are the same
as the corresponding action. The native Python import uses only the standard
library; an Ansible installation is not required on the desktop.

## Caller prerequisites

The trusted caller must admit its native executor and freshly installed
collection package before loading the API. Verify the complete package manifest,
actual load path and declared collection version. Use the approved native
1Password CLI, exact executable hashes, account, operator allowlist and item
versions. Retain the existing independently configured approval authority and
protected replay directory. This API supplies no execution authorization and
creates no authority, desktop session, SSH bridge or daemon.

The SSH Key client explicitly selects the native desktop biometric backend,
matching the Password client. An inherited manual-mode toggle cannot change
this choice; session, service-account and Connect authentication remain forbidden.

Load the module from the verified installation, then call the shared entry:

```python
from plugins.module_utils.onepassword_ssh_secret_stdin import execute_native

# approved_arguments contains the complete existing signed action contract.
public_receipt = execute_native(approved_arguments, check_mode=True)
```

The example assumes the verified collection root is already on the isolated
caller's import path. Do not load a development checkout for operational use.
Run collection validation, package builds and Ansible tasks in their prescribed
execution environments; the native caller exists for desktop-bound 1Password
and SSH Agent access.

## Unchanged unlock contract

The consumer requires exact Password and SSH Key item IDs and positive versions,
an independently pinned SSH public fingerprint, the approved private Agent
socket, one exact host/port and Ed25519 known-host entry, and a valid expiring
signature over the normalized contract. The destination is `root`, the subject
must match the destination host, and the only command is
`/bin/cryptroot-unlock`. The API exposes no arbitrary command, proxy option,
private-key export, item edit, rotation or deletion.

An optional `destination_address` selects one canonical unicast IPv4 routing
address. When provided it is part of the signed destination binding. SSH uses
that literal address while using the validated known-host host-and-port token
as its exact host-key alias: `[host]:port` for nondefault ports and the bare
host for port22. This preserves the independently pinned Ed25519 key and port.
The caller must
separately admit any required private transport; the consumer creates no tunnel
and forwards no Agent. Empty or omitted address preserves the original arguments,
receipt and signed binding. Hostnames, IPv6, unspecified, multicast, broadcast
and noncanonical address forms are rejected. Proxies remain disabled.

Check mode validates the contract, metadata and public identities without
claiming the approval, reading the password or starting SSH. Actual consumption
claims the approval once, disables core dumps, directs CLI stdout exclusively
into a private anonymous pipe and reads the exact password into mutable memory.
It uses no output-file path: native CLI file replacement cannot safely target
an inherited `/dev/fd` path. CLI output never inherits the terminal or a log.
The consumer revalidates both item identities, sends exact bytes
without a newline, closes SSH stdin and wipes its mutable secret buffer.
The returned receipt contains only public identities and operation status.

Do not print inputs, raw exceptions, CLI responses or private subprocess output.
Ansible adapters retain `no_log=true`. A partial or unknown unlock outcome
requires independent target observation; never replay a consumed approval.
An accepted native receipt does not replace the separate post-boot machine,
kernel, SSH and service acceptance.
