# VLANs and switchport — NETCONF source rendered to IOS-XE CLI

For full bidirectional content (CLI form, OpenConfig XML form, model
divergence) see the sibling file
`../cisco_iosxe_cli_to_cisco_iosxe/vlans-and-switchport.md`.

## Direction-specific disposition

The OpenConfig NETCONF codec in this repository **does not parse**
`<network-instances><vlans>` or the `<switched-vlan>` augment under
ethernet interfaces.  The parse path only walks `<interfaces>` and
their IPv4 / IPv6 children.  Therefore:

* `intent.vlans` is always empty after NETCONF parse, regardless of
  what `<network-instances>` content was in the source XML.
* Per-interface `switchport_mode` / `access_vlan` / `trunk_*` /
  `voice_vlan` / `lag_member_of` are never populated.

| Canonical field | NETCONF -> CLI |
|---|---|
| `vlans[].id` | not_applicable — parser never populates |
| `vlans[].name` | not_applicable |
| `vlans[].description` | not_applicable |
| `vlans[].tagged_ports` | not_applicable |
| `vlans[].untagged_ports` | not_applicable |
| `vlans[].ipv4_addresses` (SVI) | not_applicable |

Once the NETCONF codec wires `openconfig-vlan` parsing, the cross-
pair flips to `good` for the canonical-stable surface — the CLI
codec's render path already emits `vlan <id> / name <X>` and the
per-interface `switchport mode` / `access vlan` / `trunk allowed
vlan` / `trunk native vlan` lines that exactly mirror the source
device's CLI grammar (same vendor, same operational state).

`voice_vlan` will remain `lossy` because OpenConfig's voice-VLAN
augment isn't universally supported and the codec may not parse it
even after the L2 wire-up lands.
