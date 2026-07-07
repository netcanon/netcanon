# 13 — Codec PARSE robustness (all 12 codecs)

Lens: crash-safety + correctness of `netcanon/migration/codecs/*/parse.py` (and the
XML codec bodies in `cisco_iosxe/codec.py`, `opnsense/parse.py`) on adversarial /
malformed input — regexes that throw or catastrophically backtrack, `int()`/index
parsing without guards, unbounded loops/allocation, IndexError/KeyError/ValueError on
truncated stanzas, brace-stack + XML parsers.

Verdict: **GO-WITH-FIXES.** One real availability defect (unbounded port-range
expansion → OOM in `aruba_aoss`, MAJOR, reproduced) and one contract-violation class
(two XML codecs leak a raw `ValueError` from `parse()`, MINOR/MEDIUM, both reproduced,
→ HTTP 500 on `/sanitize`). The prefix-length crash class the seed pointed at
(iosxe v6) is genuinely closed by a uniform base-class boundary wrapper — its
siblings are NOT crashes. Everything else in this lens is safe or safe-by-design;
recorded below so verifiers don't re-hunt.

Method note: I confirmed every reported crash with a `py -c` probe importing the local
package. The critical enabling fact — pydantic `ValidationError` **is** a subclass of
`ValueError` (pydantic 2.13.0) — was verified directly.

---

## F1 (MAJOR, reproduced) — aruba_aoss unbounded port-range expansion → OOM DoS

`netcanon/migration/codecs/aruba_aoss/parse.py`

`_expand_port_range` (line 447-455) materialises a numeric port range with **no upper
clamp**:

```python
    prefix_lo, num_lo = m_lo.group(1), int(m_lo.group(2))
    prefix_hi, num_hi = m_hi.group(1), int(m_hi.group(2))
    if prefix_lo != prefix_hi or num_hi < num_lo:
        return [lo, hi]
    return [f"{prefix_lo}{n}" for n in range(num_lo, num_hi + 1)]   # <- no bound
```

The gate `_AOS_PORT_SHAPE_RE` (line 367-369) accepts an unbounded digit run
(`\d+`), so both endpoints of a huge span pass the shape check:

```python
_AOS_PORT_SHAPE_RE = re.compile(
    r"^(?:[Tt]rk\d+|\d+(?:/[A-Za-z]?\d+)?|[A-Za-z]\d+)$",
)
```

Reached from a `vlan <N>` stanza's `tagged <list>` / `untagged <list>` directives via
`_parse_port_list` → `_expand_port_range` (call sites parse.py:406, 527, 532, 539, 544;
`tagged`/`untagged` regexes at lines 247-248). The trunk-member list
(`_build_lag_from_trunk_line` → `_parse_port_list`, line 461) is a second entry point.

Trigger — this ~35-byte config expands to ~1e9 heap strings (plus a same-size `seen`
set inside `_parse_port_list`):

```
hostname SW1
vlan 10
   name TEST
   tagged 1-999999999
   exit
```

Reproduced (bounded, to avoid OOMing the probe host):

```
$ py -c "... _AOS_PORT_SHAPE_RE.match('999999999') ..."
shape matches 999999999: True
parse_port_list 1-200000 -> 200000 entries (no clamp)
# and, end-to-end via parse_intent:
parsed in 0.58s; vlan10 tagged_ports=300000
```

`1-300000` builds 300k port strings in 0.58 s; `1-999999999` scales that to ~1 billion
allocations → memory exhaustion / multi-minute hang before any pydantic validation runs
(the lists are plain `list[str]` on `CanonicalVlan.tagged_ports`). Amplification is
enormous (tens of bytes → gigabytes), so no request-body size cap mitigates it.

Reachability / blast radius: `aruba_aoss` is a public source codec on `/migrate` and
`/sanitize`. Default bind is `127.0.0.1` (so not remote-by-default), but the app is
meant to be served (Docker image, `--host` override) — treat as a self/remote DoS.

Why prior VLAN-DoS work missed it: the earlier clamps live in `_helpers._parse_vlan_list`
(line 131, clamps to 1-4094) and `arista_eos._expand_vlan_list` (line 1499-1503, clamps)
— those bound **VLAN-id** ranges. `_expand_port_range` bounds a **port-name** range and
was never clamped. `aruba_aoscx` is NOT affected (it routes trunk lists through the
shared clamped `_parse_vlan_list`; verified no `range()` port expander).

Fix: clamp the span before materialising — a switch/stack has at most a few thousand
ports, so cap `num_hi - num_lo` (e.g. reject or truncate above ~4096) exactly as the
VLAN-id helpers already do, or refuse the range with a `ParseError`.

---

## F2 (MINOR→MEDIUM, both reproduced) — XML codecs leak raw `ValueError` from `parse()`

The uniform safety net at `codecs/base.py:254-284` (`CodecBase.__init_subclass__`) wraps
every codec's `parse` to convert a pydantic `ValidationError` into the documented
`ParseError`. It catches **only** `ValidationError` (base.py:279). A plain `ValueError`
from `int("abc")` is a `ValueError` but NOT a `ValidationError`, so it is NOT converted.
Two XML `int()` sites feed unvalidated element text straight into `int()` with no local
guard, so a non-numeric value leaks a raw `ValueError` out of `parse()`:

1. `opnsense/parse.py:424` — `vid = int(tag_el.text.strip())` for `<vlans><vlan><tag>`.
   Sibling handlers in the same file (mtu 542, subnet 566/610, radius ports 264/269,
   lease 703, VRRP vhid/skew/base 772/785/802) all `try/except ValueError`; the VLAN tag
   is the lone un-guarded one.

   ```
   $ py -c "OPNsenseCodec().parse('<opnsense><vlans><vlan><tag>abc</tag>...')"
   RAISED builtins.ValueError -> invalid literal for int() with base 10: 'abc'
   ```

2. `cisco_iosxe/codec.py:1151` — `out["index"] = int(idx_el.text.strip())` in
   `_parse_subinterface` for `<subinterfaces><subinterface><index>`. Its siblings in the
   SAME function are guarded (mtu 1135-1142, prefix-length 1201-1209 / 1265-1273 both
   `except ValueError → raise ParseError` AND range-check 0-32/0-128). The index int()
   was left un-wrapped.

   ```
   $ py -c "CiscoIOSXECodec().parse('<interfaces ...><subinterface><index>notanum</index>...')"
   RAISED builtins.ValueError -> invalid literal for int() with base 10: 'notanum'
   ```

Impact:
- Violates the documented `parse() Raises: ParseError` contract (base.py:303-305).
- Defeats the guarantee `tools/sanitize.py` explicitly documents and relies on at
  lines 225-231 ("an out-of-range parsed value already surfaces here as the documented
  ParseError … no per-call pydantic handling needed"). That reasoning holds only for
  `ValidationError`; a raw `ValueError` sails past it.
- `POST /sanitize` catches only `ParseError` (`api/routes/sanitize.py:82`), so a
  malformed opnsense `config.xml` / iosxe NETCONF XML returns **HTTP 500** instead of a
  clean 400. (`_errors.py`'s `ValueError` humaniser is backup-only; it does not cover
  this route.)
- On `/migrate`, `run_plan`'s generic `except Exception` (migration_pipeline.py:315)
  catches it, but labels the job `"unexpected error in stage parsing: …"` — framed as a
  server fault rather than the clean `"parse failed: …"` that a `ParseError` produces
  (migration_pipeline.py:301-303).

Fix (either): wrap the two `int()` calls to raise `ParseError` (mirroring the guarded
siblings in the very same functions), or broaden the base wrapper at base.py:279 to also
catch `ValueError` (weigh against masking genuine internal bugs).

---

## Verified NON-findings (safe / safe-by-design — do not re-hunt)

- **Prefix-length out of range (the seed's "hunt siblings" target).** v4 `> 32` /
  v6 `> 128` across `cisco_nxos` (build sites parse.py:875/890), `cisco_iosxr`
  (441/449), `juniper_junos` (402/427), `vyos` (881/885), etc. all raise pydantic
  `ValidationError` at model construction, which the base-class wrapper
  (base.py:254-284, the generalised #229 fix) converts to `ParseError` uniformly.
  Reproduced: `cisco_nxos` `ip address 10.0.0.1/40` and `cisco_iosxr`
  `ipv6 …/200` both surface as `ParseError` via `codec.parse()` (raw `parse_intent()`
  shows the underlying `ValidationError`, but no production path calls that directly —
  `migration_pipeline`, `sanitize`, CLI all go through the wrapped `codec.parse`).
  This is the closed iosxe-v6 crash; its siblings are not crashes.
- **v6-static-route sweep (#251-260) code.** `_STATIC_ROUTE_V6_RE` family
  (nxos 337, iosxe_cli 288, aoscx 273, arista 96, …) uses `[0-9A-Fa-f:]+/\d+` — the
  prefix stays inside the free-string `destination`, never `int()`-parsed, so no crash.
  The tail-token `while t < len(tail)` loops (iosxe_cli 1358-1369 / 1408-1419; nxos
  `_make_static_route_v6`) advance `t` on every branch (`+=1`/`+=2`) — no infinite loop.
  No defect introduced.
- **vyos brace-stack parser** (parse.py:465-568): iterative (a `stack` list, no
  recursion), pops guarded by `if stack:` (472-477), all `stack[N]` reads guarded by
  `len(stack) == N`. Unbalanced/extra braces leave a non-empty stack at EOF — no crash,
  no hang. `int(plen)` (852) is `try/except ValueError`-guarded; out-of-range → the
  base wrapper. Crash-safe.
- **juniper_junos brace→set converter** (`parse_block`, parse.py:992-1051): recursion
  depth capped at `_MAX_BLOCK_DEPTH = 100` (line 965/994) → `ParseError`; EOF-inside-block
  and stray `}` handled explicitly (1005-1011, 1047-1051, 1054-1059). No stack overflow.
- **XML entity-bomb / XXE**: `opnsense` uses `_safe_fromstring` (defused) and maps
  `DefusedXmlException` / `ET.ParseError` → `ParseError` (parse.py:180-192).
- **ReDoS**: the remaining `(\S+)(?:\s+(\d+))?` shapes (aoscx 267/273, nxos 277/283/332/338,
  arista 286, iosxe_cli 91/1495, aoss 301) have no ambiguous overlap — `\S+` can't match
  the `\s`-led optional group, so backtracking is linear. Prior CodeQL polynomial-redos
  fixes (#124/#127/#128) are in place (the `(\s.*)?` trailing-token groups, e.g.
  iosxe_cli `_STATIC_ROUTE_RE` 271-282, `_VRF_DESCRIPTION_RE` 395-397, arista
  `_DHCP_DNS_SERVER_RE` 277-279). No new backtracking hazard found.
- **mikrotik (#261/#262)**: `_parse_kv` uses `_KV_RE` = `([\w\-]+)=("[^"]*"|[^\s]+)`
  (no nested quantifier — linear); `_join_continuations` is O(n) with bounded buffer
  growth; VLAN-id derivation guards with `.isdigit()` (parse.py:453) and out-of-range
  id → base wrapper. `_looks_like_*` classifiers are simple anchored matches.
- **iosxr version extraction (#263)**: `^!!\s+IOS XR Configuration\s+(?:version\s*=?\s*)?(\S+)`
  (parse.py:321-324) is linear/safe.
- **arista_eos / aruba_aoscx VLAN range expansion**: clamped to 1-4094
  (`_expand_vlan_list` 1499-1503; `_parse_vlan_list` shared helper). `merge_trunk_allowed`
  "all"/"except" branches return bounded `range(1,4095)`.
- **arista split-index calls** (`line.split(None, N)[N]`, e.g. 1018/1048/1070/1095): the
  fed line is pre-`strip()`ped and each branch's `startswith("… ")` includes the trailing
  space, so a token always exists at the indexed position — no IndexError on truncated
  lines.
- **fortigate_cli**: every `int()` on free-text (ipv6 prefix 374, vlanid 399, ports,
  lease, VRRP fields) is `try/except ValueError`-wrapped; `_split_cidr`'s unguarded
  `int(prefix)` (parse.py:98) is render-only (used at render.py:955), out of this lens.
