# Per-vendor "What works for me?" pages

Operator-facing pages — one per vendor family — answering "I run vendor
X, what does Netcanon do for me?".  These pages condense the per-codec
capability declarations + real-world fixture coverage into a
single-page operator readout.

The full per-codec capability matrix lives in
[`../CAPABILITIES.md`](../CAPABILITIES.md); per-codec live
certification state lives in
[`../../tests/fixtures/real/RESULTS.md`](../../tests/fixtures/real/RESULTS.md).
Both are sources of truth — the per-vendor pages here LINK to them
rather than duplicate.

## The pages

| Vendor family | Page | Codecs | Certification |
|---|---|---|---|
| Cisco IOS-XE | [`cisco_iosxe.md`](cisco_iosxe.md) | `cisco_iosxe_cli`, `cisco_iosxe` | certified (CLI), best_effort (NETCONF) |
| Juniper Junos | [`juniper_junos.md`](juniper_junos.md) | `juniper_junos` | certified |
| Aruba AOS-S | [`aruba_aoss.md`](aruba_aoss.md) | `aruba_aoss` | certified |
| Arista EOS | [`arista_eos.md`](arista_eos.md) | `arista_eos` | certified |
| Fortinet FortiGate | [`fortigate.md`](fortigate.md) | `fortigate_cli` | certified |
| MikroTik RouterOS | [`mikrotik_routeros.md`](mikrotik_routeros.md) | `mikrotik_routeros` | certified |
| OPNsense | [`opnsense.md`](opnsense.md) | `opnsense` | certified |

## Page format

Every page follows the same shape:

1. **TL;DR** — codec(s) + certification state.
2. **What translates well** — Tier-1 + Tier-2 surfaces from the
   capability matrix.
3. **L3 redundancy** (v0.2.0+) — VRRP / HSRP / VARP / virtual-
   gateway / CARP wire-up status; cross-references the
   `docs/v0.2.0-planning/01-vrrp-canonical/` and
   `docs/v0.2.0-planning/02-anycast-gateway/` design docs.
4. **Lossy paths** — declared lossy with cited reasons.
5. **What we don't do** — Tier-3 boundary (firewall, NAT, VPN, QoS,
   routing protocols).
6. **Real-world fixtures** — what's been validated against (links
   into `NOTICE.md` provenance).
7. **Common gotchas** — vendor-specific.
8. **See also** — capability matrix, certification state, fixture
   provenance, bug-reporting workflow.

## See also

- [`../CAPABILITIES.md`](../CAPABILITIES.md) — full capability matrix
  (the source of truth)
- [`../../tests/fixtures/real/RESULTS.md`](../../tests/fixtures/real/RESULTS.md)
  — live per-codec certification state
- [`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — real-capture fixture provenance + sanitisation notes
- [`../HOW_WE_TEST.md`](../HOW_WE_TEST.md) — the cross-mesh audit
  harness that gates these certifications
- [`../TROUBLESHOOTING.md`](../TROUBLESHOOTING.md) — when a
  translation doesn't go cleanly
- [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md) — the
  fixture-submission workflow
