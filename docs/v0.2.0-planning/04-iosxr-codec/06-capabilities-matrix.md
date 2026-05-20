# 06 — Capabilities matrix

> Proposed initial `CapabilityMatrix` declaration for the
> `cisco_iosxr` codec.  Mirrors the structure used by every
> shipped bidirectional codec (see `cisco_iosxe_cli/codec.py:106`
> for the IOS-XE reference and `juniper_junos/codec.py:116` for
> the Junos reference).

## Phase 1 declaration (parse_only, experimental)

```python
_CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
    adapter="cisco_iosxr",
    vendor_id="cisco_iosxr",
    version_range="6.x / 7.x",
    device_classes=[DeviceClass.router],
    supported=[
        "/system/hostname",
        "/interfaces/interface/name",
        "/interfaces/interface/config/name",
        "/interfaces/interface/config/description",
        "/interfaces/interface/config/enabled",
        "/interfaces/interface/ipv4/address/ip",
        "/interfaces/interface/ipv4/address/prefix-length",
        "/interfaces/interface/ipv6/address/ip",
        "/interfaces/interface/ipv6/address/prefix-length",
        "/interfaces/interface/dhcp-client-v6",
        # ──────────────────────────────────────────────────────
        # NOTE: VLAN/static route declarations omitted from Phase 1
        # `supported` — see lossy/unsupported below.
        # ──────────────────────────────────────────────────────
    ],
    lossy=[
        LossyPath(
            path="/interfaces/interface/config/type",
            reason=(
                "CLI parser infers interface type from the name prefix "
                "(GigabitEthernet → ethernetCsmacd, Loopback → "
                "softwareLoopback, Bundle-Ether → ieee8023adLag, "
                "MgmtEth → ethernetCsmacd) but cannot detect all IANA "
                "types — sub-interfaces with vendor-specific encapsulation "
                "(MPLSoGRE, segment-routing) classify as 'other'."
            ),
            severity="warn",
        ),
        LossyPath(
            path="/interfaces/interface/4th-port-segment",
            reason=(
                "IOS-XR port names use 4 segments (rack/slot/instance/"
                "port) while the cross-vendor PortIdentity supports only "
                "3 (stack/module/port).  The 4th segment is preserved "
                "via PortIdentity.meta['iosxr_port_index'] for same-"
                "vendor round-trip but DROPS to '0' when renaming to "
                "IOS-XE / Arista / any 3-segment naming target.  Operators "
                "must verify port mappings via the rename modal."
            ),
            severity="warn",
        ),
    ],
    unsupported=[
        # ── Routing protocols — Tier 3 ──
        UnsupportedPath(
            path="/routing/bgp",
            reason=(
                "IOS-XR `router bgp <asn>` is Tier-3 in v1.  The XR "
                "BGP grammar includes per-VRF address-family blocks "
                "and neighbor-group templates that diverge from IOS-XE "
                "syntax — full parse + render warrants a dedicated "
                "follow-up commit.  Phase 3 adds a minimal harvest "
                "(ASN, router-id, per-VRF RD) but full BGP modeling "
                "stays unsupported."
            ),
        ),
        UnsupportedPath(
            path="/routing/ospf",
            reason=(
                "`router ospf <pid>` stanza parses-and-ignores in v1; "
                "OSPF area + interface-cost grammar is internally "
                "consistent across XR/XE but no canonical model lands "
                "before v0.3.0."
            ),
        ),
        UnsupportedPath(
            path="/routing/isis",
            reason=(
                "`router isis <name>` parse-and-ignore.  IS-IS is "
                "SP-routing standard but no canonical surface defined."
            ),
        ),
        UnsupportedPath(
            path="/mpls",
            reason=(
                "`mpls ldp` / `mpls traffic-eng` / `mpls oam` stanzas "
                "are SP-platform fundamentals but no canonical model "
                "exists.  Parse-and-ignore in v1; Tier-3 banner notes "
                "the dropped surface."
            ),
        ),
        # ── Policy primitives — Tier 3 ──
        UnsupportedPath(
            path="/policy/route-policy",
            reason=(
                "IOS-XR `route-policy NAME ... end-policy` is a "
                "structured if/elseif/else/endif DSL distinct from "
                "IOS-XE `route-map` sequence form.  Tier-3 by design — "
                "parity with Junos `policy-options` (also unsupported). "
                "Cross-vendor route-policy translation is operator-"
                "authored on the target side."
            ),
        ),
        UnsupportedPath(
            path="/policy/prefix-set",
            reason=(
                "IOS-XR `prefix-set NAME ... end-set` set-form prefix "
                "list.  Pairs with route-policy in the Tier-3 policy "
                "surface — same operator-authored-on-target convention."
            ),
        ),
        UnsupportedPath(
            path="/policy/community-set",
            reason=(
                "IOS-XR `community-set NAME ... end-set` set-form "
                "community list.  Tier-3, same rationale as prefix-set."
            ),
        ),
        UnsupportedPath(
            path="/policy/as-path-set",
            reason=(
                "IOS-XR `as-path-set NAME ... end-set` set-form "
                "AS-path filter.  Tier-3."
            ),
        ),
        # ── EVPN / VXLAN — out of v1 scope ──
        UnsupportedPath(
            path="/vxlan-vnis/vni",
            reason=(
                "IOS-XR VXLAN runs on NCS 5500 / NCS 540 platforms via "
                "`nve` interfaces.  Rare in the SP corpus; no canonical "
                "demand surfaced.  Parse-and-ignore in v1."
            ),
        ),
        UnsupportedPath(
            path="/vxlan-vnis/source-interface",
            reason="See /vxlan-vnis/vni — same scope.",
        ),
        UnsupportedPath(
            path="/vxlan-vnis/udp-port",
            reason="See /vxlan-vnis/vni — same scope.",
        ),
        UnsupportedPath(
            path="/evpn-type5-routes/route",
            reason=(
                "IOS-XR EVPN configuration runs under top-level "
                "`l2vpn` + `evpn` + `bridge group` stanzas — "
                "grammatically distant from IOS-XE / Arista / NX-OS "
                "EVPN.  No canonical mapping in v1."
            ),
        ),
        # ── Firewall / NAT / ACL — Tier 3 ──
        UnsupportedPath(
            path="/access-list/extended",
            reason=(
                "IOS-XR `ipv4 access-list NAME / N permit ...` is "
                "Tier-3 — auto-translating ACL semantics across "
                "vendors risks shipping subtly-permissive rules.  "
                "Operator must author firewall policy manually.  "
                "Parity with the IOS-XE codec which lists the same "
                "path as unsupported."
            ),
        ),
        UnsupportedPath(
            path="/access-list/ipv6",
            reason="See /access-list/extended — same scope, IPv6 variant.",
        ),
        UnsupportedPath(
            path="/firewall",
            reason=(
                "IOS-XR firewall features (zone-based policy + ASA-"
                "integrated) are Tier-3 stateful surfaces — never "
                "auto-translatable.  Parity with IOS-XE codec."
            ),
        ),
        UnsupportedPath(
            path="/nat",
            reason=(
                "IOS-XR NAT configuration (`nat64` / `cgnat` / "
                "service-app deployments) is Tier-3.  Parity with "
                "IOS-XE codec.  Operator must author NAT manually."
            ),
        ),
        # ── L2 surfaces XR doesn't have ──
        UnsupportedPath(
            path="/vlans/vlan/id",
            reason=(
                "IOS-XR routers don't have classic VLAN stanzas "
                "(`vlan N / name X`) — VLAN-id appears only on "
                "subinterfaces via `encapsulation dot1q <vid>`. "
                "Phase 1 synthesises bare CanonicalVlan records "
                "from subinterface tags but the `name` field is "
                "always empty and there are no port-membership "
                "lists.  Migrating an XR config to a switch codec "
                "(Arista / Aruba / IOS-XE Catalyst) requires "
                "operator review of the synthesised VLAN list."
            ),
        ),
    ],
)
```

## Phase 2 amendments

When `direction` flips to `bidirectional`, add to `supported`:

```python
        "/interfaces/interface/config/vrf",      # NEW — XR `vrf <name>` on iface
        "/vlans/vlan/id",                        # Move from unsupported — Phase 2 synth lands
        "/vlans/vlan/name",
        "/routing/static-route",                 # router static stanza
        "/routing-instances/instance",           # vrf top-level + RT imports/exports
        # ── Tier 2 — local users ──
        "/aaa/authentication/users/user/config/username",
        "/aaa/authentication/users/user/config/password",
        "/aaa/authentication/users/user/config/role",  # `role` carries XR group name
        # ── Tier 2 — LAGs ──
        "/lags/lag/name",
        "/lags/lag/members",
        "/lags/lag/mode",
```

Move from `unsupported` to `lossy`:

```python
        LossyPath(
            path="/routing-instances/instance",
            reason=(
                "VRF declarations (`vrf NAME / address-family ipv4 "
                "unicast / import|export route-target`) are parsed + "
                "rendered, but `route_distinguisher` requires reading "
                "from the BGP block (`router bgp ASN / vrf NAME / rd "
                "RD`).  Phase 2 wires a minimal BGP-RD harvest; XR "
                "configs without `router bgp` stanzas keep "
                "route_distinguisher='' on round-trip even if the "
                "source declared an RD elsewhere.  Per-VRF static "
                "routes drop their VRF discriminator on canonical "
                "(same gap as the IOS-XE codec) and merge into the "
                "global VRF on round-trip."
            ),
            severity="warn",
        ),
```

## Phase 3+ amendments

When `_tier3_detection.detect_tier3_sections_iosxr()` lands, all the
explicitly-unsupported `/routing/*` and `/policy/*` paths gain a
correlated **notification surface** via
`CanonicalIntent.dropped_tier3_sections`.  No CapabilityMatrix change
— the unsupported declarations stay the same; the *user-facing*
banner improves because the operator sees the specific stanza
headers dropped.

## Phase 4 amendments (`certified` certainty)

```python
    certainty: ClassVar[str] = "certified"   # was "experimental"
```

No CapabilityMatrix delta — just the certainty flip on the codec
class metadata.  The flip is gated on ≥3 real captures
round-tripping cleanly (per `base.py:142-144` documentation), which
the 7 batfish + 2 follow-on fixtures more than satisfy.

---

## Comparison to peer codecs

How T4's matrix compares to its closest cousins:

| Codec | supported (Phase-end) | lossy (Phase-end) | unsupported (Phase-end) |
|---|---|---|---|
| `cisco_iosxe_cli` (today) | 17 | 3 | 8 |
| `juniper_junos` (today) | 19 | 3 | 2 |
| `arista_eos` (today) | ~18 | ~5 | ~10 |
| **`cisco_iosxr` Phase 1** | 10 | 2 | 14 |
| **`cisco_iosxr` Phase 2** | 22 | 3 | 12 |
| **`cisco_iosxr` Phase 4** | 22 | 3 | 12 |

The relatively high `unsupported` count at Phase 2 reflects T4's
position as an **SP-routing platform** codec — XR's home turf is
exactly the BGP / OSPF / IS-IS / route-policy / MPLS surfaces that
every other shipped codec also declares unsupported.  This is
**intentional** — Tier-3 routing-protocol grammar stays manual-
review across all codecs to avoid shipping subtly-wrong policy
across vendor boundaries.

The `lossy` count stays low because XR's Tier-1 grammar is fairly
clean — the only documented losses are interface-type inference and
the 4-segment-port truncation on cross-vendor renames.

---

## Lossy/unsupported severity decisions

| Path | Severity | Why |
|---|---|---|
| `/interfaces/interface/4th-port-segment` | warn (LossyPath) | Cross-vendor migration is the common case; warning lets it proceed.  Same-vendor XR↔XR round-trip preserves the 4th segment via `PortIdentity.meta` — no warning fires |
| `/interfaces/interface/config/type` | warn | Same rationale as the IOS-XE codec's identical declaration |
| `/routing-instances/instance` (Phase 2) | warn | Operator gets a clear notification but migration proceeds; matches IOS-XE convention |
| `/policy/route-policy` (UnsupportedPath) | (always block per matrix rules) | Honest declaration of the Tier-3 surface; operator must explicitly `force=True` to ignore.  Same convention as Junos `/firewall/filter` |
| `/routing/bgp`, `/routing/ospf`, etc. | (always block) | Honest Tier-3 declaration |

The `block` severity for unsupported paths is automatic per
`CapabilityMatrix.classify` resolution rules
(`netcanon/models/migration.py:186-210`); the operator can always
override via `force=True` on the migration request.

---

## Wiring into `definitions/vendors/cisco_iosxr.yaml`

A new vendor YAML file should land alongside Phase 1, modeled on
`definitions/vendors/cisco_iosxe.yaml`:

```yaml
# definitions/vendors/cisco_iosxr.yaml
id: cisco_iosxr
display_name: Cisco IOS-XR
device_classes:
  - router
default_timeout: 30
notes: |
  Cisco's service-provider routing NOS (ASR 9000 / NCS 5500 / 540 /
  8000 series).  Grammar diverges sharply from IOS-XE: `vrf` as a
  top-level stanza, `route-policy` instead of `route-map`,
  4-segment port names (rack/slot/instance/port), `Bundle-Ether`
  for LAGs, `ipv4 address` inside interface stanzas.
```

The vendor YAML is consumed by the UI at startup
(`netcanon/migration/canonical/loader.py` — TBD where vendor YAML
loads).  Codec's `vendor_id="cisco_iosxr"` ties the two together.

---

## How the matrix gets reviewed at PR time

The capability matrix is the **most-reviewed** piece of any new
codec PR (per `CONTRIBUTING.md` conventions).  Reviewers check:

1. **Is every `supported` path actually round-tripped by a test?**
   `tests/unit/migration/test_cisco_iosxr.py::TestCapabilityMatrix`
   should iterate the matrix and confirm each path appears in at
   least one `iter_xpaths` invocation against a sample tree.
2. **Are the `lossy` reasons specific enough?**  "Some data may be
   lost" is unacceptable.  The reasons must tell the operator
   *what* data, *when*, and *why*.
3. **Is anything in `unsupported` actually parseable?**  If yes,
   re-classify as `lossy` (preserves on round-trip with caveats).
   The `unsupported` list is for surfaces the codec **cannot** even
   carry through the canonical tree round-trip.
4. **Do the paths match the canonical xpath vocabulary?**  Check
   against `_walk_canonical` in `cisco_iosxe_cli/codec.py:445` —
   the canonical yields a fixed set of strings, and capability
   paths must match exactly for `classify()` to find them.

These conventions inform every decision in this declaration.
