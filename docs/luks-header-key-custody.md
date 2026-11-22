# Revision-bound wrapping-key custody

`plugins.module_utils.luks_header_key_custody` is an internal reusable boundary
for one primary HC Vault KV2 key record. It is not an Ansible secret lookup,
standalone deployment command or production acceptance. The native Password
creator and credential transport keep their separate trust contracts.

The closed contract binds schema1, canonical source subject, machine ID, LUKS
UUID, raw-header SHA-256, exact KV2 mount/prefix and secondary custody policy.
The record path is `<prefix>/<subject>/<raw-sha256>`. Its Vault encryption label
is `luks-header-<raw-sha256>`. A record must be one live immutable version1;
another source, revision, key purpose, secondary policy or unexpected field is
a conflict. The existing `VaultHTTP` client rejects deleted/destroyed history,
redirects and implicit proxy/TLS bypasses and uses CAS0 for creation.

`manage_key` returns only revision metadata, immutable backend references and
verified custody states. Public receipts contain no password-derived digest or
key fingerprint. `plan` reads primary HC custody first and never invokes
generation or secondary secret readback.
If a record already exists, `apply` and `verify` reuse it without generation or
write; a required independent copy must match its exact positive item pins and
key. A plan may discover those public pins; consuming a key requires them to be
explicitly retained and supplied, not silently adopted from a title search.

For explicitly admitted absent-key `apply`, a trusted deferred factory is called
only after primary absence. The secondary copy is verified before the primary
commit, HC is reread for races, creation uses CAS0 and the complete immutable
record is read back. Independent readback is repeated after commit. A failed
secondary read can leave a partial provider effect but never creates a success
receipt. Do not delete that effect, regenerate, overwrite or retry blindly.
One readback may reconcile a lost write response; `created=null` records unknown
creation attribution while `reconciled_unknown_write=true` and exact readback
prove current custody. No automatic write retry occurs.

The factory and reader are trusted Python integration points, never arbitrary
commands or Ansible task arguments. Additional native custody uses the existing
signed, internally generated Password creator and strict purpose/item codec.
The custody core does not confer creation authority, attest a native executor
or decide an operational backend. HC-only mode carries no secondary provider;
the additional-copy mode must not be propagated to other hosts implicitly.

The private primary-key consumer returns an opaque, non-JSON/non-pickle holder
only inside the fixed trusted consumer. Its representation is redacted and its
lifetime can be ended explicitly. It must never become an Ansible variable,
fact, file, command argument, environment secret or log value. Loading primary
material does not contact the desktop and does not claim a fresh independent
copy check. Python cannot promise physical zeroization of every temporary copy;
the one-shot execution/descriptor/process-cleanup boundary remains required.

Operational integration must use scoped verified-TLS AppRole credentials and
the admitted secret-memory interface, not a root token or spare unseal shares.
Existing closed credential profiles must not be weakened to combine unrelated
material. The complete header13/14/16/18/17/15 path, actual independent provider
readback, source-down recovery and cold unlock remain separate required proofs.
