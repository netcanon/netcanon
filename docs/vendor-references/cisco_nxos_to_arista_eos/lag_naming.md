# LAG membership across NX-OS -> Arista EOS

Source: `netcanon/migration/codecs/arista_eos/render.py` + `parse.py`
(authoritative in-tree source for what this codec emits and recovers)
Retrieved: 2026-08-19

## What was measured

Rendering a `CanonicalIntent` carrying one LAG through the `arista_eos`
codec and re-parsing the result, varying only the LAG name:

| `CanonicalLAG.name` / `CanonicalInterface.lag_member_of` | rendered | round-trip |
|---|---|---|
| `Port-Channel1` (Arista-native) | `channel-group 1 mode active` on each member + `interface Port-Channel1` | LAG recovered intact (name, members, mode) |
| `port-channel1` (NX-OS-native) | `interface port-channel1` only — **no `channel-group`** | LAG lost entirely |

Both cases populate `CanonicalInterface.lag_member_of`; that field, not
`CanonicalLAG.members`, is what the renderers key off. A probe that sets only
`members` reports a false drop on 7 of 12 codecs — this is the naming-sensitive
false positive that `tests/unit/migration/test_registry_capability_honesty.py`
documents when it deliberately excludes `lags` from
`_NAMING_INDEPENDENT_DROP_FIELDS`.

## Why the cross-vendor pair loses it

The Arista renderer derives the channel-group number from the LAG name. An
NX-OS source yields `port-channel1`, which does not match the `Port-Channel<N>`
shape, so no `channel-group` line is emitted and nothing re-associates the
members on re-parse.

This is a **bare-render** result. Port-name translation lives in the
orchestrator layer (`translate_port_names` / `format_port_identity`), engaged
on the `--translate` / deploy path but deliberately NOT in the cross-mesh
audit, which scores name stability instead. So the loss is expected here and
closed on the path an operator actually deploys through.

## Consequence for the expectation YAML

`lags` is **lossy** on `cisco_nxos -> arista_eos`: the canonical model carries
the LAG and both vendors model link aggregation natively, but a bare
cross-vendor render drops the membership on the name mismatch. It is not
`unsupported` — Arista models LAGs fully, and the same canonical record
round-trips when the name is Arista-shaped.
