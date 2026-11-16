# lit.foundational.podman_systemd

Manage persistent Podman kube services through Quadlet and systemd.

The role renders a `.kube` Quadlet unit, reloads systemd, and can start,
restart, stop, enable, disable, or remove the generated service.

## Requirements

Podman with native Quadlet support and systemd. Loaded teardown inspection also
requires systemd's `busctl` with JSON output in the trusted command search path.

## Variables

`podman_systemd_networks` is an optional list of native Quadlet `Network=`
values. It supports Podman's network options without adding an imperative
`podman kube play` wrapper. For example:

```yaml
podman_systemd_networks:
  - podman-default-kube-network:ip=10.89.0.20
```

Each entry must be a non-empty single-line string. Static addresses must be
reserved by the inventory and remain inside the selected Podman network.
When the rendered Quadlet changes while the requested action is `present` or
`started`, the role restarts the service so changed network settings take
effect during the same reconciliation.

`podman_systemd_log_path` optionally selects a stable native `k8s-file`
destination through bounded `PodmanArgs=--log-driver=k8s-file --log-opt=path=...`.
The file must already be a regular file with one link, owned by the role's
effective runtime UID, mode 0600 and writable, inside a prepared private directory.
Only a single Pod containing one
application container and no init containers is accepted, preventing multiple
application writers from sharing the file. Paths containing whitespace, control
characters, unit specifiers or traversal components are rejected before mutation.
An empty value preserves Podman's default logging. No reader, capture worker or
new root service is installed. Configure operating-system log rotation separately;
this setting provides neither rotation nor a hard size limit. Existing file
history is not migrated automatically when changing the destination.

See `defaults/main.yml` for the remaining service, manifest, state, and
installation inputs.

The prepared destination must be writable in the same effective identity used
by this role to manage Podman; validation runs before Quadlet rendering or a
restart. Stopping or removing a unit does not require the log file to remain
present. Keep the manifest readable until teardown completes: Podman's generated
stop command still needs that source. Stopped/absent requests inspect the loaded
manager's structured ExecStart/ExecStop/ExecStopPost arrays through its D-Bus API.
The loaded native play and down commands must identify the same readable regular
manifest, even when the caller omits logging or supplies a different desired
manifest. Restore the actual loaded source before retrying. Unsupported loaded
command layouts fail before mutation. Both joined and separate native log-option
forms are inspected. The preflight also runs with `--tags podman_systemd`.
Loaded native start/down commands must report failures normally and identify
exactly one manifest, including services using Podman's default logging without
an explicit log path. Role-generated logging/network options and trailing
boolean options are parsed explicitly; additional manifests or unsupported
loaded options require operator reconciliation before a stop or removal.
The loaded start must be one directly invoked Podman kube play command;
wrappers and unrecognized executables are rejected rather than exempted.
Every loaded ExecStop and ExecStopPost command must also be a directly invoked
native down command for the verified manifest. A wrapped or unrelated stop
cannot hide beside another verified down command.
An `absent` or `stopped` request tolerates a missing systemd unit without a manifest only
when the manager also proves it inactive. `LoadState=not-found` alone is
insufficient: a running service can outlive its unit fragment. Restore its
original definition and teardown source before retrying in that state.
A `stopped` request for an already missing inactive unit skips service
management and independently rechecks activity. Repeated requests remain
unchanged and successful; a missing fragment never excuses an active service.
A loaded unit must
stop successfully and report inactive/success
before its Quadlet can be removed. Explicit `stopped` requests require the same
post-stop state proof; a failed teardown cannot be reported as a successful stop.
After a loaded-unit stop attempt, `Result=success` is required even if its
fragment disappears. Missing or unsuccessful results preserve recovery files.
An already missing inactive `stopped` request performs no stop attempt and needs
no historical result, but independently rechecks that the service stays inactive.
A loaded service already reporting both inactive and success needs no further
stop or loaded-command inspection. This supports repeated teardown after systemd
garbage-collects the inactive unit between calls. The role independently rechecks
inactive/success before removal; active, failed, or unconfirmed services still
require the original loaded teardown preflight and a successful stop.
An explicit stop does not render a new Quadlet, create its directory or reload
systemd first. It also leaves enablement unchanged, since enable/disable can
implicitly reload a pending definition. Removal disables only after a confirmed
successful stop. It stops the existing loaded definition and preserves those bytes
for recovery even if the caller supplies different desired settings.
Stop errors and a failed service result keep
the Quadlet for recovery. Restore the manifest and recover/reset the failed
service as appropriate before retrying. Check mode cannot prove a future stop.
Optional path syntax always rejects control characters,
including a trailing newline.

Native log destinations require real parent directories owned by root or the
role's effective runtime UID, with no group/other write bits. Shared writable
parents and symlink ancestors are rejected before a Quadlet is rendered. The
manifest preflight requires sequence-shaped container fields and a mapping-shaped
application entry; it does not replace Podman's complete manifest validation.

The ancestry check resolves the executing Ansible Python interpreter with a
Python-only setup query, including when `gather_facts: false` is configured.
It does not assume `/usr/bin/python3` or execute automatic-discovery tokens as
program names. Loaded stopped/absent actions resolve the executing interpreter
separately for the read-only manager inspection; they skip active-log prechecks.

### Explicit one-off log history handoff

Changing `podman_systemd_log_path` alone does not preserve a Podman graph log when
`kube down` removes its container. The optional `tasks_from: log_handoff`
entrypoint handles this transition separately. It supports rootless user services
and must run with root escalation for private metadata custody. Podman, process
inspection and live hardlinks run as the configured runtime account. No helper,
root reader, service, timer or log rotation program is installed by this entrypoint.

Required inputs:

- `podman_systemd_log_handoff_action`: `plan`, `hold`, `copy`, `authorize_start`,
  `verify`, or `finalize`. There is no implicit action and check mode is rejected.
- `podman_systemd_log_handoff_operation`: a fresh lowercase operation identifier.
- `podman_systemd_log_handoff_profile`: only `hostname`, `runtime_user`,
  `runtime_uid`, `graphroot`, and `components`.
- Each component contains only `container`, `unit` (without `.service`),
  `manifest`, `manifest_sha256`, `quadlet`, and `destination`. Read and review these
  nonsecret identities before the maintenance operation. Do not put manifest
  contents, environments or passwords in this profile.
- `podman_systemd_log_handoff_stop_order`: every component name exactly once,
  in the consumer's dependency-safe stop order.
- `podman_systemd_log_handoff_setype`: optional destination SELinux type. The
  operating-system role remains responsible for persistent labeling policy.

The caller prepares empty single-link mode-0600 destination files, owned by the
runtime account, with trusted directory ancestry and enough free disk space for
closed-file copies. The manifest and original Quadlet must remain unchanged and
readable during stop/copy. Select the precise host, coordinate exclusive maintenance
with other operators and scheduled backups, and retain a verified data backup and
application recovery procedure. The entrypoint does not manage backup scheduling,
application configuration, startup, readiness or customer acceptance.

Run the phases in order, each through the same public entrypoint and exact profile:

```yaml
- name: Plan the reviewed native log transition
  become: true
  ansible.builtin.include_role:
    name: lit.foundational.podman_systemd
    tasks_from: log_handoff
  vars:
    podman_systemd_log_handoff_action: plan
    podman_systemd_log_handoff_operation: native-logs-1
    podman_systemd_log_handoff_profile: "{{ reviewed_native_log_profile }}"
    podman_systemd_log_handoff_stop_order: "{{ reviewed_native_log_stop_order }}"
    podman_systemd_log_handoff_setype: container_log_t
```

`plan` binds every running native `graphRoot/overlay-containers/<id>/userdata/ctr.log`,
container/unit label, process start and source/holding-directory inode. It writes
root-only mode-0600 JSON under
`/var/lib/lit-podman-log-handoff/<operation>/` before any live hardlink is made.
The original manifest must also pass the same single-Pod, single-application and
no-initializer check used for stable native destinations, before any live hold
or service stop. Its bytes are read without logging them, after regular-file
and reviewed-hash checks. Unsupported existing Pods require a separate operator
migration plan; waiting for the replacement startup to reject them could lose
unselected container logs. A preexisting plan is not overwritten.
`hold` creates or adopts exactly these
same-filesystem links in private runtime-owned directories below the graph root;
an interrupted or repeated `hold` can resume with the original profile.

`copy` first checks **all** holds, destinations, current writers, original
manifest/Quadlet hashes and loaded native stop commands before stopping any
application. It stops through the ordinary role and copies only after the old
writer identity and userdata path are gone. A nonempty destination is accepted
only as an exact prior closed copy while its old container is absent. A fresh
controller can resume after a completed component copy. Unexpected files or
identities fail without guessing a recovery action.

`authorize_start` independently checks every closed old prefix before the consumer
runs its normal setup roles with stable native destinations. This phase does not
start applications. After normal startup and application checks, `verify` checks
replacement container IDs, actual destinations/unit labels and the entire old
prefix. Quiet applications need not emit a synthetic log line. `finalize` repeats
verification, commits complete prefix hashes and replacement IDs before removing
any known hold, then removes only known source links and empty original holding
directories. It can resume after interrupted cleanup using the root-owned completed
record. The small root metadata records remain available for the operator's audit;
no application data backups are removed. Do not rotate or truncate the new files
before prefix verification/finalization completes.

This is a one-off migration contract, not the recurring application setup path.
Completed operations reject new `hold` or `copy` phases. After later container
replacement or log rotation, the historic prefix check is no longer an appropriate
ongoing health check. Configure RPM Logrotate separately and use the normal
application/backup acceptance checks for steady-state operations.

## Dependencies

None.

## Example Playbook

```yaml
---
- name: Run a persistent Keycloak pod through native Quadlet
  hosts: wunderbox
  become: true
  roles:
    - role: lit.foundational.podman_systemd
      vars:
        podman_systemd_unit_name: keycloak
        podman_systemd_manifest_path: /etc/lit/keycloak/pod.yml
        podman_systemd_networks:
          - podman-default-kube-network:ip=10.89.0.20
```

## License

MIT

## Author

Lightning IT
