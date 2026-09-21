# Dell SmartFabric OS10 — CLI grammar

Sources: Dell SmartFabric OS10 User Guide 10.5.0 / 10.5.1 / 10.5.2 and the
VXLAN + BGP EVPN Configuration Guide 10.5.0 (PDF, `dl.dell.com`), verified
against 12 real OS10 captures (see [`20-corpus.md`](20-corpus.md)).
Line numbers cite the extracted text of the **10.5.2 User Guide**.

Every form below was read from Dell's own manual or observed in a real
capture.  Nothing here is inferred from another vendor's grammar.

---

## 1. File shape

A device `show running-configuration` dump opens with two comment lines:

```
! Version 10.5.1.0
! Last configuration change at Feb  25 15:06:23 2020
!
```

Stanza delimiter is `!` at column 0.  Sub-commands are indented one space.
This is the Cisco-family shape — **and it is the cause of the detection
defect in [`30-codec-plan.md`](30-codec-plan.md)**.

`! Version <x.y.z.w>` is the `source_version` capture point (cf. `#235`,
which wired `source_version` across all 12 codecs).

---

## 2. ⚠️ Interface keyword case and spacing is NOT stable

Measured across every OS10 capture held:

| Form | Occurrences | Where |
|---|---|---|
| `interface vlanN` | 161 | device dumps (`show running-configuration`) |
| `interface Vlan N` | 28 | hand-authored config scripts |
| `interface vlan N` | 24 | mixed |

> ⚠️ **Corrected 2026-09-21.**  An earlier revision of this table read
> 137 / 50 / 24.  Those counts were taken across ALL 18 captures in the
> directory, which includes the four `mssdn_S4810-*` files — and those are
> **OS9 / FTOS**, not OS10 (`TenGigabitEthernet` ×256,
> `ManagementEthernet` ×48).  The figures above are the 14 OS10 captures
> only.  The conclusion is unchanged; the numbers were not.

The split is systematic, not random: **device output normalises to
`interface vlanN`** (lowercase, no space), while **operator-authored
configs use `interface Vlan N`**.  Netcanon is fed both.

> A parser keyed only on the device-dump form silently misses ~33% of
> real-world VLAN interfaces.  Parse must accept
> `interface\s+[Vv]lan\s*(\d+)`; render should emit the device-normalised
> `interface vlanN`.

`interface ethernet` was lowercase in 100% of captures (n=336: 262 whole
ports `ethernet<n>/<s>/<p>` plus 74 breakout subports
`ethernet<n>/<s>/<p>:<lane>`).

⚠️ **The breakout subport form is real and must be parsed** — 74
occurrences.  Unlike NX-OS's structurally ambiguous three-part name, the
OS10 `:<lane>` suffix is unambiguous, so it classifies as
`kind="breakout"` with a recoverable parent rather than falling through
to `unknown`.

---

## 3. Interfaces

```
interface ethernet1/1/15          ! physical, 3-segment node/slot/port
interface ethernet1/1/1:1         ! breakout subport
interface range ethernet1/1/1-1/1/12
interface port-channel10
interface vlan700                 ! SVI  (see §2 on case)
interface loopback0
interface mgmt1/1/1               ! out-of-band management
interface breakout 1/1/1 map 100g-1x
```

Per-interface:

| Command | Canonical surface |
|---|---|
| `description <text>` | `CanonicalInterface.description` |
| `mtu <1280-65535>` | `.mtu` |
| `no shutdown` / `shutdown` | `.enabled` |
| `ip address 10.0.0.122/24` | `.ipv4_addresses` (**CIDR**, like NX-OS/Arista) |
| `ipv6 address <addr>/<len>` | `.ipv6_addresses` |
| `ip vrf forwarding <name>` | `.vrf` |
| `no switchport` | L3 mode (default is L2) |
| `channel-group 10 mode active` | LAG membership |

`interface breakout <port> map <profile>` has **no canonical surface** —
it is a physical-layer port-splitting directive.  Tier-3 / drop.

---

## 4. L2 switchport

```
interface ethernet1/1/1
 switchport mode trunk
 switchport access vlan 700
 switchport trunk allowed vlan 711,713,715,717
```

Port-centric, Cisco-shaped.  Note `switchport access vlan` is present
**even on a trunk port**, where it means the native/untagged VLAN — the
same semantic as Cisco's `switchport trunk native vlan`, spelled
differently.  ⚠️ Mapping it to `access_vlan` on a trunk port would be a
semantic inversion of the kind #239 fixed for Junos.

---

## 5. VRF

```
ip vrf default                    ! the default VRF appears explicitly
ip vrf <name>
ip vrf management
!
interface ethernet1/1/1
 ip vrf forwarding <name>
```

Distinct from NX-OS `vrf context <name>` and Cisco `vrf definition`.
`ip vrf default` appearing as an explicit stanza is an OS10 tell.

---

## 6. Static routes

Two forms, **both accepted**:

```
ip route 10.1.1.0/24 20.1.1.1              ! CIDR   (modern, dominant)
ip route 1.1.1.0 255.255.255.0 20.1.1.1    ! dotted mask (legacy, manual L15622)
ip route vrf green 31.0.0.0/24 <nexthop>   ! per-VRF
ip route 10.1.1.0/24 ethernet 1/1/1        ! interface next-hop
ipv6 route <prefix>/<len> <nexthop>
```

⚠️ The dotted-mask form matters for detection: `cisco_iosxe_cli`'s probe
treats `ip address A.B.C.D M.M.M.M` as **IOS-exclusive**.  That guard is
about interface addresses, not routes, so it is not directly tripped — but
it shows the assumption "dotted mask ⇒ Cisco" is not safe for OS10.

**`management route` is a separate command**, not `ip route`:

```
management route 0.0.0.0/0 192.168.33.1
```

Observed in 8 real captures.  A parser treating it as a normal static
route would put a management-only default into the global RIB.

---

## 7. First-hop redundancy — VRRP (real VRRP, not HSRP)

```
vrrp version 3                    ! GLOBAL, not per-group
vrrp delay reload 180             ! GLOBAL
!
interface vlan700
 ip address 10.0.0.122/24
 !
 vrrp-group 123
  virtual-address 10.0.0.121
  priority 150
  preempt
  track <object-id>
```

- `vrrp-group <1-255>` nested in INTERFACE mode.
- `virtual-address ip-address1 [...ip-address10]` — **up to 10 addresses
  per group** (manual L58972).  `CanonicalVRRPGroup` must not assume one.
- IPv6 uses a separate `vrrp-ipv6-group` with `virtual-address <v6>`.
- Version is **system-wide** (`vrrp version 2|3`), so it does not belong on
  the per-group canonical record.

Maps to `CanonicalVRRPGroup` with `mode="vrrp"` — no HSRP normalisation
needed, unlike the NX-OS codec.

---

## 8. SNMP

```
snmp-server contact "Contact Support"
snmp-server location "Rack 1"
snmp-server community <name> {read-only | read-write}
snmp-server view <view-name> <oid-tree> {included | excluded}
snmp-server group <group> {v1|v2c|v3 <sec-level>} [access <acl>] read <view>
snmp-server host <ip> traps version 3 priv <user>
snmp-server engineID local 80:00:02:b8:04:61:62:63
snmp-server enable traps <family> <event>
snmp-server vrf <name>
snmp-server source interface <if>
```

### ⚠️⚠️ SNMPv3 USM — OS10 carries a per-line `localized` marker

Manual L9085, the full syntax:

```
snmp-server user <user-name> <group-name> <security-model>
    [[noauth | auth {md5 | sha} <auth-password>]
     [priv {des | aes} <priv-password>]]
    [localized] [access <acl-name>]
    [remote <ip-address> udp-port <port>]
```

Manual L8942: *localized keys are generated using the engine ID of the
switch; for this reason you cannot copy and use localized SNMP security
passwords in the configuration* of another switch.

**This is precisely the NX-OS `localizedkey` pattern that #471 was built
for.** The consequences for a `dell_os10` codec are non-optional:

1. Parse must stamp `auth_kind` / `priv_kind` **per line** from the
   presence of `localized` — `LOCALISED` when present, `PLAINTEXT` when
   absent.  Kind comes from the **source grammar**, never the value's
   shape (the #460 fail-open).
2. Render must **re-emit `localized`** when the recorded kind is not
   plaintext.  Recovering a key without re-marking it makes the device
   derive a key from a key — the #471 corruption, in a new grammar (#472
   found exactly this in three others).
3. `dell_os10` must be declared in `_SOURCE_DEFAULT_KIND` in
   [`netcanon/migration/_usm_keys.py`](../../../netcanon/migration/_usm_keys.py)
   or it fails closed to `localised`.
4. `/snmp/v3-user/auth-passphrase` and `/snmp/v3-user/priv-passphrase`
   must be explicitly declared in the capability matrix — `classify()`
   defaults undeclared xpaths to `supported`, i.e. **silent loss**.

A real v3 user line, from a capture (key values are placeholders in the
source):

```
snmp-server user netmon netmon 3 auth sha <KEY> priv aes <KEY>
```

(Operator-chosen names in this document are genericised; the grammar
shape is verbatim.)

Note: no `localized` on that line, so it parses as plaintext — correctly,
under the kind-from-grammar rule.

---

## 9. Local users

```
username <name> password <password> role <role> [priv-lvl <0-15>]
system-user linuxadmin password <hash>
aaa authentication login {default | console} local
```

Observed: `username admin password $6$… role sysadmin priv-lvl 15`.

- Cleartext entry is **converted to SHA-512 (`$6$`) in the running
  config** (manual: MD-5 / SHA-256 / SHA-512 accepted for backward
  compatibility with ≤10.3.1E).
- Roles: `sysadmin` (priv-lvl 15), `secadmin`, `netadmin`, `netoperator`.
- `system-user linuxadmin` is the underlying Linux account — an OS10
  tell, and a **secret-bearing line** the sanitiser must cover.

---

## 10. Management plane

```
hostname <name>
ip name-server <ip>
ip domain-name <name>
ip domain-list <name>
ntp server <ip>
ntp enable vrf <name>
logging server <ip> [tcp|udp|tls] [port] [severity <level>] [vrf <name>]
logging source-interface mgmt 1/1/1
logging console disable
logging audit enable
clock timezone <zone> <offset-h> <offset-m>
spanning-tree mode rstp
spanning-tree rstp priority 28672
lldp enable
dcbx enable
```

---

## 11. VLT (Dell's MLAG) — no canonical surface

```
vlt-domain 1
 backup destination 192.168.255.2
 discovery-interface ethernet1/1/15
 vlt-mac 00:00:00:00:00:02
!
interface port-channel10
 vlt-port-channel 10
```

Dell's multi-chassis LAG. Analogous to Cisco vPC / Aruba VSX / Arista
MLAG, none of which netcanon models today.  **Tier 3.**  Appears in 10 of
12 OS10 captures, so the Tier-3 "dropped sections" banner will fire on
most real configs — that is correct behaviour, but worth stating up front
so it is not read as a defect.

---

## 12. VXLAN / BGP EVPN

```
nve
 source-interface loopback0
!
virtual-network <vnid>
 vxlan-vni <vni>
 [untagged-vlan <vlan>]
!
interface loopback0
 ip address 192.168.1.1/32
```

Plus `evi`, `evpn`, `auto-evi`, `advertise`, `address-family l2vpn evpn`,
`remote-vtep`, and asymmetric/symmetric IRB routing modes.

OS10 uses a **`virtual-network` indirection** between VLAN and VNI, where
NX-OS binds `vlan N / vn-segment <vni>` directly and AOS-CX uses
`interface vxlan` / `vni`.  Mapping onto `CanonicalIntent.vxlan_vnis` is a
later phase, not v1.

---

## 13. Out of scope for v1 (Tier 3)

`class-map` / `policy-map` / `system qos` / `trust dot1p-map` /
`qos-map` (DCB-RoCE QoS, heavy in Azure Local configs), ACLs,
`router bgp` / `ospf`, `iscsi`, `telemetry`, `support-assist`,
`interface breakout`, `vlt-domain`, Fibre Channel / FCoE.
