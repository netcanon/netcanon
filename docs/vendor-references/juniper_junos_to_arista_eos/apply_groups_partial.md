# Apply-groups (Junos-specific inheritance) — partial cross-vendor mapping

Junos's `groups <G> { ... } / apply-groups <G>` mechanism has no
direct Arista analogue.  This doc explains how the canonical layer
handles the asymmetry.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/groups-edit.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/cli/topics/topic-map/junos-config-groups-overview.html (retrieved 2026-05-01)

Citation ids: `junos-groups-statement`, `junos-config-groups-overview`.

## Junos form

```
groups {
    GLOBAL-MTU {
        interfaces {
            <ge-*> {
                mtu 9216;
            }
        }
    }
    DC-FABRIC {
        interfaces {
            <ae*> {
                aggregated-ether-options {
                    lacp {
                        active;
                    }
                }
            }
        }
    }
}

apply-groups [ GLOBAL-MTU DC-FABRIC ];
```

`groups` defines a named template; `apply-groups` references the
template, inheriting its content into matching configuration nodes.
Wildcards (`<ge-*>`, `<ae*>`) match interface names by pattern;
operators use this for DRY config with hundreds of interfaces.

The set-form equivalent:
```
set groups GLOBAL-MTU interfaces <ge-*> mtu 9216
set apply-groups GLOBAL-MTU
```

## Arista form

Arista has **no first-class apply-groups equivalent**.  Operators
typically:
- Repeat the directive per-interface (verbose but explicit).
- Use Jinja2 / Ansible-style templating at the config-generation
  layer (CloudVision, AVD, custom CI/CD).
- Use Arista's `event-handler` / `cli alias` for limited macro
  expansion (different shape, different semantics).

EOS configurations are typically flat post-template-render; the
inheritance metadata that produced them is lost by the time the
config file is loaded onto the device.

## Canonical-layer policy

The juniper_junos codec does a **two-pass parse**:

1. **Flattening pass.** Apply-groups inheritance is resolved
   in-place: every interface that matches `<ge-*>` gets `mtu 9216`
   on its `CanonicalInterface.mtu` field.  This is the operator's
   *intent* — what the running configuration looks like after Junos
   resolves the inheritance internally.
2. **Provenance preservation pass.** The original group-scoped
   set-line tails are preserved on
   `CanonicalIntent.apply_groups` (the list of group names) and
   `CanonicalIntent.group_content` (the per-group raw content).

On Arista render:
- The **flattened content** emits as Arista config (operator's
  intent fully preserved — every interface gets its inherited MTU,
  LACP mode, etc).
- The **apply-groups structure itself** drops (no Arista analogue).
  A validation banner on the Arista output notes that
  apply-groups inheritance was flattened and any subsequent
  re-parsing of the rendered output cannot reconstruct the
  group structure.

## Mapping notes

- **Disposition.** `apply_groups` and `group_content` are tagged
  `lossy` (not `unsupported`) because the *operator intent*
  survives via flattening — only the *structural plumbing* drops.
  This is a subtler asymmetry than Aruba (which loses both intent
  and structure for fields like VRFs and VXLAN).
- **Re-edit risk.** An operator who needs to add `mtu 9216` on a
  new interface post-migration must add it explicitly on Arista —
  the wildcard inheritance does not exist.  This is documented in
  the validation banner.
- **Round-trip caveat.** Arista -> Junos reverse direction cannot
  reconstruct apply-groups (Arista source has no group concept;
  the canonical model has no `apply_groups` populated).  This is
  why the forward-direction YAML
  (`arista_eos__juniper_junos.yaml`) marks `apply_groups` and
  `group_content` as `not_applicable` — Arista source never
  populates them.
