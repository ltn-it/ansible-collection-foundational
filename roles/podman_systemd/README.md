# lit.foundational.podman_systemd

Manage persistent Podman kube services through Quadlet and systemd.

The role renders a `.kube` Quadlet unit, reloads systemd, and can start,
restart, stop, enable, disable, or remove the generated service.

## Requirements

Podman with native Quadlet support and systemd.

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
The file must already be a regular file with one link, writable by the runtime
account, inside a prepared private directory. Only a single Pod containing one
application container and no init containers is accepted, preventing multiple
application writers from sharing the file. Paths containing whitespace, control
characters, unit specifiers or traversal components are rejected before mutation.
An empty value preserves Podman's default logging. No reader, capture worker or
new root service is installed. Configure operating-system log rotation separately;
this setting provides neither rotation nor a hard size limit. Existing file
history is not migrated automatically when changing the destination.

See `defaults/main.yml` for the remaining service, manifest, state, and
installation inputs.

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
