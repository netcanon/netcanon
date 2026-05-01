# Apply-groups: Junos-specific configuration inheritance

Junos's `apply-groups` mechanism is a configuration-inheritance
primitive that has no Cisco analogue.  This file documents the
shape so cross-vendor migration's behaviour is understood.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/groups-edit.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/cli/topics/topic-map/junos-config-groups-overview.html (retrieved 2026-04-30)

Citation ids: `junos-groups-statement`, `junos-config-groups-overview`.

## Junos form

```
set groups GLOBAL system syslog file messages any notice
set groups GLOBAL system services ssh
set groups GLOBAL interfaces <ge-*> mtu 9000

set apply-groups GLOBAL
```

The `groups GLOBAL` block defines a templated set of
configuration; the `apply-groups GLOBAL` directive at the top
level imports the group's content into the active configuration.
Wildcard interface match (`<ge-*>`) is a key feature — one group
can apply MTU 9000 to every Gigabit Ethernet interface.

## Cisco IOS-XE form

Cisco has no direct analogue.  The closest equivalents are:

- **Templates** (`template <name>` under interface configuration)
  — but these are limited to interface-level config and are
  syntactically distinct from running-config defaults.
- **Macros** (legacy IOS feature, deprecated) — operator-defined
  command shortcuts; not a runtime-applied inheritance mechanism.

Most Cisco operators replicate the equivalent intent through
configuration-management tooling (Ansible, Cisco DNA Center,
NSO) rather than through device-side inheritance.

## Mapping notes

- **Canonical surface.** `CanonicalIntent.apply_groups: list[str]`
  carries the apply-groups statement names; `group_content:
  dict[str, list[list[str]]]` carries the original group-scoped
  set-line tails.  Both fields are populated only by the Junos
  parser (GAP 9b) and are always empty for Cisco source.
- **Two-pass parse.** Junos's parser does a two-pass parse:
  first pass flattens apply-groups inheritance into the canonical
  tree (so MTU 9000 appears on every matching interface); second
  pass preserves the original group-scoped lines so
  same-vendor render emits the original `set groups`/`apply-
  groups` structure.
- **Junos -> Cisco render.** The flattened canonical content is
  emitted as Cisco config; the apply-groups structure is dropped
  (Cisco has no analogue).  A validation banner notes the loss.
- **Cisco -> Junos render.** Junos render emits flat config with
  no apply-groups optimisation.  Operator may post-edit for
  style.

Disposition: **not_applicable** — Junos-only concept; the
canonical fields exist for Junos same-vendor round-trip
preservation, not for cross-vendor translation.
