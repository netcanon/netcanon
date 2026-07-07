# 14 — Codec RENDER correctness & output-injection

Lens: render-side output-injection across all 12 codecs
(`netcanon/migration/codecs/*/render.py`) + the orchestrator port-name
translation layer (`netcanon/migration/canonical/port_names.py`). Looked for the
mikrotik space-quoting class (#262) in OTHER codecs, RenderError vs crash,
KeyError/AttributeError on optional fields, ordering non-determinism,
prefix/mask off-by-one, and IPv4/IPv6 branch mistakes. All findings confirmed
with `py` probes importing the local package.

Verdict: **GO-WITH-FIXES.** One genuine, reproducible defect **class** —
unescaped double-quotes when a value is wrapped in `"..."` — is live in **three**
codecs (fortigate_cli, aruba_aoss, vyos). The reference-correct escaping already
exists in-tree (junos `_quote_always`) and in opnsense (ElementTree auto-escape),
so the fix is a known pattern, not new design. Plus one narrower mikrotik
backslash gap and a low-likelihood SNMP-community whitespace issue. No crashes,
no ordering non-determinism, no mask off-by-one, no v4/v6 branch defects found.

---

## MAJOR-1 — Unescaped `"` in quoted free-text fields (fortigate_cli, aruba_aoss, vyos)

The mikrotik #262 class, but for the **double-quote wrapping** idiom. Three
codecs wrap free-text values in `"..."` and interpolate the raw value with **no
escaping of an embedded `"`**. A source description / SNMP location / contact /
static-route comment containing a double-quote breaks out of the string, so the
rendered config is misparsed or non-deployable on the target device. This is
reachable cross-vendor: CLI parsers (Cisco/Arista/etc.) capture a `description`
free-text-to-EOL verbatim, so `description Link to "Core"` carries the quotes
into the canonical tree, then injects on render into these three targets.

### fortigate_cli (`codecs/fortigate_cli/render.py`)
No escape helper is imported (the file has `_prefix_to_mask` / `_split_cidr`
only). Raw `"..."` interpolation at:
- `render.py:433` — `set hostname "{tree.hostname}"`
- `render.py:457` — `set domain "{tree.domain}"`
- `render.py:555` — `set alias "{alias}"` (alias = `iface.description[:25]`)
- `render.py:761` — `set location "{tree.snmp.location}"`
- `render.py:763` — `set contact-info "{tree.snmp.contact}"`
- `render.py:778` — `set name "{community_name}"`
- `render.py:965` — `set comment "{route.description}"`
- also `set server "..."`, `edit "{u.name}"`, etc.

Probe (input description `Link to "Core" uplink; spaces`, snmp location
`Rack 3 "cold aisle"`, route description `via "peer"`):
```
    set alias "Link to "Core" uplink; sp"
    set location "Rack 3 "cold aisle""
    set comment "via "peer""
```
FortiOS's correct form escapes internal quotes as `\"`; these lines truncate at
the first `"` or fail commit.

### aruba_aoss (`codecs/aruba_aoss/render.py`)
Same, at `render.py:379,405,408,410,414,420,423,430,434,453,506,512-513,590,816`
(`hostname`, `snmp-server community`, `location`, `contact`, `snmpv3 user` +
passphrases, `radius-server ... key`, `password ... user-name`, vlan `name`,
iface `name "<description>"`).

Probe (iface description `Uplink to "Core" sw`, community `pub"lic`, location
`Row "A"`):
```
snmp-server community "pub"lic" Operator
snmp-server location "Row "A""
   name "Uplink to "Core" sw"
```

### vyos (`codecs/vyos/render.py`)
The `_q()` helper is a bare wrapper with **zero escaping**:
`render.py:105-107  def _q(value): return f'"{value}"'`.
Used for `address` (no quotes possible) and **`description`** (`_iface_body`,
`render.py:145`) plus snmp `contact`/`location` and vrf name.

Probe (iface description `Link "A" up`):
```
        description "Link "A" up"
```

Fix: route these through a shared quote-escaper (junos `_quote_always`
at `juniper_junos/render.py:1515` is the reference:
`s.replace("\\","\\\\").replace('"','\\"')`), or — for fortigate/aoss — escape
`"`→`\"` per each vendor's string grammar.

Severity MAJOR: produces invalid/misparsed target config; reachable cross-vendor;
likelihood moderate (quotes in descriptions/comments occur in the wild, e.g.
`description "TEMP: patch"`). Not a security issue per se (output is text an
operator reviews before applying), but it silently corrupts the deliverable.

---

## MINOR-2 — mikrotik `_escape` passes backslashes through unescaped

`codecs/mikrotik_routeros/render.py:881-883`:
```python
def _escape(value: str) -> str:
    return value.replace('"', '\\"')
```
`_escape` handles `"` but **not** `\`, whereas the sibling `_quote_if_needed`
(`render.py:864-874`, used for names — the #262 fix) correctly doubles
backslashes. `_escape` is used for every `comment="..."` (iface/bridge/tunnel/
vlan/static-route descriptions), SNMP `contact`/`location`, and SNMPv3
`authentication-password` / `encryption-password` passphrases.

RouterOS treats `\` as an escape char inside `"..."`. The sharp edge: a value
ending in a backslash escapes the **closing** quote, leaving an unterminated
string that breaks the whole `/export` parse.

Probe (description `win path \srv\share and quote "x"`):
```
comment="win path \srv\share and quote \"x\""
```
The `"` is escaped (`\"`) but the two `\` pass through raw. A trailing-backslash
description would emit `comment="path\"` → unterminated.

Severity MINOR: backslashes in free-text are less common than quotes, and the
`"`-only case (the common one) is handled; but the trailing-backslash config-break
is a real edge. Fix: make `_escape` also double backslashes (or reuse
`_quote_if_needed`'s escape body).

---

## MINOR-3 — SNMP community emitted as a bare single token (whitespace breaks it)

Multiple codecs emit the v1/v2c community as one bare CLI/node token, so a
community string containing whitespace is silently truncated or misparses the
trailing `ro`/`Operator`/authorization token:
- `arista_eos/render.py:211` — `snmp-server community {community} ro`
- `cisco_iosxe_cli/render.py:640` — `snmp-server community {community} RO`
- `cisco_nxos/render.py:253` — `snmp-server community {snmp.community}`
- `aruba_aoscx/render.py:197` — `snmp-server community {snmp.community}`
- `vyos/render.py:359` — `community {snmp.community} {` (block header)

Probe (vyos, community `pub lic`): renders `community pub lic {` — a VyOS syntax
error (`pub` parsed as the community, `lic` an unexpected token).

Severity MINOR: SNMP community strings almost never contain spaces, so
real-world likelihood is low; noted for completeness as the same
token-boundary class. (These same codecs emit `description`/`location`/`contact`
free-text-to-EOL verbatim, which is *correct* for line-oriented CLI grammar and
is **not** a bug.)

---

## Verified NON-findings (checked, clean — don't re-hunt)

- **Port-name translation empty-name output** — `translate_port_names`
  (`port_names.py:364-492`): when `format_port_identity` returns `""`/`None`
  the code keeps the ORIGINAL name verbatim (or drops it via `strip_unmappable`),
  it never assigns `iface.name = ""`. No empty-name leaks. (`port_names.py:400-469`.)
- **Port-name collisions** — no orchestrator-level guard, but this is
  architected: fortigate render has a render-time dedup + `# port collision:`
  comment (`fortigate_cli/render.py:492-531`). Not a regression.
- **Ordering non-determinism** — grepped every `render.py`: zero iteration over
  `set(...)` / `dict.values()` / `dict.keys()` / `dict.items()` in emit paths.
  All emission iterates lists (canonical order) or `sorted(...)`. Round-trip
  tree-order stability holds. mikrotik/junos dict accumulators
  (`range_emit_by_name`, `ifaces_by_kind`) rely on insertion order (py3.7+),
  which is deterministic.
- **Prefix/mask off-by-one** — shared `_prefix_to_mask` (`codecs/_helpers.py:90-106`)
  guards `0 <= prefix <= 32` and raises `RenderError` (propagates, not swallowed);
  `mask_int = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF if prefix else 0` is
  correct at the /0 and /32 endpoints. fortigate uses its own `_split_cidr` /
  `_prefix_to_mask` from `fortigate_cli/parse.py` (correct signature; probe
  rendered `set dst 10.0.0.0 255.0.0.0` fine).
- **IPv4/IPv6 branch** — fortigate correctly splits `config router static`
  (dotted mask) vs `config router static6` (`prefix/len`) via `_emit_route_body(v6)`
  (`fortigate_cli/render.py:944-956`), avoiding the >32-prefix RenderError.
  vyos picks `route6` on `":" in destination` (`vyos/render.py:278`). No mixups.
- **RenderError discipline** — every codec's `render_intent` raises `RenderError`
  (not a bare exception) on non-`CanonicalIntent` input, so the pipeline's
  `except RenderError` buckets it in the render stage (junos:108, mikrotik:105).
- **junos + opnsense escaping is correct** — junos `_quote_if_needed`
  (`:1470`) / `_quote_always` (`:1515`) escape `\` and `"`; opnsense builds XML
  via `ET.SubElement(...).text = value` which auto-escapes on serialization.
  These are the reference-correct implementations MAJOR-1's three codecs should
  follow.
