# 05 — Capabilities matrix updates

Proposed `supported` / `lossy` / `unsupported` rows per codec for
the anycast canonical surface, plus drafted edits for
[`docs/CAPABILITIES.md`](../../CAPABILITIES.md).

---

## Canonical xpath strings

The anycast surface adds the following xpaths to the canonical
xpath vocabulary (walked by each codec's `iter_xpaths`):

| xpath | Field on canonical model | Notes |
|---|---|---|
| `/interfaces/interface/ipv4/address/virtual-gateway-address` | `CanonicalIPv4Address.virtual_gateway_address` | Per-address; non-empty marks anycast intent |
| `/interfaces/interface/ipv4/address/virtual-gateway-mac` | `CanonicalIPv4Address.virtual_gateway_mac` | Per-address override; only Junos has source grammar |
| `/interfaces/interface/ipv4/address/is-secondary` | `CanonicalIPv4Address.is_secondary` | EOS VARP secondary trailer |
| `/interfaces/interface/ipv6/address/virtual-gateway-address` | `CanonicalIPv6Address.virtual_gateway_address` | Mirror of v4 |
| `/interfaces/interface/ipv6/address/virtual-gateway-mac` | `CanonicalIPv6Address.virtual_gateway_mac` | Mirror of v4 |
| `/system/anycast-gateway-mac` | `CanonicalIntent.anycast_gateway_mac` | System-wide; EOS / NX-OS / IOS-XE source it |
| `/vlans/vlan/ipv4-addresses/virtual-gateway-address` | (via fold) | The SVI-fold transform projects the per-IP anycast onto `CanonicalVlan.ipv4_addresses`; same path also appears here for VLAN-centric renderers |
| `/vlans/vlan/ipv6-addresses/virtual-gateway-address` | (via fold) | Mirror |

The VLAN-centric xpaths are derived from the SVI fold; codec
`iter_xpaths` walks the canonical tree and emits both
`/interfaces/.../virtual-gateway-address` AND
`/vlans/vlan/.../virtual-gateway-address` when the field is
non-empty on a `CanonicalVlan.ipv4_addresses[i]`.

---

## Per-codec proposed declarations

### `juniper_junos` (bidirectional)

**Add to `supported=[...]`:**
```python
"/interfaces/interface/ipv4/address/virtual-gateway-address",
"/interfaces/interface/ipv4/address/virtual-gateway-mac",
"/interfaces/interface/ipv4/address/is-secondary",   # always False on Junos (no secondary keyword)
"/interfaces/interface/ipv6/address/virtual-gateway-address",
"/interfaces/interface/ipv6/address/virtual-gateway-mac",
"/vlans/vlan/ipv4-addresses/virtual-gateway-address",
"/vlans/vlan/ipv6-addresses/virtual-gateway-address",
```

**Add to `lossy=[...]`:**
```python
LossyPath(
    path="/system/anycast-gateway-mac",
    reason=(
        "Junos has no system-wide anycast MAC declaration "
        "(per-IRB-unit ``virtual-gateway-v4-mac`` / "
        "``virtual-gateway-v6-mac`` is the only source-side "
        "grammar).  Cross-vendor sources carrying a system-wide "
        "MAC apply it to every IRB unit at render time "
        "(duplicated per-unit override emission); the inverse "
        "direction (Junos source -> system-wide-MAC target) "
        "uses the first observed per-unit MAC and emits a review "
        "banner for any unit with a differing MAC."
    ),
    severity="warn",
),
```

### `arista_eos` (bidirectional)

**Add to `supported=[...]`:**
```python
"/interfaces/interface/ipv4/address/virtual-gateway-address",  # VARP
"/interfaces/interface/ipv4/address/is-secondary",             # VARP secondary trailer
"/interfaces/interface/ipv6/address/virtual-gateway-address",  # IPv6 VARP (4.30+)
"/system/anycast-gateway-mac",                                 # ip virtual-router mac-address
"/vlans/vlan/ipv4-addresses/virtual-gateway-address",
"/vlans/vlan/ipv6-addresses/virtual-gateway-address",
```

**Add to `lossy=[...]`:**
```python
LossyPath(
    path="/interfaces/interface/ipv4/address/virtual-gateway-mac",
    reason=(
        "EOS only supports a system-wide virtual-router MAC "
        "(``ip virtual-router mac-address``).  Per-IP overrides "
        "(Junos-style ``virtual-gateway-v4-mac``) surface as a "
        "review-required banner on render; the renderer picks "
        "the first observed per-IP MAC for the system-wide "
        "field and emits comment-form review lines for any "
        "differing MACs."
    ),
    severity="warn",
),
LossyPath(
    path="/interfaces/interface/ipv6/address/virtual-gateway-mac",
    reason=(
        "Mirror of the IPv4 case.  EOS shares one system-wide "
        "MAC across IPv4 and IPv6 anycast."
    ),
    severity="warn",
),
```

### `cisco_iosxe_cli` (bidirectional)

**Add to `supported=[...]`:**
```python
"/interfaces/interface/ipv4/address/virtual-gateway-address",  # SD-Access fabric forwarding
"/system/anycast-gateway-mac",                                 # fabric forwarding anycast-gateway-mac
"/vlans/vlan/ipv4-addresses/virtual-gateway-address",
```

**Add to `lossy=[...]`:**
```python
LossyPath(
    path="/interfaces/interface/ipv4/address/virtual-gateway-mac",
    reason=(
        "IOS-XE SD-Access only supports system-wide ``fabric "
        "forwarding anycast-gateway-mac``.  Per-IP MAC overrides "
        "(Junos source) surface as review-required."
    ),
    severity="warn",
),
LossyPath(
    path="/interfaces/interface/ipv6/address/virtual-gateway-address",
    reason=(
        "IOS-XE SD-Access mode IPv6 anycast grammar is not "
        "supported in v1 (rare in deployed Catalyst-9000 SD-"
        "Access configs and not exercised by any fixture).  "
        "Tracked for a follow-up commit once a real-capture "
        "fixture lands."
    ),
    severity="warn",
),
```

### `cisco_iosxe` (NETCONF — Phase 0.5 stub)

**Add to `unsupported=[...]`** (every anycast path):
```python
UnsupportedPath(
    path="/interfaces/interface/ipv4/address/virtual-gateway-address",
    reason="Phase 0.5 stub — anycast surface not implemented.",
),
UnsupportedPath(
    path="/interfaces/interface/ipv4/address/virtual-gateway-mac",
    reason="Phase 0.5 stub.",
),
UnsupportedPath(
    path="/interfaces/interface/ipv6/address/virtual-gateway-address",
    reason="Phase 0.5 stub.",
),
UnsupportedPath(
    path="/interfaces/interface/ipv6/address/virtual-gateway-mac",
    reason="Phase 0.5 stub.",
),
UnsupportedPath(
    path="/system/anycast-gateway-mac",
    reason="Phase 0.5 stub.",
),
```

### `aruba_aoss` (bidirectional)

AOS-S is campus-class — no native anycast grammar. Declare all
paths unsupported:

```python
UnsupportedPath(
    path="/interfaces/interface/ipv4/address/virtual-gateway-address",
    reason=(
        "AOS-S has no native anycast-gateway primitive.  "
        "Aruba's anycast / virtual-gateway grammar is on the "
        "AOS-CX platform (separate codec, Tier-D).  Operators "
        "needing L3 HA on AOS-S should use VRRP "
        "(``ip vrrp vrid N``)."
    ),
),
UnsupportedPath(
    path="/interfaces/interface/ipv4/address/virtual-gateway-mac",
    reason="See ``/virtual-gateway-address`` reason.",
),
UnsupportedPath(
    path="/interfaces/interface/ipv6/address/virtual-gateway-address",
    reason="See ``/virtual-gateway-address`` reason.",
),
UnsupportedPath(
    path="/interfaces/interface/ipv6/address/virtual-gateway-mac",
    reason="See ``/virtual-gateway-address`` reason.",
),
UnsupportedPath(
    path="/system/anycast-gateway-mac",
    reason=(
        "AOS-S is a campus codec; no system-wide anycast MAC "
        "declaration exists."
    ),
),
```

### `fortigate_cli` (bidirectional)

```python
UnsupportedPath(
    path="/interfaces/interface/ipv4/address/virtual-gateway-address",
    reason=(
        "FortiGate has no native anycast-gateway primitive "
        "(use ``config router vrrp`` for L3 HA — see the VRRP "
        "task in 01-vrrp-canonical)."
    ),
),
UnsupportedPath(
    path="/interfaces/interface/ipv4/address/virtual-gateway-mac",
    reason="See ``/virtual-gateway-address`` reason.",
),
UnsupportedPath(
    path="/interfaces/interface/ipv6/address/virtual-gateway-address",
    reason="See ``/virtual-gateway-address`` reason.",
),
UnsupportedPath(
    path="/interfaces/interface/ipv6/address/virtual-gateway-mac",
    reason="See ``/virtual-gateway-address`` reason.",
),
UnsupportedPath(
    path="/system/anycast-gateway-mac",
    reason=(
        "FortiGate is not a DC-fabric edge device; no system-"
        "wide anycast MAC declaration."
    ),
),
```

### `mikrotik_routeros` (bidirectional)

```python
UnsupportedPath(
    path="/interfaces/interface/ipv4/address/virtual-gateway-address",
    reason=(
        "RouterOS has no native anycast-gateway primitive "
        "(use ``/ip vrrp`` for L3 HA)."
    ),
),
# … same pattern for the other four paths
```

### `opnsense` (bidirectional)

```python
UnsupportedPath(
    path="/interfaces/interface/ipv4/address/virtual-gateway-address",
    reason=(
        "OPNsense uses CARP (Common Address Redundancy "
        "Protocol) for L3 HA — semantically distinct from "
        "anycast (CARP is master/backup with preempt; "
        "anycast is always-present on every leaf).  Operators "
        "wanting cross-platform HA should declare via "
        "``<carp>`` in config.xml and confirm intent manually."
    ),
),
# … same pattern for the other four paths
```

---

## Drafted CAPABILITIES.md edits

The operator-facing matrix at
[`docs/CAPABILITIES.md`](../../CAPABILITIES.md) needs three
inserts:

### Insert 1: Tier-1 listing (after the existing `tunnel_type` line, around line 61)

```markdown
* `interfaces` — `name`, `description`, `enabled`, IPv4 + IPv6
  addresses, `vrf` binding, `kind` (physical / mgmt / loopback /
  uplink), `mtu`, `lag_member_of`, `dhcp_client_v6` (IPv6 DHCPv6 /
  SLAAC mode discriminator), `tunnel_type` (GRE / EoIP / IPIP /
  IPSEC / VXLAN encap discriminator), **anycast-gateway** (per-IP
  `virtual_gateway_address` + per-IP/system MAC — see "Per-codec
  notes" below for the vendor-grammar table)
```

### Insert 2: Tier-2 listing — system-wide MAC is Tier-2

(The system-wide MAC field is Tier-2 because cross-vendor mapping
isn't lossless: Junos has no system field, EOS/NX-OS/IOS-XE
do. Insert after the existing `apply_groups` line at ~line 88.)

```markdown
* `anycast_gateway_mac` — system-wide virtual-router / anycast
  MAC.  Populated by EOS (`ip virtual-router mac-address`), NX-OS
  / IOS-XE SD-Access (`fabric forwarding anycast-gateway-mac`).
  Junos has no system-wide source — per-IRB-unit
  `virtual-gateway-v4-mac` / `virtual-gateway-v6-mac` populates
  `CanonicalIPv{4,6}Address.virtual_gateway_mac` instead.  Cross-
  vendor migration that crosses the system/per-IP boundary
  surfaces a review banner.
```

### Insert 3: per-codec capability-matrix tables

After each existing per-codec table in CAPABILITIES.md (one per
codec, sections starting at line 131 `#### cisco_iosxe_cli`),
add new rows. Drafted for `juniper_junos`:

```markdown
| `/interfaces/interface/ipv4/address/virtual-gateway-address` | Supported | Junos IRB anycast (``set interfaces irb unit N family inet address X virtual-gateway-address Y``). Both halves on one canonical record. |
| `/interfaces/interface/ipv4/address/virtual-gateway-mac` | Supported | Per-unit override (``set interfaces irb unit N virtual-gateway-v4-mac M``). Junos is the only vendor with native per-IP MAC grammar. |
| `/interfaces/interface/ipv6/address/virtual-gateway-address` | Supported | Mirror of v4. |
| `/interfaces/interface/ipv6/address/virtual-gateway-mac` | Supported | Mirror of v4. |
| `/system/anycast-gateway-mac` | Lossy | Junos has no system-wide MAC; cross-vendor sources duplicate the value onto every IRB unit at render time. Inverse direction picks the first observed per-unit MAC and emits review banners for differences. |
```

Drafted for `arista_eos`:

```markdown
| `/interfaces/interface/ipv4/address/virtual-gateway-address` | Supported | EOS VARP (``ip address virtual X/Y``).  Renders without a per-leaf primary; cross-vendor flow to Junos surfaces a review banner for the missing primary. |
| `/interfaces/interface/ipv4/address/is-secondary` | Supported | EOS VARP supports multiple virtual addresses per SVI; ``secondary`` trailer round-trips via canonical. |
| `/interfaces/interface/ipv4/address/virtual-gateway-mac` | Lossy | EOS only supports system-wide MAC. Per-IP overrides from Junos sources surface as review-required. |
| `/interfaces/interface/ipv6/address/virtual-gateway-address` | Supported | IPv6 VARP (EOS 4.30+). |
| `/interfaces/interface/ipv6/address/virtual-gateway-mac` | Lossy | See IPv4. |
| `/system/anycast-gateway-mac` | Supported | ``ip virtual-router mac-address`` — colon-hex format. |
```

Drafted for `cisco_iosxe_cli`:

```markdown
| `/interfaces/interface/ipv4/address/virtual-gateway-address` | Supported | SD-Access mode (``fabric forwarding mode anycast-gateway`` per SVI).  Source-side requires both the address line and the mode line on the same SVI; render produces both. |
| `/interfaces/interface/ipv6/address/virtual-gateway-address` | Lossy | IPv6 SD-Access mode parsing deferred to a follow-up commit (no fixture coverage). |
| `/system/anycast-gateway-mac` | Supported | ``fabric forwarding anycast-gateway-mac`` — emitted in dotted-triplet hex format. |
| `/interfaces/interface/ipv4/address/virtual-gateway-mac` | Lossy | IOS-XE only supports system-wide MAC. |
```

Drafted for `aruba_aoss` / `fortigate_cli` / `mikrotik_routeros` /
`opnsense` (identical pattern):

```markdown
| `/interfaces/interface/ipv{4,6}/address/virtual-gateway-address` | Unsupported | No native anycast-gateway primitive.  Cross-vendor sources carrying anycast trigger the validation banner. |
| `/interfaces/interface/ipv{4,6}/address/virtual-gateway-mac` | Unsupported | See above. |
| `/system/anycast-gateway-mac` | Unsupported | Not a DC-fabric edge device. |
```

Drafted for `cisco_iosxe` (NETCONF stub):

```markdown
| `/interfaces/interface/ipv{4,6}/address/virtual-gateway-address` | Unsupported | Phase 0.5 stub — anycast surface not implemented. |
| `/interfaces/interface/ipv{4,6}/address/virtual-gateway-mac` | Unsupported | Phase 0.5 stub. |
| `/system/anycast-gateway-mac` | Unsupported | Phase 0.5 stub. |
```

---

## Insert into "Translation tiers" section

In the existing
[`docs/CAPABILITIES.md`](../../CAPABILITIES.md) section "Tier 2 —
translatable with caveats" (line 67-90), the new bullet point
fits naturally after the `apply_groups` line (~line 88):

```markdown
* `anycast_gateway_mac` — system-wide virtual-router /
  anycast-gateway MAC.  Populated by EOS (system-wide), NX-OS /
  IOS-XE SD-Access (system-wide).  Junos has per-IRB-unit MAC
  overrides modelled on the address records (Tier-1) instead.
  Cross-vendor mapping between the per-IP and system-wide
  representations surfaces a review banner.
```

The per-IP `virtual_gateway_address` field is Tier-1 (every
supporting vendor has a stable round-trip path through the
canonical model); the system-wide MAC is Tier-2 because the
per-IP / system-wide split isn't uniformly representable across
all vendors.

---

## Implementation-order recommendation

Per `03-parse-render-touchpoints.md` § "Implementation order":

1. **Wave 1:** Schema + transforms + `anycast_mac.py` helper +
   schema-level tests. No codec edits yet; all six paths emit as
   `unsupported` on every codec via implicit-default classification.

2. **Wave 2:** Junos parse + render + Junos capability edits +
   Junos tests + QFX10K2 fixture round-trip.

3. **Wave 3:** EOS parse + render + system-MAC field + EOS
   capability edits + EOS tests + Batfish fixture round-trip.

4. **Wave 4:** IOS-XE CLI parse + render + IOS-XE capability
   edits + IOS-XE tests.

5. **Wave 5:** Unsupported-codec declarations (FortiGate /
   MikroTik / OPNsense / AOS-S / cisco_iosxe NETCONF) + cross-
   vendor migration tests + Tier-3 rename pane (if scoped in) +
   CAPABILITIES.md edits.

After each wave, run the cross-mesh harness
(`tools/run_full_mesh.py`) to confirm no other codec regressed.
The Junos round-trip on the QFX10K2 fixture is the single
strongest signal — if Wave 2 passes that, the schema and Junos
wiring are correct.
