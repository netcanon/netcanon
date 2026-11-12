# Static routes: Juniper Junos versus FortiGate FortiOS

<!-- junos-route-preference -->
> **Update 2026-11-12 — a static route's `preference` is read as its distance.**  Up to 0.7.7 the Junos parser read no `preference` and left every `qualified-next-hop` out, so a floating route lost its backup and a route held at a preference came out at the target's default.  Each next hop's preference -- a qualified next hop's own, else the route's, else `static defaults preference` -- is now its distance, written `set distance <N>` in each next hop's `config router static` entry; where some next hops of a route state one, the others are given Junos's default, 5.  A next hop at a preference of 0 or of 255 and above, and a qualified next hop with a `metric` of its own at the preference of another next hop of the route, are left out with a row.  What the body below says of `preference` and `qualified-next-hop` predates this.

<!-- junos-rib-inet6 -->
> **Update 2026-11-12 — an IPv6 static route of `rib inet6.0` is read.**  Junos holds an IPv6 static route in `inet6.0`, `set routing-options rib inet6.0 static route ...` ([Juniper, Example: Configuring IPv6 Static Routes](https://www.juniper.net/documentation/en_US/junos12.3/topics/example/policy-ipv6-static-routes.html)), and in a routing instance in `<instance>.inet6.0` ("In a routing instance, the routing table name must include the routing instance name", [Juniper, rib (Routing Options)](https://www.juniper.net/documentation/us/en/software/junos/static-routing/topics/ref/statement/rib-edit-routing-options.html)).  Up to 0.7.7 the Junos parser read no `rib` line, and such a route was lost on every target, with nothing said, whatever the body below says of it.  A static route of `rib inet.0` and `rib inet6.0`, and of the instance's own two tables, is now read as one of `static` is; a static route of any other table is left out, and one row counts them.  The body's `set routing-options static route ::/0 ...` is not where Junos holds an IPv6 route.

<!-- vrf-route-left-out -->
> **Update 2026-11-12 — a route of a VRF is left out of a FortiOS output under a review line.**  Up to 0.7.7 the FortiOS render wrote a route of another vendor's VRF as an entry of `config router static` (`static6`), a route of the global table, where it routed traffic the source routed in another VRF; the job was `partial` for the route's VRF and said nothing more.  It now writes `# review: static route <destination> is in VRF <name>, and the output puts nothing in a VRF; not written` in its place (FortiOS names a VRF by a number, `set vrf <0-251>`, which a VRF's name does not give).  On the committed inputs the 5 routes of a VRF, on 4 cells, are left out.  What follows about a route of a VRF on the FortiOS side describes the output before this change.

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
- **Per-VRF static routes** — `unsupported`.  The `juniper_junos`
  source codec now harvests per-VRF statics onto
  `CanonicalStaticRoute.vrf` (`set routing-instances X routing-options
  static route <dest> next-hop <gw>`), so the VRF reaches canonical on
  this direction.  The loss is target-side: the FortiGate codec
  declares `/routing/static-route/vrf` `unsupported` and does not
  render the per-interface integer-VRF form, so the VRF drops on
  render.

## Cross-vendor mapping (FortiGate -> Junos)

Reverse direction (see also `../fortigate_cli_to_juniper_junos/static_routes.md`):

- **interface** — `lossy`.  FortiOS `set device "port1"` requires
  rename mesh.
- **metric** — same vendor-semantic mismatch.
- **Per-VRF** — `unsupported`.
