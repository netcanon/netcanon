# Walkthroughs

Narrative walkthroughs of real-world migration scenarios.  Where the
[per-vendor pages](../vendors/) are reference docs ("what does Netcanon
do for vendor X?"), these are *workflow* docs ("you have a fleet of X
and want to migrate to Y — here's the path, the friction points, and
the manual review checklist at the end").

Each walkthrough is paired with a reproducible demo scenario in
[`tools/demo.py`](../../tools/demo.py).  Run the demo to see exactly
what the operator sees:

```bash
python tools/demo.py --list                 # show every available pair
python tools/demo.py --pair cisco__junos    # run a specific scenario
```

## The pages

| Walkthrough | Demo scenario | Frame |
|---|---|---|
| [Cisco IOS-XE → Juniper Junos](cisco_iosxe_to_junos.md) | `cisco__junos` | Data-center leaf migration: VLANs + interfaces + static routes |
| [FortiGate → MikroTik RouterOS](fortigate_to_mikrotik.md) | `fortigate__mikrotik` | Branch-firewall consolidation: DNS + interfaces + DHCP pools |
| [Aruba AOS-S → Arista EOS](aruba_to_arista.md) | `aruba__arista` | Switch refresh: VLAN-centric → port-centric grammar |
| [OPNsense → Juniper Junos](opnsense_to_junos.md) | `opnsense__junos` | Edge-firewall migration with explicit Tier-3 boundary |

## Walkthrough format

Every walkthrough follows the same shape:

1. **Scenario** — operator's situation in 1-2 sentences
2. **What Netcanon does for you** — what's covered + what's not
3. **Run the demo** — copy-pasteable command + sample output
4. **Tier-3 boundary** — what gets dropped on this pair and why
5. **Manual review checklist** — what to verify after the rendered config is delivered, before applying to a target device
6. **See also** — capabilities matrix, vendor pages, troubleshooting

The walkthroughs are intentionally short.  They give operators a
30-second answer to "should I be using Netcanon for this migration?"
and a 5-minute answer to "what's the actual workflow look like?".
The deep technical detail lives in the per-vendor pages and the
capability matrix.

## Why these four pairs

The four scenarios were picked to span:

* **Different paradigms** — Cisco's per-interface vs Junos's
  VLAN-centric; AOS-S banner-positional vs Arista per-port; OPNsense
  XML vs Junos set-form.
* **Different scope** — switch / firewall / edge router; Tier-1 only
  vs heavy Tier-3 deferral.
* **Different operator workflows** — DC leaf, branch firewall, switch
  refresh, edge migration.

If your migration doesn't match one of these four exactly, the closest
walkthrough still applies — the matrix-honesty discipline (what's
supported, lossy, unsupported per pair) is the same regardless.

## See also

- [`../vendors/`](../vendors/) — per-vendor reference pages
- [`../CAPABILITIES.md`](../CAPABILITIES.md) — full capability matrix
- [`../HOW_WE_TEST.md`](../HOW_WE_TEST.md) — the cross-mesh audit
- [`../TROUBLESHOOTING.md`](../TROUBLESHOOTING.md) — when a walkthrough
  doesn't translate cleanly for your input
- [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md) — submit a
  fixture / bug
- [`../../tools/demo.py`](../../tools/demo.py) — the runnable demo
  script paired with these walkthroughs
