# OpenConfig YANG vs Cisco-IOS-XE-native YANG (NETCONF -> CLI direction)

## Background

Cisco IOS-XE platforms (Catalyst 9K, ISR, ASR1K, Cat8000V, CSR1Kv)
expose a single configuration database through three independent
schemas — CLI, Cisco-IOS-XE-native YANG, and OpenConfig YANG.  See
the sibling file
`../cisco_iosxe_cli_to_cisco_iosxe/oc-vs-native-yang.md` for the
full framing.

Source: [Native, IETF, OpenConfig... Why so many YANG models? — Cisco
Blogs](https://blogs.cisco.com/developer/which-yang-model-to-use)
(retrieved 2026-04-30):

> "Cisco models are typically a superset of what OpenConfig offers,
> and requests for an OpenConfig data element are converted to the
> corresponding native data element."

## Direction-specific framing: NETCONF source -> CLI target

When NETCONF is the **source**, the codec's parse path consumes the
OpenConfig XML returned by the device.  Two material consequences:

1. **CLI-target render is structurally lossless for what NETCONF
   parsed** — the CLI codec models a strict superset of what
   OpenConfig exposes (Cisco models are a superset of OpenConfig per
   the blog quote above), and the CLI is the operator-facing surface
   the device's NETCONF agent translates to / from.  Anything
   OpenConfig conveys, CLI can also convey.

2. **The "loss" is upstream of the codec pair** — it happens at the
   `<get-config>` boundary on the device itself.  When OpenConfig
   doesn't model a CLI feature (banner motd, service timestamps,
   route-maps, etc.), the NETCONF response simply doesn't include it.
   By the time the codec sees the XML, the data is already gone.
   Therefore the cross-pair disposition for those fields is
   `not_applicable` (the source NEVER had it) rather than `lossy`
   (the source had it and we're losing it).

This is the inverse of the CLI -> NETCONF case, where the CLI
source is structurally richer and the loss is real.

## Cross-pair disposition baseline (NETCONF -> CLI)

For canonical fields that OpenConfig models AND the NETCONF codec
in this repository wires:

* Same-vendor `good` for the modelled surface (interface name,
  description, enabled, type, IPv4 / IPv6).  No semantic loss; CLI
  render emits valid `running-config` text that the device would
  accept.

For canonical fields that OpenConfig models but the NETCONF codec
**doesn't yet wire** (the Phase-0.5 stub limitation):

* Cross-pair shows `not_applicable` because the NETCONF parser never
  populates these fields — `intent.vlans`, `intent.snmp`,
  `intent.lags`, `intent.routing_instances` etc. are all empty after
  parse.  CLI render emits an empty config for those sections, which
  is correct given an empty input.

For canonical fields OpenConfig itself doesn't model (banner motd,
`service timestamps`, EXEC-only commands):

* These are not in the canonical model either, so they're invisible
  to the cross-pair entirely.  Disposition `not_applicable` for
  consistency with the framing above.

The net effect: NETCONF -> CLI looks "cleaner" than CLI -> NETCONF in
the disposition matrix (more `good` / `not_applicable`, fewer
`unsupported`).  This is **not** because NETCONF -> CLI loses less
information — it's because the loss happens upstream of the codec
boundary.  Operators relying on this pair must remember that the
NETCONF source is **already** a lossy projection of the device's
real running-config; the CLI render is faithful to the projection,
not to the original config.

Confidence: **high** for the framing; **medium** for per-field
because the OpenConfig codec under-implements its declared
capability matrix.
