# What the AOS-S target codec accepts vs what the cisco_iosxe parse emits

Source: `netcanon.migration.codecs.aruba_aoss.codec.ArubaAOSSCodec` capability matrix
Retrieved: 2026-05-01

Source: [Aruba ArubaOS-Switch 16.11 Management and Configuration Guide](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-05-01

## AOS-S target — full-feature certified

The `aruba_aoss` codec is `certified` (the highest tier in the
codec taxonomy).  Its CapabilityMatrix declares the full canonical
surface as `supported`:

* `/system/hostname`, `/system/dns-server`, `/system/ntp-server`
* `/interfaces/interface/*` (name / description / enabled / type / IPv4 / IPv6)
* `/vlans/vlan/*` (id / name / tagged-ports / untagged-ports)
* `/routing/static-route`
* `/snmp/*` including `/snmp/v3-user`

The ONLY paths declared `unsupported` are:

* `/filter/rule` — Tier 3 ACLs, never auto-rendered
* `/vxlan-vnis/*` — AOS-S has no VXLAN concept

## What arrives from cisco_iosxe NETCONF parse

Almost nothing.  See `oc-parse-narrow.md` — the parser populates
`intent.interfaces` and leaves every other field empty.

## What the AOS-S render emits given that empty input

The aruba_aoss render walks the canonical tree:

* `intent.hostname == ""` -> no `hostname` line emitted
* `intent.dns_servers == []` -> no `ip dns server-address` lines
* `intent.snmp is None` -> no `snmp-server` lines
* `intent.vlans == []` -> no `vlan N` stanzas
* `intent.static_routes == []` -> no `ip route` lines
* `intent.local_users == []` -> no `password manager` lines
* `intent.radius_servers == []` -> no `radius-server` lines
* `intent.lags == []` -> no `trunk` lines

The output AOS-S CLI carries ONLY interface stanzas and (where the
synthesised SVI carries L3) inline VLAN-stanza-with-IP-address
fragments rendered through the aruba_aoss SVI absorption code path.

## Why this isn't `unsupported`

The AOS-S target accepts each of these categories perfectly.  The
gap is at the cisco_iosxe SOURCE parser, which doesn't extract the
data for the target to render.  Schema-wise this is
`not_applicable` (source field never populated) rather than
`unsupported` (target couldn't accept) or `lossy` (would be data
loss).

This is the same schema-vs-vendor classification asymmetry called
out in the `cisco_iosxe__cisco_iosxe_cli` reverse pair: when the
source wire format already lost the data, downstream classification
labels it `not_applicable` even though operationally it feels like
data loss.

## Disposition summary

For nearly every category outside `interfaces[].*`: **not_applicable**.
The reason field cites the cisco_iosxe parse-side wire-up gap and
notes that the AOS-S target accepts the path natively (so flips to
`good` once the parser is wired).
