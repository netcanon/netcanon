# 06 — Capabilities matrix

Proposed `CapabilityMatrix` declarations for the NX-OS codec, by
phase.  Each row's justification cites the grammar surface from
`01-grammar-survey.md` and the canonical xpath from
`03-canonical-mapping.md`.

Reviewers can lift these tables directly into the codec's
`_CAPS` ClassVar at the corresponding phase.

---

## 1. Phase 1 — scaffolding matrix

Goal: parse hostname + minimal interfaces + VRF + VLAN.  Most
xpaths declared `unsupported` with deferral pointers to later
phases.

```python
_CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
    adapter="cisco_nxos",
    vendor_id="cisco_nxos",
    version_range="9.x+",
    device_classes=[DeviceClass.switch, DeviceClass.router],
    supported=[
        # System
        "/system/hostname",
        # Interfaces — name + basic L3
        "/interfaces/interface/name",
        "/interfaces/interface/config/name",
        "/interfaces/interface/config/description",
        "/interfaces/interface/config/enabled",
        "/interfaces/interface/config/mtu",
        "/interfaces/interface/ipv4/address/ip",
        "/interfaces/interface/ipv4/address/prefix-length",
        "/interfaces/interface/ipv6/address/ip",
        "/interfaces/interface/ipv6/address/prefix-length",
        "/interfaces/interface/vrf",
        # VLANs (top-level only; no port projection yet)
        "/vlans/vlan/id",
        "/vlans/vlan/name",
        # VRF (basic)
        "/routing-instances/instance/name",
        "/routing-instances/instance/description",
        # Static routes (default VRF only)
        "/routing/static-route",
    ],
    lossy=[
        LossyPath(
            path="/interfaces/interface/config/type",
            reason=(
                "NX-OS interface-type is inferred from the name prefix "
                "(Ethernet → ethernetCsmacd, loopback → softwareLoopback, "
                "Vlan → l3ipvlan, port-channel → ieee8023adLag, nve → "
                "vxlan tunnel, mgmt → ethernetCsmacd).  Inference is "
                "best-effort and may not catch every IANA type."
            ),
            severity="warn",
        ),
        LossyPath(
            path="/system/raw-sections/vdc",
            reason=(
                "NX-OS `vdc <name> id N / limit-resource ...` is N7K "
                "virtualisation grammar with no canonical primitive.  "
                "Preserved verbatim in raw_sections for same-vendor "
                "round-trip; cross-vendor render emits a hard-coded "
                "id-1 default block."
            ),
            severity="warn",
        ),
        LossyPath(
            path="/system/raw-sections/features",
            reason=(
                "NX-OS `feature <name>` declarations are derived on "
                "render from the canonical-tree shape.  Source `feature` "
                "lines that aren't motivated by any canonical surface "
                "(e.g. `feature scp-server`, `feature telnet`) round-trip "
                "via raw_sections but drop on cross-vendor render — "
                "operator must re-authorise management-API features on "
                "the target device."
            ),
            severity="warn",
        ),
    ],
    unsupported=[
        # Phase 2+ surfaces
        UnsupportedPath(
            path="/interfaces/interface/switchport-mode",
            reason="Switchport / L2-mode parse + render lands in Phase 2.",
        ),
        UnsupportedPath(
            path="/interfaces/interface/access-vlan",
            reason="Phase 2.",
        ),
        UnsupportedPath(
            path="/interfaces/interface/trunk-allowed-vlans",
            reason="Phase 2.",
        ),
        UnsupportedPath(
            path="/interfaces/interface/trunk-native-vlan",
            reason="Phase 2.",
        ),
        UnsupportedPath(
            path="/interfaces/interface/lag-member-of",
            reason="LAG / port-channel parse lands in Phase 2.",
        ),
        UnsupportedPath(
            path="/vlans/vlan/tagged-ports",
            reason="VLAN-centric port projection ships with Phase 2.",
        ),
        UnsupportedPath(
            path="/vlans/vlan/untagged-ports",
            reason="VLAN-centric port projection ships with Phase 2.",
        ),
        UnsupportedPath(
            path="/lags/lag",
            reason="Phase 2.",
        ),
        UnsupportedPath(
            path="/snmp/community",
            reason="SNMP parse + render lands in Phase 2.",
        ),
        UnsupportedPath(
            path="/snmp/v3-user",
            reason="SNMPv3 USM lands in Phase 2.",
        ),
        UnsupportedPath(
            path="/local-users/user",
            reason="Local-user parse + render lands in Phase 2.",
        ),
        UnsupportedPath(
            path="/routing-instances/instance/route-distinguisher",
            reason="VRF RD / RT parse lands in Phase 3.",
        ),
        UnsupportedPath(
            path="/routing-instances/instance/rt-imports",
            reason="Phase 3.",
        ),
        UnsupportedPath(
            path="/routing-instances/instance/rt-exports",
            reason="Phase 3.",
        ),
        UnsupportedPath(
            path="/routing-instances/instance/l3-vni",
            reason="L3VNI binding (`vrf context X / vni N`) lands in Phase 4 EVPN.",
        ),
        UnsupportedPath(
            path="/routing/static-route/vrf",
            reason=(
                "Per-VRF static route (`vrf context X / ip route Y/N Z`) "
                "lands in Phase 3.  Requires the "
                "CanonicalStaticRoute.vrf schema extension."
            ),
        ),
        UnsupportedPath(
            path="/vxlan-vnis/vni",
            reason="VXLAN-EVPN parse + render lands in Phase 4.",
        ),
        UnsupportedPath(
            path="/vxlan-vnis/source-interface",
            reason="Phase 4.",
        ),
        UnsupportedPath(
            path="/vxlan-vnis/udp-port",
            reason="Phase 4.",
        ),
        UnsupportedPath(
            path="/vxlan-vnis/mcast-group",
            reason="Phase 4 (head-end only initially; mcast deferred).",
        ),
        UnsupportedPath(
            path="/anycast-gateway",
            reason=(
                "Anycast-gateway-mac + per-SVI fabric-forwarding mode "
                "are T2's canonical surface and land in Phase 4.  "
                "Declared unsupported if T2 hasn't landed by Phase 4 "
                "ship date."
            ),
        ),
        # Tier-3 — never auto-translatable
        UnsupportedPath(
            path="/routing-protocols/bgp",
            reason=(
                "NX-OS `router bgp <asn>` is Tier-3 — captured in "
                "raw_sections and surfaced via dropped_tier3_sections "
                "for the migrate-page notification banner, but never "
                "auto-rendered cross-vendor."
            ),
        ),
        UnsupportedPath(
            path="/routing-protocols/ospf",
            reason="Tier-3.",
        ),
        UnsupportedPath(
            path="/routing-protocols/eigrp",
            reason="Tier-3.",
        ),
        UnsupportedPath(
            path="/routing-protocols/isis",
            reason="Tier-3.",
        ),
        UnsupportedPath(
            path="/access-list/extended",
            reason=(
                "ACLs are Tier-3 — see `/access-list/extended` in the "
                "cisco_iosxe_cli matrix for the cross-vendor reasoning."
            ),
        ),
        UnsupportedPath(
            path="/access-list/standard",
            reason="Tier-3 (mirrors cisco_iosxe_cli).",
        ),
        UnsupportedPath(
            path="/access-list/ipv6",
            reason="Tier-3.",
        ),
        UnsupportedPath(
            path="/firewall",
            reason=(
                "NX-OS does not host a stateful firewall; the path is "
                "declared unsupported for consistency with the cross-"
                "vendor capability surface."
            ),
        ),
        UnsupportedPath(
            path="/nat",
            reason=(
                "NX-OS does not host typical edge NAT; the path is "
                "declared unsupported."
            ),
        ),
        UnsupportedPath(
            path="/qos",
            reason=(
                "QoS (`class-map type qos` / `policy-map type qos` / "
                "`service-policy input/output`) is Tier-3 — DC-grade "
                "QoS is too platform-specific to auto-translate."
            ),
        ),
    ],
)
```

**Phase 1 summary**:
* Supported: 15 paths
* Lossy: 3
* Unsupported: 25 (most are "Phase X deferred")

`certainty="experimental"` at Phase 1 ship.

---

## 2. Phase 2 — L2 + SNMPv3 + local users

Promotes 12 paths from `unsupported` to `supported`.  No new lossy
declarations (the L2 surface round-trips cleanly).  HSRP-dependent
rows gate on T1 — if T1 hasn't landed, keep `/hsrp/*` (or
`/vrrp/*` depending on T1's naming) declared `unsupported`.

```python
# Added to `supported`:
"/interfaces/interface/switchport-mode",
"/interfaces/interface/access-vlan",
"/interfaces/interface/trunk-allowed-vlans",
"/interfaces/interface/trunk-native-vlan",
"/interfaces/interface/lag-member-of",
"/vlans/vlan/tagged-ports",
"/vlans/vlan/untagged-ports",
"/lags/lag/name",
"/lags/lag/members",
"/lags/lag/mode",
"/snmp/community",
"/snmp/location",
"/snmp/contact",
"/snmp/trap-host",
"/snmp/v3-user",
"/local-users/user/name",
"/local-users/user/role",
"/local-users/user/hashed-password",

# Conditional on T1:
"/hsrp/group/group-id",
"/hsrp/group/virtual-ip",
"/hsrp/group/priority",
"/hsrp/group/preempt",

# Added to `lossy`:
LossyPath(
    path="/local-users/user/privilege-level",
    reason=(
        "NX-OS uses `role` (network-admin / network-operator / "
        "custom) instead of numeric privilege.  Codec maps "
        "network-admin → 15, everything else → 1.  Cross-vendor "
        "renderers expecting numeric privilege will round-trip "
        "non-admin roles as privilege=1."
    ),
    severity="warn",
),
LossyPath(
    path="/snmp/v3-user/auth-passphrase",
    reason=(
        "NX-OS 10.x introduced `localizedV2key` digest format; v1 "
        "codec normalises to the older `localizedkey` form on "
        "render.  Operators migrating between OS versions or "
        "vendors must re-key SNMPv3 users on the target device."
    ),
    severity="warn",
),
LossyPath(
    path="/snmp/v3-user/engine-id",
    reason=(
        "NX-OS emits engineID in colon-decimal "
        "(`128:0:0:9:3:12:...`); cross-vendor sources typically "
        "use hex.  Preserved verbatim same-vendor; cross-vendor "
        "render may emit a syntactically-valid-but-functionally-"
        "incorrect engineID that requires re-keying."
    ),
    severity="warn",
),
```

**Phase 2 summary** (cumulative):
* Supported: ~32 paths (+ ~4 HSRP if T1 landed)
* Lossy: 6
* Unsupported: ~12 (Phase 3+ surfaces remain; QoS/ACL/NAT permanent)

`certainty="best_effort"` at Phase 2 ship.

---

## 3. Phase 3 — VRF + per-VRF routes + Tier-3 detection

Promotes VRF + static-route-VRF + a few more SNMP paths.  Tightens
the existing `unsupported` declarations.

```python
# Added to `supported`:
"/routing-instances/instance/route-distinguisher",
"/routing-instances/instance/rt-imports",
"/routing-instances/instance/rt-exports",
"/routing/static-route/vrf",          # NEW canonical field

# `unsupported` removals: /routing-instances/instance/* rows, /routing/static-route/vrf row.

# Added to `lossy`:
LossyPath(
    path="/routing-instances/instance/route-distinguisher",
    reason=(
        "NX-OS supports `rd auto` (deriving RD from the BGP ASN + "
        "VRF VNI) as well as explicit `rd <asn>:<nn>`.  Codec "
        "preserves `auto` as a sentinel string; cross-vendor "
        "renderers that don't recognise the sentinel must "
        "synthesise an explicit RD or emit nothing."
    ),
    severity="warn",
),
LossyPath(
    path="/routing-instances/instance/rt-imports",
    reason=(
        "NX-OS `route-target both <rt> evpn` is shorthand for "
        "advertising the RT in both L3 IPv4 unicast AND the L2VPN "
        "EVPN address-family.  The `evpn` discriminator does not "
        "round-trip to cross-vendor renderers; the RT is preserved "
        "but the address-family scope reverts to IPv4 unicast "
        "only on cross-vendor target."
    ),
    severity="warn",
),
```

**Phase 3 summary** (cumulative):
* Supported: ~36 paths
* Lossy: 8
* Unsupported: ~9 (Phase 4 + permanent Tier-3)

`certainty="best_effort"` at Phase 3 ship.

---

## 4. Phase 4 — EVPN-VXLAN

The big promotion: VXLAN + L3VNI + (conditional on T2) anycast.

```python
# Added to `supported`:
"/routing-instances/instance/l3-vni",
"/vxlan-vnis/vni",
"/vxlan-vnis/source-interface",
"/vxlan-vnis/udp-port",
"/vxlan-vnis/mcast-group",        # populated when source had mcast; head-end stays unsupported
"/vxlan-vnis/flood-list",         # populated for head-end; usually empty (BGP-EVPN inferred)

# Conditional on T2:
"/anycast-gateway/mac",
"/interfaces/interface/anycast-gateway-mode",

# Added to `lossy`:
LossyPath(
    path="/vxlan-vnis/vni",
    reason=(
        "NX-OS `interface nve1 / member vni N / suppress-arp / "
        "ingress-replication protocol bgp` sub-flags do not "
        "round-trip — codec emits the default modern BGP-EVPN "
        "head-end-replication shape on every render.  Source "
        "configs using legacy flood-and-learn or alternate IR "
        "protocols are dropped to defaults."
    ),
    severity="warn",
),
LossyPath(
    path="/evpn-type5-routes/route",
    reason=(
        "NX-OS L3VNI Type-5 announcement is implicit when a VRF "
        "carries `vrf context X / vni N / route-target both auto "
        "evpn` plus `router bgp / vrf X / address-family ipv4 "
        "unicast / advertise l2vpn evpn`.  Codec parses the "
        "shape into CanonicalEvpnType5Route best-effort; the "
        "exact prefix-filter route-map (if any) on the source "
        "does not round-trip."
    ),
    severity="warn",
),

# Removed from `unsupported`: /vxlan-vnis/*, /anycast-gateway (if T2 landed),
# /routing-instances/instance/l3-vni.
```

**Phase 4 summary** (cumulative):
* Supported: ~45 paths (or ~47 with T2's anycast surface)
* Lossy: 10
* Unsupported: ~5 (Tier-3 + Tunnel<N> + QoS — all permanent)

`certainty="best_effort"` at Phase 4 ship; `certainty="certified"`
once the 10.x fixture lands and 3 fixtures across 2 OS versions
clear the bar (Phase 4.5).

---

## 5. Reference: full Phase-4-final `supported` list

For the implementor — the full `supported` paths list at the end
of Phase 4, sorted alphabetically:

```
/anycast-gateway/mac                              ← T2
/interfaces/interface/access-vlan
/interfaces/interface/anycast-gateway-mode        ← T2
/interfaces/interface/config/description
/interfaces/interface/config/enabled
/interfaces/interface/config/mtu
/interfaces/interface/config/name
/interfaces/interface/config/type                 ← lossy
/interfaces/interface/ipv4/address/ip
/interfaces/interface/ipv4/address/prefix-length
/interfaces/interface/ipv6/address/ip
/interfaces/interface/ipv6/address/prefix-length
/interfaces/interface/kind
/interfaces/interface/lag-member-of
/interfaces/interface/name
/interfaces/interface/switchport-mode
/interfaces/interface/trunk-allowed-vlans
/interfaces/interface/trunk-native-vlan
/interfaces/interface/vrf
/hsrp/group/group-id                              ← T1
/hsrp/group/priority                              ← T1
/hsrp/group/virtual-ip                            ← T1
/hsrp/group/preempt                               ← T1
/lags/lag/members
/lags/lag/mode
/lags/lag/name
/local-users/user/hashed-password
/local-users/user/name
/local-users/user/privilege-level                 ← lossy
/local-users/user/role
/routing-instances/instance/description
/routing-instances/instance/l3-vni
/routing-instances/instance/name
/routing-instances/instance/route-distinguisher   ← lossy ("auto" sentinel)
/routing-instances/instance/rt-exports
/routing-instances/instance/rt-imports            ← lossy ("evpn" suffix)
/routing/static-route
/routing/static-route/vrf                         ← NEW canonical field
/snmp/community
/snmp/contact
/snmp/location
/snmp/trap-host
/snmp/v3-user
/snmp/v3-user/auth-passphrase                     ← lossy (v2key)
/snmp/v3-user/engine-id                           ← lossy (colon-decimal vs hex)
/system/hostname
/vlans/vlan/id
/vlans/vlan/name
/vlans/vlan/tagged-ports
/vlans/vlan/untagged-ports
/vxlan-vnis/flood-list
/vxlan-vnis/mcast-group
/vxlan-vnis/source-interface
/vxlan-vnis/udp-port
/vxlan-vnis/vni                                   ← lossy (sub-flags)
```

**Total: ~50-54 supported paths** (depending on T1/T2 landing).

---

## 6. Permanent `unsupported` list (post-Phase-4)

These never become supported in v1 — they're either Tier-3
(operator must manually re-author) or fall outside the codec's
v1 scope:

```python
UnsupportedPath(path="/routing-protocols/bgp", reason="Tier-3"),
UnsupportedPath(path="/routing-protocols/ospf", reason="Tier-3"),
UnsupportedPath(path="/routing-protocols/eigrp", reason="Tier-3"),
UnsupportedPath(path="/routing-protocols/isis", reason="Tier-3"),
UnsupportedPath(path="/access-list/extended", reason="Tier-3"),
UnsupportedPath(path="/access-list/standard", reason="Tier-3"),
UnsupportedPath(path="/access-list/ipv6", reason="Tier-3"),
UnsupportedPath(path="/access-list/mac", reason="Tier-3"),
UnsupportedPath(path="/route-map", reason="Tier-3"),
UnsupportedPath(path="/class-map", reason="Tier-3 (QoS)"),
UnsupportedPath(path="/policy-map", reason="Tier-3 (QoS)"),
UnsupportedPath(path="/qos", reason="Tier-3 (QoS umbrella)"),
UnsupportedPath(path="/firewall", reason="NX-OS does not host stateful firewall"),
UnsupportedPath(path="/nat", reason="NX-OS does not host edge NAT"),
UnsupportedPath(path="/crypto", reason="Tier-3 (no canonical crypto model)"),
UnsupportedPath(path="/aaa", reason="Tier-3"),
UnsupportedPath(path="/monitor-session", reason="Tier-3 (SPAN/RSPAN)"),
UnsupportedPath(path="/multicast/pim", reason="Tier-3"),
UnsupportedPath(path="/interfaces/interface/tunnel-type", reason="Tunnel<N> grammar deferred — not in v1 corpus"),
UnsupportedPath(path="/interfaces/interface/dhcp-client-v6", reason="Defer — not in v1 corpus"),
UnsupportedPath(path="/dhcp-servers/pool", reason="Defer; NX-OS rarely hosts DHCP servers"),
UnsupportedPath(path="/radius-servers/server", reason="Defer — not in v1 corpus"),
```

---

## 7. Comparison with peer codecs

How NX-OS's matrix size compares to existing bidirectional codecs
(supported-path count at certified tier):

| Codec | Supported paths | Lossy | Unsupported |
|---|---|---|---|
| cisco_iosxe_cli | ~25 | 3 | ~9 |
| cisco_iosxe (NETCONF) | ~30 | similar | similar |
| arista_eos | ~28 | similar | similar |
| juniper_junos | ~35 | similar | similar |
| aruba_aoss | ~22 | similar | similar |
| fortigate_cli | ~18 | similar | similar |
| mikrotik_routeros | ~25 | similar | similar |
| opnsense | ~24 | similar | similar |
| **cisco_nxos (proposed)** | **~50-54** | **10** | **~22** |

NX-OS would ship with the **broadest declared surface** of any
codec — driven primarily by VRF + VXLAN + EVPN Type-5 + L3VNI
fields that the OpenConfig-lite model already accommodates but
no existing codec exercises in full.  This makes NX-OS the
**reference codec** for the EVPN-VXLAN cross-vendor surface,
unlocking high-fidelity translation to Arista EOS and Junos.

---

## 8. Capability matrix render in the UI

When operators use the `/migrate` page and select NX-OS as source
or target, the supported-paths list above becomes:

* **Source NX-OS, Target Arista EOS**: cross-vendor compatibility
  is high — 90%+ of the supported paths above are mirrored in
  Arista's matrix.  UI shows green "compatible" banner.
* **Source NX-OS, Target Junos QFX**: similar — Junos has VRF +
  VXLAN + EVPN.  Green banner.
* **Source NX-OS, Target IOS-XE Catalyst**: warns on
  `/routing-instances/instance/l3-vni` (IOS-XE Catalyst 9k SDA has
  the concept but a different grammar), `/vxlan-vnis/*` (IOS-XE
  VXLAN is parse-and-ignore — see existing `cisco_iosxe_cli`
  matrix line ~190).  Amber banner.
* **Source NX-OS, Target Aruba / FortiGate / MikroTik / OPNsense**:
  warns on every Tier-2 surface — these vendors don't model VXLAN
  or VRF cleanly.  Red banner for VRF/VXLAN-heavy NX-OS sources.

These banners are the operator-facing payoff of the matrix being
declarative.  The implementor should write a few smoke tests that
verify the banner JSON output matches the matrix declarations
end-to-end.

---

## 9. Implementor handoff

For Phase 1 of the NX-OS codec, the implementor:
1. Copies the **Phase 1** matrix block from § 1 into the codec's
   `_CAPS` ClassVar.
2. Writes parse + render paths covering every `supported` row.
3. Verifies via `pytest tests/unit/migration/test_cisco_nxos.py` +
   `pytest tests/unit/migration/test_real_captures.py -k nx_os`.
4. Submits the Phase 1 PR.

For Phase 2, 3, 4 — repeat with the corresponding matrix block
above.  Each phase's PR contains the matrix update + the parse +
render path enablements + test additions in one cohesive review.
