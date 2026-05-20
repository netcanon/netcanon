# IMPLEMENTED

This planning task shipped in:

* **Wave A (schema)**: commit `c5da044`
  — `feat(canonical): Wave A — VRRP / anycast / per-VRF static-route schema (ship-before-wire)`
* **Wave B (codec wire-up across 7 codecs)**: commit `e542b49`
  — `feat(codecs): Wave B + C — VRRP / HSRP / CARP / anycast-gateway wired across 7 codecs`

The IOS-XE password round-trip bugfix (`b85c39c`) was a side-quest
spawned during this work — it cleared the last blocker for round-
tripping the `batfish_iosxe_basic_vrrp.txt` fixture verbatim and is
counted under v0.2.0 cumulative even though it isn't VRRP-specific.

## What landed

* `CanonicalVRRPGroup` model with `mode in {"vrrp", "hsrp", "carp"}`
  discriminator (free string, not enum — codecs can extend).  Fields:
  `group_id` (1-255), `mode`, `virtual_ips`, `virtual_ipv6s`,
  `virtual_mac`, `priority` (1-254), `preempt`,
  `advertisement_interval`, `authentication` (opaque
  `"<scheme>:<value>"` token), `track_interfaces`, `description`.
* `CanonicalInterface.vrrp_groups: list[CanonicalVRRPGroup]`
  attachment point.
* Per-codec parse + render wire-up across **7 bidirectional codecs**:
  cisco_iosxe_cli, juniper_junos, arista_eos, aruba_aoss,
  fortigate_cli, mikrotik_routeros, opnsense (CARP variant).
* The HYBRID resolution from the synthesis README adopted as
  shipped: classic FHRP and anycast share NO canonical record;
  classic FHRP is a router-group election (group_id, priority,
  preempt are domain primitives); anycast is an IP-address property
  (lives on `CanonicalIPv4Address` / `CanonicalIPv6Address` — see
  sibling task `02-anycast-gateway/IMPLEMENTED.md`).
* Authoritative per-codec graduation state lives in
  [`tests/unit/migration/test_canonical_vrrp_anycast_schema.py`](../../../tests/unit/migration/test_canonical_vrrp_anycast_schema.py)
  `_WIRED_UP_BY_CODEC`.  Two-sided invariant enforced on every
  capability-matrix change: graduated paths MUST NOT be
  `unsupported`; un-graduated paths MUST be `unsupported`.
* **149 new codec-level tests + 31 Wave A schema tests = 180 new
  tests**.  Full unit suite: 3341 passed / 56 skipped / 0 failed
  on the post-Wave-C baseline.

## Per-codec scope highlights (from the merge commit)

* **cisco_iosxe_cli**: classic single-line per-attribute VRRP
  grammar; modern address-family form parses to group-ID-only
  shell with `lossy` declaration documenting the gap.
* **juniper_junos**: `set interfaces ... unit N family inet
  address X vrrp-group M virtual-address Y / priority / preempt /
  advertise-interval / track interface / authentication-type+key /
  description / accept-data`.  Per-VRF static route flipped to
  `lossy` (routing-instances dispatcher needs per-VRF static
  harvest — separate scope).
* **arista_eos**: classic + modern multi-line, priority / preempt
  / track / timers / description / mac-address / auth-md5 /
  auth-text.  Plus VARP system-wide MAC (Wave C).
* **aruba_aoss**: nested inside `vlan N` stanza; attaches via
  the existing SVI-absorption rules; AOS-S `preempt` vendor-
  default is `False` (unlike Cisco `True`).
* **fortigate_cli**: nested `config vrrp / edit N / set vrip X`
  inside `config system interface / edit X`; `set vrip6` triggers
  implicit `set version 3` on render.
* **mikrotik_routeros**: two-stage parse correlation
  (`/interface vrrp` declarations in scratch; `/ip address` lines
  binding to `vrrp<N>` pseudo-interfaces route into the
  corresponding group's `virtual_ips`).  `v3-protocol=ipv6`
  discriminator routes to `virtual_ipv6s`.
* **opnsense (CARP)**: walks `<virtualip><vip>` children, filters
  by `<mode>carp</mode>` (silently skipping `ipalias`,
  `proxyarp`, `vrrp` modes).  Inverted advskew->priority
  normalisation: `priority = 254 - advskew` (CARP lower-wins,
  canonical higher-wins) declared `lossy`.  Authentication
  `<password>X</password>` stores as `carp-key:X` canonical form.

## What was deferred to a future PR

* **Cisco IOS-XE NETCONF stub (`cisco_iosxe`)** — every new path
  still `unsupported` per its Phase-0.5 stub policy.  Wire-up
  blocked on the OpenConfig `openconfig-if-ip:vrrp` augment work
  the stub doesn't model today.
* **Modern VRRP address-family multi-line form** (Arista EOS +
  Cisco IOS-XE) — parses to group-ID-only shell; per-AF
  attribute round-trip declared `lossy` for now (no fixture
  coverage exercises the modern form yet).
* **Cisco IOS-XE IPv6 anycast** — kept `unsupported` (no fixture
  coverage today; SD-Access IPv6-anycast public corpus is empty).
* **Junos per-VRF static-route harvest** — flipped to `lossy`
  rather than `supported` because the routing-instances
  dispatcher doesn't yet harvest per-VRF statics.  Separate scope.
* **NX-OS HSRP wire-up** — gated on the NX-OS codec landing
  (Tier-D in `tests/fixtures/real/WANTED.md`; design in sibling
  task `03-nxos-codec/`).  Phase 2 of that codec consumes this
  task's `CanonicalVRRPGroup` directly.
* **IOS-XR VRRP wire-up** — gated on the IOS-XR codec landing
  (sibling task `04-iosxr-codec/`).

## Planning artifacts retained for posterity

The 7 design docs in this folder remain accurate reference for the
design rationale, per-vendor grammar tables, and test-shape
patterns:

* [`README.md`](README.md) — task overview + cross-vendor grammar
  matrix.
* [`01-canonical-model.md`](01-canonical-model.md) — schema
  field justifications.
* [`02-per-vendor-grammar.md`](02-per-vendor-grammar.md) —
  per-codec grammar + edge cases (still useful for the NX-OS HSRP
  and IOS-XR VRRP work in v0.3.0+).
* [`03-parse-render-touchpoints.md`](03-parse-render-touchpoints.md)
  — exact `file:line` insertion points (now superseded by the
  shipped code; kept as the design-of-record).
* [`04-test-plan.md`](04-test-plan.md) — test inventory; actual
  shipped counts ran ahead (149 codec tests vs ~80-120
  estimated).
* [`05-capabilities-matrix-updates.md`](05-capabilities-matrix-updates.md)
  — `CapabilityMatrix` rows + `docs/CAPABILITIES.md` edits.
* [`06-fixture-targets.md`](06-fixture-targets.md) — fixture
  pull list (most codecs still need real VRRP fixtures; tracked
  in `tests/fixtures/real/WANTED.md`).

Future codec additions (NX-OS HSRP from sibling task
`03-nxos-codec/`, IOS-XR VRRP from `04-iosxr-codec/`) should cite
these docs for the canonical surface design and the per-vendor
grammar conventions.
