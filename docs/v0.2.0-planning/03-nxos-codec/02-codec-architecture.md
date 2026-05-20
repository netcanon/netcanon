# 02 — Codec architecture

Concrete module layout, class shape, parse + render strategies, port-name
handling, `iter_xpaths`, and `probe` design for the NX-OS bidirectional
codec.

Mirrors the existing `cisco_iosxe_cli` post-split layout — this is the
closest grammar cousin in the tree, and aligning lets `_walk_canonical`
+ `_tier3_detection` + the shared transforms work unchanged.

---

## 1. Module layout

```
netcanon/migration/codecs/cisco_nxos/
├── __init__.py              # re-export the codec class
├── codec.py                 # CiscoNXOSCodec — metadata + delegators
├── parse.py                 # parse_intent() + per-stanza helpers
├── render.py                # render_intent() + per-stanza emit helpers
└── port_names.py            # classify_port_name / format_port_identity
```

Companion edits to non-codec files (declared here for the implementor):

| File | Edit |
|---|---|
| `netcanon/migration/codecs/__init__.py` | Add `from . import cisco_nxos` next to the existing codec imports. |
| `netcanon/migration/codecs/base.py` | Add `"cli-nxos"` to `INPUT_FORMATS`. |
| `netcanon/migration/_tier3_detection.py` | Add `detect_tier3_sections_nxos(raw: str)` helper mirroring the IOS-XE detector — see § 8 below. |
| `tests/unit/migration/test_real_captures.py` | Add `"nx_os": "cisco_nxos"` to `_DIR_TO_CODEC_NAME`. |
| `tests/fixtures/real/nx_os/` | New directory; populated by Phase 1+. |
| `definitions/vendors.yaml` | Add `cisco_nxos` vendor row (id, display_name `"Cisco NX-OS"`, device_classes `[switch, router]`). |
| `docs/CAPABILITIES.md` | Add NX-OS column to the cross-vendor capability matrix. |

---

## 2. Class shape (`codec.py`)

The pattern mirrors `CiscoIOSXECLICodec` 1-to-1.  Class signature in
pseudo-Python:

```python
@register
class CiscoNXOSCodec(CodecBase):
    """Bidirectional codec for Cisco NX-OS ``show running-config`` text.

    Targets the Nexus 3000 / 5000 / 7000 / 9000 series and the Nexus
    9000V virtual platform.  Distinct vendor identity from
    ``cisco_iosxe`` — different grammar surface, different
    ``CapabilityMatrix``, different render path.
    """

    name: ClassVar[str] = "cisco_nxos"
    version_hint: ClassVar[str | None] = "9.x / 10.x"
    input_format: ClassVar[str] = "cli-nxos"
    direction: ClassVar[str] = "bidirectional"
    certainty: ClassVar[str] = "experimental"  # → best_effort → certified
    canonical_model: ClassVar[str] = "openconfig-lite"

    description: ClassVar[str] = (
        "Paste the output of `show running-config` from a Cisco Nexus "
        "switch.  NX-OS is Cisco's data-center NOS; grammar is distinct "
        "from IOS-XE (use the `cisco_iosxe_cli` codec for Catalyst / "
        "ASR / ISR captures)."
    )

    sample_input: ClassVar[str] = (
        '!Command: show running-config\n'
        'version 9.2(3) Bios:version\n'
        'hostname Nexus-Leaf1\n'
        'vdc Nexus-Leaf1 id 1\n'
        '  limit-resource vlan minimum 16 maximum 4094\n'
        '\n'
        'feature interface-vlan\n'
        'feature lacp\n'
        '\n'
        'vlan 1,10\n'
        'vlan 10\n'
        '  name PROD\n'
        '\n'
        'vrf context management\n'
        '\n'
        'interface Vlan10\n'
        '  no shutdown\n'
        '  ip address 10.10.10.1/24\n'
        '\n'
        'interface Ethernet1/1\n'
        '  switchport access vlan 10\n'
        '\n'
        'interface mgmt0\n'
        '  vrf member management\n'
        '  ip address 192.0.2.10/24\n'
    )

    output_extension: ClassVar[str] = "cfg"

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="cisco_nxos",
        vendor_id="cisco_nxos",
        version_range="9.x+",
        device_classes=[DeviceClass.switch, DeviceClass.router],
        supported=[...],   # see 06-capabilities-matrix.md
        lossy=[...],
        unsupported=[...],
    )

    @property
    def capabilities(self) -> CapabilityMatrix:
        return self._CAPS

    def parse(self, raw: str) -> CanonicalIntent:
        from .._tier3_detection import detect_tier3_sections_nxos
        intent = parse_intent(raw)
        intent.dropped_tier3_sections = detect_tier3_sections_nxos(raw)
        return intent

    def render(self, tree: Any) -> str:
        return render_intent(tree)

    def iter_xpaths(self, tree: Any) -> Iterable[str]:
        if isinstance(tree, CanonicalIntent):
            from ..cisco_iosxe_cli.codec import _walk_canonical
            yield from _walk_canonical(tree)

    def classify_port_name(self, name: str):
        return _port_names.classify_port_name(name)

    def format_port_identity(self, identity) -> str | None:
        return _port_names.format_port_identity(identity)

    @classmethod
    def probe(cls, raw_prefix: str) -> tuple[int, str] | None:
        ...  # see § 7
```

Key class-level decisions:

* `iter_xpaths` reuses `_walk_canonical` from `cisco_iosxe_cli/codec.py`.
  This is precisely why that helper lives at module level rather than
  inside a parse/render module — cross-codec consumers like this one
  import it directly.  No duplication.
* `direction = "bidirectional"` from day one even though render path
  doesn't exist until Phase 4.  Earlier phases declare lots of
  `unsupported` paths in the capability matrix; once a path is
  declared, the pipeline silently skips it at render time.  Operators
  see the "X paths unsupported" banner.  This matches how Aruba
  AOS-S shipped (started best_effort, added paths incrementally).

* `unsupported_rename_categories` — Phase 1 likely declares
  `frozenset({"local_users"})` if Phase 1 doesn't ship the local-user
  parse / render path; clear that declaration as the surface lands.

---

## 3. Parse strategy (line-oriented, indentation-significant)

Same parser shape as `cisco_iosxe_cli/parse.py`:

1. **Top-level scan**: iterate lines once; dispatch on the leading
   token (no leading whitespace).  Top-level tokens of interest:
   `hostname`, `version`, `vdc`, `feature`, `username`,
   `ip` (`ip route` / `ip domain-lookup` / `ipv6 route`),
   `vlan`, `vrf`, `interface`, `router`, `evpn`, `snmp-server`,
   `boot`, `line`, `copp`, `rmon`, `hardware`, `mac`,
   `fabric` (anycast-gateway-mac), `nv` (overlay), `no`,
   `ssh`, `icam`.

2. **Per-block scan**: when a block-opening token fires
   (`interface`, `vrf context`, `vdc`, `evpn`, `router bgp`,
   `vlan N`), gather subsequent indented lines (2-space) until
   the next top-level line.  Hand the block to a per-stanza
   parser.

3. **Helper module functions** (mirrors iosxe_cli):
   * `_extract_hostname(raw)`
   * `_parse_globals(raw, intent)` — system services, mac aging, copp
   * `_parse_feature_block(raw, intent)` — collect feature lines
     into `intent.raw_sections["features"]` for round-trip
   * `_parse_vdc_block(raw, intent)` — preserve `vdc` block in
     `raw_sections["vdc"]`
   * `_parse_routing_instances(raw)` — `vrf context` blocks
   * `_parse_interfaces(raw, intent)` — all `interface` blocks
   * `_parse_vlans(raw)` — top-level `vlan` blocks + comma/range
   * `_parse_static_routes(raw, intent)` — top-level + per-VRF
   * `_parse_snmp(raw)` — `snmp-server user` lines
   * `_parse_local_users(raw)` — `username` lines
   * `_parse_lags(raw, intent)` — `port-channelN` blocks + members
   * `_parse_vxlan(raw)` — `interface nve1` + `evpn` block +
     `vlan / vn-segment` (Phase 4)
   * `_parse_hsrp_groups(raw, intent)` — `hsrp N` sub-blocks under
     SVIs (Phase 2; gates on T1)
   * `_synthesize_vlans_from_svis(intent)` — same pattern as
     iosxe_cli to avoid Bug 1 (silently-dropped SVI IPs)
   * `_parse_tier3_sections(raw, intent)` — bgp / ospf / eigrp / acl /
     route-map into `raw_sections`

4. **Order of operations** (matches iosxe_cli `parse_intent`):
   ```
   intent.hostname = _extract_hostname(raw)
   _parse_globals(raw, intent)
   intent.routing_instances = _parse_routing_instances(raw)
   intent.interfaces = _parse_interfaces(raw, intent)
   intent.vlans = _parse_vlans(raw)
   _synthesize_vlans_from_svis(intent)
   intent.static_routes = _parse_static_routes(raw, intent)
   intent.snmp = _parse_snmp(raw)
   intent.local_users = _parse_local_users(raw)
   intent.lags = _parse_lags(raw, intent)
   intent.vxlan_vnis = _parse_vxlan(raw)          # Phase 4
   _parse_tier3_sections(raw, intent)             # bgp/ospf/etc → raw_sections
   project_switchport_to_vlan(intent)             # shared transform
   ```

5. **Regex constants** (lifted in shape from iosxe_cli):
   ```python
   _IFACE_RE = re.compile(r"^interface\s+(\S+)", re.IGNORECASE)
   _IP_CIDR_RE = re.compile(
       r"^\s+ip\s+address\s+(\d+\.\d+\.\d+\.\d+)/(\d+)",
       re.IGNORECASE,
   )
   _IPV6_CIDR_RE = re.compile(
       r"^\s+ipv6\s+address\s+(\S+)/(\d+)",
       re.IGNORECASE,
   )
   _NO_SWITCHPORT_RE = re.compile(r"^\s+no\s+switchport\s*$", re.IGNORECASE)
   _SWITCHPORT_MODE_RE = re.compile(r"^\s+switchport\s+mode\s+(\S+)", re.IGNORECASE)
   _VRF_MEMBER_RE = re.compile(r"^\s+vrf\s+member\s+(\S+)\s*$", re.IGNORECASE)
   _VRF_CONTEXT_RE = re.compile(r"^vrf\s+context\s+(\S+)\s*$", re.IGNORECASE)
   _STATIC_ROUTE_RE = re.compile(
       r"^ip\s+route\s+(\S+)/(\d+)\s+(\S+)", re.IGNORECASE,
   )
   _HSRP_GROUP_RE = re.compile(r"^\s{2}hsrp\s+(\d+)\s*$", re.IGNORECASE)
   _HSRP_IP_RE = re.compile(r"^\s{4}ip\s+(\d+\.\d+\.\d+\.\d+)", re.IGNORECASE)
   _NVE_MEMBER_VNI_RE = re.compile(
       r"^\s+member\s+vni\s+(\d+)(\s+associate-vrf)?\s*$",
       re.IGNORECASE,
   )
   _VLAN_VN_SEGMENT_RE = re.compile(
       r"^\s+vn-segment\s+(\d+)\s*$", re.IGNORECASE,
   )
   _SNMP_USER_RE = re.compile(
       r"^snmp-server\s+user\s+(\S+)(?:\s+(\S+))?"
       r"\s+auth\s+(md5|sha|sha224|sha256|sha384|sha512)"
       r"\s+(\S+)"
       r"\s+priv\s+(\S+)\s+(\S+)"
       r"(?:\s+localized(V2)?key)?"
       r"(?:\s+engineID\s+(\S+))?",
       re.IGNORECASE,
   )
   _USERNAME_RE = re.compile(
       r"^username\s+(\S+)\s+password\s+(\d+)\s+(\S+)\s+role\s+(\S+)",
       re.IGNORECASE,
   )
   _VLAN_TOP_RE = re.compile(r"^vlan\s+([\d,\-]+)\s*$", re.IGNORECASE)
   _VLAN_NAME_RE = re.compile(r"^\s+name\s+(.+)", re.IGNORECASE)
   _CHANNEL_GROUP_RE = re.compile(
       r"^\s+channel-group\s+(\d+)\s+mode\s+(\S+)", re.IGNORECASE,
   )
   _FABRIC_ANYCAST_MAC_RE = re.compile(
       r"^fabric\s+forwarding\s+anycast-gateway-mac\s+(\S+)",
       re.IGNORECASE | re.MULTILINE,
   )
   ```

   Several IOS-XE regex constants are reused unchanged
   (`_HOSTNAME_RE`, `_SWITCHPORT_ACCESS_RE`,
   `_SWITCHPORT_TRUNK_ALLOWED_RE`, `_SWITCHPORT_TRUNK_NATIVE_RE`,
   `_CHANNEL_GROUP_RE`, `_DESC_RE`, `_SHUTDOWN_RE`, `_NO_SHUTDOWN_RE`,
   `_MTU_RE`).

6. **The L2-default flip**: critical NX-OS-specific logic — in
   `_parse_interfaces`, when encountering `interface Ethernet1/N`,
   default `iface.switchport_mode = "access"` UNLESS the block
   contains `no switchport`.  Mirrors the device's commit semantics.
   IOS-XE's parser does the opposite (default routed; declare
   switchport mode explicitly).

---

## 4. Render strategy (canonical → NX-OS text)

The render path emits in a specific order so dependent features land
after their gating `feature` lines.  Pseudocode:

```python
def render_intent(tree: CanonicalIntent) -> str:
    lines: list[str] = []

    # ── Banner ──
    lines.append("!Command: show running-config")
    lines.append("")
    lines.append(f"version 9.2(3) Bios:version")    # synthesised
    lines.append(f"hostname {tree.hostname}")
    lines.append(f"vdc {tree.hostname} id 1")
    lines.extend(_default_vdc_limit_resources())   # synthesised; or use raw_sections["vdc"]
    lines.append("")

    # ── Feature block (render-derived from canonical tree) ──
    features = _derive_features(tree)              # see § 5
    for f in features:
        lines.append(f"feature {f}")
    lines.append("")

    # ── User accounts ──
    for u in tree.local_users:
        lines.append(_render_local_user(u))
    if tree.local_users:
        lines.append("ip domain-lookup")           # default to on
        lines.append("copp profile strict")
        lines.append("")

    # ── SNMP ──
    if tree.snmp:
        lines.extend(_render_snmp(tree.snmp))

    # ── Fabric anycast (T2; Phase 4) ──
    if anycast := _find_anycast(tree):
        lines.append(
            f"fabric forwarding anycast-gateway-mac {anycast.mac}"
        )

    # ── Static routes (top-level, default VRF) ──
    for sr in tree.static_routes:
        if not sr.vrf:                             # new field; see § 9
            lines.append(_render_static_route(sr))

    # ── VLANs (coalesced) ──
    if tree.vlans:
        lines.append(f"vlan {_coalesce_vlan_ids(tree.vlans)}")
        for v in tree.vlans:
            if v.name or _has_vn_segment(v, tree.vxlan_vnis):
                lines.append(f"vlan {v.id}")
                if v.name:
                    lines.append(f"  name {v.name}")
                if vni := _vni_for_vlan(v.id, tree.vxlan_vnis):
                    lines.append(f"  vn-segment {vni}")
        lines.append("")

    # ── VRF contexts (with per-VRF static routes embedded) ──
    for ri in tree.routing_instances:
        lines.extend(_render_vrf_context(ri, tree.static_routes))

    # ── Interfaces (in canonical sort order) ──
    for iface in _sort_interfaces_nxos(tree.interfaces):
        lines.extend(_render_interface(iface, tree))

    # ── nve1 (Phase 4) ──
    if tree.vxlan_vnis:
        lines.extend(_render_nve1(tree))

    # ── line / boot footers ──
    lines.append("line console")
    lines.append("line vty")
    if boot := tree.raw_sections.get("boot"):
        lines.append(boot)
    else:
        lines.append("boot nxos bootflash:/nxos.9.2.3.bin")

    # ── router bgp / evpn footers ──
    if tree.vxlan_vnis:
        lines.extend(_render_evpn_block(tree))

    if (bgp := tree.raw_sections.get("router bgp")):
        lines.append(bgp)

    return "\n".join(lines) + "\n"
```

### 4.1 Interface sort order

NX-OS captures emit interfaces in a stable order:
1. `Vlan1`, then numerically ascending `Vlan<N>`
2. `nve1` (if present)
3. `Ethernet1/1` ... `Ethernet1/<MAX>` (full chassis)
4. `port-channel<N>` (ascending)
5. `mgmt0`
6. `loopback0` ... `loopback<N>`

Renderer mirrors this order so round-tripped output is byte-identical
to the source for the common case.  `_sort_interfaces_nxos` keys off
`port_names.classify_port_name(iface.name).kind` + the numeric index.

### 4.2 Empty-interface emission

If `tree.source_vendor == "cisco_nxos"` AND the source's empty-port
list was preserved (via a new optional
`raw_sections["empty_interfaces"]` capturing the list of bare port
names), re-emit those bare lines.  Cross-vendor sources don't have
the concept — render only the populated `tree.interfaces`.

---

## 5. Feature-derivation logic

`_derive_features(tree)` walks the canonical tree once and returns
the sorted list of `feature` strings to emit:

```python
def _derive_features(tree: CanonicalIntent) -> list[str]:
    features: set[str] = set()

    # SVIs → interface-vlan
    if any(_is_svi(i) for i in tree.interfaces):
        features.add("interface-vlan")

    # LAGs → lacp
    if tree.lags:
        features.add("lacp")

    # HSRP groups (T1) → hsrp
    if _has_hsrp(tree):
        features.add("hsrp")

    # VXLAN → nv overlay + vn-segment-vlan-based
    if tree.vxlan_vnis:
        features.add("nv overlay")
        features.add("vn-segment-vlan-based")

    # Anycast (T2) → fabric forwarding
    if _has_anycast(tree):
        features.add("fabric forwarding")

    # Tier-3 routing protocols → feature bgp/ospf/eigrp
    if "router bgp" in tree.raw_sections:
        features.add("bgp")
    if "router ospf" in tree.raw_sections:
        features.add("ospf")
    if "router eigrp" in tree.raw_sections:
        features.add("eigrp")

    # SNMPv3 → no feature gate (always on)
    # LLDP is on by default; not emitted

    return sorted(features)
```

Output order matters (NX-OS commit semantics) — `feature` lines
before any dependent stanza.  The `_derive_features` result lands
at line ~20 of the rendered config, before the user / SNMP / VLAN /
VRF / interface blocks.

`nv overlay evpn` is a separate **top-level** line (not a `feature`),
emitted just before the first VXLAN-aware stanza (typically right
after the feature block).

---

## 6. Render order summary

```
!Command: show running-config
version
hostname
vdc + limit-resource block
(blank)
nv overlay evpn                 ← only if vxlan present
feature <X>                     ← one per derived feature, sorted
feature <Y>
...
(blank)
no password strength-check      ← if hint preserved
username ...                    ← local users
ip domain-lookup                ← default on
copp profile strict             ← preserved from raw_sections
snmp-server user ...
rmon event ...                  ← preserved from raw_sections
fabric forwarding anycast-gateway-mac ...   ← T2
ip route ... (default VRF)
ipv6 route ...
vlan <coalesced list>
vlan <N> / name X / vn-segment Y
vrf context <X> blocks
(blank)
hardware access-list tcam ...   ← preserved from raw_sections
(blank)
interface Vlan<N> blocks
interface nve1 block            ← Phase 4
interface Ethernet1/N blocks
interface port-channel<N> blocks
interface mgmt0
interface loopback<N> blocks
line console
line vty
boot nxos bootflash:...
router bgp <asn>                ← Tier-3 raw
evpn / vni <N> l2 / ... blocks  ← Phase 4
```

---

## 7. Probe ladder (`@classmethod probe(...)`)

NX-OS has a strong primary marker; the ladder is shallower than
IOS-XE's.

```python
@classmethod
def probe(cls, raw_prefix: str) -> tuple[int, str] | None:
    lowered = raw_prefix.lower()

    # Shape sanity — reject XML / JSON (mirrors iosxe_cli)
    if detect_input_shape(raw_prefix) is not None:
        return None

    # PRIMARY marker — `!Command: show running-config` appears as
    # the FIRST line of every NX-OS show running-config in modern
    # OS versions.  Unambiguous; no other vendor in our matrix
    # emits this string.  IOS-XE classic emits
    # `Building configuration...` / `Current configuration:`; the
    # presence of any of those markers is a STRONG signal this is
    # NOT NX-OS even if `!Command:` appears later in a paste of
    # multiple captures.
    if "building configuration" in lowered:
        return None
    if "current configuration :" in lowered:
        return None

    if "!command: show running-config" in lowered:
        # Belt-and-braces: check for at least one NX-OS-shape
        # structural marker (catches cases where !Command: appears
        # in a non-NX-OS comment paste).
        nxos_hits = 0
        if re.search(r"^feature\s+\S+", raw_prefix, re.MULTILINE):
            nxos_hits += 1
        if re.search(r"^vdc\s+\S+\s+id\s+\d+", raw_prefix, re.MULTILINE):
            nxos_hits += 1
        if re.search(
            r"^interface\s+(Ethernet\d+/\d+|nve1|mgmt0|port-channel\d+)",
            raw_prefix, re.MULTILINE,
        ):
            nxos_hits += 1
        if re.search(
            r"^\s+ip\s+address\s+\d+\.\d+\.\d+\.\d+/\d+",
            raw_prefix, re.MULTILINE,
        ):
            nxos_hits += 1
        if nxos_hits >= 1:
            return (98, "NX-OS !Command banner + structural markers")
        return (90, "NX-OS !Command banner")

    # SECONDARY markers — no banner but structural cues
    secondary = 0
    if re.search(r"^feature\s+(bgp|interface-vlan|hsrp|lacp|nv overlay)",
                 raw_prefix, re.MULTILINE | re.IGNORECASE):
        secondary += 2  # `feature X` is NX-OS specific
    if re.search(r"^vdc\s+\S+\s+id\s+\d+", raw_prefix, re.MULTILINE):
        secondary += 2
    if re.search(r"^vrf\s+context\s+\S+", raw_prefix, re.MULTILINE):
        secondary += 1
    if re.search(r"^interface\s+nve1\b", raw_prefix, re.MULTILINE):
        secondary += 2
    if re.search(r"^interface\s+Ethernet1/\d+", raw_prefix, re.MULTILINE):
        secondary += 1
    if re.search(r"^\s+vrf\s+member\s+\S+", raw_prefix, re.MULTILINE):
        secondary += 1
    if re.search(
        r"^\s+ip\s+address\s+\d+\.\d+\.\d+\.\d+/\d+",
        raw_prefix, re.MULTILINE,
    ) and not re.search(
        r"^\s+ip\s+address\s+\d+\.\d+\.\d+\.\d+\s+\d+\.\d+\.\d+\.\d+",
        raw_prefix, re.MULTILINE,
    ):
        # CIDR form without any dotted-mask form is a Nexus signal
        secondary += 1

    if secondary >= 5:
        return (95, f"NX-OS structural signals ({secondary})")
    if secondary >= 3:
        return (85, f"NX-OS structural signals ({secondary})")
    if secondary >= 1:
        return (60, "one or two NX-OS structural signals")

    return None
```

**Scoring rationale**:
* `!Command: show running-config` + structural marker = **98**.
  Highest-confidence detection across all codecs.
* Banner alone = **90** (still high — banner is unambiguous).
* No banner but `feature X` + `vdc X id N` + `interface nve1` = **95**.
* Weak structural signals only = **60**.

**Probe ordering note**: the codec registry orders probe calls by
codec name; cisco_iosxe / cisco_iosxe_cli must NOT accidentally
claim NX-OS input.  Both IOS-XE probes return `None` on
`Building configuration...` absent — that's already the existing
behaviour.  The NX-OS probe at 98 wins decisively against any
weaker IOS-XE result.

---

## 8. `_tier3_detection.detect_tier3_sections_nxos`

New function in `netcanon/migration/_tier3_detection.py`, mirroring
the existing `detect_tier3_sections_iosxe_cli`:

```python
_NXOS_TIER3_HEADERS: tuple[tuple[str, str], ...] = (
    (r"^router\s+bgp\s+\d+", "router bgp"),
    (r"^router\s+ospf\s+\d+", "router ospf"),
    (r"^router\s+eigrp\s+\d+", "router eigrp"),
    (r"^router\s+isis\b", "router isis"),
    (r"^ip\s+access-list\s+\S+", "ip access-list"),
    (r"^ipv6\s+access-list\s+\S+", "ipv6 access-list"),
    (r"^mac\s+access-list\s+\S+", "mac access-list"),
    (r"^route-map\s+\S+", "route-map"),
    (r"^class-map\s+", "class-map"),
    (r"^policy-map\s+", "policy-map"),
    (r"^crypto\s+", "crypto"),
    (r"^aaa\s+", "aaa"),
    (r"^monitor\s+session\s+\d+", "monitor session"),
    (r"^feature\s+pim", "feature pim"),
    (r"^ip\s+pim\s+", "ip pim"),
)


def detect_tier3_sections_nxos(raw: str) -> list[str]:
    """Return de-duplicated Tier-3 stanza headers detected in *raw*.

    See ``detect_tier3_sections_iosxe_cli`` for the contract.
    """
    seen: set[str] = set()
    for line in raw.splitlines():
        for pattern, header in _NXOS_TIER3_HEADERS:
            if re.match(pattern, line, re.IGNORECASE):
                seen.add(header)
                break
    return sorted(seen)
```

---

## 9. `CanonicalStaticRoute.vrf` extension (proposed)

NX-OS embeds per-VRF static routes inside the `vrf context` block:

```
vrf context management
  ip route 0.0.0.0/0 10.0.0.2
```

To round-trip, `CanonicalStaticRoute` needs a `vrf: str = ""` field:

```python
class CanonicalStaticRoute(BaseModel):
    destination: str
    gateway: str = ""
    interface: str = ""
    metric: int = 0
    description: str = ""
    vrf: str = ""                       # NEW — empty = default/global VRF
```

The IOS-XE codec's existing lossy declaration
(`/routing-instances/instance` matrix row in
`cisco_iosxe_cli/codec.py` says VRF per-static-route round-trip
fidelity is the open gap) — this extension closes the gap on both
IOS-XE and NX-OS in one move.  Phase 3 PR ships the schema change
alongside the NX-OS parser support.

Same logic applies to `CanonicalStaticRoute.metric` for the NX-OS
metric form: NX-OS uses `ip route DEST/N GW [<metric>]` (single
integer at the end).  Already in the schema.

---

## 10. Port-names (`port_names.py`)

### 10.1 `classify_port_name(name)`

NX-OS port forms (all case-insensitive, but NX-OS emits them in
exact case shown):

| Form | `PortIdentity` |
|---|---|
| `Ethernet1/24` | `physical`, module=1, port=24, `name_speed_hint=""` |
| `Ethernet1/1/1` | `breakout`, stack=1, module=1, port=1, lane=... (rare; mostly 4x10G on QSFP) |
| `Ethernet101/1/1` | `physical`, stack=101, module=1, port=1 (N7K linecard slot) |
| `port-channel1` | `lag`, index=1 |
| `Vlan10` | `svi`, index=10 |
| `loopback0` | `loopback`, index=0 |
| `nve1` | new `kind="vtep"` OR `kind="virtual"` — see § 10.3 |
| `mgmt0` | `mgmt`, port=0 |

NX-OS notably uses **only one prefix** for all Ethernet speeds
(`Ethernet`) regardless of 1G/10G/40G/100G.  This means the
`name_speed_hint` field is always empty on classify and always
ignored on format — `format_port_identity` always emits `Ethernet<a>/<b>`.

Cross-vendor implication: when translating Cisco IOS-XE
`GigabitEthernet1/0/24` → NX-OS, the speed hint `"gig"` is
discarded (NX-OS doesn't encode speed in the name).  Reverse
direction NX-OS → IOS-XE: the IOS-XE formatter falls back to
`GigabitEthernet` (its default speed prefix when hint is empty),
which is wrong for 10G/40G ports.  **Mitigation**: the cross-vendor
orchestrator (`netcanon.migration.canonical.port_names`) should
look at the source `iface.mtu` or `iface.interface_type` for a
speed hint when the identity is bare.  This is a follow-up gap
to surface to maintainers; the NX-OS codec itself is correct
in dropping the hint on the NX-OS side.

### 10.2 Regex patterns

```python
_PHYSICAL_RE = re.compile(
    r"^Ethernet"
    r"(?P<a>\d+)/(?P<b>\d+)(?:/(?P<c>\d+))?$",
    re.IGNORECASE,
)

_LOGICAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"^port-channel(\d+)$", "lag"),
    (r"^Vlan(\d+)$", "svi"),
    (r"^loopback(\d+)$", "loopback"),
    (r"^mgmt(\d+)$", "mgmt"),
    (r"^nve(\d+)$", "vtep"),    # new kind, see § 10.3
)
```

### 10.3 New `PortIdentity.kind = "vtep"`?

NX-OS's `nve1` is functionally distinct from a loopback or a
physical port — it's the VXLAN tunnel endpoint, a virtual
construct.  Two options:

* **Add `"vtep"` to `PortKind` enum** in
  `netcanon/migration/canonical/port_names.py`.  Pro: precise
  cross-vendor model.  Con: only NX-OS has a distinct kind; Arista
  EOS embeds VTEP semantics in a `Vxlan1` interface (which
  classifies as `unknown` today); Junos has no distinct interface.
* **Fold `nve1` into `kind="virtual"` or `kind="unknown"`**.  Pro:
  no schema change.  Con: cross-vendor port-name translation
  loses the semantic.

Recommendation: **add `"vtep"`** as part of Phase 4 (when the codec
needs it).  Cross-vendor formatters return `None` for the kind
(no native representation), same fall-through as `hw_aggregate`.

### 10.4 `format_port_identity(identity)`

```python
def format_port_identity(identity: PortIdentity) -> str | None:
    if identity.kind == "physical":
        if identity.stack is not None:
            return f"Ethernet{identity.stack}/{identity.module or 0}/{identity.port or 0}"
        return f"Ethernet{identity.module or 0}/{identity.port or 0}"
    if identity.kind == "breakout":
        return f"Ethernet{identity.stack or 1}/{identity.module or 0}/{identity.port or 0}/{identity.breakout_lane or 1}"
    if identity.kind == "lag":
        return f"port-channel{identity.index or 1}"
    if identity.kind == "svi":
        return f"Vlan{identity.index or 1}"
    if identity.kind == "loopback":
        return f"loopback{identity.index or 0}"
    if identity.kind == "mgmt":
        # NX-OS has exactly one mgmt port, always mgmt0
        return "mgmt0"
    if identity.kind == "vtep":
        return "nve1"
    if identity.kind == "virtual":
        return f"loopback{identity.index or 0}"   # closest analogue
    return None
```

`mgmt` returns the constant `"mgmt0"` regardless of `port`
(NX-OS has exactly one mgmt port).  Cross-vendor inbound from
Aruba `oobm` / Junos `fxp0` / IOS-XE `Mgmt-vrf Gi0/0` all collapse
to `mgmt0` correctly.

`vtep` always returns the constant `"nve1"` (NX-OS has exactly
one VTEP).

---

## 11. `iter_xpaths` (delegates to `_walk_canonical`)

The codec class's `iter_xpaths` is a 3-line delegator to the
existing `_walk_canonical` helper at the top of
`cisco_iosxe_cli/codec.py`.  This helper yields the same xpath
strings every cross-vendor consumer's `CapabilityMatrix.supported`
declares.  No new xpaths introduced by NX-OS in v1.

Phase 4 adds:
* `/vxlan-vnis/vni`
* `/vxlan-vnis/source-interface`
* `/vxlan-vnis/udp-port`
* `/vxlan-vnis/mcast-group`

These already exist in `_walk_canonical` (Arista EOS uses them) —
just need to be added to the NX-OS `supported` list when Phase 4
ships.

Phase 3 (with the `CanonicalStaticRoute.vrf` extension from § 9)
adds `/routing/static-route/vrf` to `_walk_canonical` — that's a
6-line patch to the helper.

---

## 12. Round-trip invariant

`parse(render(tree)) == tree` must hold for the supported subset.
Notable invariant points where care is needed:

1. **VLAN coalescing** — `vlan 1,10,2000` → 3 records → `vlan 1,10,2000` on
   render.  Order must be ascending; gaps must collapse (no
   `vlan 10-12` if only 10 and 12 are present).
2. **`no switchport` round-trip** — a routed `Ethernet1/N` parses
   with `switchport_mode=None`; render must emit `no switchport`
   when `switchport_mode is None and iface.ipv4_addresses` (a
   routed port has the explicit declaration).  Bare interfaces
   with no IP / no switchport state stay bare.
3. **`feature` lines round-trip** — parsed feature lines stored
   in `raw_sections["features"]` are NOT used by render; render
   re-derives them.  If the source declared extra `feature`
   lines (e.g. `feature scp-server`) that the canonical tree
   can't motivate, those are lost.  Declare lossy in matrix:
   `/system/raw-sections/features`.
4. **`engineID` round-trip** — preserved verbatim on
   `CanonicalSNMPv3User.engine_id`.  Mind that NX-OS uses
   colon-decimal (`128:0:0:9:3:12:...`); the cross-vendor IOS-XE
   render expects hex.  Convert at format boundary OR declare lossy.
5. **`copp profile strict`, `rmon event ...`, `hardware
   access-list tcam ...`** — all preserved verbatim in
   `raw_sections`.  Cross-vendor sources do not populate these;
   the render path emits a NX-OS default block when they're
   absent (so a render of an IOS-XE source produces a
   syntactically-valid NX-OS config).

The implementor should write a parametrised round-trip test:
```python
@pytest.mark.parametrize("fixture", FIXTURES_DIR.glob("*.txt"))
def test_round_trip(fixture):
    raw = fixture.read_text()
    codec = CiscoNXOSCodec()
    tree1 = codec.parse(raw)
    rendered = codec.render(tree1)
    tree2 = codec.parse(rendered)
    assert tree1 == tree2
```

…and only mark fixtures `_KNOWN_ROUNDTRIP_GAPS` when the gap is
explicitly declared lossy in the capability matrix.

---

## 13. Implementation order recap

1. Phase 1 PR — `codec.py` (full class shell), `parse.py`
   (hostname / vlans / vrf-context skeleton / basic interfaces),
   `render.py` (skeleton + minimal output), `port_names.py` (full
   classify/format).  All ~400-500 LOC + 250 LOC tests.
2. Phase 2 PR — flesh out `parse.py` (switchport / LAG / HSRP /
   SNMPv3 / local-users), `render.py` (matching paths).  Gates on
   T1 landing for the HSRP slice.
3. Phase 3 PR — VRF + per-VRF static route + Tier-3 raw-sections.
   Includes the `CanonicalStaticRoute.vrf` schema extension.
4. Phase 4 PR — VXLAN-EVPN block parsing + render + the new
   `PortIdentity.kind = "vtep"`.  Gates on T2 for anycast.

Each PR ships its phase's full capability-matrix declaration so the
validation report reflects current scope.

---

## 14. Where the codec does NOT mirror IOS-XE

For implementor reference — places where the lift-and-shift from
`cisco_iosxe_cli` will NOT work and the codec must diverge:

* **IP address regex**: NX-OS has only CIDR; IOS-XE has both.
  Don't try to share the regex.
* **VRF stanza keyword**: `vrf context` vs `vrf definition`.
  Same shape, different keyword — distinct helper.
* **VRF interface bind**: `vrf member` vs `vrf forwarding`.
* **HSRP grammar**: `hsrp N` vs `standby N`.  Indented sub-block
  shape is identical (`preempt` / `ip X` / `priority N`).
* **Switchport default**: parser must default
  `switchport_mode="access"` on bare `Ethernet1/N`; renderer must
  emit `no switchport` for routed ports.  Opposite of IOS-XE.
* **VLAN comma/range form**: NX-OS has it; IOS-XE doesn't.
  Borrow Arista EOS's coalescer.
* **VXLAN VTEP**: `interface nve1` (always nve1) vs IOS-XE's
  `interface nve<N>` (catalyst 9k SDA).  Different shape inside.
* **Tier-3 banner**: distinct
  `_NXOS_TIER3_HEADERS` constant in `_tier3_detection.py`.

All other parsing logic IS shareable — switchport-access /
trunk-allowed / trunk-native / channel-group / mtu / description /
shutdown / no-shutdown / loopback / port-channel container.
