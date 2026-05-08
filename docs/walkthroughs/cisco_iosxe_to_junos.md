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
- LAGs (`Port-channel<N>`) → `ae<N>` aggregated-ethernet

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

Sample output (truncated):

```
SCENARIO: Cisco IOS-XE -> Juniper Junos
========================================================================

INPUT (cisco_iosxe_cli)
========================================================================
hostname leaf-01
!
vlan 10
 name DATA
!
interface GigabitEthernet0/0/0
 description Uplink to spine
 switchport access vlan 10
!
ip route 0.0.0.0 0.0.0.0 192.168.1.1

OUTPUT (juniper_junos)
========================================================================
set system host-name leaf-01
set system name-server 192.168.1.10
set system name-server 192.168.1.11
set system ntp server 192.168.1.20
set interfaces GigabitEthernet0/0/0 description "Uplink to spine"
set interfaces GigabitEthernet0/0/1 description "Server-A"
set vlans DATA vlan-id 10
set vlans VOICE vlan-id 20
set routing-options static route 0.0.0.0/0 next-hop 192.168.1.1
```

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

- [ ] **Interface naming**: Cisco `GigabitEthernet0/0/0` becomes the
      same string in Junos because Netcanon preserves names by
      default.  If you want `ge-0/0/0` mapping, run with
      `--rename-interfaces` (the rename mesh handles
      Cisco↔Junos↔Arista name translation).
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
