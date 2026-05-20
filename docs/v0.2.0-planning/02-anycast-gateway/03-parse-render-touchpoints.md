# 03 — Parse/render touchpoints

Concrete file:line touchpoints in each codec's `parse.py` /
`render.py` for the anycast-gateway wiring. Code shapes are
sketched in markdown code blocks; the actual implementation lives
in the merge commit.

---

## Schema (cross-cutting)

### `netcanon/migration/canonical/intent.py`

* **Line ~89 (`CanonicalIPv4Address`):** add the `is_secondary`,
  `virtual_gateway_address`, `virtual_gateway_mac` fields. Place
  them after `prefix_length` so the JSON serialisation order is
  stable.

* **Line ~115 (`CanonicalIPv6Address`):** add the
  `virtual_gateway_address`, `virtual_gateway_mac` fields after
  `scope`.

* **Line ~640 (`CanonicalIntent`):** add the `anycast_gateway_mac`
  field after `apply_groups` / `group_content`.

Sketched diff (illustrative — actual edit lands in the merge commit):

```python
# CanonicalIPv4Address — add after prefix_length:
is_secondary: bool = False
virtual_gateway_address: str = ""
virtual_gateway_mac: str = ""

# CanonicalIPv6Address — add after scope:
virtual_gateway_address: str = ""
virtual_gateway_mac: str = ""

# CanonicalIntent — add at top-level:
anycast_gateway_mac: str = ""
```

### `netcanon/migration/canonical/transforms.py`

* **Line 310-370 (`project_svi_to_vlan`):** widen the
  `CanonicalIPv4Address` copy in the synthesis branch (line 352-356)
  and the merge branch (line 365-368) to pass through ALL fields
  via `model_copy(deep=True)`:

```python
# At line ~352 (synthesis branch):
ipv4_addresses=[
    a.model_copy(deep=True) for a in iface.ipv4_addresses
],

# At line ~365 (merge branch):
for addr in iface.ipv4_addresses:
    if (addr.ip, addr.prefix_length) not in existing_addrs:
        existing.ipv4_addresses.append(addr.model_copy(deep=True))
```

Mirror IPv6 fold path (same module, mid-file IPv6 branch).

### `netcanon/migration/canonical/anycast_mac.py` (NEW)

New module ~30 LOC. Helper functions for MAC format
normalisation (parse) and per-vendor render formatting:

```python
# netcanon/migration/canonical/anycast_mac.py

_COLON_HEX_RE = re.compile(r"^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$")
_DOTTED_TRIPLET_RE = re.compile(r"^[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}$")

def normalise_to_colon_hex(s: str) -> str:
    """Convert any of the three vendor MAC formats to colon-hex.

    Accepts: ``00:1c:73:00:dc:01`` (Arista/Junos),
    ``0001.c73a.0000`` (NX-OS / IOS-XE), ``00-1c-73-00-dc-01``
    (Windows-style; rare in vendor configs).  Returns empty string
    for unparseable input (parse-tolerant)."""

def to_dotted_triplet(colon_hex: str) -> str:
    """Render Cisco-style dotted-triplet.  ``00:1c:73:00:dc:01`` ->
    ``001c.7300.dc01``."""
```

---

## Juniper Junos

### `netcanon/migration/codecs/juniper_junos/parse.py`

#### Touchpoint 1: per-unit virtual-gateway-address — IPv4

**Insert at line ~1268** (after the existing IPv4 address branch
in `_apply_interfaces`):

```python
# Current code at line 1262-1282 parses:
#   set interfaces <name> unit <N> family inet address <ip>/<prefix>
# Extension: detect the optional 'virtual-gateway-address <Y>' trailer
# on the SAME line.
if (
    len(tokens) >= 9
    and tokens[3] == "family"
    and tokens[4] == "inet"
    and tokens[5] == "address"
    and tokens[7] == "virtual-gateway-address"
):
    vga = tokens[8]
    # Attach to the address record we JUST appended above.
    # existing is the list of (ip, prefix) tuples in target_state["ipv4"]
    # We need to widen the in-memory state shape to carry vga.
```

To carry the per-address `virtual_gateway_address` through the
multi-pass parse, **widen `target_state["ipv4"]` to store dicts
rather than tuples**:

```python
# OLD shape (current code):
#   target_state["ipv4"] = [(ip_str, prefix), ...]
# NEW shape:
#   target_state["ipv4"] = [
#       {"ip": ip_str, "prefix": prefix,
#        "virtual_gateway_address": "", "virtual_gateway_mac": ""},
#       ...
#   ]
```

This affects:

* **`parse.py:1262-1282`** — IPv4 address line parse: emit dict
  not tuple; also detect the optional `virtual-gateway-address`
  trailer.
* **`parse.py:1314-1330`** — IPv6 address line parse: same widening
  pattern.
* **`parse.py:365-368`** — materialisation loop (where
  `iface.ipv4_addresses.append(CanonicalIPv4Address(...))` reads
  the tuples back): unpack the dict instead, populate all fields.
* **`parse.py:373-390`** — IPv6 materialisation: same.
* **`parse.py:566-573`** — IRB-fold loop into
  `CanonicalVlan.ipv4_addresses`: unpack the dict.
* **`parse.py:583-590`** — IRB sub_iface fold: copy `model_copy(deep=True)`.

#### Touchpoint 2: per-unit virtual-gateway-v4-mac / -v6-mac

**Insert at line ~1340** (a new branch in `_apply_interfaces`
on the `unit <N>` dispatcher):

```python
# ``set interfaces <name> unit <N> virtual-gateway-v4-mac <MAC>``
if (
    name == "irb"
    and irb_state is not None
    and len(tokens) >= 5
    and tokens[3] == "virtual-gateway-v4-mac"
):
    mac = _normalise_to_colon_hex(tokens[4])
    if mac:
        entry = irb_state.setdefault(unit_num, {"ipv4": [], "ipv6": []})
        entry["v4_mac"] = mac

# ``set interfaces <name> unit <N> virtual-gateway-v6-mac <MAC>``
if (
    name == "irb"
    and irb_state is not None
    and len(tokens) >= 5
    and tokens[3] == "virtual-gateway-v6-mac"
):
    mac = _normalise_to_colon_hex(tokens[4])
    if mac:
        entry = irb_state.setdefault(unit_num, {"ipv4": [], "ipv6": []})
        entry["v6_mac"] = mac
```

The per-unit MACs go into `irb_state[vid]["v4_mac"]` /
`["v6_mac"]`. At materialisation time
(`parse.py:543-621` — the IRB-fold loop), stamp every address
record's `virtual_gateway_mac` field with the unit's MAC:

```python
# In the IRB-fold loop (around line 566):
v4_mac = irb_entry.get("v4_mac", "")
v6_mac = irb_entry.get("v6_mac", "")
for entry in irb_entry.get("ipv4", []):  # entry is now a dict
    addr = CanonicalIPv4Address(
        ip=entry["ip"],
        prefix_length=entry["prefix"],
        virtual_gateway_address=entry.get("virtual_gateway_address", ""),
        virtual_gateway_mac=entry.get("virtual_gateway_mac", "") or v4_mac,
    )
    # ... append-with-dedup logic as before
```

The `or v4_mac` pattern lets a per-address override (rare; not in
the QFX10K2 fixture) take precedence over the unit-wide default.

#### Touchpoint 3: optional dotted-name shorthand `set interfaces irb.<N>`

**Lines 1265-1330** in the dotted-unit branch — same widening
applies. Operators occasionally paste
`set interfaces irb.2021 unit 0 family inet address ...
virtual-gateway-address ...`; the existing code routes through
the sub-interface state bucket. The widening is uniform.

### `netcanon/migration/codecs/juniper_junos/render.py`

#### Touchpoint 4: emit virtual-gateway-address on address line

**Modify lines 439-444 and 499-503** (the IPv4-address emit loops
for sub-interfaces and parent-interface respectively):

```python
# CURRENT (line 439-444 — sub-interface branch):
for addr in iface.ipv4_addresses:
    out.append(
        f"set interfaces {parent} unit {unit_num} "
        f"family inet address "
        f"{addr.ip}/{addr.prefix_length}"
    )

# NEW:
for addr in iface.ipv4_addresses:
    line = (
        f"set interfaces {parent} unit {unit_num} "
        f"family inet address "
        f"{addr.ip}/{addr.prefix_length}"
    )
    if addr.virtual_gateway_address:
        line += f" virtual-gateway-address {addr.virtual_gateway_address}"
    out.append(line)
```

Same pattern for the parent-interface IPv4 emit (line 499-503),
IPv6 emit lines (449-454 and 504-509), and the IRB-from-VLAN
synthesis (line 754-763).

#### Touchpoint 5: emit per-unit virtual-gateway-v{4,6}-mac

**Add after the IPv6-address emit loop** in both the sub-interface
branch (after line 454) and the IRB-from-VLAN synthesis (after
line 763):

```python
# Per-unit MAC overrides emit AFTER all addresses on the unit.
# Use a "first non-empty wins" strategy when multiple addresses
# on the same unit carry different MACs (the Junos grammar only
# supports one MAC per unit per family).
v4_mac = next(
    (a.virtual_gateway_mac for a in iface.ipv4_addresses if a.virtual_gateway_mac),
    "",
)
if v4_mac:
    out.append(
        f"set interfaces {parent} unit {unit_num} "
        f"virtual-gateway-v4-mac {v4_mac}"
    )
v6_mac = next(
    (a.virtual_gateway_mac for a in iface.ipv6_addresses if a.virtual_gateway_mac),
    "",
)
if v6_mac:
    out.append(
        f"set interfaces {parent} unit {unit_num} "
        f"virtual-gateway-v6-mac {v6_mac}"
    )
```

For the IRB-from-VLAN synthesis path (line 754-763), the MAC
needs to come from the VLAN's address records since the VLAN is
the canonical home for IRB SVI L3.

### `netcanon/migration/codecs/juniper_junos/codec.py`

#### Touchpoint 6: capability matrix

**Insert at line 130** (in the `supported=[...]` list, alongside
existing `/interfaces/.../ipv4/...` paths):

```python
supported=[
    # ... existing entries ...
    "/interfaces/interface/ipv4/address/virtual-gateway-address",  # anycast
    "/interfaces/interface/ipv4/address/virtual-gateway-mac",
    "/interfaces/interface/ipv6/address/virtual-gateway-address",
    "/interfaces/interface/ipv6/address/virtual-gateway-mac",
    # NOTE: Junos has no system-wide MAC; anycast_gateway_mac stays
    # implicitly unsupported (per-IP overrides are the Junos model).
]
```

---

## Arista EOS

### `netcanon/migration/codecs/arista_eos/parse.py`

#### Touchpoint 7: per-Vlan-SVI `ip address virtual`

**Insert at line ~896** (after the existing `if
line.startswith("ip address ")` branch which currently parses
non-virtual addresses):

```python
# Current code at line 881-896 parses ``ip address X/Y [secondary]``
# (non-virtual).  Add a sibling branch for VARP:
if line.startswith("ip address virtual "):
    # Discriminate from ``ip address virtual source-nat`` (Tier-3).
    parts = line.split()
    if len(parts) >= 4 and parts[3] == "source-nat":
        # Tier-3 VARP source-NAT — parse-and-ignore.
        return
    # ``ip address virtual X/Y [secondary]``
    rest = line.split(None, 3)[3].strip()  # everything after "ip address virtual"
    tokens = rest.split()
    addr_token = tokens[0]
    is_secondary = len(tokens) >= 2 and tokens[1] == "secondary"
    if "/" in addr_token:
        ip, prefix = addr_token.split("/", 1)
        try:
            iface.ipv4_addresses.append(CanonicalIPv4Address(
                ip="",  # no per-leaf primary on EOS VARP
                prefix_length=int(prefix),
                virtual_gateway_address=ip,
                is_secondary=is_secondary,
            ))
        except ValueError:
            pass
    return
```

#### Touchpoint 8: top-level `ip virtual-router mac-address`

**Insert into the top-level / non-stanza dispatcher** in
`_parse_top_level` (location: search for top-level system commands
near the top of `_parse_stanzas` or in a sibling helper —
`netcanon/migration/codecs/arista_eos/parse.py` may have these
inline; suspect around line 250-400):

```python
# ``ip virtual-router mac-address 00:1c:73:00:dc:01`` — system-wide
# anycast / VARP MAC.  Capture into the canonical anycast_gateway_mac
# field.
if line.startswith("ip virtual-router mac-address "):
    mac = line.split(None, 3)[3].strip()
    from ...canonical.anycast_mac import normalise_to_colon_hex
    normalised = normalise_to_colon_hex(mac)
    if normalised:
        intent.anycast_gateway_mac = normalised
    return
```

The exact line for this insertion depends on where the EOS parser
handles other top-level `ip ...` directives (e.g.
`ip routing`, `ip route`, `ip name-server`); see
`arista_eos/parse.py` for the per-section dispatcher.

#### Touchpoint 9: IPv6 VARP (EOS 4.30+)

**Insert at line ~942** (in the IPv6 address branch):

```python
# After parsing ``ipv6 address`` keywords, add a sibling branch for
# ``ipv6 address virtual X/Y``:
if line.startswith("ipv6 address virtual "):
    rest = line.split(None, 3)[3].strip()
    addr_token = rest.split()[0]
    if "/" in addr_token:
        ip, prefix = addr_token.split("/", 1)
        try:
            iface.ipv6_addresses.append(CanonicalIPv6Address(
                ip="",
                prefix_length=int(prefix),
                scope="global",
                virtual_gateway_address=ip,
            ))
        except ValueError:
            pass
    return
```

### `netcanon/migration/codecs/arista_eos/render.py`

#### Touchpoint 10: emit `ip address virtual` for VARP records

**Modify lines 549-552** (the existing IPv4 emit loop):

```python
# CURRENT:
for addr in iface.ipv4_addresses:
    out.append(
        f"   ip address {addr.ip}/{addr.prefix_length}"
    )

# NEW: VARP records render as `ip address virtual X/Y`, regular
# primaries as `ip address X/Y`.
for addr in iface.ipv4_addresses:
    if addr.virtual_gateway_address:
        line = (
            f"   ip address virtual "
            f"{addr.virtual_gateway_address}/{addr.prefix_length}"
        )
        if addr.is_secondary:
            line += " secondary"
        out.append(line)
    else:
        out.append(
            f"   ip address {addr.ip}/{addr.prefix_length}"
        )
```

Mirror IPv6 (line 556-561 area).

#### Touchpoint 11: emit top-level `ip virtual-router mac-address`

**Insert near the end of `render_intent`**, after the
interface-emit loop and before the static-route emit (line varies;
typically around line 650-700 in arista_eos/render.py):

```python
# System-wide VARP / anycast MAC.  Emitted at top level AFTER
# all interface stanzas (matches Batfish-fixture observed order).
if tree.anycast_gateway_mac:
    out.append(f"ip virtual-router mac-address {tree.anycast_gateway_mac}")
    out.append("!")
```

### `netcanon/migration/codecs/arista_eos/codec.py`

#### Touchpoint 12: capability matrix

**Insert at line ~134** (in the `supported=[...]` list):

```python
supported=[
    # ... existing entries ...
    "/interfaces/interface/ipv4/address/virtual-gateway-address",  # VARP
    "/interfaces/interface/ipv4/address/is-secondary",
    "/interfaces/interface/ipv6/address/virtual-gateway-address",  # VARP v6 (4.30+)
    "/system/anycast-gateway-mac",                                 # ip virtual-router mac-address
]
```

Note: EOS does NOT support per-IP `virtual-gateway-mac` overrides
(only the system-wide field); declare that path **lossy** with a
review reason:

```python
lossy=[
    # ... existing entries ...
    LossyPath(
        path="/interfaces/interface/ipv4/address/virtual-gateway-mac",
        reason=(
            "EOS only supports a system-wide virtual-router MAC "
            "(``ip virtual-router mac-address``); per-IP overrides "
            "(Junos-style ``virtual-gateway-v4-mac``) drop to a "
            "review banner on render.  The first observed per-IP "
            "MAC populates the system-wide field; subsequent "
            "differing MACs emit comment-form review lines."
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
]
```

---

## Cisco IOS-XE CLI

### `netcanon/migration/codecs/cisco_iosxe_cli/parse.py`

#### Touchpoint 13: per-SVI `fabric forwarding mode anycast-gateway`

**Insert into the per-interface stanza dispatcher** (location in
the SVI / interface branch around the existing `ip address`
handling at line ~803; the exact line depends on the codec's
dispatcher layout):

```python
# Discriminator: ``fabric forwarding mode anycast-gateway`` marks
# the SVI's primary IP as the anycast gateway.  Accumulate a
# per-interface flag; apply at stanza-close time.
if line.strip() == "fabric forwarding mode anycast-gateway":
    iface_state["fabric_forwarding_anycast"] = True
    return
```

At stanza-close time (the existing materialisation point — search
for "ipv4_addresses=[..." in `cisco_iosxe_cli/parse.py`):

```python
if iface_state.get("fabric_forwarding_anycast"):
    for addr in iface.ipv4_addresses:
        addr.virtual_gateway_address = addr.ip   # NX-OS shape: same value
```

#### Touchpoint 14: top-level `fabric forwarding anycast-gateway-mac`

**Insert into the top-level dispatcher**:

```python
if line.startswith("fabric forwarding anycast-gateway-mac "):
    mac = line.split(None, 3)[3].strip()
    from ...canonical.anycast_mac import normalise_to_colon_hex
    normalised = normalise_to_colon_hex(mac)
    if normalised:
        intent.anycast_gateway_mac = normalised
    return
```

### `netcanon/migration/codecs/cisco_iosxe_cli/render.py`

#### Touchpoint 15: emit `fabric forwarding mode anycast-gateway` per SVI

**In the SVI / interface emit loop** (location: search for the
existing `ip address ip mask` emit at line ~263-272):

```python
# In the per-interface body emit, AFTER the ip address line:
emitted_anycast_mode = False
for addr in iface.ipv4_addresses:
    # ... existing emit ...
    if addr.virtual_gateway_address and not emitted_anycast_mode:
        body.append(" fabric forwarding mode anycast-gateway")
        emitted_anycast_mode = True
```

#### Touchpoint 16: emit top-level `fabric forwarding anycast-gateway-mac`

```python
# Near the top of render_intent, in the global / system block:
if tree.anycast_gateway_mac:
    from ...canonical.anycast_mac import to_dotted_triplet
    out.append(
        f"fabric forwarding anycast-gateway-mac "
        f"{to_dotted_triplet(tree.anycast_gateway_mac)}"
    )
```

### `netcanon/migration/codecs/cisco_iosxe_cli/codec.py`

#### Touchpoint 17: capability matrix

```python
supported=[
    # ... existing entries ...
    "/interfaces/interface/ipv4/address/virtual-gateway-address",
    "/system/anycast-gateway-mac",
]

# Note: IOS-XE CLI source coverage is intentionally limited to
# SD-Access mode.  Configs without ``fabric forwarding mode
# anycast-gateway`` on the SVI parse-and-ignore the anycast
# semantic (same canonical record, no virtual_gateway_address).
```

---

## Cisco NX-OS (Tier-D — depends on NX-OS codec landing)

Placeholder file references (no NX-OS codec module exists yet —
this section will turn into concrete touchpoints when the
`netcanon/migration/codecs/cisco_nxos/` directory lands per
sibling task `03-nxos-codec/`):

* **`netcanon/migration/codecs/cisco_nxos/parse.py`** (placeholder)
  — `ip address X/Y anycast` per-SVI line: same shape as the
  IOS-XE SD-Access mirror, but the `anycast` trailer is the
  discriminator (not a separate `fabric forwarding mode` line).
  Per-IP record: `CanonicalIPv4Address(ip="<X>", prefix_length=Y,
  virtual_gateway_address="<X>")` (mirror; see
  [`01-canonical-model.md`](01-canonical-model.md) § "NX-OS
  shape note").

* **`netcanon/migration/codecs/cisco_nxos/parse.py`** (placeholder)
  — top-level `fabric forwarding anycast-gateway-mac` — same
  shape as IOS-XE.

* **`netcanon/migration/codecs/cisco_nxos/render.py`** (placeholder)
  — emit `ip address X/Y anycast` when `ip ==
  virtual_gateway_address` (the NX-OS mirror signature); emit
  `fabric forwarding anycast-gateway-mac MAC` at the top level
  in dotted-triplet form.

* **`netcanon/migration/codecs/cisco_nxos/codec.py`** (placeholder)
  — capability matrix lists the same supported paths as IOS-XE.

---

## Aruba AOS-CX (Tier-D — depends on AOS-CX codec landing)

Placeholder file references:

* **`netcanon/migration/codecs/aruba_aoscx/parse.py`** (placeholder)
  — `interface vlanN / ip address X/Y virtual` — mirror of EOS
  VARP shape.

* **`netcanon/migration/codecs/aruba_aoscx/render.py`** (placeholder)
  — emit `ip address X/Y virtual` when
  `virtual_gateway_address` is set on the address record.

* **`netcanon/migration/codecs/aruba_aoscx/codec.py`** (placeholder)
  — capability matrix.

---

## FortiGate / MikroTik / OPNsense (declare `Unsupported`)

For each of these three codecs, the only touchpoint is the
capability matrix (no parse / render changes — the canonical
fields stay empty when nothing in the source maps to them).

### `netcanon/migration/codecs/fortigate_cli/codec.py`

```python
unsupported=[
    # ... existing entries ...
    UnsupportedPath(
        path="/interfaces/interface/ipv4/address/virtual-gateway-address",
        reason=(
            "FortiGate has no native anycast-gateway primitive; "
            "use ``config router vrrp`` for L3 HA (see VRRP task)."
        ),
    ),
    UnsupportedPath(
        path="/interfaces/interface/ipv6/address/virtual-gateway-address",
        reason="Mirror of the IPv4 case.",
    ),
    UnsupportedPath(
        path="/system/anycast-gateway-mac",
        reason=(
            "FortiGate has no system-wide anycast MAC "
            "declaration (the device is not DC-fabric edge)."
        ),
    ),
]
```

### `netcanon/migration/codecs/mikrotik_routeros/codec.py`

Same pattern — three `UnsupportedPath` entries with reason text
referencing RouterOS's standard `/ip vrrp` instead.

### `netcanon/migration/codecs/opnsense/codec.py`

Same pattern — three `UnsupportedPath` entries with reason text
referencing CARP (Common Address Redundancy Protocol) as the
nearest semantic (though CARP is preempt-based, not anycast).

---

## Aruba AOS-S (`aruba_aoss` — declare `Unsupported`)

AOS-S is campus-class; no native anycast. Three `UnsupportedPath`
entries on
`netcanon/migration/codecs/aruba_aoss/codec.py`. Same pattern as
FortiGate / MikroTik / OPNsense.

---

## cisco_iosxe (NETCONF — Phase 0.5 stub)

Already declares every non-interfaces field `unsupported`. Add
the three new anycast paths to the existing `unsupported=[]`
list on `netcanon/migration/codecs/cisco_iosxe/codec.py` for
mesh-audit honesty:

```python
unsupported=[
    # ... existing entries ...
    UnsupportedPath(
        path="/interfaces/interface/ipv4/address/virtual-gateway-address",
        reason="Phase 0.5 stub — anycast surface not implemented.",
    ),
    UnsupportedPath(
        path="/interfaces/interface/ipv6/address/virtual-gateway-address",
        reason="Phase 0.5 stub.",
    ),
    UnsupportedPath(
        path="/system/anycast-gateway-mac",
        reason="Phase 0.5 stub.",
    ),
]
```

---

## Summary

| Codec | parse.py LOC | render.py LOC | codec.py LOC (caps) | Touchpoints |
|---|---|---|---|---|
| Junos | ~50 | ~30 | ~10 | T1-T6 |
| EOS | ~40 | ~25 | ~15 | T7-T12 |
| IOS-XE CLI | ~25 | ~20 | ~5 | T13-T17 |
| NX-OS (Tier-D) | placeholder | placeholder | placeholder | sketched |
| AOS-CX (Tier-D) | placeholder | placeholder | placeholder | sketched |
| FortiGate / MikroTik / OPNsense / AOS-S / cisco_iosxe NETCONF | 0 | 0 | ~5 each | unsupported decls only |
| `canonical/intent.py` | +6 fields | n/a | n/a | schema additions |
| `canonical/transforms.py` | ~5 widening | n/a | n/a | fold copy preserve fields |
| `canonical/anycast_mac.py` | ~30 (new file) | n/a | n/a | format normalisation |

Total parse + render LOC for the three supporting codecs:
**~190 LOC**. Schema + transforms + helpers: **~50 LOC**.
Capability matrix edits across all codecs: **~50 LOC**. Grand
total **~290 LOC** (excluding tests).

This is within the ~350-500 LOC budget declared in
[`README.md`](README.md) § "Estimated total LOC + test count".
