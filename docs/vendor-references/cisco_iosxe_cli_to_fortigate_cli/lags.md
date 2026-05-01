# LAG / port-channel / aggregate: Cisco IOS-XE versus FortiGate FortiOS

## Cisco IOS-XE

Source: Cisco IOS XE LAN Switching Configuration Guide — EtherChannel.

Cisco models LAGs as **`Port-channel<N>`** virtual interfaces with
member ports declaring `channel-group <N> mode <mode>`:

```
interface Port-channel10
 description "Uplink to core"
 ip address 10.0.0.1 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/0/0
 channel-group 10 mode active
 no shutdown
!
interface GigabitEthernet0/0/1
 channel-group 10 mode active
 no shutdown
```

LACP modes: `active` (initiate), `passive` (respond), `on` (static
no-LACP), `auto`/`desirable` (PAgP — Cisco-only legacy).

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — Networking / Aggregate interfaces](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings).
Source: FortiOS CLI Reference — `config system interface / set type aggregate`.
Retrieved: 2026-04-30

FortiOS models LAGs via `set type aggregate` on a parent interface
with `set member` listing the bundled physical ports:

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

Notable FortiOS specifics:

- **Operator-named aggregate.**  Unlike Cisco's mandated
  `Port-channel<N>` form, FortiGate LAGs take any operator-curated
  name (convention: `LAG_<role>` or `agg<n>`).
- **`set member` lists physical ports.**  FortiGate does not have
  the inverse reverse-pointer (no `channel-group` directive on the
  member); membership is declared from the aggregate side.  The
  FortiGate codec maintains a second-pass that synthesises the
  `lag_member_of` reverse-link on each member's `CanonicalInterface`.
- **LACP modes**: `static`, `passive`, `active` (no PAgP).  The
  canonical-to-FortiOS mapping is documented in
  `parse._FORTIGATE_LACP_TO_CANONICAL` and its inverse.

## Cross-vendor mapping (Cisco -> FortiGate)

Canonical surface:

```
class CanonicalLAG(BaseModel):
    name: str
    members: list[str] = Field(default_factory=list)
    mode: str = "active"            # "active" | "passive" | "static"
```

- **name** — `lossy`.  Cisco's `Port-channel10` differs in shape
  from FortiGate's operator-named `LAG_<role>`.  The rename mesh
  applies operator-curated mappings on cross-vendor render; without
  an override, the FortiGate codec preserves whatever the source
  emitted (so a Cisco-source LAG named `Port-channel10` lands in
  FortiOS as an interface edit with that exact name — FortiOS
  accepts but the resulting name violates FortiOS naming
  conventions).
- **members** — `good`.  Direct preservation; the rename mesh
  applies on member names.
- **mode** — `lossy`.  PAgP modes (`auto`, `desirable`) on Cisco
  have no FortiOS equivalent; cross-vendor migration coerces them
  to LACP `active` / `passive` with a banner.

Disposition for LAGs overall: **lossy**.  Reason: name-shape
divergence and PAgP-mode incompatibility require operator-curated
mappings on cross-vendor migration.
