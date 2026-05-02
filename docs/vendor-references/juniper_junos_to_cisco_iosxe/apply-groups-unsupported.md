# Apply-groups — Junos-only configuration inheritance

Source: [Junos Configuration Groups Overview](https://www.juniper.net/documentation/us/en/software/junos/cli/topics/concept/junos-config-groups-overview.html)
Retrieved: 2026-05-01

Source: [Junos `apply-groups` statement reference](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/apply-groups-edit.html)
Retrieved: 2026-05-01

## What apply-groups does in Junos

Junos's `groups` hierarchy lets operators define reusable
config templates and inherit them at multiple points in the
configuration tree:

```
set groups COMMON system services ssh
set groups COMMON system login user readonly class read-only
set groups COMMON system login user readonly authentication encrypted-password "$6$..."
set apply-groups COMMON
```

The `set apply-groups COMMON` line at the top of the config
inherits everything under `set groups COMMON ...` into the
implicit top of the configuration tree.  Inheritance can happen
at any hierarchy level (`set interfaces ge-0/0/0 apply-groups
LAG-MEMBER`, etc.).

## How the juniper_junos codec captures apply-groups

GAP 9b added a two-pass parse that:

1. **Pass 1.** Walks `set groups <G> <config-path-prefix> <tail>`
   lines and stores them in `CanonicalIntent.group_content[G]`
   as a list of tail-tuples.
2. **Pass 2.** Walks `set apply-groups <G>` lines (at any
   hierarchy level) and stores the group names in
   `CanonicalIntent.apply_groups`.
3. **Materialise.** Inheritance is materialised into the
   canonical fields (system / login / interfaces / protocols /
   SNMP / routing-options / routing-instances / vlans) so a
   downstream consumer sees the effective config without needing
   to re-do the inheritance logic.

The provenance pair (`apply_groups` + `group_content`) survives
into the canonical tree so a same-vendor render can re-emit the
original `set groups` + `apply-groups` structure rather than the
flattened materialised form.

## What the cisco_iosxe render does

Nothing.  The render walks `intent.interfaces` only.
`intent.apply_groups` and `intent.group_content` are silently
dropped.

Cisco IOS-XE has no equivalent inheritance mechanism — the
config tree is flat and operators repeat configuration verbatim.
Even if the cisco_iosxe codec were extended to render hostname /
DNS / etc., it would emit the flattened materialised form (which
the GAP 9b two-pass parse already produced into the canonical
tree) — not the `groups` / `apply-groups` structure.

## Disposition

| Field | Disposition | Reason |
|---|---|---|
| `apply_groups` | unsupported | Junos-only concept; no Cisco analogue |
| `group_content` | unsupported | Companion to apply_groups |

The `unsupported` classification is structurally honest: even
with full render-side wire-up on the cisco_iosxe codec, these
fields would never round-trip.  They're Junos-specific
provenance that drops on cross-vendor migration with a
validation banner — same behaviour as the
juniper_junos__cisco_iosxe_cli sibling pair.

## Operational implication

Junos operators using apply-groups for compliance / template
enforcement (a common DC pattern — "all leaf switches inherit
LEAF_BASE group") will find their config flattens entirely on
cross-vendor migration.  The Cisco target receives the
materialised effective config but loses the structural
template — re-applying compliance enforcement on Cisco requires
a different mechanism (typically external config-management
tooling rather than in-config inheritance).

The flattening itself is lossy on a different axis: a Junos
operator's intent ("this device inherits from LEAF_BASE plus
local overrides") flattens to "this device has these
configurations" without indication of which came from a group
vs which were explicit.  Restoring the structural template on
target-side migration requires operator review; canonical doesn't
preserve enough metadata to round-trip.

## Forward-direction symmetry

The forward direction (cisco_iosxe -> juniper_junos) marks these
fields `not_applicable` because Cisco source NEVER populates
them (no Cisco analogue at all).  This direction marks them
`unsupported` because Junos source DOES populate them but Cisco
target can't accept.  Same operational meaning, different
schematic labelling — driven by the schema's distinction between
"source has nothing to translate" (`not_applicable`) vs "source
has data, target can't accept" (`unsupported`).
