# LAG / aggregate / port-channel: FortiGate FortiOS versus Cisco IOS-XE

Reverse-direction sibling of
[`../cisco_iosxe_cli_to_fortigate_cli/lags.md`](../cisco_iosxe_cli_to_fortigate_cli/lags.md).
Source URLs unchanged.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — Aggregate interfaces](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings).
Retrieved: 2026-04-30

```
config system interface
    edit "LAG_INTERNAL"
        set type aggregate
        set member "port3" "port4" "port5"
        set lacp-mode active
        set ip 10.0.0.1 255.255.255.252
        set status up
    next
end
```

## Cisco IOS-XE

Source: Cisco IOS XE LAN Switching Configuration Guide — EtherChannel.

```
interface Port-channel10
 ip address 10.0.0.1 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/0/3
 channel-group 10 mode active
 no shutdown
```

## Cross-vendor mapping (FortiGate -> Cisco)

Canonical surface (same as forward direction):

```
class CanonicalLAG(BaseModel):
    name: str
    members: list[str] = Field(default_factory=list)
    mode: str = "active"
```

- **name** — `lossy`.  FortiOS's operator-named `LAG_INTERNAL`
  has no Cisco equivalent; the Cisco render synthesises a
  `Port-channel<N>` integer ID.  The canonical model has no
  numeric LAG-ID field, so the Cisco render must invent an ID
  (default behaviour: pick the next available integer; operators
  override via the per-pane port-rename surface).
- **members** — `good`.  Direct preservation; the rename mesh
  applies on member port names (FortiGate `port3` -> Cisco
  `GigabitEthernet0/0/3` after the rename mesh's
  speed-prefix-defaulted mapping).
- **mode** — `good`.  FortiOS LACP modes (`active`, `passive`,
  `static`) map cleanly to Cisco (`active`, `passive`, `on`).
  Cisco's PAgP modes are not a concern on this direction
  (FortiGate doesn't emit them).

Disposition for LAGs overall: **lossy**.  Reason: name-shape
divergence (FortiGate operator-named -> Cisco synthetic
`Port-channel<N>` integer ID) requires operator-curated
mappings, and per-member rename for the Cisco-side
speed-prefixed names.
