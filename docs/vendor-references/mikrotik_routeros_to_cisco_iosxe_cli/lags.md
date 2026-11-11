# Link aggregation (LAGs): MikroTik RouterOS versus Cisco IOS-XE

## MikroTik RouterOS

Source: [Bonding — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8323193/Bonding)

Source: [Linux bonding — Switch Configuration](https://docs.kernel.org/networking/bonding.html)

Retrieved: 2026-04-30

```
/interface bonding
add name=bond1 mode=802.3ad slaves=ether1,ether2 \
    lacp-rate=30secs link-monitoring=mii \
    transmit-hash-policy=layer-2-and-3
```

RouterOS bonding modes:

- `802.3ad` — LACP
- `active-backup` — failover
- `balance-rr` / `balance-xor` / `balance-tlb` / `balance-alb`
- `broadcast`

The `slaves=` parameter declares membership at the bond level.

## Cisco IOS-XE

```
interface Port-channel10
 description core-uplink-bundle

interface GigabitEthernet0/0/1
 channel-group 10 mode active

interface GigabitEthernet0/0/2
 channel-group 10 mode active
```

Cisco models channel-group modes:

- `active` — LACP-active
- `passive` — LACP-passive
- `on` — static
- `desirable` / `auto` — PAgP (Cisco-only, deprecated for new
  designs)

## Cross-vendor mapping

The canonical surface is

```
CanonicalLAG(name, members[], mode: "active" | "passive" | "static" | "active-backup")
```

### Mode mapping (MikroTik -> Cisco)

| RouterOS mode | Canonical mode | Cisco mode |
|---|---|---|
| `802.3ad` | `active` | `active` |
| `balance-rr` (or no `mode`: RouterOS's default) / `balance-xor` / `broadcast` | `static` | `on` |
| `active-backup` / `balance-tlb` / `balance-alb` | `active-backup` | `on`, with a `! review:` line |

RouterOS source using `802.3ad` round-trips cleanly.  `balance-rr`,
`balance-xor` and `broadcast` need the switch's ports grouped, and
are written as a static `channel-group N mode on`.
`active-backup`, `balance-tlb` and `balance-alb` "do not require any
specific configuration of the switch" (Linux bonding), and IOS-XE
has no such bond: they are written `channel-group N mode on` with a
`! review:` line beside it and a warning in the job, and the
switch's ports must then be configured as that static aggregate (or
the host bond re-designed).

### Disposition

| Field | Disposition (MikroTik -> Cisco) |
|---|---|
| `lags[].name` | lossy (vendor-specific naming; rename mesh handles) |
| `lags[].members` | good |
| `lags[].mode` | lossy (active-backup / balance-tlb / balance-alb have no Cisco equivalent and are written `mode on` with a review line; the static modes are written `mode on`; only `802.3ad` round-trips cleanly) |
| `interfaces[].lag_member_of` | good |
