# LAG render gap — RouterOS source to cisco_iosxe NETCONF target

Source: [openconfig-if-aggregate YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-if-aggregate.html)
Retrieved: 2026-05-01

Source: [openconfig-lacp YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-lacp.html)
Retrieved: 2026-05-01

Source: [Bonding — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8323193/Bonding)
Retrieved: 2026-05-01

## RouterOS bonding source

RouterOS bonding is a single section:

```
/interface bonding
add name=bond1 mode=802.3ad slaves=ether1,ether2 \
    transmit-hash-policy=layer-2-and-3 lacp-rate=1sec
```

The MikroTik parser populates:

* `intent.lags[]` — one record per `/interface bonding` row, with
  `name=bond1`, `members=["ether1", "ether2"]`, `mode="active"`
  (canonicalised from `mode=802.3ad`).
* `intent.interfaces[].lag_member_of` — set on each member
  interface, pointing to the bonding name.

RouterOS supports modes the canonical model does not enumerate
exhaustively (`active-backup`, `balance-rr`, `balance-xor`,
`balance-tlb`, `balance-alb`, `broadcast`).  These map to canonical
`mode="static"` with banner; only `802.3ad` maps cleanly to
`active`.

## What the cisco_iosxe target render emits

Nothing for LAG aggregator records.  The `_render_canonical()`
method walks `intent.interfaces` only — it never reads
`intent.lags[]`.

What DOES survive:

* `intent.interfaces[name="bond1"]` records — emits as a standard
  `<interface>` element with `interface_type="ieee8023adLag"`
  (since the RouterOS parser inferred this on parse from the
  `bondN` name prefix).  L3 addresses on the LAG itself survive.

What does NOT survive:

* Top-level `intent.lags[]` records (the aggregator-side metadata
  that includes member list and LACP mode).
* `interfaces[].lag_member_of` — no `openconfig-if-aggregate:
  aggregate-id` leaf is emitted on member interfaces.
* LACP rate / mode / system-id — `openconfig-lacp` is entirely out
  of scope.

The result: a downstream OpenConfig consumer sees `bond1` as a
standalone LAG-typed interface with no member-interface
relationships.  The members appear as standalone interfaces with
no parent-LAG back-pointer.  Reconstructing the bonding requires
either re-applying the configuration from a different source, or
hand-editing the member relationships on the target Cisco device.

## Disposition

`lags`: `unsupported` with reason citing the render-side wire-up
gap.  When the cisco_iosxe codec grows
`openconfig-if-aggregate` render support, this flips to `lossy` —
RouterOS-side modes beyond `802.3ad` (active-backup, balance-rr,
etc.) have no Cisco EtherChannel equivalent and would lose nuance.

`interfaces[].lag_member_of`: `unsupported` — same render gap.

## Reference: what the sibling CLI target does emit

For comparison, the `cisco_iosxe_cli` render of the same canonical
record produces:

```
interface Port-channel1
 description bond1
!
interface GigabitEthernet0/0/1
 channel-group 1 mode active
!
interface GigabitEthernet0/0/2
 channel-group 1 mode active
```

None of this aggregator wire-up lands via the cisco_iosxe NETCONF
render.

## Direction-specific note

This is symmetric in classification with the inverse direction
(`cisco_iosxe -> mikrotik_routeros`), where the source codec
similarly does not parse the aggregate / LACP augments.  Both
directions of this pair share the same root-cause: the cisco_iosxe
NETCONF stub does not handle LAG aggregation in either parse or
render.  Promoting either side of the LAG handling would move the
disposition of one direction toward `lossy`; promoting both moves
both to `lossy` (with mode-set divergence as the residual loss).
