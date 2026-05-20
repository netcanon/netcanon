# IMPLEMENTED

This planning task shipped in:

* **Wave A (schema)**: commit `c5da044`
  — `feat(canonical): Wave A — VRRP / anycast / per-VRF static-route schema (ship-before-wire)`
* **Wave C (codec wire-up across 3 codecs)**: commit `e542b49`
  — `feat(codecs): Wave B + C — VRRP / HSRP / CARP / anycast-gateway wired across 7 codecs`
  (Wave C is the anycast portion; Wave B is the classic VRRP/HSRP/CARP
  portion documented in sibling
  [`../01-vrrp-canonical/IMPLEMENTED.md`](../01-vrrp-canonical/IMPLEMENTED.md).)

## What landed

* New fields on `CanonicalIPv4Address` and `CanonicalIPv6Address`:
  - `virtual_gateway_address: str = ""` — companion virtual IP.
    Junos one-line `family inet address X virtual-gateway-address Y`
    stores both pieces on the same record.
  - `virtual_gateway_mac: str = ""` — per-address MAC override
    (Junos per-unit `virtual-gateway-v4-mac` /
    `virtual-gateway-v6-mac`).  Empty means "fall back to the
    chassis-wide MAC".
  - `is_secondary: bool = False` — supports the Arista VARP
    `secondary` trailer + Cisco / Arista classic-secondary
    semantics; also unblocked a pre-existing EOS parser gap.
* New system-wide field: `CanonicalIntent.anycast_gateway_mac: str
  = ""`.  Arista `ip virtual-router mac-address`, NX-OS /
  IOS-XE-SD-Access `fabric forwarding anycast-gateway-mac`.  MACs
  canonicalised to colon-hex; per-vendor renderers re-emit in
  their native format (Arista colon-hex, NX-OS dotted-triplet,
  IOS-XE dotted-triplet).
* Per-codec parse + render wire-up across **3 bidirectional
  codecs**:
  - **juniper_junos** — `family inet address X/M virtual-gateway-
    address Y`, `family inet6 ... virtual-gateway-address`,
    per-unit `virtual-gateway-v4-mac` / `virtual-gateway-v6-mac`
    overrides.  IRB-to-VLAN fold extended to preserve the new
    fields onto `CanonicalVlan.ipv4_addresses`.  QFX10K2 fixture
    now round-trips anycast data **preserved** (previously
    silently dropped).
  - **arista_eos** — `ip address virtual X/Y [secondary]`,
    `ipv6 address virtual`, system-wide `ip virtual-router
    mac-address`.  VARP-only records carry `ip=""` (EOS has no
    per-leaf primary; virtual is the only IP).  `secondary`
    trailer preservation closes a pre-existing EOS parser gap.
    `source-nat` discriminator on `ip address virtual` is Tier-3
    parse-and-ignore (VRF-leaked traffic).
  - **cisco_iosxe_cli SD-Access** — per-SVI `fabric forwarding
    mode anycast-gateway` (mirror semantics: primary IP IS the
    virtual; no separate virtual-gateway-address field on the
    wire); system `fabric forwarding anycast-gateway-mac`.  MAC
    parser accepts all 3 vendor forms (dotted-triplet, colon-hex,
    dash-hex); renderer always emits dotted-triplet.
* Authoritative per-codec graduation state lives in
  [`tests/unit/migration/test_canonical_vrrp_anycast_schema.py`](../../../tests/unit/migration/test_canonical_vrrp_anycast_schema.py)
  `_WIRED_UP_BY_CODEC`.  Anycast-relevant graduated paths:
  `/interfaces/interface/ipv4/address/virtual-gateway-address`,
  `/interfaces/interface/ipv6/address/virtual-gateway-address`,
  `/anycast-gateway-mac`.
* The independent-surface decision (NOT merged into
  `CanonicalVRRPGroup`) adopted as shipped.  Anycast lives on
  the address records; classic FHRP lives on
  `CanonicalInterface.vrrp_groups` (sibling task).  No
  `mode="anycast"` value on the VRRP discriminator.

## What was deferred to a future PR

* **Cisco IOS-XE NETCONF stub (`cisco_iosxe`)** — all anycast
  paths still `unsupported`.  OpenConfig anycast-gateway augments
  aren't modelled by the stub today.
* **Junos `/anycast-gateway-mac` (chassis-wide MAC)** — kept
  `unsupported`.  Junos has NO chassis-wide anycast MAC concept;
  per-unit `virtual-gateway-v4-mac` / `virtual-gateway-v6-mac`
  is the only Junos surface and lands on the per-address record.
  Cross-vendor sources that populate the chassis MAC produce a
  review banner on Junos render (operator-visible signal of the
  cross-vendor mapping gap).
* **Arista per-IP `virtual-gateway-mac`** — declared `lossy`
  (the planning doc proposed a cascade pattern; the shipped
  agent decision was `lossy` instead, because EOS only has the
  chassis-wide MAC and per-IP override doesn't exist in the
  grammar).  Cross-vendor sources from Junos that populate
  per-IP MAC fields surface a review banner on Arista render.
* **Cisco IOS-XE IPv6 anycast** — `unsupported`.  No fixture
  coverage; SD-Access IPv6-anycast public corpus is empty.
* **Cisco NX-OS DAG (`ip address X/Y anycast`)** — gated on the
  NX-OS codec landing (Tier-D; design in sibling task
  `03-nxos-codec/`).  Phase 4 of that codec consumes this task's
  per-address anycast surface directly.
* **Aruba AOS-CX `ip address X/Y virtual`** — gated on the
  AOS-CX codec landing (Tier-D; not yet scoped in
  `docs/v0.2.0-planning/`).

The four codecs without native anycast grammar
(aruba_aoss, fortigate_cli, mikrotik_routeros, opnsense) declare
the anycast paths `unsupported` — their vendor grammar simply
doesn't model anycast natively.  Cross-vendor migration toward
those targets surfaces an "Unsupported path" banner via the
migrate-page Tier-3 detection.

## Planning artifacts retained for posterity

The 7 design docs in this folder remain accurate reference:

* [`README.md`](README.md) — task overview + per-vendor grammar
  matrix + decision rationale for independent-surface.
* [`01-canonical-model.md`](01-canonical-model.md) — schema
  decision (per-address vs merged-VRRP).
* [`02-per-vendor-grammar.md`](02-per-vendor-grammar.md) —
  per-codec grammar + MAC-format normalisation table.
* [`03-parse-render-touchpoints.md`](03-parse-render-touchpoints.md)
  — exact `file:line` insertion points; IRB-to-VLAN fold
  extension (now superseded by the shipped code).
* [`04-test-plan.md`](04-test-plan.md) — test inventory.
* [`05-capabilities-matrix-updates.md`](05-capabilities-matrix-updates.md)
  — `CapabilityMatrix` rows + `docs/CAPABILITIES.md` edits.
* [`06-fixture-targets.md`](06-fixture-targets.md) — fixture
  pull list.  IOS-XE SD-Access fabric-forwarding fixture remains
  a P1 gap (not available in public corpora today — see
  `tests/fixtures/real/WANTED.md`).

Future codec additions (NX-OS DAG from sibling task
`03-nxos-codec/`, AOS-CX `ip address virtual` whenever that
codec lands) should cite these docs for the canonical surface
design and the cross-vendor MAC-format conventions.
