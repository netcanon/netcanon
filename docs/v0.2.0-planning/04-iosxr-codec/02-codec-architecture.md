# 02 — Codec architecture

> Module layout, class shape, parse + render strategies for the
> proposed `cisco_iosxr` bidirectional codec.  Follows the post-split
> convention established by `cisco_iosxe_cli/` and `juniper_junos/`
> (see `netcanon/migration/codecs/README.md`).

## File layout

```
netcanon/migration/codecs/cisco_iosxr/
├── __init__.py        # 28 lines — CiscoIOSXRCodec re-export only
├── codec.py           # ~450 lines — class metadata + capabilities +
│                      #              probe + iter_xpaths + port-name
│                      #              delegates + _walk_canonical
│                      #              cross-codec import alias
├── parse.py           # ~800 lines — parse_intent(raw) entry +
│                      #              line-walker + per-stanza
│                      #              dispatchers + helpers
├── render.py          # ~600 lines — render_intent(tree) entry +
│                      #              per-section emitters + helpers
└── port_names.py      # ~250 lines — classify_port_name +
                       #              format_port_identity + module-
                       #              level regex + speed maps
```

Total ~2,100 production lines including blanks + docstrings.  Tests
add a comparable amount under `tests/unit/migration/`.

The codec module gets a wire-up entry in
`netcanon/migration/codecs/__init__.py` (side-effect import for the
registry) — same pattern as the other codecs.

---

## Class shape

```python
@register
class CiscoIOSXRCodec(CodecBase):
    """Bidirectional codec for Cisco IOS-XR `show running-config`."""

    name: ClassVar[str] = "cisco_iosxr"
    version_hint: ClassVar[str | None] = "6.x / 7.x"   # tested on 6.2.2, 6.6.2
    input_format: ClassVar[str] = "cli-iosxr"          # NEW — add to INPUT_FORMATS
    direction: ClassVar[str] = "bidirectional"         # bumped from parse_only after Phase 2
    certainty: ClassVar[str] = "experimental"          # bumped to certified after Phase 4
    canonical_model: ClassVar[str] = "openconfig-lite"
    description: ClassVar[str] = (
        "Paste the output of `show running-config` from a Cisco "
        "IOS-XR device (ASR 9000 / NCS 5500 / 8000 / NCS 540 series). "
        "XR uses 4-segment port names (GigabitEthernet0/0/0/0), "
        "`vrf` as a top-level stanza, and `route-policy` instead of "
        "`route-map` — these are surfaced as separate canonical "
        "fields where modeled and via the Tier-3 notification banner "
        "where not."
    )
    sample_input: ClassVar[str] = (
        "!! IOS XR Configuration 6.6.2\n"
        "!\n"
        "hostname Router\n"
        "domain name example.com\n"
        "!\n"
        "vrf customer-a\n"
        " address-family ipv4 unicast\n"
        "  import route-target\n"
        "   65001:100\n"
        "  !\n"
        "  export route-target\n"
        "   65001:100\n"
        "  !\n"
        " !\n"
        "!\n"
        "interface Loopback0\n"
        " ipv4 address 10.255.0.1 255.255.255.255\n"
        "!\n"
        "interface GigabitEthernet0/0/0/0\n"
        " description WAN uplink\n"
        " ipv4 address 198.51.100.1 255.255.255.252\n"
        "!\n"
        "interface MgmtEth0/RP0/CPU0/0\n"
        " vrf customer-a\n"
        " ipv4 address 192.168.1.1 255.255.255.0\n"
        "!\n"
        "end\n"
    )
    output_extension: ClassVar[str] = "cfg"

    _CAPS: ClassVar[CapabilityMatrix] = (
        # See 06-capabilities-matrix.md for the full declaration.
        ...
    )

    @property
    def capabilities(self) -> CapabilityMatrix:
        return self._CAPS

    def parse(self, raw: str) -> CanonicalIntent:
        from ..._tier3_detection import detect_tier3_sections_iosxr
        intent = parse_intent(raw)
        intent.dropped_tier3_sections = detect_tier3_sections_iosxr(raw)
        return intent

    def render(self, tree: Any) -> str:
        return render_intent(tree)

    def iter_xpaths(self, tree: Any) -> Iterable[str]:
        # Reuses the shared cross-codec _walk_canonical from
        # cisco_iosxe_cli — same canonical surface, identical xpaths.
        if isinstance(tree, CanonicalIntent):
            from ..cisco_iosxe_cli.codec import _walk_canonical
            yield from _walk_canonical(tree)

    def classify_port_name(self, name: str):
        return _port_names.classify_port_name(name)

    def format_port_identity(self, identity) -> str | None:
        return _port_names.format_port_identity(identity)

    @classmethod
    def probe(cls, raw_prefix: str) -> tuple[int, str] | None:
        ...
```

The `_CAPS` value is detailed in `06-capabilities-matrix.md`.
`parse()` and `render()` delegate to sibling modules following the
established post-split pattern.

---

## Parse strategy

### Indentation-based hierarchy with `!` separators

Same fundamental approach as `cisco_iosxe_cli/parse.py` — line scan
with regex-based per-section dispatch — but with deeper indent
nesting.  Where IOS-XE typically has 1-2 indent levels, XR routinely
has 3-4:

```
vrf red                       ← depth 0 (top-level)
 address-family ipv4 unicast  ← depth 1
  import route-target         ← depth 2
   65102:2                    ← depth 3 (leaf list element)
   65102:4
  !                           ← unwind to depth 1
  export route-target
   ...
  !
 !                            ← unwind to depth 0
!
```

**Walker outline:**

```python
def parse_intent(raw: str) -> CanonicalIntent:
    # 1. Shape sanity — reject XML / JSON early via shared helper.
    # 2. Strip banner lines:
    #    `!! IOS XR Configuration 6.6.2`
    #    `!! Last configuration change at ...`
    #    `Building configuration...`
    #    `end`
    #    These provide the probe signal but carry no canonical state.
    # 3. Top-level dispatch — for each top-level stanza:
    #       - hostname <name>          → intent.hostname
    #       - domain name <fqdn>       → intent.domain
    #       - username <name> {block}  → CanonicalLocalUser
    #       - vrf <name> {block}       → CanonicalRoutingInstance
    #       - interface <name> {block} → CanonicalInterface
    #       - router static {block}    → CanonicalStaticRoute list
    #       - ssh server v2            → metadata (ignored in v1)
    #       - line default {block}     → Tier-3 ignore
    #       - call-home {block}        → Tier-3 ignore
    #       - route-policy ... end-policy → Tier-3 ignore + notification
    #       - prefix-set ... end-set       → Tier-3 ignore + notification
    #       - router bgp {block}       → Tier-3 (Phase 3: harvest VRF RD)
    #       - router ospf {block}      → Tier-3 ignore
    #       - mpls ldp {block}         → Tier-3 ignore
    # 4. Post-pass:
    #    - Synthesise CanonicalVlan from `.subif`+`encapsulation dot1q`
    #    - Promote interfaces bound to a mgmt-VRF to kind="mgmt"
    #    - Project switchport state to VLAN-centric lists (no-op for
    #      XR since XR doesn't have classic switchports — but kept
    #      for canonical-tree shape consistency)
    return intent
```

### Stanza-block scanning

Each top-level stanza is scanned as a contiguous block:

```python
def _scan_block(lines: list[str], i: int) -> tuple[list[str], int]:
    """Return (block_lines, next_i) for the stanza starting at lines[i].

    Walks until indentation returns to the start indent and emits
    `!`, OR until end-of-file.  Nested `!` lines INSIDE the block
    are preserved verbatim — they are sub-stanza terminators
    consumed by inner-loop scanners.
    """
    start_indent = _indent_of(lines[i])
    block: list[str] = [lines[i]]
    j = i + 1
    while j < len(lines):
        line = lines[j]
        if _is_blank(line) or _is_comment(line):
            j += 1
            continue
        ind = _indent_of(line)
        # `!` at the start indent closes the stanza.
        if line.lstrip() == "!" and ind == start_indent:
            j += 1
            break
        # Lines at a SHALLOWER indent also close the stanza
        # (defensive — guards against missing `!` lines in the wild).
        if ind <= start_indent and not line.lstrip().startswith("!"):
            break
        block.append(line)
        j += 1
    return block, j
```

### Route-policy / prefix-set DSL handling

These are Tier-3 in v1 — parse-and-skip with banner notification.
Recognition uses dedicated terminators (`end-policy`, `end-set`) not
the universal `!`:

```python
_ROUTE_POLICY_RE = re.compile(r"^route-policy\s+(\S+)\s*$", re.IGNORECASE)
_END_POLICY_RE   = re.compile(r"^end-policy\s*$",            re.IGNORECASE)
_PREFIX_SET_RE   = re.compile(r"^prefix-set\s+(\S+)\s*$",    re.IGNORECASE)
_COMMUNITY_SET_RE = re.compile(r"^community-set\s+(\S+)\s*$", re.IGNORECASE)
_END_SET_RE      = re.compile(r"^end-set\s*$",                re.IGNORECASE)

# Skip the whole block; surface a header in dropped_tier3_sections.
```

### VRF stanza parse

XR's VRF stanza places RT imports/exports in a sub-block, not
per-line directives:

```
vrf red
 address-family ipv4 unicast
  import route-target
   65102:2
   65102:4
  !
  export route-target
   65102:2
   65102:4
  !
 !
!
```

Parse pseudo-code:

```python
def _parse_vrf_stanza(block_lines: list[str]) -> CanonicalRoutingInstance:
    name = _RE_VRF_HEAD.match(block_lines[0]).group(1)
    inst = CanonicalRoutingInstance(name=name)
    in_af = False
    in_import = in_export = False
    for line in block_lines[1:]:
        # detect af block / import block / export block transitions
        # collect bare community lines (65102:2) into the
        # currently-open import/export list
        ...
    return inst
```

RD is **not** parsed from the `vrf` stanza — it lives under
`router bgp`.  Phase 2 will add a minimal `router bgp / vrf X /
rd <rd>` harvester to backfill `CanonicalRoutingInstance.route_distinguisher`.

### Interface parse

The interface parser handles 5 distinct name patterns dispatched on
the prefix:

1. `interface GigabitEthernet<r>/<s>/<i>/<p>` — physical (4-segment)
2. `interface TenGigE<r>/<s>/<i>/<p>` / `HundredGigE<r>/<s>/<i>/<p>`
   / `FortyGigE<r>/<s>/<i>/<p>` etc.
3. `interface MgmtEth0/RP0/CPU0/<p>` — management
4. `interface Loopback<n>` — loopback
5. `interface Bundle-Ether<n>` — LAG
6. `interface <parent>.<subif>` — subinterface (any prefix)

Inside the stanza, observe:
- `ipv4 address <ip> <mask>` → `ipv4_addresses` (dotted mask form;
  `_mask_to_prefix()` reuse from `cisco_iosxe_cli.parse` — kept
  module-private there but can lift to shared helper)
- `ipv6 address <prefix>` → `ipv6_addresses` (CIDR form, no separate
  mask token)
- `description <text>` → `description`
- `shutdown` → `enabled = False` (default `True`)
- `mtu <n>` → `mtu`
- `vrf <name>` (note: NOT `vrf forwarding` — XR drops the `forwarding`)
  → `vrf` field + post-pass mgmt-VRF promotion
- `bundle id <n> mode <m>` → on member ports, sets
  `lag_member_of = f"Bundle-Ether{n}"` + records the mode for
  cross-vendor LAG mode preservation
- `bundle minimum-active links <n>` (only on Bundle-Ether stanzas;
  not modeled in v1 — Tier-3 ignore)
- `encapsulation dot1q <vlan-id>` → synthesises a `CanonicalVlan`
  during the post-pass; sets `access_vlan` on the subinterface

### Static route parse

```python
def _parse_router_static(block_lines: list[str]) -> list[CanonicalStaticRoute]:
    """Parse a `router static / ...` block.

    Forms:
        router static
         address-family ipv4 unicast
          10.0.0.0/8 GigabitEthernet0/0/0/2 11.1.1.2
          11.0.0.0/8 Null0
         !
         vrf blue
          address-family ipv4 unicast
           11.0.0.0/8 GigabitEthernet0/0/0/2 11.1.1.2
          !
         !
        !
    """
    # walk nested address-family blocks; for each leaf line:
    #   <CIDR> <nexthop-token>+
    # Set destination = CIDR; classify nexthop-token as interface or IP.
```

CIDR-form destination is preserved in `CanonicalStaticRoute.destination`
verbatim (which already uses CIDR notation per
`netcanon/migration/canonical/intent.py:264`).

---

## Render strategy

### Output structure

Render emits stanzas in an operator-natural order that round-trips
through the parser:

1. `!! IOS XR Configuration <version>` banner (preserved from
   metadata; fallback `6.6.2` literal if unset — matches the seed
   corpus version)
2. `hostname <name>`
3. `domain name <fqdn>`
4. `username <name>` blocks
5. `vrf <name>` blocks
6. `interface <name>` blocks (ordered: Loopback → MgmtEth →
   physical → Bundle-Ether → subinterfaces)
7. `router static` block (consolidated; per-VRF sub-blocks emitted
   inside)
8. `ssh server v2` (preserved metadata only if seen on parse)
9. `end`

### `commit` semantics — NOT emitted

Per Open Question 1 in `README.md`, render emits no `commit` line.
The output matches `show running-config` shape, which is what
operators consume.  If a future caller needs session-transcript
form, a separate `output_extension="session"` rendering mode can be
added.

### Bundle-Ether / Port-channel cross-vendor render

The render's interface emission loop walks `intent.interfaces`.
When an interface's name is `Port-channel<N>` (e.g. from an IOS-XE
source) AND the render target is `cisco_iosxr`, the cross-vendor
orchestrator's port-name renamer rewrites it to `Bundle-Ether<N>`
**before** render runs — driven by `classify_port_name` + the peer
codec's `format_port_identity`.  The renderer itself only sees
already-renamed XR-native names.

Same mechanism handles `GigabitEthernet0/0/0` (IOS-XE 3-segment) →
`GigabitEthernet0/0/0/0` (XR 4-segment) — `PortIdentity` carries
stack/module/port; XR's `format_port_identity` prepends a `0/`
rack segment.

### LAG mode render

Member-port `bundle id <n> mode <m>` lines emit during the
interface block.  Mode mapping (XR vs canonical):

| Canonical `CanonicalLAG.mode` | XR wire form |
|---|---|
| `"active"` | `bundle id <n> mode active` |
| `"passive"` | `bundle id <n> mode passive` |
| `"static"` | `bundle id <n> mode on` |

(Same vocabulary as IOS-XE channel-group; render-side mirror of
`_CISCO_LAG_MODE_MAP` from `cisco_iosxe_cli/parse.py:227`.)

### Static route render

Group routes by VRF, then by address-family:

```
router static
 address-family ipv4 unicast
  <prefix1> <iface1> <nh1>
  <prefix2> <nh2>
 !
 vrf blue
  address-family ipv4 unicast
   <prefix3> <iface3> <nh3>
  !
 !
!
```

The render walks `intent.static_routes` and groups by an implicit
VRF (none today — `CanonicalStaticRoute` carries no VRF field; this
is a documented lossy path on the IOS-XE codec at
`/routing-instances/instance`).  Until the canonical schema adds
per-route VRF, all static routes render under the global VRF.

---

## Port-name handling

### `port_names.py` module

Mirror of `cisco_iosxe_cli/port_names.py` with XR-specific patterns.

```python
# Physical interface — accepts 4-segment AND 3-segment forms.
# The 3-segment form is uncommon but appears on some Cisco RX/CRS
# platforms; absorbed defensively.
_PHYSICAL_RE = re.compile(
    r"^(?P<prefix>"
    r"FastEthernet|GigabitEthernet|TenGigE|TwentyFiveGigE|"
    r"FortyGigE|HundredGigE|FourHundredGigE|TwoHundredGigE)"
    r"(?P<a>\d+)/(?P<b>\d+)/(?P<c>\d+)(?:/(?P<d>\d+))?$",
    re.IGNORECASE,
)

# 4-segment: rack/slot/instance/port (modern ASR9k / NCS).
# 3-segment: legacy CRS / older ASR with no rack number.

_MGMT_RE = re.compile(
    r"^MgmtEth(?P<rack>\d+)/(?P<rp>RP\d+|RSP\d+)/(?P<cpu>CPU\d+)/(?P<port>\d+)$",
    re.IGNORECASE,
)

_LOGICAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"^Bundle-Ether(\d+)$", "lag"),
    (r"^Loopback(\d+)$", "loopback"),
    (r"^Null(\d+)$", "null"),         # XR-specific blackhole interface
    (r"^tunnel-ip(\d+)$", "tunnel"),  # XR GRE/IP tunnel naming
    (r"^tunnel-te(\d+)$", "tunnel"),  # XR MPLS-TE tunnel
)

# Speed mapping — same canonical vocabulary as cisco_iosxe_cli:
_XR_PREFIX_TO_SPEED = {
    "fastethernet": "fast",
    "gigabitethernet": "gig",
    "tengige": "10gig",
    "twentyfivegige": "25gig",
    "fortygige": "40gig",
    "hundredgige": "100gig",
    "twohundredgige": "200gig",
    "fourhundredgige": "400gig",
}

# Inverse — used by format_port_identity for cross-vendor renames.
_XR_SPEED_TO_PREFIX = {v: k for k, v in _XR_PREFIX_TO_SPEED.items()}
# Title-case the prefix on render (XR convention).
```

### `classify_port_name`

```python
def classify_port_name(name: str) -> PortIdentity:
    """Parse an XR port name into a PortIdentity.

    4-segment physical → kind="physical", stack=rack, module=slot,
                         port=instance, breakout_lane=port-on-instance
                         (NO — XR's 4-segment is not breakout; use
                         the meta dict to preserve all 4 indices)
    ...
    """
    # 4-segment physical: rack/slot/instance/port.
    # The natural PortIdentity mapping is:
    #   stack  = rack    (0 for single-rack ASR; non-zero on chassis)
    #   module = slot    (the slot number, e.g. RP0, line-card N)
    #   port   = instance
    #   meta["iosxr_port_index"] = port  (preserve the 4th segment)
    #
    # The 4th segment is the per-PIC port number; cross-vendor
    # mesh to IOS-XE drops it (IOS-XE 3-segment is stack/module/port;
    # the XR "instance" gets folded into the IOS-XE "module" by the
    # orchestrator).  This is a documented lossy translation, surfaced
    # via the rename modal warning.
```

### `format_port_identity`

```python
def format_port_identity(identity: PortIdentity) -> str | None:
    """Render a PortIdentity as an XR port name.

    Cross-vendor input (e.g. PortIdentity from IOS-XE 3-segment):
       stack=1, module=0, port=24, name_speed_hint="gig"
       → "GigabitEthernet1/0/24" (3-segment XR — legacy form)
       OR "GigabitEthernet0/1/0/24" (4-segment — prepend 0/ rack
          on the assumption that single-rack is the common case)

    Same-vendor round-trip (PortIdentity from XR parse):
       stack=0, module=0, port=0, meta["iosxr_port_index"]="0"
       → "GigabitEthernet0/0/0/0"
    """
    if identity.kind == "physical":
        prefix = _XR_SPEED_TO_PREFIX.get(
            identity.name_speed_hint, "GigabitEthernet"
        )
        # Title-case the prefix per XR convention.
        prefix = _to_xr_titlecase(prefix)
        # Restore 4th segment from meta if same-vendor; else default 0.
        idx = identity.meta.get("iosxr_port_index", "0")
        if identity.stack is not None and identity.module is not None:
            return f"{prefix}{identity.stack}/{identity.module}/{identity.port or 0}/{idx}"
        ...
    if identity.kind == "lag":
        return f"Bundle-Ether{identity.index or 1}"
    if identity.kind == "loopback":
        return f"Loopback{identity.index or 0}"
    if identity.kind == "mgmt":
        # No native cross-vendor MgmtEth representation — fall back
        # to MgmtEth0/RP0/CPU0/0 (the canonical XR mgmt port).
        return "MgmtEth0/RP0/CPU0/0"
    # svi, tunnel, etc. — handled per kind
    return None
```

---

## `iter_xpaths` method

Identical to Junos — reuse the shared canonical walker:

```python
def iter_xpaths(self, tree: Any) -> Iterable[str]:
    if isinstance(tree, CanonicalIntent):
        from ..cisco_iosxe_cli.codec import _walk_canonical
        yield from _walk_canonical(tree)
```

No xpath-vocabulary divergence vs IOS-XE — the canonical surface is
the same.  All capability declarations use the existing path
strings.

---

## `probe` method

Detection signals, in confidence-tier order:

```python
@classmethod
def probe(cls, raw_prefix: str) -> tuple[int, str] | None:
    """Detect Cisco IOS-XR `show running-config` text.

    Strong signals:
      * `!! IOS XR Configuration <version>` banner — UNAMBIGUOUS;
        no other vendor emits this exact form.  Score 98.
      * 4-segment port name pattern + `ipv4 address` keyword
        (rather than `ip address`) — high confidence even without
        the banner.  Score 90.

    Medium signals:
      * 4-segment port name pattern alone — could be a custom
        operator naming convention on IOS-XE, but unusual.  Score 75.
      * `Bundle-Ether<N>` interface declaration.  Score 70.
      * `route-policy <NAME>` + `end-policy` — XR DSL signature.
        Score 70.

    Weak signals:
      * `vrf <name>` top-level with `address-family ipv4 unicast`
        sub-block (without `vrf definition` IOS-XE form).  Score 50.

    Banner detection MUST come first since it's the highest-
    confidence signal AND the cheapest check.
    """
    # Reject XML / JSON early.
    if detect_input_shape(raw_prefix) is not None:
        return None

    if re.search(r"^!! IOS XR Configuration", raw_prefix, re.MULTILINE):
        return (98, "IOS XR Configuration banner present")

    hits = 0
    if re.search(
        r"^interface\s+(GigabitEthernet|TenGigE|HundredGigE|FortyGigE|"
        r"TwentyFiveGigE|FourHundredGigE)\s*\d+/\d+/\d+/\d+\b",
        raw_prefix, re.IGNORECASE | re.MULTILINE,
    ):
        hits += 2  # 4-segment port — strong
    if re.search(r"^\s+ipv4\s+address\s+\d", raw_prefix, re.MULTILINE):
        hits += 1
    if re.search(r"^interface\s+Bundle-Ether\d+", raw_prefix, re.MULTILINE):
        hits += 1
    if re.search(r"^interface\s+MgmtEth\d+/RP\d+/CPU\d+/\d+",
                 raw_prefix, re.MULTILINE):
        hits += 2  # MgmtEth — XR-only
    if re.search(r"^route-policy\s+\S+", raw_prefix, re.MULTILINE):
        hits += 1
    if re.search(r"^end-policy\s*$", raw_prefix, re.MULTILINE):
        hits += 1
    if re.search(r"^prefix-set\s+\S+", raw_prefix, re.MULTILINE):
        hits += 1

    if hits >= 4:
        return (92, f"{hits} IOS-XR grammar markers (banner absent)")
    if hits >= 2:
        return (75, f"{hits} IOS-XR grammar markers")
    return None
```

This probe **must** rank above `cisco_iosxe_cli` for XR captures.
Test the ranking explicitly via
`tests/unit/migration/test_codec_probe.py` (existing file pattern).

---

## `dropped_tier3_sections` detection

Add `detect_tier3_sections_iosxr` to
`netcanon/migration/_tier3_detection.py`.  Stanza headers to detect:

```python
_TIER3_HEADERS_IOSXR = (
    # Routing protocols
    r"^router bgp\s+\d+",
    r"^router ospf\s+",
    r"^router ospfv3\s+",
    r"^router isis\s+",
    r"^router rip$",
    r"^router pim$",
    # MPLS
    r"^mpls ldp$",
    r"^mpls traffic-eng$",
    r"^mpls oam$",
    # Policy primitives
    r"^route-policy\s+",
    r"^prefix-set\s+",
    r"^community-set\s+",
    r"^extcommunity-set\s+",
    r"^as-path-set\s+",
    r"^rd-set\s+",
    # Filters
    r"^ipv4 access-list\s+",
    r"^ipv6 access-list\s+",
    r"^class-map\s+",
    r"^policy-map\s+",
    # L2VPN / EVPN
    r"^l2vpn$",
    r"^evpn$",
    r"^bridge group\s+",
    # Misc
    r"^multicast-routing$",
    r"^call-home$",
)
```

Surfaced verbatim in the migrate page banner; never read by render.

---

## Cross-codec helper reuse

| Helper | Source | XR reuse strategy |
|---|---|---|
| `_walk_canonical` | `cisco_iosxe_cli/codec.py:445` | Import directly; canonical surface is identical |
| `_mask_to_prefix` | `cisco_iosxe_cli/parse.py:169` | Duplicate into `cisco_iosxr/parse.py` (parse-only) — small enough to fork rather than lift to a shared module |
| `_prefix_to_mask` | `cisco_iosxe_cli/render.py` | Same — duplicate (render-only) |
| `detect_input_shape` | `netcanon/migration/codecs/_input_shape.py` | Import directly |
| `sanitise_hostname` | `netcanon/migration/_naming.py` | Import directly |
| `classify_hash` / `is_migratable` | `netcanon/migration/_user_secrets.py` | Import directly for the `username` render path |
| `project_switchport_to_vlan` | `netcanon/migration/canonical/transforms.py` | No-op for XR (no switchports) but call for consistency |

---

## Order of implementation within Phase 1

To enable per-PR incremental review, implement in this order:

1. Skeleton files + class metadata + capability matrix declaration
   (`__init__.py`, `codec.py` with empty parse/render).  Codec
   registers; probe works; no canonical parse yet.  **Ship gate:**
   `pytest tests/unit/migration/test_real_captures.py::test_real_capture_parses_cleanly`
   passes for all 7 batfish fixtures because parse_intent returns a
   `CanonicalIntent(hostname="parsed")` placeholder.  *(20-30 LOC)*
2. `parse.py`: `_extract_hostname`, `_parse_globals` (domain),
   `_parse_users`.  **Ship gate:** `coverage["hostname"]=1` for every
   real-capture fixture.  *(~150 LOC)*
3. `parse.py`: `_parse_interfaces` — physical / Loopback / MgmtEth /
   Bundle-Ether.  No subinterfaces yet.  **Ship gate:**
   `coverage["interfaces"]>=2` for every real-capture fixture.
   *(~300 LOC)*
4. `parse.py`: `_parse_router_static`.  **Ship gate:**
   `coverage["static_routes"]>=1` for the iBGP border fixture.
   *(~100 LOC)*
5. `parse.py`: subinterface + `encapsulation dot1q` →
   `CanonicalVlan` synthesis.  *(~80 LOC)*
6. `port_names.py`: full classify + format with cross-vendor mesh
   tests.  *(~200 LOC)*
7. `_tier3_detection.detect_tier3_sections_iosxr()`.  Ship gate:
   `dropped_tier3_sections` populated for every fixture with
   `router bgp` etc.  *(~50 LOC)*
8. Unit + real-capture test suite.  *(~600-800 LOC)*

Phases 2-4 add the render path, VRF stanza, RD-from-BGP, and
fixture polish per the `README.md` phasing plan.
