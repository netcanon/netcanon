# Link aggregation (LAGs): MikroTik RouterOS versus Cisco IOS-XE

## MikroTik RouterOS

Source: [Bonding — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8323193/Bonding)

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
CanonicalLAG(name, members[], mode: "active" | "passive" | "static")
```

### Mode mapping (MikroTik -> Cisco)

| RouterOS mode | Canonical mode | Cisco mode |
|---|---|---|
| `802.3ad` | `active` | `active` |
| `active-backup` / `balance-*` / `broadcast` | (no canonical) | (no Cisco equivalent) |

RouterOS source using `802.3ad` round-trips cleanly; using any
other mode (active-backup, balance-xor, etc.) falls outside the
canonical scope — these are Linux-bond-style modes with no
Cisco-side LACP/EtherChannel equivalent.  The codec emits a
banner and the operator decides.

### Disposition

| Field | Disposition (MikroTik -> Cisco) |
|---|---|
| `lags[].name` | lossy (vendor-specific naming; rename mesh handles) |
| `lags[].members` | good |
| `lags[].mode` | lossy (active-backup / balance-* RouterOS modes have no Cisco equivalent; only `802.3ad` round-trips cleanly) |
| `interfaces[].lag_member_of` | good |
