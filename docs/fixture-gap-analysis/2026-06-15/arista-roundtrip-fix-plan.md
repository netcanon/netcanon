# Arista EOS round-trip fixes — design / fix-plan

_Scoped 2026-06-15 from the `fixture-acquire` pass. The AVD `eos_cli_config_gen`
`host1.cfg` kitchen-sink (Apache-2.0) is the richest single gap-fill config found
(closes **8** arista surfaces: SNMPv3, classic VRRP, IPv6 VARP, IPv4/IPv6 vgw-mac,
DHCP-pool, tunnel, dhcpv6) but it **fails the real-capture round-trip gate** on 3
distinct defects. This plan fixes all three so the fixture can land. Each defect was
confirmed by parse→render→parse on the real AVD file (270 KB)._

> Risk frame: `arista_eos` is **certified**, and two of the three fixes touch
> **shared / canonical** surfaces (a cross-codec transform + the canonical RADIUS
> model). Treat as a careful, fully-gated PR. Must regenerate cross-mesh + phase4
> artifacts and re-run the full unit + real-capture gate. Do NOT change behaviour the
> existing cisco_iosxe_cli tests + `cross_vendor_expectations/*.yaml` rely on without
> updating them deliberately.

## Defect 1 — SVI `description` → `CanonicalVlan.name` fold is not round-trip-stable

**Symptom:** `vlans` name drift (`SVI Description` → `SVI_Description`) and
`routing_instances` collapse **20 → 18** on round-trip.

**Root cause:** `netcanon/migration/canonical/transforms.py::project_svi_to_vlan`
(line ~349) synthesises a `CanonicalVlan(name=iface.description)` when an
`interface Vlan<N>` SVI has no matching top-level `vlan <N>` stanza. This is a
**deliberate, test-covered feature** (`test_cisco_iosxe_cli.py::test_svi_description_fills_name_when_no_stanza`,
`test_synthetic_cisco_iosxe_kitchen_sink.py::test_synthesised_vlan_inherits_svi_description`,
and `cross_vendor_expectations/arista_eos__mikrotik_routeros.yaml` all rely on it) — so it
**must not be removed wholesale**.

The instability is two-fold and arista-specific:
1. arista `render.py` (line ~418) sanitises VLAN names `re.sub(r"\s+","_")` (EOS names
   can't contain spaces), but arista `parse.py` does not — so the folded name
   `"SVI Description"` (parse 1) becomes `"SVI_Description"` (render → parse 2).
2. The EVPN MAC-VRF name in `_parse_router_bgp` (`router bgp / vlan <N>`) is derived from
   `vlan.name` — but `_parse_router_bgp` runs **before** `project_svi_to_vlan`, so on
   parse 1 the VLAN doesn't exist yet → falls back to `VLAN<N>`; on parse 2 the
   render-emitted `vlan <N> / name SVI_Description` stanza exists → keys off
   `SVI_Description`. Many VLANs share the description `"SVI Description"`, so multiple
   MAC-VRFs collapse onto one name on parse 2 → 20→18.

**Fix (arista-local, keep the feature):**
- In `arista_eos/parse.py`, after `project_svi_to_vlan(intent)`, normalise the
  SVI-derived VLAN names the same way render will: `vlan.name = re.sub(r"\s+","_",
  vlan.name.strip())` for VLANs whose name came from the description fold. Simplest robust
  approach: apply the same sanitisation render uses to **every** `CanonicalVlan.name` at
  the end of arista parse so parse output == render output (idempotent). This is
  arista-only (do NOT put it in the shared transform — mikrotik/opnsense VLAN
  comments legitimately allow spaces; cisco is parse_only).
- Decouple the MAC-VRF name from the mutable folded name so distinct VIDs never collapse:
  in `_parse_router_bgp`, when keying `router bgp / vlan <N>`, prefer a stable key. Either
  (a) run `project_svi_to_vlan` **before** `_parse_router_bgp` so both parses see the same
  (sanitised) name, **and** ensure distinct VIDs with the same name don't merge (key the
  routing-instance by `(name, vid)` or keep `VLAN<vid>` when the name is
  description-derived); or (b) leave order as-is but have `_parse_router_bgp` look up the
  VLAN name from the SVI's already-folded value. Option (a) with a vid-stable MAC-VRF key
  is cleanest. **Verify the `arista_eos__mikrotik_routeros.yaml` + EVPN cross-mesh
  expectations** still hold (regen if the sanitised underscore form changes them — the
  underscore form is what EOS actually emits, so it's the more-correct canonical).

**Regression guard:** the existing cisco tests must still pass (cisco uses the shared
transform unchanged). Add an arista round-trip unit test on a minimal synthetic config:
`interface Vlan24 / description SVI Description` + `router bgp / vlan 24 / rd ... /
route-target both ...` (no `vlan 24` stanza) → assert `parse(render(parse(x)))` stable on
`vlans` + `routing_instances`.

## Defect 2 — RADIUS 12 → 9 (canonical model can't distinguish same-host servers)

**Symptom:** `radius_servers` 12 → 9. Confirmed losses: host `10.10.11.156` 3→2,
`10.10.10.249` 2→1, `10.10.11.158` 1→0.

**Root cause:** real EOS distinguishes same-host RADIUS servers by
`vrf` / `tls ssl-profile` / `port` / `timeout` / `retransmit` — **none of which are in
`CanonicalRADIUSServer`** (only `host`, `key`, `auth_port`, `acct_port`). Parse 1 produces
canonically-near-identical records; render emits a reduced form; reparse collapses the
duplicates. Also `radius-server host X key 7 <hash>` mis-parses: `_RADIUS_KEY_RE` captures
the type indicator `7` as the key instead of the hash.

**Fix (canonical-schema change — cross-codec; scope carefully):**
- Extend `CanonicalRADIUSServer` (in `canonical/intent.py`) with optional fields:
  `vrf: str = ""`, `tls: bool = False` (or `server_type`), and a single `port` /
  `secure_port` if needed for `tls port N`. Keep backward-compatible defaults so other
  codecs (fortigate_cli, aruba_aoss) are unaffected (they just don't set them).
- arista `parse.py`: capture `vrf <name>`, `tls`/`ssl-profile`, `port N` from the
  remainder; fix the `key 7 <hash>` / `key 0 <plain>` / `key 8a <hash>` parse to skip the
  EOS key-type digit and capture the actual secret. arista `render.py`: emit the captured
  qualifiers so the round-trip is stable.
- **Audit every codec that reads/writes `radius_servers`** (fortigate_cli, aruba_aoss,
  others) + the cross-mesh — a schema add is low-risk if fields are optional, but the
  cross-mesh `_compare` + any RADIUS cross-vendor expectation must be re-checked + regen.
- If full modelling is judged too invasive, the **minimum** stable fix is to make
  same-host distinctness survive: include the un-modelled qualifier string in a single
  opaque field so identical-host records aren't byte-identical, OR dedupe at parse so
  count is stable both ways. Prefer real modelling of `vrf` + `tls` (they're common).

**Regression guard:** minimal synthetic arista config with two same-host `radius-server
host` lines differing only by `vrf` and one with `key 7 <hash>`; assert count + key
survive the round-trip.

## Defect 3 — Port-Channel `switchport access vlan` dropped on render (LOW risk, localized)

**Symptom:** `Port-Channel100.access_vlan` `200 → None` (only Po100; `Port-Channel20`
renders its access-vlan fine).

**Root cause:** arista `render.py` interface loop has a branch condition that emits
`switchport access vlan` for some interfaces but not Po100 — likely an
L3/has-IP/has-members gate that Po100 trips but Po20 doesn't. Read the interface render
block (`render.py` ~480–545, the `vlan_member_names` / L3-detection logic around line
497–540) and fix the condition so a LAG with `access_vlan` set still emits the line.

**Regression guard:** minimal synthetic `interface Port-Channel100 / switchport access
vlan 200` (+ whatever Po100-specific attribute trips the branch) → assert
`access_vlan` survives render.

## Sequence + validation

1. Branch off `main` (or rebase on #68 once merged).
2. Implement defect 3 (smallest), then defect 1 (transform/parse), then defect 2 (schema).
3. Add the 3 focused synthetic regression tests above.
4. Re-fetch the AVD fixture (raw URL in `tests/fixtures/real/NOTICE.md` candidate notes /
   `docs/fixture-gap-analysis/2026-06-15/candidates.json`), sanitize (strip the inline
   RSA private-key block → placeholder; keep public cert chain), add the `!`-attribution
   header, place at `tests/fixtures/real/arista_eos/avd_eos_cli_gen_host1.cfg`.
5. Confirm it parses + **round-trips** + detects uniquely; add the NOTICE/RESULTS/WANTED
   rows + CHANGELOG entry.
6. Run the full gate: `tests/unit` + `tests/integration` + `test_real_captures.py`;
   **regenerate** `CROSS_MESH_RESULTS.md` + `PHASE4_RECONCILIATION.md` via
   `tools/run_full_mesh.py` + `tools/run_phase4_reconciliation.py` (CODEC_BUG should stay
   5 unless a fix legitimately changes a cell — explain any delta).
7. PR. The payoff: the 8-surface AVD fixture lands, closing arista's largest remaining
   gap cluster, plus the RADIUS schema + SVI-fold fixes benefit cisco_iosxe_cli and the
   cross-mesh too.

## Related deferred findings (same acquisition pass)
- **cisco_nxos**: `interface nve1 / member vni <N> / mcast-group` + ingress-replication
  not harvested into `CanonicalVxlan` → `/vxlan-vnis/mcast-group` + `/flood-list` are
  matrix-`supported` but effectively only synthetically reachable (matrix-honesty gap).
- **juniper_junos**: VRRP round-trip data loss (the `batfish_juniper_vrrp` testconfig).
- **cisco_iosxr**: `classify_port_name` drops the 4th segment of `TenGigE0/0/0/N` →
  interface reorder on round-trip (low priority; XR has 0 open supported gaps).
- **fortigate_cli**: SNMPv3 implicit `auth-proto`/`priv-proto` defaults → render asymmetry
  (auth_protocol/priv_protocol empty on parse). Separate from the RADIUS schema work.
