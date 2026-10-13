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

becomes Arista output:

```
vlan 10
   name USERS

interface Vlan10
   ip address 192.168.10.1/24

interface 1
   switchport mode access
   switchport access vlan 10

interface 2
   switchport mode access
   switchport access vlan 10

... (interfaces 3-20 similar)
```

This is the canonical-intermediate-model paying off: AOS-S's
VLAN-centric `untagged 1-20` is read into the canonical
`CanonicalVlan.untagged_ports` list and onto a record for each of
the twenty ports — AOS-S prints no `interface` stanza for a port
with nothing of its own to say, and the parser gives it a record all
the same — and Arista writes each record as per-port `switchport
access vlan` directives.

**Note on port naming:** the demo emits bare numeric port names
(`interface 1`, `interface 2`, ...) — Arista accepts both bare-
numeric and `Ethernet<N>` forms.  If you want the Arista-canonical
`Ethernet1` / `Ethernet2` form, use the migrate-page rename modal
(web UI) or pass `port_rename_map` in the `POST /api/v1/migration/plan`
payload — the rename mesh propagates each AOS-S-numeric → Arista-
`Ethernet<N>` port rewrite to every surface that *references* the port
(VLAN tagged/untagged lists, LAG members, etc.), not just the interface
itself.  Renaming other identity classes has its own sibling fields
(`vlan_rename_map`, `local_user_rename_map`, `snmp_community_rename_map`,
`snmpv3_user_rename_map`).

**Two names in this output were not translated, and are right as
they stand.**  The AOS-S codec carries each VLAN's address on an
interface it names `Vlan10` / `Vlan20`, and the port translator does
not read that name: it is left as it is, and `netcanon demo` lists
both under its advisories (`could not classify port name 'Vlan10';
left verbatim`).  On EOS `interface Vlan10` is what that interface is
called, so through the migrate page or the API this job is
`completed` and neither name asks for a decision.  Onto a target
that calls the interface something else — Junos, AOS-CX — the same
two names hold the job `partial` until each has an entry in
`port_rename_map`.  See
[`../CAPABILITIES.md`](../CAPABILITIES.md) § D1.

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

- [ ] **Port-name expansion**: AOS-S `untagged 1-20` expands to bare
      `interface 1` through `interface 20` on Arista by default
      (Arista accepts both bare-numeric and `Ethernet<N>` forms).
      If you want canonical `Ethernet1` / `Ethernet2` naming, invoke
      the rename mesh — see the "Note on port naming" callout in the
      paradigm-flip section above.
- [ ] **Trunk port allowed-VLAN lists**: AOS-S `tagged 21-24` for
      VLAN 20 means "ports 21-24 are tagged in VLAN 20."  The Arista
      output shows `interface 21-24 / switchport mode trunk /
      switchport trunk allowed vlan 20` (bare numeric); verify if
      you have any multi-VLAN trunk patterns.
- [ ] **A port that is untagged in one VLAN and tagged in others**
      (none in this demo): it is written `switchport trunk native
      vlan <N>` with N ALSO on the allowed line, because a trunk's
      list is what it carries.  Release 0.7.7 and earlier left N off
      the allowed line, in jobs that said `completed`; what an EOS
      switch does with a native VLAN its list leaves out is not
      established from Arista's pages, so on a switch migrated then,
      add the native VLAN to the allowed list.  The demo's ports
      21-24 are tagged only (`no untagged 1-24` took them out of
      VLAN 1): they are written no native line, and an Arista trunk
      that states none uses native VLAN 1.
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
