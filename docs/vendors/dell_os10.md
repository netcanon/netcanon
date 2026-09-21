# Dell SmartFabric OS10 — What works for me?

If you operate Dell EMC PowerSwitch hardware running **SmartFabric
OS10** — the S-series leaf / ToR and Z-series spine class — and want to
know what Netcanon does for you, this is the page.

## TL;DR

- **`dell_os10`** — `show running-configuration` text **bidirectional**
  (parse AND render).  **Certification: best_effort.**

OS10 is Dell's modern Debian-based NOS.  It is **not** the older
Force10 **OS9 / FTOS** grammar (`interface TenGigabitEthernet 0/1`,
`ManagementEthernet`, VLAN-centric `tagged` / `untagged`) — that is a
different language, and this codec **refuses** it outright rather than
mis-parse it into a plausible-looking wrong answer.  If you paste an OS9
config, auto-detection returns no candidate instead of silently handing
it to the wrong codec.

> **Why `best_effort` and not `certified`?**  Every other codec's
> `certified` rests on an **in-tree real capture corpus**.  The OS10
> corpus used to build this codec — 14 real configs — carries live
> password hashes and is held out-of-tree, so it cannot be committed.
> The codec is validated against those 14 captures (all parse cleanly
> and round-trip canonical-stable) plus a committed synthetic
> kitchen-sink fixture and full cross-vendor mesh coverage, but the
> honest label for "no committed real corpus" is `best_effort`.

## What translates well

[Tier 1](../CAPABILITIES.md#tier-1--auto-translatable-cross-vendor-stable)
— auto-translatable:

- `hostname`
- Interfaces — name, description, admin state, MTU, IPv4 + IPv6
  addresses (CIDR), `ip vrf forwarding` binding
- L2 switchport — access / trunk mode, access VLAN, trunk allowed-VLAN
  list, trunk **native** VLAN, `channel-group` membership
- VLANs — ID, name, tagged / untagged port lists
- Static routes — including per-VRF (`ip route vrf <name> …`)
- VRFs — name (`ip vrf <name>`)

[Tier 2](../CAPABILITIES.md#tier-2--translatable-with-caveats) —
translatable with caveats:

- LAGs (`interface port-channel N`, reconciled with cross-vendor names
  like `Port-channel<N>` / `ae<N>` / `lag N`)
- SNMP v2c (community / location / contact / trap host) and v3 USM users
- Local users — name, role, `priv-lvl`, hashed password
- **VRRP** — group ID, priority, preempt, virtual addresses

## L3 redundancy: real VRRP

OS10 runs **real VRRP**, not a vendor FHRP dialect:

```text
interface vlan461
 ip address 192.168.46.3/26
 !
 vrrp-group 46
  priority 110
  preempt
  virtual-address 192.168.46.1
```

This matters in both directions:

- **OS10 as target.** A source carrying HSRP (Cisco) or CARP (OPNsense)
  is re-expressed as VRRP.  The operator's redundancy *intent* for the
  virtual IP survives, but **the wire protocol changes** — so
  `/interfaces/interface/vrrp-groups/group/mode` is declared `lossy`
  rather than quietly reported as a faithful translation.  Same-vendor
  VRRP round-trips losslessly.
- **OS10 as source.** `priority`, `preempt` and the virtual addresses
  round-trip to any target that models VRRP.

⚠️ **One parsing subtlety worth knowing if you read the configs
yourself:** OS10 device dumps separate an SVI's L3 block from its
nested VRRP block with a **one-space indented `!`**.  A parser that
treats any bare `!` as a stanza terminator drops the entire VRRP group.
This codec closes a stanza only on a column-0 line, which is why the
groups above survive.

## SNMPv3 keys — read this before migrating users

An SNMPv3 USM key is localised against **the agent's own engine ID**, and
Dell states such keys cannot be copied between switches.  So:

- A key that belongs to **another device** is **refused** — the codec
  emits a review comment instead of an `snmp-server user` line.  It is
  never re-emitted behind the `localized` keyword, which would claim the
  digest was already this switch's and make OS10 derive a key from a key.
- A source **passphrase** is portable and renders *without* `localized`,
  so OS10 localises it itself on commit.

⚠️ OS10's per-codec default is **`plaintext`** — the **opposite** of
NX-OS.  An OS10 value with no trailing `localized` marker is a
passphrase.

Practical consequence: **plan to re-key SNMPv3 users** when migrating
between vendors.  Auth algorithms also downgrade — OS10 offers only
`md5` / `sha`, so any SHA-2 variant collapses to `sha`, and privacy
offers only `des` / `aes`, so AES-192/256 collapse to `aes`.  Both are
declared `lossy`; neither is silent.

## Port naming

OS10 uses three-segment lower-case names, `ethernet<stack>/<module>/<port>`:

```text
ethernet1/1/30      ->  stack 1, module 1, port 30
ethernet1/1/10:1    ->  breakout subport (lane 1 of port 10)
mgmt1/1/1           ->  management port
```

Breakout subports (the `:lane` suffix) are unambiguous and classify
properly rather than falling through to `unknown`.  The chassis-level
`interface breakout 1/1/1 map 100g-1x` lines that *declare* the split
are not ports and do not become interfaces.

## What we don't do

Declared `unsupported` — the loss is reported, never silent:

- **VXLAN / EVPN.**  OS10 reaches an overlay through a
  `virtual-network <vnid>` indirection that is deferred past v1.
- **BGP / OSPF / IS-IS**, ACLs, QoS/DCB, NAT and firewall surfaces —
  [Tier 3](../CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered),
  captured for the dropped-Tier-3 banner and never auto-rendered.
- **VLT** (Dell's MLAG) — detected for the Tier-3 banner, not modelled.
- Management-plane scalars: `ip domain-name`, `ip name-server`,
  `ntp server`, `logging server`, DHCP pools and `radius-server`.

Declared `lossy` — translated with a caveat:

- VLAN **description**.  OS10 carries exactly one human label for a
  VLAN (the SVI's `description`) and the render spends it on the VLAN
  **name**, so a separate canonical description has nowhere to go.
- Anycast gateway (`virtual-gateway-address` / `-mac`).  OS10 has no
  VARP / distributed-anycast-gateway concept — first-hop redundancy is
  real VRRP.  Migrating from Arista VARP or NX-OS anycast gateway means
  re-authoring it as a VRRP group.
- VRF sub-details — description, RD, route-targets and L3VNI all live
  under Tier-3 `router bgp`, so `ip vrf <name>` carries the name alone.

## Two things that would have been silent bugs

Recorded here because they change how you should read a migration report:

1. **`switchport access vlan` on a trunk port is the NATIVE VLAN.**
   OS10 emits no `switchport trunk native vlan` line at all.  Reading it
   as the access VLAN inverts the port's L2 semantics.
2. **`management route` is not `ip route`.**  It installs into the
   management VRF only.  In the reference corpus it outnumbers `ip
   route` 8:2, so treating it as a normal static route would put a
   management-only default into the global RIB.

## See also

- [`../CAPABILITIES.md`](../CAPABILITIES.md) — the full per-codec
  capability matrix (§A lists every lossy / unsupported path with its
  reason).
- [`../vendor-research/dell_os10/`](../vendor-research/dell_os10/) — the
  grammar dossier this codec was built from, including the measured
  counts behind each trap above.
