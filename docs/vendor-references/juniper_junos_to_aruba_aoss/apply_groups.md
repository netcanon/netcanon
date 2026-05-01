# Apply-groups: Junos-specific configuration inheritance

Junos's `apply-groups` mechanism is a configuration-inheritance
primitive with no Aruba AOS-S analogue.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/groups-edit.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/cli/topics/topic-map/junos-config-groups-overview.html (retrieved 2026-05-01)

Citation ids: `junos-groups-statement`,
`junos-config-groups-overview`.

## Junos form

```
set groups GLOBAL system syslog file messages any notice
set groups GLOBAL system services ssh
set groups GLOBAL interfaces <ge-*> mtu 9000
set apply-groups GLOBAL
```

The `groups GLOBAL` block defines a templated set of configuration;
the `apply-groups GLOBAL` directive at the top level imports the
group's content into the active configuration.  Wildcard interface
match (`<ge-*>`) is a key feature.

## Aruba AOS-S form

AOS-S has **no analogue** for apply-groups.  All configuration is
flat — there is no inheritance / wildcard / template mechanism in
the running-config syntax.  Configuration replication across the
fleet is handled by external tooling (Aruba AirWave, Aruba Central,
or operator-managed scripts).

## Cross-vendor mapping

* Canonical surface: `CanonicalIntent.apply_groups: list[str]`
  carries the apply-groups statement names; `group_content:
  dict[str, list[list[str]]]` carries the original group-scoped
  set-line tails.  Both fields are populated only by the Junos
  parser (GAP 9b) and are always empty for Aruba source.
* Two-pass parse: Junos's parser does a two-pass parse — first pass
  flattens apply-groups inheritance into the canonical tree (so
  MTU 9000 appears on every matching interface); second pass
  preserves the original group-scoped lines so same-vendor render
  emits the original `set groups` / `apply-groups` structure.
* Junos -> Aruba render: the flattened canonical content is
  emitted as Aruba config; the apply-groups structure is dropped
  (Aruba has no analogue).  A validation banner notes the loss,
  but the operator's INTENT is preserved (every interface that
  inherited MTU 9000 from the group still carries MTU 9000 on the
  flattened canonical layer).

Caveat: the aruba_aoss codec does not parse `mtu` directives today,
so any group-inherited MTU values still drop at the Aruba render
boundary regardless of the apply-groups flattening.  This is
codec-side wire-up rather than a cross-vendor mapping issue.

Disposition: **lossy** (when Junos is source — the flattened content
crosses but the group structure itself is dropped).
**not_applicable** for the `apply_groups` / `group_content` fields
themselves on Aruba target render (the fields are Junos-only by
construction).
