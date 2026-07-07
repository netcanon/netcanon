# 41 — Adversarial verification of codec findings (reports 13/14/15)

Method: every finding below was reproduced (or refuted) with a read-only `py -c`
probe importing the local `netcanon` package. No edits/git/pytest/servers. Probe
outputs are inline. I checked each finding against the seed's KNOWN NON-BUGS list
(materialization / dedup / declared-lossy-is-honest / port-name orchestrator layer)
— none of the confirmed findings are one of those.

**Bottom line: every claimed finding REPRODUCED.** No refutations. I DOWNGRADED
three severities (F1/F2 udp-port MAJOR→MEDIUM; F4 anycast-MAC MAJOR→MINOR; F3 roster
MAJOR→MEDIUM) because their real blast radius is narrower than "major", and I
UPHELD the two genuine correctness/availability defects (aoss OOM MAJOR, quote
breakout MAJOR) and the broken-IOS GAP-7 hole (F5 MAJOR).

---

## Report 13 — codec PARSE robustness

### 13-F1 — aruba_aoss unbounded port-range → OOM — **CONFIRMED, MAJOR**
Probe (bounded, to avoid OOMing the host):
```
shape matches 999999999: True
1-1000   -> 1000 entries   in 0.000s (no clamp)
1-50000  -> 50000 entries  in 0.006s
1-200000 -> 200000 entries in 0.032s
expand 1-300000 -> 300000 entries
# end-to-end through the PUBLIC codec.parse():
parsed in 0.53s; vlan10 tagged_ports=300000
```
`_AOS_PORT_SHAPE_RE` accepts an unbounded `\d+`; `_expand_port_range`
(`aruba_aoss/parse.py:447-455`) materialises `range(num_lo, num_hi+1)` with **no
clamp**. `tagged 1-300000` in a `vlan` stanza builds 300k strings in 0.53 s through
the full public `codec.parse`; `1-999999999` scales that to ~1e9 allocations →
memory exhaustion before any pydantic validation. Reachable on `/migrate` and
`/sanitize` (public source codec). The prior VLAN-DoS clamps bound VLAN-**id**
ranges (`_helpers._parse_vlan_list`, `arista_eos._expand_vlan_list`), not port-name
ranges — genuinely un-clamped. Amplification (tens of bytes → GB) defeats any
request-body cap. **Final: MAJOR (availability/DoS).**

### 13-F2 — XML codecs leak raw `ValueError` from `parse()` → HTTP 500 — **CONFIRMED, MINOR→MEDIUM**
Both sites reproduced through the wrapped public `codec.parse`:
```
opnsense  <vlans><vlan><tag>abc</tag>...      -> builtins.ValueError: invalid literal for int() ... 'abc'
cisco_iosxe <subinterface><index>notanum</index> -> builtins.ValueError: invalid literal for int() ... 'notanum'
```
Root cause verified: the base-class safety net (`codecs/base.py:275-281`) catches
**only** `ValidationError`, and a plain `int("abc")` `ValueError` is not a subclass
of it — so it sails past the wrapper. `opnsense/parse.py:424` and
`cisco_iosxe/codec.py:1151` are the lone un-guarded `int()` sites (their in-function
siblings all `try/except ValueError → ParseError`). Confirmed the HTTP consequence:
`api/routes/sanitize.py:82` catches only `ParseError`, and the app-level
`@app.exception_handler(Exception)` (`api/routes/ui.py:155-167`) returns a generic
**500 "Internal Server Error"** — not the clean 400 a `ParseError` yields. Contract
in `base.py` docstring ("Raises: ParseError") is violated. **Final: MINOR→MEDIUM
(contract violation + 500-on-malformed-input; two sites; text-only, no RCE).**

### 13 verified NON-findings — SPOT-CHECKED, agree
Confirmed the prefix-length class is genuinely closed: `cisco_nxos ip address
10.0.0.1/40` and `cisco_iosxr ipv6 .../200` both surface as `ParseError` via the
wrapped `codec.parse` (only raw `parse_intent()` shows the underlying
`ValidationError`, and no production path calls that). Not re-hunted further — the
seed and report agree these are safe-by-design.

---

## Report 14 — codec RENDER / output-injection

### 14-MAJOR-1 — unescaped `"` in quoted free-text (fortigate_cli, aruba_aoss, vyos) — **CONFIRMED, MAJOR**
Rendered a `CanonicalIntent` with iface description `Link "A" up`, SNMP community
`pub"lic`, location `Row "A"`, contact `Joe "Ops"`:
```
vyos:          description "Link "A" up"     contact "Joe "Ops""    location "Row "A""    community pub"lic {
aruba_aoss:    snmp-server community "pub"lic" Operator   snmp-server location "Row "A""   name "Link "A" up"
fortigate_cli: set alias "Link "A" up"   set location "Row "A""   set contact-info "Joe "Ops""   set name "pub"lic"
```
All three interpolate the raw value into `"..."` with zero escaping (`vyos/render.py:105-107`
`_q` is a bare `f'"{value}"'`). Embedded `"` breaks out → misparsed / non-deployable
target config. Confirmed the reference-correct in-tree fix exists: junos renders the
same description as `description "Link \"A\" up"` (`_quote_always`), and opnsense uses
ElementTree auto-escaping. Reachable cross-vendor (CLI parsers capture
`description ...`-to-EOL verbatim into the canonical tree). Not a security issue
(operator-reviewed text output) but silently corrupts the deliverable. **Final: MAJOR
(correctness/deliverable corruption).**

### 14-MINOR-2 — mikrotik `_escape` passes backslashes through — **CONFIRMED, MINOR**
```
_escape('path\\') -> 'path\\'   (unchanged)
emitted           -> comment="path\"        <-- trailing \ escapes the closing quote => unterminated string
_quote_if_needed('path\\') -> '"path\\\\"'  (sibling correctly doubles the backslash)
```
`mikrotik/render.py:881-883` `_escape` handles `"` but not `\`. A trailing-backslash
free-text value escapes the closing quote → unterminated string breaks the whole
`/export` parse. The common `"`-only case is handled; backslash edge is real but
rarer. **Final: MINOR.**

### 14-MINOR-3 — SNMP community emitted as a bare token — **CONFIRMED, MINOR**
```
vyos community 'pub lic' -> community pub lic {   (VyOS syntax error: 'lic' unexpected)
```
Whitespace in a v1/v2c community truncates/misparses. Real-world likelihood low
(communities rarely contain spaces). Same token-boundary class across
arista/iosxe_cli/nxos/aoscx/vyos. **Final: MINOR.**

---

## Report 15 — support-matrix / walker honesty (drift)

### 15-F1 — cisco_nxos declares `/vxlan-vnis/udp-port` supported but normalises to 4789 — **CONFIRMED, MAJOR→MEDIUM**
```
cisco_nxos: render(udp_port=8472) -> reparse udp_port = 4789 ; classify('/vxlan-vnis/udp-port') = 'supported'
validate_against(tree, cisco_nxos): severity=ok, paths=[], udp-port mentioned? False
# realistic pair:
vyos parse of a port-less vxlan config -> udp_port = 8472  (baked default)
```
A source carrying 8472 (VyOS dataplane default, baked at `vyos/parse.py:801`)
migrated to NX-OS silently becomes 4789 while `validate_against` reports **severity
ok with no mention of udp-port** — a matrix lie in the dangerous direction. This is
NOT the seed's "declared-lossy is honest" non-bug; it is the inverse (declared
*supported*, actually lossy). Genuine honesty defect. I downgrade MAJOR→**MEDIUM**:
the trigger requires a non-default source port AND mixed-VTEP coexistence to bite,
but it is a real silent drop with a clean report. **Final: MEDIUM.**

### 15-F2 — aruba_aoscx has NO declaration for `/vxlan-vnis/udp-port` (fail-open supported) — **CONFIRMED, MEDIUM**
```
aruba_aoscx: render(udp_port=8472) -> reparse 4789 ; classify('/vxlan-vnis/udp-port') = 'supported'
validate_against: severity=ok, udp-port mentioned? False
```
Same silent-drop-with-clean-report as F1; here `classify()` fail-opens because the
path appears nowhere in `aruba_aoscx/codec.py`. **Final: MEDIUM** (same reasoning as F1).

### 15-F3 — ship-before-wire invariant roster frozen at 8 codecs — **CONFIRMED, MAJOR→MEDIUM**
`test_canonical_vrrp_anycast_schema.py:405-417` parametrize list = exactly
{cisco_iosxe_cli, cisco_iosxe, juniper_junos, arista_eos, aruba_aoss,
fortigate_cli, mikrotik_routeros, opnsense} — codecs 9-12 (cisco_nxos, cisco_iosxr,
aruba_aoscx, vyos) are ABSENT, and `_WIRED_UP_BY_CODEC` (:339-403) has 8 keys, none
for those four. Grep confirmed the roster is a hardcoded literal, NOT derived from
`list_codecs()`, and there is no guard-the-guard tying it to the registry. So the
memory-documented "two-sided invariant catches half-wired + forgot-to-declare" holds
only for 2/3 of the fleet. This is a guard GAP (root cause of F4), not a runtime
defect on its own, so I downgrade MAJOR→**MEDIUM**.

### 15-F4 — `/anycast-gateway-mac` undeclared on cisco_iosxr + vyos (classifies supported, drops) — **CONFIRMED, MAJOR→MINOR**
Round-trip sweep of `anycast_gateway_mac='0000.1111.2222'`:
```
arista_eos      supported  roundtrip='0000.1111.2222'   (honest)
cisco_iosxe_cli supported  roundtrip='00:00:11:11:22:22' (honest, format-normalised)
cisco_nxos      supported  roundtrip='00:00:11:11:22:22' (honest)
cisco_iosxr     supported  roundtrip=''   <-- DROP, classify lies
vyos            supported  roundtrip=''   <-- DROP, classify lies
```
cisco_iosxr and vyos classify `/anycast-gateway-mac` supported but drop the value.
Confirmed. (aruba_aoscx returned '' on my bare-intent probe, but report 15 correctly
scopes F4 to iosxr+vyos and defends aoscx as conditionally-supported when an SVI
mount exists — I did not attempt to refute that narrower claim.) Blast radius: on
realistic fabric configs the per-address VGA `unsupported` co-fires, so only a source
carrying ONLY the chassis MAC walks unflagged. I downgrade MAJOR→**MINOR**
(mitigated by co-flagging; genuine but narrow honesty lie).

### 15-F5 — vyos `vif` parse leaves `dot1q_vlan=None` → broken IOS sub-interface, clean report — **CONFIRMED, MAJOR**
```
vyos parse of `ethernet eth1 { vif 100 { address 10.1.1.1/24 } }`:
  iface 'eth1.100'  dot1q_vlan=None  ipv4=['10.1.1.1/24']
render tree through cisco_iosxe_cli:
  interface eth1.100
   ip address 10.1.1.1 255.255.255.0      <-- NO 'encapsulation dot1Q 100' (IOS rejects IP on a sub-if w/o encap)
validate_against(tree, cisco_iosxe_cli, source=vyos): severity=ok, dot1q mentioned? False
```
Genuine source-side GAP-7 under-parse: `dot1q_vlan` is never populated
(`vyos/parse.py:461,486`), so the walker never yields `/interfaces/interface/dot1q-vlan`
and the honesty system is structurally blind — broken output, clean report. NOT a
known non-bug (vyos-as-target declares dot1q-vlan unsupported honestly; this is
vyos-as-**source**). **Final: MAJOR (invalid target config emitted silently).**

### 15-F6 — VLAN-mount `secondary-ip` walk flag-gated vs interface-mount cardinality-gated — **CONFIRMED (code-level), MINOR**
`xpath_walker.py:96` interface mount: `if idx > 0 or addr.is_secondary`;
`xpath_walker.py:226` VLAN mount: `if addr.is_secondary:` only. The asymmetry is the
exact hole-class the interface mount was patched for (audit 276eaeb). Report's own
assessment (non-exploitable today — L3-capable VLAN targets either render both IPs or
declare `/vlans/vlan/ipv4/address/ip` lossy/unsupported) is consistent with the code.
**Final: MINOR (latent walker inconsistency, no silent loss today).**

### 15-F7 — interface-mount `virtual-gateway-mac` (v4+v6) undeclared across the 6 no-anycast codecs — **CONFIRMED, MINOR**
Classify sweep confirmed `/interfaces/interface/ipv4/address/virtual-gateway-mac` ==
`supported` on aruba_aoss, fortigate_cli, mikrotik_routeros, opnsense, cisco_iosxr,
vyos (all of which drop the anycast surface); arista_eos alone declares it lossy. As
the report notes, the per-address MAC always accompanies a virtual-gateway-address
whose `unsupported` declaration co-fires, so the loss is co-flagged but mis-itemized —
a bookkeeping asymmetry, not an operator-facing lie. **Final: MINOR.**

### 15 verified NON-findings — SPOT-CHECKED, agree
nxos VXLAN mcast-group + flood-list round-trip (probed adjacent to F1); dot1q-vlan
target-side is honest on all 12 codecs. No refutations here.

---

## Rejected / non-applicable known-non-bugs
None of the confirmed findings collapse to a seed known-non-bug. The vxlan udp-port
and anycast-MAC findings are the *inverse* of "declared-lossy is honest" (they are
declared-*supported* but actually lossy), so they are legitimate. The quote-breakout
and OOM are render/parse defects, not the port-name orchestrator layer.
