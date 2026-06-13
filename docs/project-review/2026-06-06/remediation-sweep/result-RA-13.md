# RA-13 — R-13 / CC-02: cross-vendor `is_secondary` fidelity (classic `ip address … secondary`)

**Agent:** RA-13
**Branch:** `review/2026-06-06-sweep`
**Finding:** R-13 / CC-02 — "second half" (the cleanup half — non-capturing VRRP regex — already shipped in #15; do NOT redo).
**Scope:** make classic `ip address X secondary` survive `cisco_iosxe_cli → arista_eos` and `arista_eos → arista_eos` by populating `CanonicalIPv4Address.is_secondary` on parse and honoring it in the arista plain-`ip address` render branch.
**Mode:** READ-ONLY analysis. Orchestrator applies + tests. All edits below are *additive and backward-compatible* (proof in Blast-radius §).

---

## 0. Path correction (important for the orchestrator)

The task brief uses bare paths (`cisco_iosxe_cli/parse.py`, `canonical/intent.py`, …). The **actual** repo layout nests every codec under `netcanon/migration/`. All edits below use the real paths:

| Brief path | Real path |
|---|---|
| `canonical/intent.py` | `netcanon/migration/canonical/intent.py` |
| `cisco_iosxe_cli/parse.py` | `netcanon/migration/codecs/cisco_iosxe_cli/parse.py` |
| `cisco_iosxe_cli/render.py` | `netcanon/migration/codecs/cisco_iosxe_cli/render.py` |
| `arista_eos/parse.py` | `netcanon/migration/codecs/arista_eos/parse.py` |
| `arista_eos/render.py` | `netcanon/migration/codecs/arista_eos/render.py` |

There is also a **stale duplicate tree** at `build/lib/netcanon/migration/codecs/…` (build artifact). Do NOT edit it — it is not the import target. (Confirm `import netcanon` resolves to the `netcanon/` source tree, not `build/`, before running tests; it does in a normal editable install.)

Line numbers below are from the live source as of this analysis and will drift; the literal `old_string` anchors are what matters.

---

## 1. Current-state verification (all confirmed)

- **Flag**: `netcanon/migration/canonical/intent.py:124` — `is_secondary: bool = False` on `CanonicalIPv4Address`; `:165` — same default on `CanonicalIPv6Address`. Default `False` everywhere. ✔
- **Cisco `_IP_RE`**: `cisco_iosxe_cli/parse.py:74-77` — captures only `(ip)(mask)`, NOT the `secondary` trailer. ✔
- **Cisco handler**: `:781-797` — stores `{"ip", "prefix_length"}`, deliberately drops the keyword (docstring at 786-793 says it round-trips *positionally*). ✔
- **Cisco dict→model**: `:1066-1073` — builds `CanonicalIPv4Address(ip=…, prefix_length=…, virtual_gateway_address=vga)`; does NOT pass `is_secondary`. ✔
- **Cisco RENDER**: `cisco_iosxe_cli/render.py:285-288` — positional: `suffix = " secondary" if idx > 0 else ""`. Never reads `addr.is_secondary` for IPv4. **Stays unchanged** (its positional scheme is unaffected by parse setting the flag — see Blast-radius). ✔
- **Arista VARP parse** (`ip address virtual …`): `arista_eos/parse.py:959-977` — ALREADY computes `is_secondary = len(tokens) >= 2 and tokens[1].lower() == "secondary"` and passes it. (This is the idiom we mirror.) ✔
- **Arista plain `ip address` parse**: `arista_eos/parse.py:979-994` — explicitly DROPS the `secondary` trailer ("first address wins", comment at 982-983). **This is bug site #2.** ✔
- **Arista VARP render**: `arista_eos/render.py:579-596` — honors `is_secondary` (appends `" secondary"`). ✔
- **Arista plain `else` render branch**: `arista_eos/render.py:597-600` — emits `ip address {ip}/{prefix}` with NO `secondary`. **This is bug site #3.** ✔

**Consequence (verified):** classic `ip address X secondary` is lost on `cisco_iosxe_cli → arista_eos` (cisco drops it on parse AND it never reaches a `CanonicalIPv4Address`; arista plain-render wouldn't emit it anyway) and on `arista_eos → arista_eos` (arista plain-parse drops it on the way in).

**Bonus finding (out of scope, noted for orchestrator):** the *other* cisco codec — `cisco_iosxe` (NETCONF/XML, distinct from `cisco_iosxe_cli`) — also never sets `is_secondary`. Its expectation YAML `tests/fixtures/cross_vendor_expectations/cisco_iosxe__arista_eos.yaml:269-276` *claims* "Multiple addresses per subinterface emit as multiple Arista `ip address … secondary` directives" with `disposition: good`. That claim is **currently false** for the plain-render branch. Edit #3 (arista render) makes it *renderable*, but the XML codec still won't *set* the flag, so cisco_iosxe→arista secondary fidelity remains a gap. See Open Questions — flag for a follow-up finding; **do not expand this RA's scope.**

---

## 2. The three edits (exact literal old → new)

### Edit 2.1 — Cisco parse: extend `_IP_RE` to optionally capture `secondary`

**File:** `netcanon/migration/codecs/cisco_iosxe_cli/parse.py` (~74-77)

`old_string`:
```python
_IP_RE = re.compile(
    r"^\s+ip\s+address\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)",
    re.IGNORECASE,
)
```

`new_string`:
```python
_IP_RE = re.compile(
    r"^\s+ip\s+address\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)"
    r"(?:\s+(secondary))?",
    re.IGNORECASE,
)
```

Notes:
- The original regex was *unanchored at the tail* (no `$`), so it already tolerated the `secondary` trailer by ignoring it — adding an optional 3rd group is purely additive: group(1)/group(2) are byte-identical for every input. The `(?:\s+(secondary))?` only ever *adds* a group-3 capture; it never changes the match boundary for ip/mask.
- `secondary` may be followed by `vrf <name>` per IOS-XE syntax; the non-anchored regex matches `secondary` and ignores any `vrf` tail exactly as before (VRF is handled elsewhere via `vrf forwarding`). No change to VRF handling.

### Edit 2.2 — Cisco parse: store `is_secondary` in the scratch dict when the trailer is present

**File:** `netcanon/migration/codecs/cisco_iosxe_cli/parse.py` (~781-797)

`old_string`:
```python
        im = _IP_RE.match(line)
        if im:
            ip_str = im.group(1)
            mask_str = im.group(2)
            prefix_len = _mask_to_prefix(mask_str)
            # IOS-XE accepts one primary + multiple secondary addresses
            # per interface (``ip address X.X.X.X MASK [secondary]``).
            # The render-side companion in :mod:`.render` emits the
            # ``secondary`` keyword for index>=1.  Trailing ``secondary``
            # is captured but not stored — the canonical model represents
            # the address list ordering as primary-first; the keyword is
            # recoverable on re-render.  Per Cisco IP Addressing Services
            # Configuration Guide, IOS-XE 17.x.
            current["ipv4"].append(
                {"ip": ip_str, "prefix_length": prefix_len},
            )
            continue
```

`new_string`:
```python
        im = _IP_RE.match(line)
        if im:
            ip_str = im.group(1)
            mask_str = im.group(2)
            prefix_len = _mask_to_prefix(mask_str)
            # IOS-XE accepts one primary + multiple secondary addresses
            # per interface (``ip address X.X.X.X MASK [secondary]``).
            # The render-side companion in :mod:`.render` re-derives the
            # ``secondary`` keyword *positionally* (index>=1), so cisco
            # self-round-trips are unaffected by the flag below.  We DO
            # capture ``is_secondary`` into the canonical model now (R-13)
            # so the fact survives a cross-vendor hop to a codec whose
            # render honours the flag explicitly (e.g. arista_eos's plain
            # ``ip address`` branch).  Per Cisco IP Addressing Services
            # Configuration Guide, IOS-XE 17.x — ``ip address ip-address
            # mask [secondary [vrf vrf-name]]``.
            current["ipv4"].append(
                {
                    "ip": ip_str,
                    "prefix_length": prefix_len,
                    "is_secondary": im.group(3) is not None,
                },
            )
            continue
```

### Edit 2.3 — Cisco dict→model conversion: pass `is_secondary` through

**File:** `netcanon/migration/codecs/cisco_iosxe_cli/parse.py` (~1066-1073)

`old_string`:
```python
    fabric_anycast = raw.get("fabric_forwarding_anycast", False)
    ipv4_addrs: list[CanonicalIPv4Address] = []
    for a in raw.get("ipv4", []):
        vga = a["ip"] if fabric_anycast else ""
        ipv4_addrs.append(CanonicalIPv4Address(
            ip=a["ip"],
            prefix_length=a["prefix_length"],
            virtual_gateway_address=vga,
        ))
```

`new_string`:
```python
    fabric_anycast = raw.get("fabric_forwarding_anycast", False)
    ipv4_addrs: list[CanonicalIPv4Address] = []
    for a in raw.get("ipv4", []):
        vga = a["ip"] if fabric_anycast else ""
        ipv4_addrs.append(CanonicalIPv4Address(
            ip=a["ip"],
            prefix_length=a["prefix_length"],
            is_secondary=a.get("is_secondary", False),
            virtual_gateway_address=vga,
        ))
```

Note: `.get("is_secondary", False)` keeps the dict shape backward-compatible (any dict built without the key still works); defaults match the model default.

### Edit 2.4 — Arista parse: set `is_secondary` from the plain-branch trailer instead of dropping it

**File:** `netcanon/migration/codecs/arista_eos/parse.py` (~979-994)

`old_string`:
```python
    if line.startswith("ip address "):
        # ``ip address 10.0.0.1/31`` — CIDR form only (EOS).
        rest = line.split(None, 2)[2].strip()
        # Some ``ip address`` lines have ``secondary`` trailer —
        # ignore the trailer, first address wins.
        addr = rest.split()[0]
        if "/" in addr:
            ip, prefix = addr.split("/", 1)
            try:
                iface.ipv4_addresses.append(CanonicalIPv4Address(
                    ip=ip,
                    prefix_length=int(prefix),
                ))
            except ValueError:
                pass
        return
```

`new_string`:
```python
    if line.startswith("ip address "):
        # ``ip address 10.0.0.1/31`` — CIDR form only (EOS).
        # ``ip address 10.0.0.1/31 secondary`` — secondary address.
        rest = line.split(None, 2)[2].strip()
        tokens = rest.split()
        addr = tokens[0]
        # Mirror the VARP branch: a ``secondary`` keyword after the
        # address marks an additional (non-primary) address.  Captured
        # into ``is_secondary`` (R-13) so the fact survives the round-
        # trip and cross-vendor hops, instead of being silently dropped.
        is_secondary = len(tokens) >= 2 and tokens[1].lower() == "secondary"
        if "/" in addr:
            ip, prefix = addr.split("/", 1)
            try:
                iface.ipv4_addresses.append(CanonicalIPv4Address(
                    ip=ip,
                    prefix_length=int(prefix),
                    is_secondary=is_secondary,
                ))
            except ValueError:
                pass
        return
```

Note: `rest.split()[0]` → `tokens = rest.split(); addr = tokens[0]` is behaviourally identical for the address token (both take the first whitespace-delimited token); we just retain `tokens` to inspect token[1]. `rest` is guaranteed non-empty here because the line starts with the literal `"ip address "` prefix and reached this branch; `tokens` is therefore non-empty (same assumption the original `rest.split()[0]` already relied on).

### Edit 2.5 — Arista render: append `secondary` in the plain `else` branch when `is_secondary`

**File:** `netcanon/migration/codecs/arista_eos/render.py` (~597-600)

`old_string`:
```python
            else:
                out.append(
                    f"   ip address {addr.ip}/{addr.prefix_length}"
                )
```

`new_string`:
```python
            else:
                plain_line = (
                    f"   ip address {addr.ip}/{addr.prefix_length}"
                )
                if addr.is_secondary:
                    plain_line += " secondary"
                out.append(plain_line)
```

Note: this mirrors the existing VARP-branch idiom at `render.py:584-585` (`if addr.is_secondary: line += " secondary"`). Indentation: the `else:` here is nested inside `for addr in iface.ipv4_addresses:` inside `for iface in …`; the body is at 16 spaces (the `out.append(` was at 16). The `old_string` anchor captures the exact existing indentation.

---

## 3. New round-trip tests (full content)

Add to **`tests/unit/migration/test_arista_eos.py`** (new test class — sits naturally alongside `TestVARPAnycast` which already covers the *virtual* branch; this covers the *plain* branch + the cross-vendor hop). The file already imports `AristaEOSCodec`, `CanonicalIntent`, `CanonicalInterface`, `CanonicalIPv4Address` (verify imports; they are used by existing tests in this file). The cross-vendor test also needs `from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec` — **confirm the exact class name** (see Open Questions Q1); the snippet below uses `CiscoIOSXECLICodec`.

```python
class TestPlainSecondaryAddressFidelity:
    """R-13 / CC-02 — classic ``ip address X[/Y] secondary`` (NOT VARP)
    must preserve ``is_secondary`` through parse and render.

    Before R-13 the arista_eos plain ``ip address`` parse branch and the
    cisco_iosxe_cli ``ip address`` handler both silently dropped the
    ``secondary`` keyword, so a secondary address was lost on
    cisco_iosxe_cli -> arista_eos and on arista_eos -> arista_eos.
    """

    def test_arista_plain_parse_sets_is_secondary(self):
        """``ip address X/Y secondary`` (no ``virtual``) lands as
        ``is_secondary=True``; the primary stays ``False``."""
        raw = (
            "hostname sw1\n"
            "interface Vlan20\n"
            "   ip address 10.0.20.1/24\n"
            "   ip address 10.0.99.1/24 secondary\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        iface = next(i for i in intent.interfaces if i.name == "Vlan20")
        assert len(iface.ipv4_addresses) == 2
        assert iface.ipv4_addresses[0].ip == "10.0.20.1"
        assert iface.ipv4_addresses[0].is_secondary is False
        assert iface.ipv4_addresses[1].ip == "10.0.99.1"
        assert iface.ipv4_addresses[1].is_secondary is True
        # Plain addresses must NOT be mistaken for VARP.
        assert iface.ipv4_addresses[1].virtual_gateway_address == ""

    def test_arista_plain_render_emits_secondary(self):
        """Render appends ``secondary`` to a plain ``ip address`` whose
        canonical record carries ``is_secondary=True`` — and NOT to the
        primary."""
        intent = CanonicalIntent(
            hostname="sw1",
            interfaces=[
                CanonicalInterface(
                    name="Vlan20",
                    ipv4_addresses=[
                        CanonicalIPv4Address(
                            ip="10.0.20.1", prefix_length=24,
                        ),
                        CanonicalIPv4Address(
                            ip="10.0.99.1", prefix_length=24,
                            is_secondary=True,
                        ),
                    ],
                ),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "   ip address 10.0.20.1/24" in out
        assert "   ip address 10.0.99.1/24 secondary" in out
        # The primary must NOT carry the trailer.
        assert "   ip address 10.0.20.1/24 secondary" not in out

    def test_arista_plain_self_round_trip_preserves_secondary(self):
        """arista_eos -> arista_eos preserves ``is_secondary`` on a
        plain (non-VARP) secondary address."""
        raw = (
            "hostname sw1\n"
            "interface Vlan20\n"
            "   ip address 10.0.20.1/24\n"
            "   ip address 10.0.99.1/24 secondary\n"
            "!\n"
        )
        codec = AristaEOSCodec()
        tree1 = codec.parse(raw)
        tree2 = codec.parse(codec.render(tree1))
        i1 = next(i for i in tree1.interfaces if i.name == "Vlan20")
        i2 = next(i for i in tree2.interfaces if i.name == "Vlan20")
        assert len(i1.ipv4_addresses) == len(i2.ipv4_addresses) == 2
        for a, b in zip(i1.ipv4_addresses, i2.ipv4_addresses):
            assert a.ip == b.ip
            assert a.prefix_length == b.prefix_length
            assert a.is_secondary == b.is_secondary
        # Specifically the secondary survived as a secondary.
        assert i2.ipv4_addresses[1].is_secondary is True

    def test_cisco_cli_to_arista_preserves_secondary(self):
        """cisco_iosxe_cli ``ip address X MASK secondary`` -> arista_eos
        renders as ``ip address X/Y secondary`` (the R-13 cross-vendor
        target).  Cisco parses dotted-mask; arista emits CIDR."""
        cisco_raw = (
            "hostname r1\n"
            "interface Vlan20\n"
            " ip address 10.0.20.1 255.255.255.0\n"
            " ip address 10.0.99.1 255.255.255.0 secondary\n"
            "!\n"
        )
        intent = CiscoIOSXECLICodec().parse(cisco_raw)
        iface = next(i for i in intent.interfaces if i.name == "Vlan20")
        assert iface.ipv4_addresses[0].is_secondary is False
        assert iface.ipv4_addresses[1].is_secondary is True
        out = AristaEOSCodec().render(intent)
        assert "   ip address 10.0.20.1/24" in out
        assert "   ip address 10.0.99.1/24 secondary" in out
        assert "   ip address 10.0.20.1/24 secondary" not in out
```

Add to **`tests/unit/migration/test_synthetic_cisco_iosxe_cli_kitchen_sink.py`** *or* a cisco_iosxe_cli unit module — a cisco self-round-trip guard proving the positional render is unchanged AND the flag is now set on parse (defends against a future refactor that makes cisco render read the flag and double-count):

```python
class TestCiscoCLISecondaryAddress:
    """R-13 — cisco_iosxe_cli now CAPTURES ``is_secondary`` on parse
    (for cross-vendor fidelity) while its render stays POSITIONAL, so
    self-round-trips are byte-stable."""

    def test_parse_sets_is_secondary_from_trailer(self):
        raw = (
            "hostname r1\n"
            "interface Vlan20\n"
            " ip address 10.0.20.1 255.255.255.0\n"
            " ip address 10.0.99.1 255.255.255.0 secondary\n"
            "!\n"
        )
        intent = CiscoIOSXECLICodec().parse(raw)
        iface = next(i for i in intent.interfaces if i.name == "Vlan20")
        assert iface.ipv4_addresses[0].is_secondary is False
        assert iface.ipv4_addresses[1].is_secondary is True

    def test_self_round_trip_positional_secondary_unchanged(self):
        """Render derives ``secondary`` positionally (idx>0), so the
        re-rendered config matches the canonical input form regardless
        of the flag."""
        raw = (
            "hostname r1\n"
            "interface Vlan20\n"
            " ip address 10.0.20.1 255.255.255.0\n"
            " ip address 10.0.99.1 255.255.255.0 secondary\n"
            "!\n"
        )
        codec = CiscoIOSXECLICodec()
        out = codec.render(codec.parse(raw))
        assert " ip address 10.0.20.1 255.255.255.0" in out
        assert " ip address 10.0.99.1 255.255.255.0 secondary" in out
        # Primary must not gain a spurious trailer.
        assert " ip address 10.0.20.1 255.255.255.0 secondary" not in out
        # Idempotent: a second pass is identical.
        assert codec.render(codec.parse(out)) == out
```

> Both modules: import the cisco CLI codec via the module's existing import style. Verify the class name (Q1) and the exact rendered indentation for cisco (the live render uses a single leading space — ` ip address …` at `render.py:288` — confirmed; arista uses three spaces `   ip address`).

---

## 4. Existing tests that assert the OLD (lossy) behavior

**None found that would break.** Detail:

- `grep -i secondary tests/` — the only *code* assertions about `secondary`/`is_secondary` live in:
  - `tests/unit/migration/test_arista_eos.py` → class `TestVARPAnycast` (lines ~1650-1883). Every one of these uses the **`ip address virtual …`** (VARP) grammar, which ALREADY sets and honors `is_secondary` (the branch at parse.py:959-977 / render.py:579-596). The plain `ip address` branch is **not** exercised by any existing test (confirmed: regex `ip address (?!virtual)` over that file = 0 matches). My edits don't touch the VARP branch, so these all keep passing.
  - `tests/unit/migration/test_canonical_vrrp_anycast_schema.py` → `TestCanonicalIPv4Address.test_secondary_flag` / `test_defaults` (lines ~170-203). Pure model-field tests (`is_secondary` defaults `False`; can be set `True`). Unaffected — my edits preserve the default and only *set* it from real wire input.
- The cisco kitchen-sink `secondary` hit (`test_synthetic_cisco_iosxe_cli_kitchen_sink.py:320`) is an unrelated comment about RADIUS "primary/secondary parity", not address handling.

**No test currently asserts that the plain branch DROPS `secondary`.** So there is nothing to *update* — only the new tests in §3 to *add*. (Contrast: had such a negative assertion existed, it would need flipping. It does not.)

**Doc/expectation YAMLs to be aware of (no code break, but truthfulness):**
- `tests/fixtures/cross_vendor_expectations/cisco_iosxe__arista_eos.yaml:269-276` already *asserts* (in prose, `disposition: good`) that multiple cisco addresses emit as multiple `ip address … secondary` on arista. That note is for the **`cisco_iosxe` (XML)** codec, NOT `cisco_iosxe_cli`. Edit #3 (arista render) makes the *render* side capable, but the XML codec still doesn't set the flag — so that note remains partly aspirational. The full-mesh tests (`test_run_full_mesh.py`) consume these YAMLs for matrix-consistency, not for exact `secondary` byte-checks, so no test breaks. **Recommend a separate follow-up** to either (a) wire `is_secondary` into the `cisco_iosxe` XML codec, or (b) downgrade that YAML note. Out of scope for RA-13.
- There is **no** `secondary` mention in `cisco_iosxe_cli__arista_eos.yaml` (the in-scope pair), so nothing there to reconcile.

---

## 5. Risk / blast-radius — why each edit is additive

This is the **common IPv4 parse path**, so caution is warranted. Each edit is provably non-regressing:

1. **`_IP_RE` (Edit 2.1).** The original pattern had no `$` anchor, so it *already* matched lines with a `secondary` (or `secondary vrf X`) tail and simply ignored everything past group 2. Adding `(?:\s+(secondary))?` cannot change where groups 1/2 match (regex is greedy left-to-right; ip and mask are fixed-shape `\d+\.\d+\.\d+\.\d+`). For every existing input, `group(1)` and `group(2)` are byte-identical; only a *new* optional `group(3)` appears. **No line that matched before stops matching; no captured ip/mask changes.**

2. **Cisco handler dict (Edit 2.2).** Adds one key (`"is_secondary"`) to the scratch dict. The dict's only consumer is the conversion at parse.py:1067 (verified: the sole read site; sole append site is 794). `is_secondary` is `im.group(3) is not None` → `False` for every config without the keyword (i.e. all existing fixtures except those explicitly using `secondary`). **No existing field mutated.**

3. **Cisco dict→model (Edit 2.3).** Adds `is_secondary=a.get("is_secondary", False)`. `.get(..., False)` means dicts built without the key (or by any other code path) still default to `False` = the model default. **Cisco RENDER never reads `is_secondary` for IPv4** (it derives the trailer positionally at render.py:287), so setting the flag is *inert* for cisco self-round-trips: re-rendered output is byte-identical. The flag only matters when a render that *does* read it (arista plain branch) is the target. **cisco→cisco unchanged; cisco→arista gains fidelity.** No double-`secondary` risk: cisco render ignores the flag; arista render reads it; neither both-reads-and-positions.

4. **Arista plain parse (Edit 2.4).** `rest.split()[0]` and `tokens[0]` extract the identical address token; the only new behaviour is reading `tokens[1] == "secondary"` to set the flag (mirrors the already-shipped VARP branch verbatim). For a primary line (`ip address X/Y` with no trailer) `len(tokens) < 2` → `is_secondary=False` = prior behaviour. **Primary addresses unchanged; secondaries stop being silently lost.**

5. **Arista plain render (Edit 2.5).** Appends `" secondary"` ONLY when `addr.is_secondary` is `True`. Every canonical record that reaches this branch today has `is_secondary == False` (because parse dropped it and nothing else set it on the plain path), so existing renders are byte-identical. The trailer only appears for records that *legitimately* carry the flag (post-Edit-2.4 arista parse, or post-Edit-2.3 cisco_iosxe_cli parse). Mirrors the VARP-branch idiom. **Existing output unchanged; new output is valid EOS (`ip address X/Y secondary` is the documented EOS secondary syntax).**

**Cross-codec ripple check:** every codec that builds `CanonicalIPv4Address` without `is_secondary` continues to get the `False` default (model default unchanged). Codecs whose render ignores `is_secondary` (cisco_iosxe_cli IPv4, and all others except arista's two branches) are unaffected by records that now carry `True` — they just don't emit a trailer (acceptable: those targets either lack the concept or express it differently; this is a *fidelity improvement opportunity*, not a regression). The arista IPv6 plain branch is **not** in scope here (R-13 is the v4 classic path); IPv6 VARP already handles its own `secondary` (render.py:606-614). The matching IPv6 plain-`ipv6 address` arista branch likely has the same latent gap — see Open Questions Q3.

**Build-tree caveat:** `build/lib/netcanon/...` holds a stale copy of all five files. Editing it is unnecessary and could confuse a `build/`-shadowed import. Apply edits ONLY under `netcanon/`.

---

## 6. Self-assessment

**Confidence: HIGH (9/10).**
- All five edit sites located and read in the live tree; line anchors verified against current source.
- Backward-compatibility argued per-edit from the actual code (unanchored regex; positional cisco render; `False` model default; mirrored VARP idiom).
- No existing test asserts the old lossy plain-path behaviour (verified by targeted greps), so nothing needs flipping — only additions.
- The one residual uncertainty is the cisco-CLI codec **class name** used by the new cross-vendor test (Q1) — a 1-line import the orchestrator can confirm trivially.

**Blockers: none.** Read-only deliverable complete; orchestrator can apply + run `pytest tests/unit/migration/test_arista_eos.py tests/unit/migration/test_synthetic_cisco_iosxe_cli_kitchen_sink.py tests/unit/migration/test_canonical_vrrp_anycast_schema.py -q`.

### Open questions
- **Q1 (import name).** The cisco-CLI codec class — `CiscoIOSXECLICodec`? Confirm from `netcanon/migration/codecs/cisco_iosxe_cli/__init__.py` (or `codec.py`) before running the cross-vendor test. The cisco_iosxe (XML) class is `CiscoIOSXECodec` (seen in `test_capability_matrix_honesty.py:59`); the CLI variant is a different class. If the codec's public entrypoint is via the registry rather than a direct class import, route the test through the registry like other cross-vendor tests in the file.
- **Q2 (cisco_iosxe XML codec, out of scope).** Should `is_secondary` also be wired into the *XML* `cisco_iosxe` codec so that `cisco_iosxe__arista_eos.yaml:269-276`'s `disposition: good` note becomes literally true? Recommend a separate finding; do not bundle into R-13.
- **Q3 (arista IPv6 plain branch, likely sibling gap).** The arista `ipv6 address virtual` branch handles `secondary`, but does the plain `ipv6 address X/Y` branch drop it the same way the v4 plain branch did? R-13 scopes to the classic v4 path; if symmetry is wanted, a one-line mirror in the v6 plain parse+render is the same shape. Flag as a candidate follow-up rather than scope-creeping this RA.
- **Q4 (capability-matrix declarations).** Does flipping `cisco_iosxe_cli`/`arista_eos` IPv4-address fidelity require any `CapabilityMatrix` xpath disposition change (e.g. an `interfaces[].ipv4_addresses[].is_secondary` leaf)? I found no per-leaf `is_secondary` xpath in the matrices and the honesty tests key on top-level fields, so likely no — but the orchestrator should run the full-mesh suite to confirm no `validate_against` reasoning shifts.

---

## RETURN summary
- **Result path:** `docs/project-review/2026-06-06/remediation-sweep/result-RA-13.md`
- **3 edit sites confirmed** (5 literal edits): (1) cisco_iosxe_cli `_IP_RE` regex + handler dict + dict→model conversion [3 edits in `netcanon/migration/codecs/cisco_iosxe_cli/parse.py`]; (2) arista_eos plain `ip address` parse [`arista_eos/parse.py:979-994`]; (3) arista_eos plain `else` render branch [`arista_eos/render.py:597-600`]. Cisco render stays positional/unchanged.
- **Existing test asserting old behavior:** NONE (TestVARPAnycast covers only the VARP branch; the schema test covers only model defaults — both keep passing). Nothing to flip; only new tests to add. One *doc* YAML (`cisco_iosxe__arista_eos.yaml:269-276`) has an aspirational note about the OTHER (XML) cisco codec — out of scope, flagged for follow-up.
- **Confidence:** HIGH (9/10).
- **Blockers:** none. Single trivial confirmation needed: cisco-CLI codec class name for the cross-vendor test import (Q1).
