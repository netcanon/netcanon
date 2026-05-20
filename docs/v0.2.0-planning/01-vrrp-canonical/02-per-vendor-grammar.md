# 02 — Per-vendor grammar reference

For each of the 7 bidirectional codecs + the NETCONF stub, this file
captures:

1. Codec module path
2. 5-10 lines of the vendor's VRRP grammar with source citation
3. Field-by-field mapping (vendor token → canonical field)
4. Edge cases (multi-group, IPv6, secondary virtual IPs, auth, track)

Where a "wire example" line is from a real fixture in the corpus,
the line number is cited from
`tests/fixtures/real/<vendor>/<file>`. Where it is from vendor
documentation, the citation includes the doc title + version.

---

## 1. Cisco IOS-XE CLI (`cisco_iosxe_cli`)

**Codec module:** [`netcanon/migration/codecs/cisco_iosxe_cli/`](../../../netcanon/migration/codecs/cisco_iosxe_cli/)
* parse: [`parse.py:585`](../../../netcanon/migration/codecs/cisco_iosxe_cli/parse.py) (`_parse_interfaces`)
* render: [`render.py:252`](../../../netcanon/migration/codecs/cisco_iosxe_cli/render.py) (interface render loop)
* capabilities: defined in [`codec.py`](../../../netcanon/migration/codecs/cisco_iosxe_cli/codec.py)

### Grammar (from `tests/fixtures/real/cisco_iosxe/batfish_iosxe_basic_vrrp.txt`)

```text
interface GigabitEthernet0/2
 ip address 192.168.1.1 255.255.255.0
 duplex auto
 speed auto
 media-type rj45
 vrrp 12 ip 192.168.1.254
 vrrp 12 priority 110
!
```
(lines 80-87 of the fixture)

Additional grammar from Cisco IP Addressing Services Configuration
Guide, IOS-XE 17.x, "Configuring VRRP" chapter (publicly available
at cisco.com/c/en/us/td/docs/ios-xml/ios/ipapp_fhrp):

```text
interface GigabitEthernet0/0/1
 vrrp 10 ip 10.1.10.254
 vrrp 10 ip 10.1.10.253 secondary
 vrrp 10 priority 110
 vrrp 10 preempt delay minimum 30
 vrrp 10 description CORE-GW
 vrrp 10 authentication md5 key-string SECRET
 vrrp 10 track 1 decrement 20
 vrrp 10 timers advertise 3
 vrrp 10 ipv6 fe80::1
!
```

Also IOS-XE 17.12+ adds the modern Address Family form:

```text
interface GigabitEthernet0/0/2
 vrrp 10 address-family ipv4
  address 10.1.20.254 primary
  priority 110
  preempt
 exit
!
```

### Field mapping

| Wire token | Canonical field | Notes |
|---|---|---|
| `vrrp N ip X` | `group_id=N`, `virtual_ips=[X]` | first occurrence creates the group |
| `vrrp N ip X secondary` | append `X` to `virtual_ips` | second + IP per VRID |
| `vrrp N ipv6 X` | append `X` to `virtual_ipv6s` | VRRPv3 |
| `vrrp N priority P` | `priority=P` | |
| `vrrp N preempt` | `preempt=True` | default is true already |
| `no vrrp N preempt` | `preempt=False` | |
| `vrrp N description "<text>"` | `description="<text>"` | |
| `vrrp N authentication md5 key-string SECRET` | `authentication="md5:SECRET"` | opaque pass-through |
| `vrrp N authentication text PASSWORD` | `authentication="plain:PASSWORD"` | |
| `vrrp N track <obj> decrement <D>` | `track_interfaces=[<obj>]` | decrement is Lossy |
| `vrrp N timers advertise <S>` | `advertisement_interval=S` | seconds form |
| `vrrp N timers advertise msec <MS>` | flag as Lossy | msec form drops to default 1s |

### Edge cases

* **Multiple groups per interface.** IOS-XE accepts arbitrary
  VRID numbers on the same port; codec parses all of them into
  `vrrp_groups: list`. Test: 2-group fixture.
* **IPv6 (VRRPv3).** `vrrp N ipv6 X` populates `virtual_ipv6s`;
  same VRID can carry both v4 + v6.
* **Address-family modern form.** IOS-XE 17.12+ uses nested
  `address-family ipv4` block. Parser must recognise both forms;
  render emits the legacy form for v1 (broader compatibility).
  Modern form is `lossy` until proven by a real fixture.
* **Track-object with decrement.** `track 1 decrement 20` —
  track object 1 (which has its own SLA/route binding declared
  in a top-level `track 1 ...` stanza). Canonical surfaces only
  the object name; decrement is Lossy. The track-object stanza
  itself parses-and-ignores (Tier-3 territory).
* **Authentication.** Plaintext authentication is deprecated;
  MD5 form is the only one in modern fixtures. Codec carries
  the opaque blob.
* **Preempt delay.** `preempt delay minimum N` adds a startup
  delay before claiming master role. Lossy — only the bare
  `preempt` boolean survives.
* **`vrrp N shutdown`.** Disables the group while keeping
  config. Not in canonical model in v0.2.0; surfaces as Lossy.

---

## 2. Cisco IOS-XE NETCONF (`cisco_iosxe`)

**Codec module:** [`netcanon/migration/codecs/cisco_iosxe/`](../../../netcanon/migration/codecs/cisco_iosxe/)
* parse: [`codec.py:474`](../../../netcanon/migration/codecs/cisco_iosxe/codec.py) (`parse`)
* render: [`codec.py:602`](../../../netcanon/migration/codecs/cisco_iosxe/codec.py) (`_render_canonical`)
* capabilities: [`codec.py:191`](../../../netcanon/migration/codecs/cisco_iosxe/codec.py)

### Grammar (from OpenConfig `openconfig-if-ip` v0.4 augmentation)

```xml
<interfaces xmlns="http://openconfig.net/yang/interfaces">
  <interface>
    <name>GigabitEthernet0/0/2</name>
    <subinterfaces>
      <subinterface>
        <ipv4 xmlns="http://openconfig.net/yang/interfaces/ip">
          <addresses><address>
            <ip>192.168.1.1</ip>
            <vrrp xmlns="http://openconfig.net/yang/interfaces/ip">
              <vrrp-group>
                <virtual-router-id>10</virtual-router-id>
                <config>
                  <virtual-router-id>10</virtual-router-id>
                  <virtual-address>192.168.1.254</virtual-address>
                  <priority>110</priority>
                  <preempt>true</preempt>
                </config>
              </vrrp-group>
            </vrrp>
          </address></addresses>
        </ipv4>
      </subinterface>
    </subinterfaces>
  </interface>
</interfaces>
```

### Field mapping

This codec is a Phase-0.5 stub — its `_render_canonical()`
emits only the `openconfig-interfaces` subtree (see
`codec.py:191` capability matrix). For v0.2.0 the codec stays
**unsupported** on `/interfaces/interface/vrrp_groups`. The
matrix declaration matches the existing `/snmp/v3-user`,
`/vxlan-vnis/vni`, `/routing-instances/instance` pattern.

Implementation note: when the NETCONF codec gets a full
canonical render path (Phase 1+), the `vrrp_groups` field
serialises via the schema above. For v0.2.0 this is a
**capability-matrix-only** change (~5 LOC).

### Edge cases

None in scope — the matrix flags unsupported and the cross-mesh
audit picks up the gap.

---

## 3. Arista EOS (`arista_eos`)

**Codec module:** [`netcanon/migration/codecs/arista_eos/`](../../../netcanon/migration/codecs/arista_eos/)
* parse: [`parse.py:860`](../../../netcanon/migration/codecs/arista_eos/parse.py) (`_apply_iface_subcommand`)
* render: [`render.py:478`](../../../netcanon/migration/codecs/arista_eos/render.py) (interface render loop)
* capabilities: [`codec.py`](../../../netcanon/migration/codecs/arista_eos/codec.py)

### Classic VRRP grammar (EOS 4.20+)

```text
interface Vlan10
   ip address 10.1.10.2/24
   vrrp 10 ipv4 10.1.10.254
   vrrp 10 priority 110
   vrrp 10 preempt
   vrrp 10 description CORE-GW
   vrrp 10 ipv6 fe80::1
   vrrp 10 track Ethernet1 decrement 20
!
```
(Arista EOS User Manual, "VRRP Configuration" section.)

### Modern VARP grammar (EOS 4.21+)

```text
interface Vlan10
   ip address 10.1.10.2/24
   ip address virtual 10.1.10.254/24
   ipv6 address virtual fd20::1/64
!
ip virtual-router mac-address 00:1c:73:00:dc:01
```
(from `tests/fixtures/real/arista_eos/batfish_labval_dc1_leaf2a_eos4230.txt`:
line 202 `ip address virtual 10.1.10.1/24`, line 286
`ip virtual-router mac-address 00:1c:73:00:dc:01`)

### Field mapping (classic + VARP)

| Wire token | Canonical field | Notes |
|---|---|---|
| `vrrp N ipv4 X` | `group_id=N, mode="vrrp", virtual_ips=[X]` | modern keyword form |
| `vrrp N ip X` | same | legacy form (pre-4.21) — codec accepts both |
| `vrrp N ipv6 X` | append `virtual_ipv6s` | |
| `vrrp N priority P` | `priority=P` | |
| `vrrp N preempt` / `no vrrp N preempt` | `preempt={True\|False}` | |
| `vrrp N description "<text>"` | `description="<text>"` | |
| `vrrp N track <iface> decrement <D>` | `track_interfaces=[<iface>]` | decrement Lossy |
| `ip address virtual X/Y` | `mode="anycast", virtual_ips=[X]` (no group_id from wire — synthesized as VLAN-id where applicable) | VARP |
| `ipv6 address virtual X/Y` | `mode="anycast", virtual_ipv6s=[X]` | VARP v6 |
| `ip virtual-router mac-address X` (TOP-LEVEL) | `virtual_mac=X` on every anycast group | global → per-group fan-out |

### Edge cases

* **VARP without classic VRRP.** Pure DC-fabric leaves use only
  `ip address virtual X/Y` lines with no `vrrp N` block. The
  parser synthesises a `CanonicalVRRPGroup(mode="anycast",
  group_id=<vlan-id>)` per VARP IP.
* **VARP + classic on the same interface.** Rare but legal.
  Two separate `CanonicalVRRPGroup` records, one per `mode`.
* **`ip virtual-router mac-address` is global.** Parser captures
  it once and back-fills every VARP group's `virtual_mac`.
  Render hoists the value to the top-level line by walking
  groups for the first non-empty `virtual_mac` with
  `mode="anycast"`.
* **Multiple ipv4 virtuals per group.** EOS supports
  `vrrp N ipv4 X` repeated; canonical handles via list.
* **VRF awareness.** VARP IPs honour the VRF binding of the
  interface; no separate VRF token on the VARP line.
* **Source-NAT for VARP.** `ip address virtual source-nat vrf X
  address Y` (line 287 of the leaf2a fixture) is a NAT
  primitive (Tier 3) — drops to parse-and-ignore.

---

## 4. Juniper Junos (`juniper_junos`)

**Codec module:** [`netcanon/migration/codecs/juniper_junos/`](../../../netcanon/migration/codecs/juniper_junos/)
* parse: [`parse.py:1099`](../../../netcanon/migration/codecs/juniper_junos/parse.py) (`_apply_interfaces`) — extend the IRB unit address handler at line 1262
* render: [`render.py:439`](../../../netcanon/migration/codecs/juniper_junos/render.py) (sub-interface address emit) — extend with a vrrp-group sub-statement walk
* capabilities: [`codec.py`](../../../netcanon/migration/codecs/juniper_junos/codec.py)

### Classic vrrp-group grammar (Junos 15+)

```text
set interfaces ge-0/0/1 unit 0 family inet address 10.1.10.2/24
set interfaces ge-0/0/1 unit 0 family inet address 10.1.10.2/24 vrrp-group 10 virtual-address 10.1.10.254
set interfaces ge-0/0/1 unit 0 family inet address 10.1.10.2/24 vrrp-group 10 priority 110
set interfaces ge-0/0/1 unit 0 family inet address 10.1.10.2/24 vrrp-group 10 preempt
set interfaces ge-0/0/1 unit 0 family inet address 10.1.10.2/24 vrrp-group 10 authentication-type md5
set interfaces ge-0/0/1 unit 0 family inet address 10.1.10.2/24 vrrp-group 10 authentication-key "OPAQUE-KEY"
set interfaces ge-0/0/1 unit 0 family inet address 10.1.10.2/24 vrrp-group 10 track interface ge-0/0/2 priority-cost 20
```
(Junos OS Network Interfaces User Guide, "Configuring VRRP" chapter,
Junos 18.x+.)

### Anycast (virtual-gateway-address) grammar

```text
set interfaces irb unit 2021 family inet address 10.221.0.5/16 virtual-gateway-address 10.221.0.1
set interfaces irb unit 2021 family inet6 address fd20:2021::5/64 virtual-gateway-address fd20:2021::1
set interfaces irb unit 2021 virtual-gateway-v4-mac 02:00:21:00:00:01
set interfaces irb unit 2021 virtual-gateway-v6-mac 02:00:21:06:00:01
```
(from `tests/fixtures/real/junos/ksator_labmgmt_qfx10k2_junos173.set`,
lines 95-99.)

### Field mapping

| Wire token tail | Canonical field | Notes |
|---|---|---|
| `family inet address X vrrp-group N virtual-address Y` | `mode="vrrp", group_id=N, virtual_ips=[Y]`, group attached to interface carrying `X` | classic |
| `family inet address X vrrp-group N priority P` | `priority=P` on the group | |
| `family inet address X vrrp-group N preempt` | `preempt=True` | |
| `family inet address X vrrp-group N no-preempt` | `preempt=False` | |
| `family inet address X vrrp-group N authentication-type md5` | `authentication="md5:"` prefix | merged with -key |
| `family inet address X vrrp-group N authentication-key "S"` | append `S` to `authentication` value | |
| `family inet address X vrrp-group N track interface Y priority-cost P` | `track_interfaces=[Y]` | priority-cost is Lossy |
| `family inet address X vrrp-group N fast-interval MS` | `advertisement_interval=ceil(MS/1000)` | sub-second drops to Lossy |
| `family inet address X virtual-gateway-address Y` | `mode="anycast", group_id=<irb-unit>, virtual_ips=[Y]` | anycast |
| `family inet6 address X virtual-gateway-address Y` | `mode="anycast", virtual_ipv6s=[Y]` | anycast v6 |
| `irb unit N virtual-gateway-v4-mac M` | `virtual_mac=M` on the anycast group of unit N | |
| `irb unit N virtual-gateway-v6-mac M` | (alias of v4 mac; same `virtual_mac` field) | both forms collapse onto one canonical |

### Edge cases

* **Per-address binding.** Junos binds the group to the
  ADDRESS, not the unit. Canonical model uses interface-scope
  (`vrrp_groups` on `CanonicalInterface`), so the parser must
  pick which address the group binds to and record it as
  `_addr_anchor` scratch state for round-trip; render-side
  re-attaches the group to the primary address.
  ALTERNATIVELY: pick the highest-priority address (lowest IP
  numerically) on render. Lossy if both addresses are present.
* **Bracket-list virtual-addresses.** `virtual-address [ X Y Z ]`
  is legal — multiple virtual IPs per group.
* **VRRPv3 (Junos `inet6`).** Same vrrp-group concept under
  `family inet6 address` — parser walks both families.
* **Anycast + classic on same unit.** Rare. Two separate
  records on `vrrp_groups`.
* **Track-interface priority-cost vs IOS-XE decrement.** Same
  semantic; canonical drops both to Lossy.
* **`fast-interval` (ms).** Sub-second advertisement; Lossy.
* **`authentication-type` and `authentication-key` are separate
  set-lines.** Parser must merge: see "structural-collapse"
  approach used for LAG `aggregated-ether-options` at
  [`parse.py:1167`](../../../netcanon/migration/codecs/juniper_junos/parse.py).

---

## 5. Aruba AOS-S (`aruba_aoss`)

**Codec module:** [`netcanon/migration/codecs/aruba_aoss/`](../../../netcanon/migration/codecs/aruba_aoss/)
* parse: [`parse.py:424`](../../../netcanon/migration/codecs/aruba_aoss/parse.py) (`_parse_vlan_stanza`) — VRRP body is inside the `vlan N` block
* render: [`render.py:578`](../../../netcanon/migration/codecs/aruba_aoss/render.py) — VLAN render loop
* capabilities: [`codec.py`](../../../netcanon/migration/codecs/aruba_aoss/codec.py)

### Grammar (from ArubaOS-Switch 16.10 Advanced Traffic Management Guide,
"Configuring VRRP" chapter)

```text
router vrrp
;
vlan 10
   name "Tenant_A"
   untagged 1-24
   ip address 10.1.10.2/24
   ip vrrp vrid 10
      virtual-ip-address 10.1.10.254
      priority 110
      preempt-mode
      enable
      authentication plain-text-key SECRET
      track-id 1
      exit
   exit
```

### Field mapping

| Wire token | Canonical field | Notes |
|---|---|---|
| `router vrrp` (top-level enabler) | (no field) — implicit when any group exists | required by AOS-S |
| `ip vrrp vrid N` | `group_id=N, mode="vrrp"` | start of nested block inside vlan stanza |
| `virtual-ip-address X` | append `X` to `virtual_ips` | AOS-S accepts at most one |
| `priority P` | `priority=P` | |
| `preempt-mode` / `no preempt-mode` | `preempt=True\|False` | |
| `enable` | (no canonical equivalent; absence ⇒ implicit disabled) | render must emit |
| `authentication plain-text-key SECRET` | `authentication="plain:SECRET"` | |
| `authentication md5 KEY` | `authentication="md5:KEY"` | |
| `track-id N` | `track_interfaces=[<tracked-iface-by-id>]` | track-id maps to a top-level track stanza |
| `description "<text>"` | `description="<text>"` | AOS-S 16.11+ |
| `advertise-interval-centisec C` | `advertisement_interval=ceil(C/100)` | centisec form — Lossy |

### Edge cases

* **VLAN-scoped only.** AOS-S only mounts VRRP inside `vlan N`
  blocks (the VLAN IS the SVI). Canonical attaches the group
  to the corresponding `CanonicalInterface` with `name="Vlan<N>"`
  (synthesized by the codec's SVI-absorption pattern in
  `aruba_aoss/_svi_absorption.py`). VRRP groups never appear
  on physical interface stanzas.
* **Top-level `router vrrp` enabler.** Required on AOS-S — the
  render must emit a `router vrrp` line at the top if any group
  exists.
* **Single virtual IP only.** AOS-S `virtual-ip-address` takes
  one address. Cross-vendor renders from a vendor with multiple
  IPs per group surface a Lossy comment (`! review: AOS-S
  supports only one virtual-ip-address per vrid; secondary
  virtuals X, Y dropped`).
* **No anycast.** Pure VRRP only.
* **`enable` is mandatory.** Render emits `enable` for every
  group; parse defaults `enabled=True` (matches the canonical
  `CanonicalInterface.enabled` pattern).
* **Track-ID indirection.** Aruba's `track-id` references a
  top-level `track <id> interface <iface>` stanza. Canonical
  carries the resolved interface name; parser does a two-pass
  lookup.

---

## 6. FortiGate (`fortigate_cli`)

**Codec module:** [`netcanon/migration/codecs/fortigate_cli/`](../../../netcanon/migration/codecs/fortigate_cli/)
* parse: [`parse.py:301`](../../../netcanon/migration/codecs/fortigate_cli/parse.py) (`_apply_system_interface`)
* render: [`render.py`](../../../netcanon/migration/codecs/fortigate_cli/render.py)
* capabilities: [`codec.py`](../../../netcanon/migration/codecs/fortigate_cli/codec.py)

### Grammar (from FortiOS 7.2 CLI Reference, "system interface" → "vrrp")

```text
config system interface
    edit "vlan10"
        set vdom "root"
        set ip 10.1.10.2 255.255.255.0
        set type vlan
        set vlanid 10
        config vrrp
            edit 10
                set vrgrp 0
                set vrip 10.1.10.254
                set priority 110
                set preempt enable
                set start-time 3
                set adv-interval 1
                set vrdst-priority 0
                set version 2
                set status enable
            next
        end
    next
end
```

Also `tests/fixtures/real/fortigate/user_contrib_fg100e_fos7213.conf`
shows the v6 / virtual-mac sub-keys at lines 390, 415-416:

```text
        set vrrp-virtual-mac disable
        ...
            set vrrp-virtual-mac6 disable
            set vrip6_link_local ::
```

### Field mapping

| Wire token (inside `config vrrp / edit N`) | Canonical field | Notes |
|---|---|---|
| `edit N` | `group_id=N, mode="vrrp"` | new sub-block; FortiOS bounds N to 1-255 |
| `set vrip X` | append `X` to `virtual_ips` | mandatory |
| `set vrip6 X` | append `X` to `virtual_ipv6s` | VRRPv3 |
| `set priority P` | `priority=P` | |
| `set preempt enable` / `disable` | `preempt={True\|False}` | |
| `set adv-interval S` | `advertisement_interval=S` | seconds |
| `set version 2/3` | (no field — V3 inferred from presence of vrip6) | Lossy |
| `set vrrp-virtual-mac enable` | (no canonical equivalent — vendor default MAC behaviour) | Lossy |
| `set authentication "<token>"` | `authentication="plain:<token>"` | FortiOS 6.4+ |
| `set status enable` | (codec defaults enabled=True; missing ⇒ no record) | |
| `set vrdst <iface>` | `track_interfaces=[<iface>]` | FortiOS "destination" tracking |
| `set proxy-arp <ip>` | (separate proxy-ARP — Tier-3) | drop |

### Edge cases

* **`vrgrp`** — VRRP group-of-groups (synchronized switching).
  Not in canonical scope; Lossy.
* **`vrdst-priority`** — alternate-priority for destination
  unreachable. Lossy.
* **`start-time`** — startup delay before joining election.
  Lossy.
* **Multiple groups per system interface.** Multiple
  `edit N` blocks under one `config vrrp` — codec creates
  multiple records.
* **`set version 2/3`** — wire version selection. Canonical
  carries via the address-family discriminator (presence of
  `virtual_ipv6s` ⇒ V3). FortiGate-specific knob falls Lossy.

---

## 7. MikroTik RouterOS (`mikrotik_routeros`)

**Codec module:** [`netcanon/migration/codecs/mikrotik_routeros/`](../../../netcanon/migration/codecs/mikrotik_routeros/)
* parse: [`parse.py:53`](../../../netcanon/migration/codecs/mikrotik_routeros/parse.py) (`parse_intent`) — add new `elif section == "/interface vrrp"` dispatch
* render: [`render.py:93`](../../../netcanon/migration/codecs/mikrotik_routeros/render.py) (`render_intent`)
* capabilities: [`codec.py`](../../../netcanon/migration/codecs/mikrotik_routeros/codec.py)

### Grammar (from MikroTik wiki, "Manual:Interface/VRRP")

```text
/interface vrrp
add interface=ether1 name=vrrp1 vrid=10 priority=110 v3-protocol=ipv4 preemption-mode=yes interval=1s
/ip address
add address=10.1.10.254/24 interface=vrrp1
```

### Field mapping

| Wire token | Canonical field | Notes |
|---|---|---|
| `interface=X` | parent interface (`X`) carries the group | back-pointer |
| `name=Y` | (synthetic; not modelled — used for `/ip address` binding) | parser holds via scratch dict |
| `vrid=N` | `group_id=N` | |
| `priority=P` | `priority=P` | |
| `preemption-mode=yes/no` | `preempt={True\|False}` | |
| `interval=Ns` | `advertisement_interval=N` | s suffix optional |
| `v3-protocol=ipv4/ipv6` | (discriminator; v3 with v6 ⇒ canonical surfaces `virtual_ipv6s`) | |
| `authentication=ah/simple/none` | `authentication="ah:" or "plain:" or ""` | |
| `password=<token>` | append to authentication value | |
| `on-backup=script` | (Tier-3 — script binding drops) | Lossy |

The VIP itself lives on a SEPARATE line in `/ip address`:

```text
/ip address
add address=10.1.10.254/24 interface=vrrp1
```

Parser must cross-reference: walk `/ip address` lines, look up
`interface=` value in the VRRP scratch dict, and stash the IP on
the corresponding canonical record.

### Edge cases

* **Pseudo-interface model.** RouterOS treats `vrrp1` as a
  first-class interface — IPs are bound via `/ip address`, not
  via the VRRP section. Parser does a two-pass.
* **v3-protocol=ipv6.** VRRPv3 with v6 virtual; canonical
  populates `virtual_ipv6s` instead.
* **No group-of-groups.** Each `/interface vrrp add` line is
  one record.
* **on-backup script.** RouterOS-specific Tier-3 (runs a script
  on backup-to-master transition). Drop with a review comment.

---

## 8. OPNsense (`opnsense`)

**Codec module:** [`netcanon/migration/codecs/opnsense/`](../../../netcanon/migration/codecs/opnsense/)
* parse: [`parse.py:132`](../../../netcanon/migration/codecs/opnsense/parse.py) (`parse_intent`) — add `<virtualip>` walker
* render: [`render.py`](../../../netcanon/migration/codecs/opnsense/render.py)
* capabilities: [`codec.py`](../../../netcanon/migration/codecs/opnsense/codec.py)

### Grammar (from OPNsense docs.opnsense.org, "Virtual IPs" chapter,
and `tests/fixtures/real/opnsense/user_contrib_supergate_opn25.xml`
line 4527-4531 which has an empty `<virtualip>` envelope)

```xml
<virtualip version="1.0.1" persisted_at="..." description="Virtual IP configuration">
  <vip>
    <mode>carp</mode>
    <interface>vlan10</interface>
    <vhid>10</vhid>
    <advskew>0</advskew>
    <advbase>1</advbase>
    <password>secret-bcrypt-hash</password>
    <subnet>10.1.10.254</subnet>
    <subnet_bits>24</subnet_bits>
    <type>single</type>
    <descr>HA VIP</descr>
  </vip>
</virtualip>
```

### Field mapping

| XML element | Canonical field | Notes |
|---|---|---|
| `<vip><mode>carp</mode>` | `mode="carp"` | |
| `<vhid>N` | `group_id=N` | |
| `<subnet>X</subnet>` + `<subnet_bits>P` | append `X` to `virtual_ips` (prefix lives on the parent CanonicalIPv4Address) | |
| `<advskew>S` + `<advbase>B` | `priority=255-S`, `advertisement_interval=B` | advskew → priority inversion |
| `<password>HASH` | `authentication="carp-key:HASH"` | bcrypt hash, opaque |
| `<descr>` | `description` | |
| `<interface>NAME` | back-pointer to `CanonicalInterface.name` | OPNsense logical iface name |
| `<mode>other</mode>` | NOT carp — alias/proxy/etc.; ignore | Tier-3 |

### Edge cases

* **Logical interface name resolution.** OPNsense `<interface>`
  refers to the LOGICAL pane name (e.g. `lan`, `opt1`, `vlan10`)
  not the physical device. The parser must walk `<interfaces>`
  first to build the alias → canonical-name map.
* **CARP password is mandatory.** Real fixtures always have one.
  Cross-vendor migration into VRRP devices surfaces a review
  comment (the password isn't a VRRP authentication-key).
* **`advskew` ⇒ priority.** OPNsense's election bias inverts:
  lower advskew wins. Convert via `priority = 255 - advskew`.
  Document the inversion in the codec comments.
* **No multiple virtual IPs per VHID.** Each VHID gets one
  `<subnet>` — matches Aruba's single-virtual-ip-address
  constraint.
* **VRRP mode.** OPNsense also supports `<mode>vrrp</mode>` for
  pure VRRP (no CARP). Codec maps `mode="vrrp"` (not "carp").
  Same record shape; differs only on render which omits
  `<password>` for VRRP mode.
* **IPv6 VIPs.** `<subnet>fe80::1</subnet>` + `<subnet_bits>64`.
  Populates `virtual_ipv6s`.
* **Empty `<virtualip>` envelope.** The supergate fixture has
  `<vip/>` (self-closing empty) — parser treats as zero groups
  (no records emitted).

---

## Summary — feature coverage matrix

| Feature | IOS-XE CLI | NETCONF | EOS | Junos | AOS-S | FortiGate | MikroTik | OPNsense |
|---|---|---|---|---|---|---|---|---|
| Classic VRRP | yes | n/a (stub) | yes | yes | yes | yes | yes | yes |
| Anycast / VARP | n/a | n/a | yes | yes (virtual-gateway) | n/a | n/a | n/a | n/a |
| CARP | n/a | n/a | n/a | n/a | n/a | n/a | n/a | yes |
| IPv6 (VRRPv3) | yes | n/a | yes | yes | partial (16.11+) | yes | yes (v3-protocol=ipv6) | yes |
| Multiple virtuals per group | yes | n/a | yes | yes | NO (Lossy) | yes | yes | NO (Lossy) |
| Custom virtual-MAC | implicit | n/a | global (cascade) | per-IRB | n/a | toggle only | n/a | derived from VHID |
| Track interfaces | track-object | n/a | yes | yes | yes (track-id) | yes (vrdst) | n/a (Lossy) | n/a |
| Authentication | yes (md5/plain) | n/a | n/a (Lossy) | yes (md5) | yes (plain/md5) | yes (plain) | yes (ah/plain) | yes (CARP-key) |
| Description | yes (17.x) | n/a | yes | yes | 16.11+ | n/a (Lossy) | n/a (Lossy) | yes |
| Preempt delay | Lossy | n/a | Lossy | Lossy | n/a | start-time (Lossy) | n/a | n/a |

`yes` = vendor-native + canonical model. `Lossy` = vendor-native
but the canonical model drops a per-vendor sub-field. `n/a` =
vendor doesn't model.
