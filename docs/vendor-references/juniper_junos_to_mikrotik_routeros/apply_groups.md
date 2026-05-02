# apply-groups + group_content (Junos source-only): Juniper Junos versus MikroTik RouterOS

How Junos's `apply-groups` inheritance is preserved on the canonical
layer, and what happens to it on RouterOS render.

Sources:
- Juniper: https://www.juniper.net/documentation/en_US/junos12.3/topics/concept/junos-cli-config-groups-overview.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/groups-edit-junos-os.html (retrieved 2026-05-01)

Citation ids: `junos-config-groups-overview`,
`junos-groups-statement`.

## Junos form

```
set groups GLOBAL-SETTINGS interfaces ge-0/0/0 description \
    "Inherited from GLOBAL-SETTINGS apply-group"
set groups GLOBAL-SETTINGS interfaces ge-0/0/0 mtu 9000
set groups GLOBAL-SETTINGS system syslog host 10.0.0.252 any info
set apply-groups GLOBAL-SETTINGS

set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/31
```

Junos's `groups` mechanism is a hierarchical inheritance / template
system.  Operators define a named group with config statements (any
subtree under the group hierarchy) and reference it via
`set apply-groups <name>` at the root or anywhere lower in the
hierarchy.  At commit time, Junos merges the group content into the
target hierarchy positions; the merged config is what runs.  The
merge is non-destructive (top-level statements override group
statements at the same path).

The juniper_junos codec implements GAP 8 (two-pass parse) to resolve
group content into the canonical tree, then GAP 9b preserves both
the apply-groups STATEMENT (`CanonicalIntent.apply_groups`) and the
GROUP CONTENT (`CanonicalIntent.group_content`) so a Junos -> Junos
round-trip emits an equivalent group structure rather than the
flattened post-inheritance form.

## RouterOS form

RouterOS does NOT model hierarchical inheritance / templates.  Every
configuration statement is fully-qualified at the top level —
RouterOS scripts (`/system script`) can synthesise repeating
patterns, but the running config does not carry inheritance metadata.

## Cross-vendor mapping

* `apply_groups`: Junos-specific concept.  Junos source populates
  the list (e.g. `["GLOBAL-SETTINGS", "tenant-default"]`); RouterOS
  target codec does not consume it — drop with no emission.  The
  GROUP CONTENT (under `CanonicalIntent.group_content`) has already
  been flattened into the canonical tree by GAP 8's two-pass parse,
  so the target sees the post-inheritance config and renders it
  faithfully.  The original group structure is lost on cross-vendor
  render — the RouterOS output has fully-flattened, fully-qualified
  statements.
* `group_content`: companion to `apply_groups`; Junos source-only.
  Drop on RouterOS target render (the canonical tree already
  carries the flattened content via the two-pass parse).

Disposition: **lossy** for `apply_groups` / `group_content` on Junos
source — the structure (which statements were grouped vs which were
top-level) is lost on cross-vendor render, but the SEMANTIC content
(the post-inheritance values) is preserved via two-pass parse +
flat re-emission.  This is "lossy" rather than "unsupported" because
the values still land on the target; it is "lossy" rather than "good"
because the structural information (group naming, group reuse) is
absent in the rendered RouterOS config.
