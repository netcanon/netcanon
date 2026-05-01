# VLAN configuration: Aruba AOS-S versus FortiGate FortiOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Advanced Traffic Management Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

VLAN definition syntax (verbatim from the manual's worked examples):

```
vlan 10
   name "USERS"
   untagged 1-12
   tagged 23-24
   ip address 10.10.10.1 255.255.255.0
   exit
vlan 20
   name "VOICE"
   untagged 13-20
   tagged 23-24
   ip address 10.10.20.1/24
   exit
```

Membership is **VLAN-centric**: the VLAN stanza itself enumerates
the port lists with `tagged <port-list>` / `untagged <port-list>`
lines.  Port lists accept ranges (`1-24`), comma-separated lists
(`25,26`), or mixed (`A1-A4,B1`).  The SVI's L3 address is also
absorbed into the VLAN stanza — there is no separate `interface
Vlan10` stanza on AOS-S.

VLAN names are quoted; the manual notes "VLAN names can be 32
characters or fewer".  VLAN IDs 1-4094 are valid (1 reserved as
`DEFAULT_VLAN`).

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate Cookbook — VLAN configuration](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/) (`config system interface / set type vlan`).
Source: [Fortinet FortiOS CLI Reference](https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/).
Retrieved: 2026-04-30

FortiGate models VLANs as **child interfaces** hanging off a
parent (physical or aggregate); there is no first-class `vlan`
global object.  The standard pattern uses a dotted name
(`<parent>.<vlanid>`) but operators may use any edit name:

```
config system interface
    edit "port4.300"
        set alias "guest-vlan-300"
        set type vlan
        set vlanid 300
        set interface "port4"
        set ip 10.30.0.1 255.255.255.0
        set status down
    next
    edit "VL_200"
        set alias "voice-vlan-200"
        set vlanid 200
        set interface "agg1"
        set ip 10.200.0.1 255.255.255.0
        set status up
    next
end
```

Notable FortiOS specifics:

- **No global VLAN object.**  VLAN identity is carried by the
  child-interface edit ID + `set vlanid` numeric.  Multiple ports
  cannot share a VLAN by membership — each L3 attachment requires
  its own child interface.
- **Per-VLAN tagged/untagged port list does not exist.**  FortiGate
  is L3-only beyond the hardware-switch sub-feature on a few
  low-end models (FortiGate 60E series).  L2 trunking is expressed
  by configuring multiple VLAN child interfaces on the same
  parent.
- **VLAN name = edit ID** by convention.  Aruba's separate VLAN
  name string does not survive cross-vendor.

## Cross-vendor mapping (Aruba -> FortiGate)

Canonical surface:

```
class CanonicalVlan(BaseModel):
    id: int
    name: str = ""
    description: str = ""
    tagged_ports: list[str]
    untagged_ports: list[str]
    ipv4_addresses: list[CanonicalIPv4Address]
```

- **id** — `good`.  Direct preservation.
- **name** — `lossy`.  FortiGate render uses the edit ID as
  identity; the canonical name lands as `set alias` (capped 25
  chars) but is not the primary identity.
- **description** — `lossy`.  Aruba has no per-VLAN description
  field beyond `name`; if both vendors carried one, FortiGate has
  no `set description` on a VLAN edit.
- **tagged_ports / untagged_ports** — `lossy`.  This is the
  hard model-translation gap: Aruba's port list per VLAN does not
  map to FortiGate's child-interface model.  Cross-vendor render
  on Aruba -> FortiGate would need to synthesise N VLAN child
  interfaces (one per parent port × per VLAN), which the v1
  render does not do.  Operators must manually reconstruct multi-
  port VLAN membership on FortiGate post-migration.
- **ipv4_addresses (SVI absorption)** — `good`.  Aruba's `vlan 10
  / ip address X/N` populates `CanonicalVlan.ipv4_addresses`;
  FortiGate render emits the address on the synthesised VLAN
  child interface (`set ip`).

Disposition: **lossy**.  Reason: model translation gap —
FortiGate's child-interface VLAN model has no primitive for
"this VLAN's tagged port list".
