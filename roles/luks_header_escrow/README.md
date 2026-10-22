# lit.foundational.luks_header_escrow

Persist the sole installed LUKS2 header declared by `crypttab` as an immutable,
controller-side Ansible Vault document. Raw header bytes exist only in a
protected temporary directory on the managed host and protected Ansible memory;
they are never written as controller plaintext.

## Requirements

- A Linux managed host with exactly one active `crypttab` source.
- `cryptsetup`, `findfs`, `readlink`, `id`, `awk`, and Bash at the declared absolute paths.
- Privilege to read and back up the installed LUKS2 header.
- A canonical protected **tmpfs** root for raw scratch; `/run` is the default.
- An Ansible Vault identity already loaded by the controller. Select its label
  with `luks_header_escrow_vault_id`; the role never accepts password material.
- An existing, non-symlinked `0700` escrow root owned by the effective
  controller user, with the normalized absolute escrow path below it.
- Durable controller storage. In AAP, mount the escrow root into the execution
  environment from persistent, separately backed-up storage; job-local project
  and container filesystems are ephemeral and are not valid escrow targets.

The enabled role intentionally refuses check mode. Callers should also enforce
their own fleet-selection, operating-system, lifecycle-phase, and confirmation
policy before invoking it.

## Variables

For an installed source, set `luks_header_escrow_expected_machine_id` and
`luks_header_escrow_expected_uuid` from the independently retained inventory
identity. Both checks run before raw-header capture. Their defaults are empty
for compatibility with existing first-install discovery; independent day-2
acceptance entrypoints must require both explicitly.

See `defaults/main.yml` for the complete interface. Important inputs are:

- `luks_header_escrow_enabled`: explicit opt-in; defaults to `false`.
- `luks_header_escrow_path`: absolute controller ciphertext path.
- `luks_header_escrow_controller_root_path`: allowed canonical controller root.
- `luks_header_escrow_vault_id`: loaded Ansible Vault identity label used when
  creating an absent ciphertext document; it may contain only ASCII letters,
  digits, dots, underscores, and hyphens, and defaults to `default`.
- `luks_header_escrow_schema_version`: immutable document schema; currently `1`.
- `luks_header_escrow_max_raw_bytes`: approved raw-header ceiling, capped at 20 MiB.
- `luks_header_escrow_subject`: document subject; defaults to `inventory_hostname`.
- `luks_header_escrow_crypttab_path`: managed-host `crypttab` path.
- `luks_header_escrow_cryptsetup_path`: absolute `cryptsetup` path.
- `luks_header_escrow_remote_temporary_root`: protected managed-host temporary root.
- `luks_header_escrow_allow_regular_file_device`: test/lab-only opt-in for a
  regular-file LUKS2 source; production defaults require a canonical block device.

The managed-host temporary root must already be canonical, owned by the
effective execution user, grant that owner `rwx`, and deny group/other write
access. Every ancestor back to `/` must be owned by root or that user and either
deny group/other writes or use sticky-directory protection. The shared `luks_header_snapshot` module allocates private scratch, validates the
real UUID, size and SHA-256 and removes all owned files in the same managed-side
process before returning. Each cryptsetup child has a bounded timeout and its
own process group. Failure and handled termination reap only that child and
clean up scratch; controller loss does not leave an idle between-task raw file.
Host process `SIGKILL` cannot run cleanup; scratch is restricted to volatile
tmpfs and this is not a power-loss/cold-boot acceptance claim.

On success, `luks_header_escrow_result` contains only safe metadata: whether
ciphertext was created, existence, path, ciphertext SHA-256, and LUKS UUID. It
never contains the header or the plaintext escrow document.

The `preflight` task entrypoint validates the same role interface plus
controller path, ownership, and permission policy without contacting the
managed host.

The delegated controller stat uses the current Ansible interpreter, local
connection, no privilege escalation, and Ansible's private `DEFAULT_LOCAL_TMP`.
It does not inherit the source host's login, privilege or temporary-directory
requirements. This also supports read-only execution environments whose login
home is not writable. Source SSH and remote temporary-directory settings stay
scoped to the managed host.

The separate `revision` task entrypoint uses the same managed snapshot with
`include_payload=false`. Enable it with `luks_header_escrow_revision_enabled`
(default `false`) and pin both expected machine ID and UUID. It needs no wrapping
key, controller ciphertext path or provider access. Its closed public result
`luks_header_escrow_revision_result` contains schema version, subject, source
machine ID, UUID, raw size, raw SHA-256 and completed scratch removal. It never
contains raw bytes or a scratch path. A disabled plan clears any stale result.
The normal `main` entrypoint does not implicitly run this planning operation.

`luks_header_escrow_timeout_seconds` defaults to 30 and must be 1–60 seconds per
cryptsetup command. A revision is an observation, not a lock on future keyslot
changes; the consuming capture must compare the actual raw hash again before
publishing to an external provider.

The role captures and verifies an immutable header document; it does not restore
a header, rotate LUKS keys, prune escrow, or replace the required independent
backup and recovery procedure. Loss of the sole ciphertext or its Vault identity
makes this escrow unusable, so back up and recovery-test both separately.

## Dependencies

None. The role uses `lit.foundational.ansible_vault_document` from this
collection for atomic create-if-absent encryption and exact immutable readback.

## Example Playbook

```yaml
---
- name: Escrow one installed LUKS2 header
  hosts: encrypted_linux
  gather_facts: false
  become: true
  serial: 1

  roles:
    - role: lit.foundational.luks_header_escrow
      vars:
        luks_header_escrow_enabled: true
        # Pre-create and mount this 0700 directory from durable controller storage.
        luks_header_escrow_controller_root_path: /mnt/ansible-escrow
        luks_header_escrow_path: >-
          {{ '/mnt/ansible-escrow/luks-headers/'
             ~ inventory_hostname ~ '.vault.yml' }}
        luks_header_escrow_vault_id: production
```

## License

MIT

## Author

Lightning IT
