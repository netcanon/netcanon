# Cisco IOS-XE → Juniper Junos

## Scenario

You operate a Cisco IOS-XE fleet (Catalyst 9300 / CSR1000v / Cat8000V)
and you're migrating a leaf or distribution layer to Juniper QFX or
EX.  You have hundreds of switches with a consistent pattern:
hostname, VLANs, switchport-mode access ports, infrastructure
descriptions, DNS / NTP servers, default route.  Hand-translating
isn't sustainable.

## What Netcanon does for you

**Translates:**

- `hostname` → `set system host-name`
- `vlan <id>` + `name` → `set vlans <name> vlan-id <id>`
- `interface ... switchport access vlan` → membership rolled up
  onto the canonical VLAN; rendered into Junos VLAN-centric form
- Interface descriptions, enabled/disabled state, MTU, IPv4 + IPv6
  addresses, VRF binding
- `ip name-server` → `set system name-server`
- `ntp server` → `set system ntp server`
- `ip route` → `set routing-options static route ... next-hop`
- `snmp-server community ... RO/RW` → `set snmp community ... authorization`
- LAGs (`Port-channel<N>`) → `ae<N>` aggregated-ethernet
- **Interface names**, translated across vendor conventions
  (`GigabitEthernet1/0/1` → `ge-1/0/1`) when a target profile is
  selected or the rename pane is engaged (see the checklist below)

**Deferred (Tier-3, see [`../CAPABILITIES.md`](../CAPABILITIES.md)):**

- Zone-based firewall, ACLs beyond simple grammar
- NAT (`ip nat inside source list`)
- IPsec VPN (crypto maps, IKEv2 profiles)
- QoS (`class-map` / `policy-map`)
- BGP / OSPF / EIGRP routing-protocol stanzas (informational only —
  not auto-rendered)

## Run the demo

```bash
python tools/demo.py --pair cisco__junos
```

Actual demo output:

```
INPUT (cisco_iosxe_cli)
========================================================================
hostname access-sw-01
!
vlan 10
 name DATA
!
vlan 20
 name VOICE
!
interface GigabitEthernet1/0/1
 description Server-A
 switchport mode access
 switchport access vlan 10
 no shutdown
!
interface GigabitEthernet1/0/2
 description Desk-Phone
 switchport mode access
 switchport access vlan 20
 no shutdown
!
interface GigabitEthernet1/0/24
 description Uplink-to-core
 switchport mode trunk
 switchport trunk allowed vlan 10,20
!
snmp-server community public RO
ip name-server 192.168.1.10
ip name-server 192.168.1.11
ntp server 192.168.1.20
!
ip route 0.0.0.0 0.0.0.0 192.168.1.1

OUTPUT (juniper_junos)
========================================================================
set system host-name access-sw-01
set system name-server 192.168.1.10
set system name-server 192.168.1.11
set system ntp server 192.168.1.20
set interfaces ge-1/0/1 description "Server-A"
set interfaces ge-1/0/1 unit 0 family ethernet-switching interface-mode access
set interfaces ge-1/0/1 unit 0 family ethernet-switching vlan members DATA
set interfaces ge-1/0/2 description "Desk-Phone"
set interfaces ge-1/0/2 unit 0 family ethernet-switching interface-mode access
set interfaces ge-1/0/2 unit 0 family ethernet-switching vlan members VOICE
set interfaces ge-1/0/24 description "Uplink-to-core"
set interfaces ge-1/0/24 unit 0 family ethernet-switching interface-mode trunk
set interfaces ge-1/0/24 unit 0 family ethernet-switching vlan members DATA
set interfaces ge-1/0/24 unit 0 family ethernet-switching vlan members VOICE
set vlans DATA vlan-id 10
set vlans VOICE vlan-id 20
set routing-options static route 0.0.0.0/0 next-hop 192.168.1.1
set snmp community public authorization read-only

========================================================================
Interface-name translations applied
========================================================================
  GigabitEthernet1/0/1 -> ge-1/0/1
  GigabitEthernet1/0/2 -> ge-1/0/2
  GigabitEthernet1/0/24 -> ge-1/0/24
```

The demo runs the rename-aware pipeline (the same path the browser UI
takes once you select a target profile), so Cisco interface names are
translated to native Junos form (`GigabitEthernet1/0/1` → `ge-1/0/1`)
rather than left verbatim.

## Tier-3 boundary

If your IOS-XE configs include `ip access-list extended`, `crypto ...`,
`router bgp`, `service-policy ...`, or zone-based firewall config,
those stanzas will be:

1. **Detected** by the parser
2. **Surfaced via the migrate-page Tier-3 banner** ("X firewall rules
   detected; not auto-translated")
3. **NOT rendered** into the Junos output

You'll need to hand-translate firewall + NAT + crypto separately.
That's by design — see [`../COMPARISON.md`](../COMPARISON.md) for
adjacent tools (Capirca / Aerleon for firewall ACL translation).

## Manual review checklist

Before applying the rendered Junos config to a real QFX/EX device,
verify:

- [ ] **Interface naming**: netcanon auto-translates names across
      vendor conventions (Cisco `GigabitEthernet1/0/1` → Junos
      `ge-1/0/1`).  Every `POST /api/v1/migration/plan` translation and
      the browser UI's standard translate flow do this **by default** —
      no target profile or rename map required.  (The low-level
      `run_plan` primitive still preserves names verbatim for callers
      that compose their own transforms.)  Verify the auto-mapping
      matches your slot/module layout before applying — the heuristic
      preserves the structural coordinates (`1/0/1`) but can't know
      your physical hardware; use the rename modal / a `port_rename_map`
      to override any port that needs a different target name.
- [ ] **VLAN-Vlan SVI mapping**: IOS-XE's `interface Vlan<id>` SVIs
      translate to Junos's `interface irb.<id>` form.  Verify the
      irb numbering matches your VLAN IDs.
- [ ] **Trunk port allowed-vlan lists**: comma-separated ranges
      (`switchport trunk allowed vlan 10,20,30-40`) round-trip
      through the VLAN-centric model; verify expansion is correct.
- [ ] **Hashed credentials**: Cisco type-9 hashes (`$9$`) survive
      round-trip; type-7 hashes are migration-blocked when targeting
      non-Cisco vendors and surface as `# REVIEW: ...` review
      comments in the rendered output.
- [ ] **Routing-protocol stanzas**: `router ospf`, `router bgp`,
      `router eigrp` are parse-tolerant but NOT auto-rendered.  Plan
      separate hand-translation for protocol config.

## See also

- [Cisco IOS-XE vendor page](../vendors/cisco_iosxe.md)
- [Juniper Junos vendor page](../vendors/juniper_junos.md)
- [`../CAPABILITIES.md`](../CAPABILITIES.md) — full capability matrix
- [`../TROUBLESHOOTING.md`](../TROUBLESHOOTING.md)
- [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md)
