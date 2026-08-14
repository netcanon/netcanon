# Phase 4b findings — residual `CODEC_BUG` cells (2026-06-13 triage)

After the **capability-aware anycast reclassification** landed in
`tools/run_phase4_reconciliation.py` — the reconciler now reads each target
codec's `_CAPS` and treats anycast-companion drift (`virtual_gateway_*`) to
an anycast-**unsupported** target as `EXPECTED_UNSUPPORTED` rather than
`CODEC_BUG` — the 424-cell / 45-real-fixture mesh leaves **5 residual
`CODEC_BUG` cells**.

> **Cell/fixture counts are as-of this 2026-06-13 triage.**  The mesh has since
> grown (1224 cells at HEAD); the live totals + the current residual cell list
> are in [`PHASE4_RECONCILIATION.md`](PHASE4_RECONCILIATION.md).  The cell list
> below was **re-verified against `_phase4_runs/latest.json` on 2026-08-13**:
> the count still holds at 5, but row #4 had drifted and is corrected here —
> the `juniper_junos → fortigate_cli` / `vlans[].id` cell named by the previous
> revision **exists nowhere in the mesh**, and `fortigate_cli` does not appear
> in the residual set at all.  Re-verify this list against `latest.json`
> whenever the count is quoted: the 2026-07-12 HEAD review (finding D19)
> refreshed the *count* and explicitly asserted the cell list still matched,
> which was already untrue.

All 5 were triaged and are **benign methodology / modelling artifacts — not
codec defects.**  Documented here (per the Phase 4b convention) so the count
in `PHASE4_RECONCILIATION.md` reads as *explained* rather than as open
alarms.

> Triage origin: a 13-cell `CODEC_BUG` sweep prompted the reconciler fix.
> 8 of the 13 were the v0.2.0 anycast surface (arista VARP / junos
> anycast-gateway → cisco_iosxe-NETCONF / opnsense targets that declare
> anycast unsupported) and are now auto-classified `EXPECTED_UNSUPPORTED`.
> These 5 remain because they are cross-field / structural differences,
> not a single `_CAPS`-declared-unsupported path.

| # | Source → Target | Fixture | Field | Root cause | Verdict |
|---|---|---|---|---|---|
| 1 | arista_eos → cisco_iosxe_cli | `batfish_eos_evpn_vlan_based_leaf.txt` | `vlans` | Arista synthesises a content-free SVI placeholder address record (`ip=""`, no anycast) on the VLAN for VARP SVIs whose only real address lives on the sibling `interface VlanN`. cisco_iosxe_cli doesn't reproduce the empty marker. No data lost. | benign — empty-SVI-marker modelling |
| 2 | arista_eos → cisco_iosxe_cli | `batfish_labval_dc1_leaf2a_eos4230.txt` | `vlans` | Same as #1. | benign |
| 3 | juniper_junos → aruba_aoss | `ksator_labmgmt_qfx10k2_junos173.set` | `vlans[].ipv4_addresses` | Junos carries the SVI address on the `irb` **interface**; Aruba's SVI-on-VLAN model (`absorbs_svi_into_vlan`) relocates it onto the **VLAN** record. The address survives — it's on a different canonical field (`source=[]`, `target=[10.231.0.7]`). | benign — SVI projection asymmetry |
| 4 | juniper_junos → cisco_iosxe_cli | `jnprautomate_mnha_vsrx_a_junos.set` | `interfaces[].ipv4_addresses` | Junos `lo0.10` carries three /32 addresses, all primary (`is_secondary=false`). IOS-XE permits one primary address per interface, so the CLI render correctly demotes the 2nd and 3rd to `secondary`. All three addresses survive with identical prefix lengths — only the `is_secondary` flag differs. | benign — correct multi-primary → primary+secondary normalisation (same class as #5) |
| 5 | cisco_iosxe → cisco_iosxe_cli | `kitchen_sink.xml` (synthetic) | `interfaces[].ipv4_addresses` | The synthetic fixture lists 3 *primary* addresses on one interface; the CLI render correctly demotes the 2nd/3rd to `secondary` (IOS permits one primary per interface). Correct normalisation, not loss. | benign — correct NETCONF→CLI normalisation (synthetic-fixture shape) |

## Why these aren't auto-reclassified (and aren't worth forcing)

Unlike the anycast surface — where the target codec's `_CAPS` declares the
path unsupported, giving the reconciler an authoritative, general signal —
these 5 are **cross-field / structural** differences the field-by-field
reconciler can't distinguish from real loss without cross-field-aware
comparison:

* **#1 / #2** — drift is on the `vlans` whole field; cisco_iosxe_cli *does*
  support VLAN SVIs, it just doesn't emit a content-free placeholder.  The
  cleanest durable fix is an arista **parse** tweak (don't synthesise an
  empty `ipv4_addresses` record on a VLAN whose SVI address is
  VARP-on-interface) — a codec change with round-trip implications,
  deferred as a low-priority nit.
* **#3** — needs interface↔VLAN cross-field awareness (the address moved,
  it wasn't lost).
* **#4 / #5** — correct multi-primary → primary+secondary normalisation.  The
  comparator diffs each address record field-by-field and sees the
  `is_secondary` flag flip; telling "demoted per a target-platform rule" apart
  from "lost" needs target-capability awareness it doesn't have.  #4 is the
  real-fixture instance, #5 the synthetic one — one root cause, two cells.

None block any user-facing translation; they are reconciler-taxonomy edge
cases.  Left as low-volume, **documented** signal rather than masked with
fixture-specific suppressions (which would risk hiding real future drift).

## See also

* `tools/run_phase4_reconciliation.py` — `_target_anycast_declaration` /
  `_drift_is_anycast_companion_only` implement the capability-aware
  reclassification described above.
* `tests/unit/audit/test_run_phase4_reconciliation.py` — guards the
  reclassification (anycast→unsupported-target reclassifies; real IP drift
  and anycast-supporting targets stay `CODEC_BUG`).
