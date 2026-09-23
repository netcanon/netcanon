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
mis-parse it into a plausible-looking wrong answer.

> **Corrected 2026-09-23 (#485).**  This paragraph used to promise that
> "auto-detection returns no candidate" for an OS9 paste.  That was a
> whole-product claim, and it was **false**: the OS10 codec did refuse,
> but `cisco_iosxe_cli` then claimed the file at confidence **95**
> ("IOS-specific banner sequence detected"), because Force10 emits
> `service timestamps` and one such banner was enough.  Measured on four
> real S4810 captures, it parsed them into 90 interfaces collapsed onto
> 5 distinct names, 0 VLANs and 0 IP addresses.  The deferral now lives
> in `cisco_iosxe_cli.probe()`, so the claim above is true again — but
> if you migrated an OS9 config before this, re-check what source codec
> was used.

> **Why `best_effort` and not `certified`?**  Every other codec's
> `certified` rests on an **in-tree real capture corpus**.  The OS10
> development corpus — 40 real configs spanning five OS10 releases —
> is held out-of-tree: some captures carry live password hashes, and
> the best-structured material of all carries no redistribution
> licence.  The codec is validated against those 40 captures plus a
> committed synthetic kitchen-sink fixture and full cross-vendor mesh
> coverage, but the honest label for "no committed real corpus" is
> `best_effort`.  See
> [Real-world fixtures](#real-world-fixtures-weve-validated-against).

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

## Lossy paths

Declared `lossy` means: translated, but something measurable is left
behind.  Never silent — each one is reported in the migration diff.

**VRRP sub-fields** — the group itself round-trips; these do not:

- **`…/vrrp-groups/group/mode`** — a cross-family source (HSRP, CARP)
  is re-expressed as real VRRP.  The virtual-IP intent survives; the
  wire protocol changes.
- **`…/advertisement-interval`**, **`…/authentication`**,
  **`…/virtual-mac`**, **`…/description`** — not modelled in v1; the
  group renders without them and the target applies its defaults.
- **`…/virtual-ipv6s`** — OS10 expresses IPv6 VRRP through a separate
  `vrrp-ipv6-group` stanza that v1 does not render, so IPv6 virtual
  addresses drop while the IPv4 group survives.
- **`…/track-interfaces`** — OS10 tracks a track-*object* id, not an
  interface name, so a canonical track list has no faithful OS10 form.

**Anycast / virtual gateway** — OS10 has no VARP or
distributed-anycast-gateway concept at all:

- **`/interfaces/…/ipv4|ipv6/address/virtual-gateway-address`** and
  **`…/virtual-gateway-mac`**, plus the `/vlans/vlan/…` companions —
  the address renders, the virtual gateway does not.  Migrating from
  Arista VARP or NX-OS anycast gateway means re-authoring as VRRP.

**SNMPv3 USM** — see the section above before migrating users:

- **`auth-passphrase`** / **`priv-passphrase`** — a key localised to
  the source agent's engine ID is refused with its user.
- **`auth-protocol`** — OS10 offers only `md5` / `sha`, so every SHA-2
  variant collapses to `sha`.  A real cryptographic downgrade.
- **`priv-protocol`** — AES-192/256 collapse to `aes`, 3DES to `des`.
- **`engine-id`** — OS10 states it on its own `snmp-server engineID
  local` line, so a per-user engine ID has nowhere to go.

**VRF sub-details** — `ip vrf <name>` carries the name alone:

- **`instance-type`** (mac-vrf downgrades to `vrf`),
  **`description`**, **`route-distinguisher`**, **`rt-imports`**,
  **`rt-exports`**, **`l3-vni`** — the RD and route-targets live under
  Tier-3 `router bgp`; the L3VNI needs the deferred `virtual-network`
  indirection.

**Interface + misc:**

- **`/interfaces/interface/config/type`** — inferred from the name
  prefix on render rather than carried explicitly.
- **`/interfaces/interface/tunnel-type`** — the port survives as an
  `interface <name>` stanza; its encapsulation does not.
- **`dhcp-client`** / **`dhcp-client-v6`** — OS10 spells these
  `ip address dhcp` / `ipv6 address autoconfig`; v1 models no value.
- **`/interfaces/…/ipv6/address/secondary-ip`** — the IPv4 render
  re-emits `secondary`, the IPv6 form does not.
- **`/vlans/vlan/description`** — OS10 carries exactly one human label
  per VLAN (the SVI's `description`) and the render spends it on the
  VLAN **name**.
- **`/routing/static-route/description`** — destination, next-hop and
  administrative distance only.

## Real-world fixtures we've validated against

**There are none in-tree** — the reason this codec ships `best_effort`.
Unlike every `certified` codec, `dell_os10` has no section in
[`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md).

Development instead used a **40-capture out-of-tree corpus** covering
five OS10 releases — **10.4.3.1, 10.4.3.4, 10.5.1.0, 10.5.1.4,
10.5.4.4** — across S3048, S4112F-ON, S5212F-ON, S5232F, S5248F-ON and
Z-series platforms, plus four **OS9 / FTOS S4810** captures kept as
negative controls.  Measured over that corpus:

- **40/40 parse** without exception
- **38/40 round-trip canonical-stable.**  The two exceptions are not
  defects: both are Microsoft reference configs scrubbed to a literal
  `$CREDENTIAL_PLACEHOLDER$` token, which the credential gate
  correctly refuses to re-emit — see
  `tests/unit/migration/codecs/dell_os10/test_render_refuses_unmodelled_credential.py`
- **4/4 OS9 captures refused**, as intended

Why it cannot simply be committed: the captures divide almost exactly
along the wrong axis.  The permissively-licensed material (MIT) carries
**no `! Version` banner**, while every capture that pins an OS10
release is **unlicensed**.  So committing the licensed half would not
satisfy the `certified` bar of ≥3 captures across ≥2 OS versions
anyway.  **One permissively-licensed OS10 `show running-configuration`
with its version banner intact remains the single highest-value
contribution to this codec** — see
[`WANTED.md`](../../tests/fixtures/real/WANTED.md).

## Common gotchas

⚠️ **Auto-detection needs an OS10 marker in the first 500 bytes.**
Detection hands each codec only the leading `DEFAULT_PROBE_BYTES = 500`.
Measured across the 40-capture corpus, **19 detect correctly, 7 return
no candidate, and 10 are claimed by `cisco_iosxe_cli` instead** — OS10
and IOS-XE share the `!`-delimited Cisco shape, so a capture that spends
its opening budget on a template header, a console login banner, or a
block of QoS never reaches an OS10-exclusive token.  If auto-detection
picks the wrong vendor, **select `dell_os10` explicitly** — parsing is
unaffected, since only the probe window is at issue.  Pinned in
`tests/unit/migration/codecs/dell_os10/test_probe_window_limits.py`
and tracked in
[`../vendor-research/dell_os10/30-codec-plan.md`](../vendor-research/dell_os10/30-codec-plan.md)
§9.

⚠️ **A user whose password hash we can't model is dropped, loudly.**
The renderer refuses to re-emit a credential it cannot prove is safe to
reuse, leaving a `review:` comment naming the user instead of a
`username` line.  A config whose secrets were scrubbed by some other
tool will therefore render with no users at all — that is the gate
working, not a parser fault.

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
