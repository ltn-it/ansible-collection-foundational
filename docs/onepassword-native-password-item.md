# Native Password item planning and creation

`lit.foundational.onepassword_secret_item` and the native Python entrypoint
`plugins.module_utils.onepassword_secret_item.execute_native(arguments,
check_mode=False)` use one shared implementation and the same documented action
contract. The native entrypoint uses only Python's standard library; it does not
require Ansible on the desktop. The Ansible action remains controller-only and
marks its invocation `no_log`.

The caller must first attest the native executor and the exact installed
Collection package and invoke the pinned native desktop CLI. Importing this
helper alone is not executor attestation or release approval. Concrete executor
pins, item references and operational commands belong in the private operations
repository.

`plan` inspects metadata without creating an item or reading a password. `apply`
creates only an absent item, generates its password internally in 1Password and
discards creation stdout and stderr. It requires the existing expiring,
asymmetrically signed, single-use Approval Authority, binding the complete
normalized contract and source revisions. No unsigned native exception exists.
Pin the returned item ID and positive version before a later consuming operation.
Re-reading metadata uses `--cache=false`; an unexpected existing item, duplicate
title, changed version, account, user, category, tags or purpose fails closed.

The return value contains only creation/planning state, item ID/version, operator
UUID and safe approval metadata. The helper offers no password read, update,
rotation, archive, delete or arbitrary-command interface. Service-account,
Connect and shell-session token environments remain forbidden. Session secrets
are not exported to an EE.

Tags accept 1–64 safe characters, permitting a full SHA-256 header-version tag.
The allowed character set is unchanged; commas, whitespace, unsafe boundary
characters and values longer than 64 remain rejected. A per-version header key
must use the exact dedicated title, tags and public purpose metadata required by
its consuming codec. Disk unlock passphrases and general Ansible Vault passwords
are not substitutes. This reusable creator does not decide retention or remove
predecessor keys.

The isolated native regression runs a real `python -I -S` process with no Ansible
imports, a synthetic attested CLI and ephemeral signed approval. It verifies
metadata planning, generation-output suppression, pin readback, cache bypass,
single-use replay rejection and missing-approval rejection. It is not a live
1Password custody or disaster-recovery acceptance.
