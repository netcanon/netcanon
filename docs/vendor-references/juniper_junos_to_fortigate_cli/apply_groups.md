# Junos apply-groups — lossy on Junos -> FortiGate in v1

## Junos apply-groups: configuration inheritance

Source: [Junos `groups` statement reference](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/groups-edit.html).
Source: [Junos configuration-groups overview](https://www.juniper.net/documentation/us/en/software/junos/cli/topics/topic-map/junos-config-groups-overview.html).
Retrieved: 2026-05-01.

Junos's apply-groups mechanism allows configuration inheritance:
named groups under `set groups <G> ...` define configuration
fragments that are then inherited at specific points via `set
apply-groups <G>` directives:

```
set groups GLOBAL-SETTINGS interfaces ge-0/0/0 description "Inherited from GLOBAL-SETTINGS"
set groups GLOBAL-SETTINGS interfaces ge-0/0/0 mtu 9000
set groups GLOBAL-SETTINGS system syslog host 10.0.0.252 any info
set apply-groups GLOBAL-SETTINGS
#
# Top-level lines that supplement the inherited content
set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/31
```

After two-pass parse:

- The `description` and `mtu` fields on `ge-0/0/0` come from the
  group.
- The IP address comes from the top-level line.
- The merged result is what the device uses.

## Canonical model: GAP 9b two-pass parse

Per the Junos codec docstring, GAP 9b implements a two-pass parse:

1. **Pass 1**: collect `set groups <G> ...` content into the
   canonical `group_content` dict (per-group set-line tails).
2. **Pass 2**: walk `set apply-groups <G>` directives and flatten
   group content INTO the top-level canonical fields (interfaces,
   system, etc.).

Both:

- Top-level canonical fields contain the *merged* result (the same
  thing the device sees).
- `apply_groups: list[str]` records WHICH groups were applied.
- `group_content: dict[str, list[list[str]]]` records the original
  per-group set-line tails.

This shape means:

- Same-vendor (Junos -> Junos) round-trip emits both the
  apply-groups directives AND the group definitions, preserving the
  original inheritance structure.
- Cross-vendor (Junos -> any-non-Junos) render flattens — the
  inheritance structure drops, but the merged content survives.

## FortiGate has no analogous inheritance mechanism

FortiGate FortiOS has no analogue to Junos apply-groups.  FortiOS
configuration is mostly flat (each `edit <id>` block declares its
own settings); inheritance is limited to nested
`config / next / end` scoping.

Some related (but not analogous) FortiGate constructs:

- **Address objects + groups** (`config firewall address` /
  `address-group`) — these are firewall-policy targets, not
  configuration-template objects.
- **Global vs VDOM scope** — `config global` vs `config vdom / edit
  <name>` — provides multi-tenancy, not config-template
  inheritance.

The FortiGate codec does not consume Junos's `apply_groups` /
`group_content` canonical fields.

## Disposition on cross-vendor migration

- **apply_groups** — `lossy` on Junos -> FortiGate.  The
  inheritance-structure drops on FortiGate render, but the
  flattened content survives in the top-level canonical fields
  (post-GAP-8 two-pass parse).  A validation banner notes the
  loss.
- **group_content** — `lossy` for the same reason.  FortiGate render
  does not consume the per-group set-line tails.

The semantic intent is preserved (the FortiGate target receives the
same effective configuration as the Junos source had after
inheritance resolution); only the *attribution* (which group each
setting came from) drops.

## What this means in practice

Operators migrating Junos -> FortiGate accept that:

- FortiGate config is generated as if all Junos lines were typed at
  the top level (no group abstraction).
- If the operator later edits the FortiGate config and wants to
  re-introduce DRY-ness, they do it via FortiGate's own scoping
  primitives (VDOMs, address-groups for firewall objects).
- Re-migrating back to Junos would NOT re-introduce the apply-
  groups structure (round-trip is one-way).
