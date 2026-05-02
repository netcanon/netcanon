# LAG render gap — cisco_iosxe NETCONF source to RouterOS target

Source: [openconfig-if-aggregate YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-if-aggregate.html)
Retrieved: 2026-05-01

Source: [openconfig-lacp YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-lacp.html)
Retrieved: 2026-05-01

Source: [Bonding — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8323193/Bonding)
Retrieved: 2026-05-01

## OpenConfig aggregate scope

OpenConfig models LAGs through two augments:

1. `openconfig-if-aggregate` — augments the interface list with
   logical aggregator records (the LAG itself).  Carries
   `aggregate-id` per member interface plus aggregator config
   (`lag-type`, `min-links`).
2. `openconfig-lacp` — separate `<lacp>` top-level container with
   per-LAG LACP rate / mode / system-id config.

The cisco_iosxe codec parses neither augment.  However, LAG-shaped
interface records (Cisco's `Port-channel<N>` family) DO land on the
canonical tree when they appear at the top level of `<interfaces>`:

* `interfaces[].name = "Port-channel1"` — survives
* `interfaces[].interface_type = "iana-if-type:ieee8023adLag"` —
  survives (this is the IANA ident the source XML carries)
* `interfaces[].ipv4_addresses` / `ipv6_addresses` on the
  Port-channel — survives

What does NOT survive:

* `interfaces[].lag_member_of` — would come from the
  `openconfig-if-aggregate:aggregate-id` leaf on member interfaces;
  the codec does not extract it.  Member interfaces appear on the
  canonical tree but with no parent-LAG back-pointer.
* `intent.lags[]` records — would come from the aggregator-side
  walk; the codec does not populate this list.
* LACP mode / rate / min-links — never reach canonical.

## RouterOS bonding form

RouterOS bonding is a single section:

```
/interface bonding
add name=bond1 mode=802.3ad slaves=ether1,ether2 \
    transmit-hash-policy=layer-2-and-3 lacp-rate=1sec
```

The `slaves=` field is the inverse of OpenConfig's per-member
`aggregate-id` — RouterOS stores membership on the bonding record
rather than on each member.  The MikroTik codec's render walks
`intent.lags` to emit this; if `intent.lags` is empty (as it is
after cisco_iosxe parse), no `/interface bonding` lines appear.

## What survives the cross-pair

When a `Port-channel1` interface appears in the source XML, the
cisco_iosxe parser produces a `CanonicalInterface` record with
`name="Port-channel1"`, `interface_type="iana-if-type:ieee8023adLag"`,
plus any L3 addresses.  The MikroTik render emits this as a
free-standing `/interface ethernet` (because the type-inference
table does not recognise `Port-channel*` as a bonding-prefix) plus
its addresses.

This is incorrect: `Port-channel1` should map to `bond1` (or some
operator-chosen bonding name) under `/interface bonding`, with its
member interfaces declared in the `slaves=` field.  Because the
member-relationship is not in the canonical tree, the operator must
re-establish the bonding manually on the target RouterOS device.

## Disposition

`lags`: `not_applicable` — source codec produces no aggregator
records on parse.

`interfaces[].lag_member_of`: `not_applicable` — source codec does
not extract membership.

These flip to `lossy` if the cisco_iosxe codec ever wires up the
aggregate / LACP augments.  Until then, the operator-visible result
is that LAG topology must be reconstructed by hand on the target.
