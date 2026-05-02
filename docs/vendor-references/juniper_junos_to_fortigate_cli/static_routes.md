# Static routes: Juniper Junos versus FortiGate FortiOS

## Juniper Junos

Source: [Junos static routing topic-map](https://www.juniper.net/documentation/us/en/software/junos/static-routing/topics/topic-map/static-routing-overview.html).
Retrieved: 2026-05-01.

Junos models static routes under `set routing-options static
route ...`:

```
set routing-options static route 0.0.0.0/0 next-hop 198.51.100.1
set routing-options static route 10.99.0.0/16 next-hop 10.20.0.254
set routing-options static route 192.168.50.0/24 qualified-next-hop 10.0.0.5 preference 10
set routing-options static route 192.168.50.0/24 qualified-next-hop 10.0.0.6 preference 20
set routing-options static route ::/0 next-hop 2001:db8::2
#
# Per-VRF
set routing-instances TENANT_A routing-options static route 192.168.100.0/24 next-hop 10.10.0.1
```

Notable Junos specifics:

- **Destination form**: CIDR.
- **Next hop**: `next-hop <addr>`; `discard` / `reject` for special
  forms; `qualified-next-hop` for multi-NH preference.
- **Preference**: AD analogue; lower = preferred.
- **Per-VRF**: under `set routing-instances <name> routing-options
  static route ...`.
- **Outgoing interface**: typically encoded via next-hop reachability,
  not a separate field.

## FortiGate FortiOS

Source: [FortiGate / FortiOS Administration Guide — Routing / Static routes](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-05-01.

FortiGate models static routes under `config router static`, keyed
by numeric edit ID:

```
config router static
    edit 1
        set dst 0.0.0.0 0.0.0.0
        set gateway 198.51.100.1
        set device "port1"
    next
    edit 2
        set dst 10.99.0.0 255.255.0.0
        set gateway 10.20.0.254
        set device "agg1"
        set distance 5
    next
end
```

Notable FortiOS specifics:

- **Destination**: dotted-quad address + dotted-quad mask.
- **Outgoing interface**: `set device "<ifname>"` (typically
  required for ECMP keying).
- **Distance**: `set distance N` (1-255).  Default 10.
- **VRF binding**: `set vrf <id>` (FortiOS 7.0+, integer 0-251).
  Not parsed into canonical in v1.

## Cross-vendor mapping (Junos -> FortiGate)

Canonical surface (`CanonicalStaticRoute`).

- **destination** — `good`.  CIDR -> dotted-mask on FortiGate render.
- **gateway** — `good`.  Direct map.
- **interface** — `lossy`.  Junos has no first-class outgoing-
  interface field; FortiGate render synthesises from next-hop
  reachability if needed.
- **metric** — `lossy`.  Junos `preference` and FortiGate `distance`
  are vendor-specific scalars not 1:1.  Integer preserves; semantics
  differ.
- **description** — `lossy`.  Junos has no per-route description in
  the canonical canonical scope; FortiGate `set comment` is not
  emitted in v1.
- **qualified-next-hop** flattens to multiple canonical entries with
  different metrics; FortiGate render emits multiple `edit N`
  records.
- **Per-VRF static routes** — `unsupported`.  CanonicalStaticRoute
  lacks a `vrf` field.

## Cross-vendor mapping (FortiGate -> Junos)

Reverse direction (see also `../fortigate_cli_to_juniper_junos/static_routes.md`):

- **interface** — `lossy`.  FortiOS `set device "port1"` requires
  rename mesh.
- **metric** — same vendor-semantic mismatch.
- **Per-VRF** — `unsupported`.
