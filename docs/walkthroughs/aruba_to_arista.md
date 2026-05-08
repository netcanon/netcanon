# Aruba AOS-S → Arista EOS

## Scenario

You operate a fleet of HPE/Aruba 2920 / 2930F / 5400R switches and
you're refreshing to Arista DCS-7050S / 7280R for a DC consolidation.
The challenge: AOS-S uses a *VLAN-centric* grammar (positional port
lists per VLAN, `untagged 1-20 / tagged 21-24`) where Arista uses
*per-port* `switchport mode access vlan <id>`.  The translation
inverts the model.

## What Netcanon does for you

**Translates:**

- `hostname "..."` → `hostname ...`
- VLAN definitions (`vlan <id> / name "..." / untagged ... / tagged
  ...`) → projected into per-port `switchport access vlan` /
  `switchport trunk allowed vlan` form on Arista
- IPv4 SVI L3 (`vlan 10 / ip address ...`) → `interface Vlan10` with
  IP address on Arista
- Static routes (`ip default-gateway` / `ip route`) → `ip route`
- LAGs (`trk<N>`) → `Port-Channel<N>` with `channel-group N mode
  <mode>` on member Ethernets
- SNMP v1/v2c/v3 — `snmpv3 user` mappings; `snmp-server community`
- RADIUS — `radius-server host`
- Local users — `password manager sha1` hashes form-preserved
  (caveat: hash-portability policy may require re-issue)

**Deferred (Tier-3):**

- AOS-S specific firewall (`access-list extended` beyond simple ACL)
- Routing-protocol stanzas (RIP / OSPF) parse-tolerant but not
  auto-rendered
- PoE policy detail beyond per-port `power-over-ethernet enable`

## Run the demo

```bash
python tools/demo.py --pair aruba__arista
```

The embedded scenario covers hostname, three VLANs (DEFAULT, USERS
with port range 1-20, MGMT with tagged 21-24), inter-VLAN L3 IPs,
default gateway, DNS, and an SNMP community.

## Paradigm flip — the headline transformation

The interesting bit of this pair is the model inversion.  AOS-S
input:

```
vlan 10
   name "USERS"
   untagged 1-20
   ip address 192.168.10.1 255.255.255.0
```

becomes Arista output (conceptually):

```
vlan 10
   name USERS

interface Vlan10
   ip address 192.168.10.1/24

interface Ethernet1
   switchport mode access
   switchport access vlan 10

interface Ethernet2
   switchport mode access
   switchport access vlan 10

... (Ethernet3-20 similar)
```

This is the canonical-intermediate-model paying off: AOS-S's
VLAN-centric `untagged 1-20` projects through the canonical
`CanonicalVlan.untagged_ports` list, then re-projects into Arista's
per-port `switchport access vlan` directives via the
`project_vlan_to_switchport` transform.

## Tier-3 boundary in this scenario

Switch refreshes are mostly Tier-1/2 surface — interfaces, VLANs,
SVIs, static routes, basic AAA/SNMP.  The Tier-3 banner usually shows
empty or near-empty for AOS-S → Arista migrations.  Watch for:

- `dhcp-snooping` — Aruba has rich `authorized-server` lists +
  trust-port + VLAN scope.  Arista has `dhcp snooping` but the
  semantic + grammar differ.  **Currently parse-only on the AOS-S
  side; Arista render path is future work.**
- `web-management ssl` / `ip authorized-managers` — management-plane
  ACLs, parse-tolerant.

## Manual review checklist

Before deploying the rendered Arista config to a real DCS device,
verify:

- [ ] **Port-name expansion**: AOS-S `untagged 1-20` should expand to
      `Ethernet1` through `Ethernet20` on Arista (not `Eth1/1-20`).
      The port-name rename mesh handles this automatically; verify
      the mapping for your specific Arista platform's port
      enumeration.
- [ ] **Trunk port allowed-VLAN lists**: AOS-S `tagged 21-24` for
      VLAN 20 means "ports 21-24 are tagged in VLAN 20."  The Arista
      output should show `interface EthernetN / switchport trunk
      allowed vlan 20` for ports 21-24.  Verify if you have any
      multi-VLAN trunk patterns.
- [ ] **MLAG**: if you're consolidating to an Arista MLAG pair, the
      `Port-Channel` reconciliation will translate AOS-S `trk<N>` to
      `Port-Channel<N>`.  Plan the MLAG peer-link config natively
      on Arista (not auto-rendered).
- [ ] **`include-credentials` mode**: AOS-S has two modes; running-
      config exposure of hashed passwords differs.  Hashes
      (`password manager sha1`) round-trip with format preservation
      but may need re-issue on Arista for production.
- [ ] **Spanning-tree mode**: AOS-S defaults to RSTP; Arista DCS-
      series often runs MSTP.  Verify the target spanning-tree mode
      matches your DC fabric design.

## See also

- [Aruba AOS-S vendor page](../vendors/aruba_aoss.md)
- [Arista EOS vendor page](../vendors/arista_eos.md)
- [`../CAPABILITIES.md`](../CAPABILITIES.md)
- [`../HOW_WE_TEST.md`](../HOW_WE_TEST.md) — the cross-mesh audit
  that pins this pair's translation accuracy
- [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md)
