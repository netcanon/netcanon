# Link aggregation (LAGs): Cisco IOS-XE versus MikroTik RouterOS

## Cisco IOS-XE

Source: Cisco IOS XE LAN Switching Configuration Guide — EtherChannel.

```
interface Port-channel10
 description core-uplink-bundle

interface GigabitEthernet0/0/1
 channel-group 10 mode active

interface GigabitEthernet0/0/2
 channel-group 10 mode active
```

Cisco models a LAG as an `interface Port-channel<N>` parent with
member ports declaring `channel-group <N> mode {active | passive |
on | desirable | auto}`.  `active` is LACP-active, `on` is static
(no protocol).

## MikroTik RouterOS

Source: [Bonding — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8323193/Bonding)

Retrieved: 2026-04-30

```
/interface bonding
add name=bond1 mode=802.3ad slaves=ether1,ether2 \
    lacp-rate=30secs link-monitoring=mii \
    transmit-hash-policy=layer-2-and-3
```

RouterOS uses `/interface bonding add` with `slaves=` (the comma-
separated member list) and `mode=` selecting from a richer set:

- `802.3ad` — LACP (matches Cisco's `mode active`)
- `active-backup` — failover
- `balance-rr` / `balance-xor` / `balance-tlb` / `balance-alb` —
  Linux-bonding-style hash modes
- `broadcast` — replicate frames

The `slaves=` parameter list is the inverse of Cisco's per-interface
`channel-group` declaration: RouterOS declares membership at the
bond level; Cisco declares it on the member.

## Cross-vendor mapping

The canonical surface is

```
CanonicalLAG(name, members[], mode: "active" | "passive" | "static")
```

### Mode mapping

| Cisco channel-group mode | Canonical mode | RouterOS bonding mode |
|---|---|---|
| `active` | `active` | `802.3ad` |
| `passive` | `passive` | `802.3ad` (no separate passive on RouterOS) |
| `on` | `static` | `balance-xor` (rough equivalent) or `802.3ad` w/ no peer |

RouterOS's bonding modes beyond `802.3ad` (active-backup, balance-
rr, balance-xor) have no Cisco equivalent — operators using those
modes are running Linux-bond semantics that don't translate to the
Catalyst-style EtherChannel.

### Name mapping

Cisco's `Port-channel10` (lowercase 'c' historically; `Port-Channel`
on Arista; the Cisco rename mesh canonicalises capitalisation) maps
to RouterOS's operator-chosen `bond1` / `bond2`.  Cross-vendor
migration uses the rename mesh; the `lag_member_of` field on
`CanonicalInterface` carries the back-pointer.

### Disposition

| Field | Disposition |
|---|---|
| `lags[].name` | lossy (vendor-specific naming convention; rename mesh canonicalises) |
| `lags[].members` | good |
| `lags[].mode` | lossy (active/passive/static -> RouterOS bonding mode mapping) |
| `interfaces[].lag_member_of` | good |
