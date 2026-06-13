# RA-24 — Normalise the 8 codec `__init__.py` headers

**Agent:** RA-24  
**Finding refs:** R-24 / DE-03 / DE-04  
**Branch:** `review/2026-06-06-sweep`  
**Date:** 2026-06-12

---

## 1. Diagnosis

All 8 codec `__init__.py` files were read in full along with their corresponding `codec.py` files to extract the `certainty` ClassVar. The following inconsistencies were found:

| Codec | Ordinal style | `Direction:` line | `Certainty:` line in header | `certainty` ClassVar |
|---|---|---|---|---|
| `arista_eos` | "6th" (digit) | Present | Present — `certified` | `certified` |
| `aruba_aoss` | "4th" (digit) | ABSENT | Present — `certified` | `certified` |
| `cisco_iosxe` | "first" (word) | Present | Present — `best_effort` | `best_effort` |
| `cisco_iosxe_cli` | ABSENT | Present | Present — `certified` | `certified` |
| `fortigate_cli` | "5th" (digit) | ABSENT | Present — `certified` | `certified` |
| `juniper_junos` | "7th" (digit) | Present (embedded in Scope) | ABSENT | `certified` |
| `mikrotik_routeros` | "third" (word) | ABSENT | Present — `certified` | `certified` |
| `opnsense` | "second" (word) | ABSENT | ABSENT | `certified` |

Problems:
1. **Ordinal style** flips between word-form ("first/second/third") and digit-form ("4th/5th/6th/7th"). `cisco_iosxe_cli` has no ordinal at all.
2. **`Direction:` line** is missing from `aruba_aoss`, `fortigate_cli`, `mikrotik_routeros`, `opnsense`. `juniper_junos` has it embedded inside the prose Scope block rather than as a standalone labelled line.
3. **`Certainty:` line** is missing from `juniper_junos` and `opnsense`.

All existing `Certainty:` values already match their `codec.py` ClassVar — no mismatch exists today. The risk is only in the two codecs where the line is being **added**.

---

## 2. Chosen template

After studying Arista EOS (`__init__.py`) and MikroTik (`__init__.py`) as the most-complete references and cross-checking with the split-codec convention in `codecs/README.md`, the following canonical header structure is chosen:

```
"""
<VendorName> <format> codec — <Nth> <adjective>.

Scope
-----
<prose describing what the codec parses/renders, grammar quirks,
 structural notes, out-of-scope items>

Module layout:
    * codec.py    — <CodecClass> class (metadata, delegation,
                    probe, port-name bridges)
    * parse.py    — <brief parse description>
    * render.py   — canonical tree → <vendor> CLI/XML text
    * port_names.py — cross-vendor port-name bridge
    [* <extra.py> — <brief description>  (only if present)]

Direction: ``<value>``.
Certainty: ``<value>`` — <one-line rationale>.
"""
```

Rules applied:
- **Ordinal:** digit-form everywhere ("1st / 2nd / 3rd / 4th / 5th / 6th / 7th / 8th"). `cisco_iosxe_cli` gets "2nd shipped CLI codec" (it ships after the NETCONF codec which is first).
- **`Direction:` line:** standalone labelled line at the end of the module layout block, before `Certainty:`.
- **`Certainty:` line:** always present; value must match `codec.py` ClassVar exactly.
- **Module layout block:** adjusted to match the actual files present in each codec package.
- **Scope heading:** retained where the prose merits a section; for shorter headers a single paragraph is fine.

---

## 3. Certainty ClassVar → header value table

| Codec | `certainty` ClassVar (from `codec.py`) | Header `Certainty:` line value |
|---|---|---|
| `arista_eos` | `certified` | `certified` |
| `aruba_aoss` | `certified` | `certified` |
| `cisco_iosxe` | `best_effort` | `best_effort` |
| `cisco_iosxe_cli` | `certified` | `certified` |
| `fortigate_cli` | `certified` | `certified` |
| `juniper_junos` | `certified` | `certified` |
| `mikrotik_routeros` | `certified` | `certified` |
| `opnsense` | `certified` | `certified` |

---

## 4. Per-codec apply-ready edits

Each section gives the **complete docstring replacement** — literal old→new for the `"""..."""` block at the top of each `__init__.py`. Only the docstring is changed; the `from` import lines below it are untouched.

---

### 4.1 `arista_eos/__init__.py`

**Problem:** Ordinal "6th" is digit (good), but the one-line summary reads "first DC-switching specialist" (word ordinal for the secondary tag). `Direction:` and `Certainty:` are already present and correct. Module layout is complete. No changes to `Direction:`/`Certainty:` values needed — only minor prose normalisation to the summary line and removing the redundant "first" ordinal qualifier.

**Old (lines 1–46):**
```python
"""
Arista EOS codec — 6th shipped codec, first DC-switching specialist.

Scope
-----
Parses / renders Arista EOS ``show running-config`` text.  EOS CLI
is a deliberate Cisco-IOS dialect but with several divergences that
warrant a distinct codec rather than folding into ``cisco_iosxe_cli``:

    * Port naming: ``Ethernet1`` (flat, no speed prefix) not Cisco's
      ``GigabitEthernet0/1``.  Speed comes from the port-profile /
      transceiver metadata rather than the name.  Breakouts use
      2-part slash: ``Ethernet50/1`` ... ``Ethernet50/4``.
    * IP-address form: CIDR (``10.0.0.1/31``) not dotted-mask
      (``10.0.0.1 255.255.255.254``).
    * Local-user grammar: ``username X role <name>`` replaces Cisco's
      ``privilege <N>`` semantics; password algorithm labels are
      explicit (``secret sha512 $6$...``, ``secret 5 $1$...``).
    * Port-channel name: capitalised ``Port-Channel1``, not Cisco's
      ``Port-channel1``.  CanonicalLAG.name preserves the case.
    * Default L2/L3: physical interfaces default to L2
      (``switchport`` implicit); ``no switchport`` flips to L3.  On
      Cisco IOS-XE the L2/L3 default varies by platform and the
      explicit mode setting is always present.

Supported / lossy / unsupported xpaths: see ``_CAPS`` on
:class:`.codec.AristaEOSCodec`.  Tier-3 parse-tolerant stanzas
(BGP/OSPF, MLAG/VXLAN/VRF, eAPI, STP, AAA, TerminAttr) are
detected and routed to ``CanonicalIntent.dropped_tier3_sections``
for the migrate-page banner.

Direction: ``bidirectional``.
Certainty: ``certified``.

Module layout:
    * codec.py — ``AristaEOSCodec`` class (metadata, delegation,
                 probe, port-name bridges)
    * parse.py — line-scan + per-stanza dispatch over EOS
                 ``show running-config`` text
    * render.py — canonical tree → EOS CLI text
    * port_names.py — cross-vendor port-name bridge
"""
```

**New:**
```python
"""
Arista EOS codec — 6th shipped codec; DC-switching specialist.

Scope
-----
Parses / renders Arista EOS ``show running-config`` text.  EOS CLI
is a deliberate Cisco-IOS dialect but with several divergences that
warrant a distinct codec rather than folding into ``cisco_iosxe_cli``:

    * Port naming: ``Ethernet1`` (flat, no speed prefix) not Cisco's
      ``GigabitEthernet0/1``.  Speed comes from the port-profile /
      transceiver metadata rather than the name.  Breakouts use
      2-part slash: ``Ethernet50/1`` ... ``Ethernet50/4``.
    * IP-address form: CIDR (``10.0.0.1/31``) not dotted-mask
      (``10.0.0.1 255.255.255.254``).
    * Local-user grammar: ``username X role <name>`` replaces Cisco's
      ``privilege <N>`` semantics; password algorithm labels are
      explicit (``secret sha512 $6$...``, ``secret 5 $1$...``).
    * Port-channel name: capitalised ``Port-Channel1``, not Cisco's
      ``Port-channel1``.  CanonicalLAG.name preserves the case.
    * Default L2/L3: physical interfaces default to L2
      (``switchport`` implicit); ``no switchport`` flips to L3.  On
      Cisco IOS-XE the L2/L3 default varies by platform and the
      explicit mode setting is always present.

Supported / lossy / unsupported xpaths: see ``_CAPS`` on
:class:`.codec.AristaEOSCodec`.  Tier-3 parse-tolerant stanzas
(BGP/OSPF, MLAG/VXLAN/VRF, eAPI, STP, AAA, TerminAttr) are
detected and routed to ``CanonicalIntent.dropped_tier3_sections``
for the migrate-page banner.

Module layout:
    * codec.py      — ``AristaEOSCodec`` class (metadata, delegation,
                      probe, port-name bridges)
    * parse.py      — line-scan + per-stanza dispatch over EOS
                      ``show running-config`` text
    * render.py     — canonical tree → EOS CLI text
    * port_names.py — cross-vendor port-name bridge

Direction: ``bidirectional``.
Certainty: ``certified`` — validated against real-capture fixtures;
    see ``tests/fixtures/real/RESULTS.md`` for the per-fixture matrix.
"""
```

---

### 4.2 `aruba_aoss/__init__.py`

**Problem:** `Direction:` line is absent. `Certainty:` line is present and correct (`certified`). Ordinal is "4th" (digit — good). Module layout block exists but uses the "post-split per the codecs/README.md" parenthetical; retain this for traceability. `_svi_absorption.py` is present in the package and must stay in the layout.

**Old (lines 1–56):**
```python
"""
Aruba AOS-S codec — 4th real vendor, Session C of the
vendor-config-research plan.

Scope
-----
Parses / renders ``show running-config`` from the ArubaOS-Switch
family (2530 / 2540 / 2930 running 16.x firmware, formerly ProCurve).
This is NOT the same as AOS-CX (the newer switching OS running on
CX 6200/6300/8320 hardware).

Architecturally interesting because AOS-S is **natively VLAN-centric**
— VLAN port membership is declared *inside* the ``vlan`` stanza
(``untagged 1-24`` / ``tagged 25-26``), not per-interface like Cisco.
This is the model the :class:`CanonicalVlan` tagged_ports /
untagged_ports design was built around, so Aruba is the first codec
where those fields round-trip without a transpose.

Supported / lossy / unsupported xpaths: see ``_CAPS`` on
:class:`.codec.ArubaAOSSCodec`.  Tier 1 coverage spans hostname,
VLAN-centric stanzas (id / name / ``untagged`` + ``tagged`` port
lists / SVI), interfaces, static routes, SNMP community + SNMPv3
users + groups, NTP, local users, RADIUS, LAG trunks.

Structural quirks handled:
    * ``;`` is the comment character (not ``!``)
    * Stanza delimiter is ``exit`` at the outdented position, or the
      next unindented line
    * Port names are bare: ``1``, ``1/1``, ``A1``, ``Trk1``
    * ``routing`` on an interface enables L3 (replaces ``no switchport``)
    * IP addresses support BOTH ``A.B.C.D M.M.M.M`` and ``A.B.C.D/N``
    * VLAN port lists: ``untagged 1-24``, ``untagged 1,3,5``,
      ``tagged 25-26,A1``

Out of scope (declared unsupported in matrix):
    * STP per-port (``spanning-tree 1-24 priority 4``)
    * 802.1X, MAC auth (RADIUS-bind/AAA policy)
    * ACLs (``access-list``)

Module layout (post-split per the codecs/README.md split-codec
convention):
    * ``codec.py``           — ``ArubaAOSSCodec`` class (metadata,
                               delegation, probe, port-name bridges)
    * ``parse.py``           — line-walker + per-stanza parsers
                               (``_parse_vlan_stanza`` /
                               ``_parse_interface_stanza``)
    * ``render.py``          — canonical tree → AOS-S CLI text
    * ``port_names.py``      — cross-vendor port-name identity bridge
    * ``_svi_absorption.py`` — SVI-into-VLAN absorption flag (single
                               source of truth for ``absorbs_svi_into_vlan``)

Certainty: ``certified`` — validated against real-capture fixtures
under ``tests/fixtures/real/aruba_aoss/`` (HPE community captures
spanning WC.16.07 / WB.16.08 / WC.16.10 / WC.16.11 / KB.15.15); see
``tests/fixtures/real/RESULTS.md`` for the per-fixture matrix.
"""
```

**New:**
```python
"""
Aruba AOS-S codec — 4th shipped codec; campus L2/L3 switching.

Scope
-----
Parses / renders ``show running-config`` from the ArubaOS-Switch
family (2530 / 2540 / 2930 running 16.x firmware, formerly ProCurve).
This is NOT the same as AOS-CX (the newer switching OS running on
CX 6200/6300/8320 hardware).

Architecturally interesting because AOS-S is **natively VLAN-centric**
— VLAN port membership is declared *inside* the ``vlan`` stanza
(``untagged 1-24`` / ``tagged 25-26``), not per-interface like Cisco.
This is the model the :class:`CanonicalVlan` tagged_ports /
untagged_ports design was built around, so Aruba is the first codec
where those fields round-trip without a transpose.

Supported / lossy / unsupported xpaths: see ``_CAPS`` on
:class:`.codec.ArubaAOSSCodec`.  Tier 1 coverage spans hostname,
VLAN-centric stanzas (id / name / ``untagged`` + ``tagged`` port
lists / SVI), interfaces, static routes, SNMP community + SNMPv3
users + groups, NTP, local users, RADIUS, LAG trunks.

Structural quirks handled:
    * ``;`` is the comment character (not ``!``)
    * Stanza delimiter is ``exit`` at the outdented position, or the
      next unindented line
    * Port names are bare: ``1``, ``1/1``, ``A1``, ``Trk1``
    * ``routing`` on an interface enables L3 (replaces ``no switchport``)
    * IP addresses support BOTH ``A.B.C.D M.M.M.M`` and ``A.B.C.D/N``
    * VLAN port lists: ``untagged 1-24``, ``untagged 1,3,5``,
      ``tagged 25-26,A1``

Out of scope (declared unsupported in matrix):
    * STP per-port (``spanning-tree 1-24 priority 4``)
    * 802.1X, MAC auth (RADIUS-bind/AAA policy)
    * ACLs (``access-list``)

Module layout (post-split per the codecs/README.md split-codec
convention):
    * ``codec.py``           — ``ArubaAOSSCodec`` class (metadata,
                               delegation, probe, port-name bridges)
    * ``parse.py``           — line-walker + per-stanza parsers
                               (``_parse_vlan_stanza`` /
                               ``_parse_interface_stanza``)
    * ``render.py``          — canonical tree → AOS-S CLI text
    * ``port_names.py``      — cross-vendor port-name identity bridge
    * ``_svi_absorption.py`` — SVI-into-VLAN absorption flag (single
                               source of truth for ``absorbs_svi_into_vlan``)

Direction: ``bidirectional``.
Certainty: ``certified`` — validated against real-capture fixtures
    under ``tests/fixtures/real/aruba_aoss/`` (HPE community captures
    spanning WC.16.07 / WB.16.08 / WC.16.10 / WC.16.11 / KB.15.15);
    see ``tests/fixtures/real/RESULTS.md`` for the per-fixture matrix.
"""
```

---

### 4.3 `cisco_iosxe/__init__.py`

**Problem:** Ordinal is "first" (word). No `Module layout:` block (this codec keeps parse+render inline in `codec.py` per the README note — the block should reflect that). `Direction:` and `Certainty:` are present and correct. The codec is a NETCONF adapter, not a CLI codec, so no `parse.py`/`render.py` sibling files exist.

**Old (lines 1–30):**
```python
"""
Cisco IOS-XE NETCONF adapter — first real adapter.

Operates against captured OpenConfig NETCONF ``<get-config>`` responses
(and produces ``<edit-config>``-ready output).  Live ncclient transport
is the embedded server's responsibility — the same split as the backup
collectors vs. collectors-consumers in the existing app.

Shares ``vendor_id=cisco_iosxe`` with the CLI codec (``cisco_iosxe_cli``)
— both target the same vendor YAML.  Distinguished by
``INPUT_FORMATS`` (``netconf-xml`` vs ``cli``).

Supported / lossy / unsupported xpaths: see ``_CAPS`` on
:class:`.codec.CiscoIOSXECodec`.  The render path emits the
``openconfig-interfaces`` subtree only; other surfaces are explicitly
declared unsupported in the matrix.  IPv4 and IPv6 addresses on
sub-interfaces are both shipped.

Declares ``unsupported_rename_categories = {'snmpv3'}`` — Tier-2
SNMPv3 round-trip is parser-side only; render emits no SNMPv3
container, so the rename rail flips amber for this category.

Direction: ``bidirectional``.
Certainty: ``best_effort`` — NETCONF stub; see
``tests/fixtures/real/RESULTS.md`` for the under-development matrix.
"""
```

**New:**
```python
"""
Cisco IOS-XE NETCONF adapter — 1st shipped codec; OpenConfig wire format.

Scope
-----
Operates against captured OpenConfig NETCONF ``<get-config>`` responses
(and produces ``<edit-config>``-ready output).  Live ncclient transport
is the embedded server's responsibility — the same split as the backup
collectors vs. collectors-consumers in the existing app.

Shares ``vendor_id=cisco_iosxe`` with the CLI codec (``cisco_iosxe_cli``)
— both target the same vendor YAML.  Distinguished by
``INPUT_FORMATS`` (``netconf-xml`` vs ``cli``).

Supported / lossy / unsupported xpaths: see ``_CAPS`` on
:class:`.codec.CiscoIOSXECodec`.  The render path emits the
``openconfig-interfaces`` subtree only; other surfaces are explicitly
declared unsupported in the matrix.  IPv4 and IPv6 addresses on
sub-interfaces are both shipped.

Declares ``unsupported_rename_categories = {'snmpv3'}`` — Tier-2
SNMPv3 round-trip is parser-side only; render emits no SNMPv3
container, so the rename rail flips amber for this category.

Module layout:
    * codec.py — ``CiscoIOSXECodec`` class (metadata, delegation,
                 probe, iter_xpaths) + inline parse + render helpers.
                 Parse/render are kept inline (not split to sibling
                 modules) because the XML-tree traversal differs
                 enough from the CLI-text codec pattern that a split
                 offered no clarity win; see ``codecs/README.md``.

Direction: ``bidirectional``.
Certainty: ``best_effort`` — Phase-0.5 NETCONF stub; render covers
    the ``openconfig-interfaces`` subtree only.  See
    ``tests/fixtures/real/RESULTS.md`` for the under-development matrix.
"""
```

---

### 4.4 `cisco_iosxe_cli/__init__.py`

**Problem:** No ordinal at all. `Direction:` and `Certainty:` are present and correct. Module layout block is present and well-formed.

**Old (lines 1–28):**
```python
"""
Cisco IOS-XE CLI codec — parses + renders ``show running-config`` text.

Shares ``vendor_id=cisco_iosxe`` with the NETCONF codec — both
target the same vendor YAML.  This means a stored
``show running-config`` backup (captured by the existing Netmiko
collector) can be fed directly into the translator pipeline via the
``source_filename`` shorthand on ``POST /api/v1/migration/plan``.

Direction: ``bidirectional``.
Certainty: ``certified``.

Module layout:
    * codec.py — ``CiscoIOSXECLICodec`` class (metadata, delegation,
                 probe, port-name bridges) + ``_walk_canonical``
                 (kept at module level so cross-codec ``iter_xpaths``
                 imports remain stable).
    * parse.py — line-scan + per-stanza dispatch over IOS-XE
                 ``show running-config`` text.  Public entry:
                 :func:`parse_intent`.
    * render.py — canonical tree → IOS-XE running-config text.
                 Public entry: :func:`render_intent`.
    * port_names.py — cross-vendor port-name bridge.
"""
```

**New:**
```python
"""
Cisco IOS-XE CLI codec — 2nd shipped codec; parses + renders
``show running-config`` text.

Scope
-----
Shares ``vendor_id=cisco_iosxe`` with the NETCONF codec — both
target the same vendor YAML.  This means a stored
``show running-config`` backup (captured by the existing Netmiko
collector) can be fed directly into the translator pipeline via the
``source_filename`` shorthand on ``POST /api/v1/migration/plan``.

Module layout:
    * codec.py      — ``CiscoIOSXECLICodec`` class (metadata, delegation,
                      probe, port-name bridges) + ``_walk_canonical``
                      (kept at module level so cross-codec ``iter_xpaths``
                      imports remain stable).
    * parse.py      — line-scan + per-stanza dispatch over IOS-XE
                      ``show running-config`` text.  Public entry:
                      :func:`parse_intent`.
    * render.py     — canonical tree → IOS-XE running-config text.
                      Public entry: :func:`render_intent`.
    * port_names.py — cross-vendor port-name bridge.

Direction: ``bidirectional``.
Certainty: ``certified`` — validated against real-capture fixtures;
    see ``tests/fixtures/real/RESULTS.md`` for the per-fixture matrix.
"""
```

---

### 4.5 `fortigate_cli/__init__.py`

**Problem:** `Direction:` line is absent. `Certainty:` line is present and correct (`certified`). Ordinal is "5th" (digit — good). Module layout block exists. `vlan_heuristics.py` is present and must remain in the layout.

**Old (lines 1–51):**
```python
"""
FortiGate CLI codec — 5th real codec.

Scope
-----
Parses / renders FortiOS CLI text.  FortiOS uses a recursive
``config/edit/set/next/end`` grammar — 5 keywords, arbitrary nesting
up to 3 levels in practice (``config > edit > config-subtable > edit``).

Supported / lossy / unsupported xpaths: see ``_CAPS`` on
:class:`.codec.FortiGateCLICodec`.  Top-level coverage spans
``config system {global,dns,ntp,interface,snmp,admin,dhcp}`` plus
``config router static`` and ``config user radius``.  SNMPv3 users
are NOT modelled — the codec declares ``unsupported`` for that xpath.

Structural quirks handled:
    * ``#config-version=`` banner on export (strong probe signal)
    * Quoted string values with spaces (``set alias "WAN uplink"``)
    * Multi-token set values (``set allowaccess ping https ssh``)
    * Integer ``edit`` IDs (static routes) + quoted ``edit`` IDs (ifaces)
    * ``set ip A.B.C.D M.M.M.M`` dotted-decimal mask form
    * ``set radius-port 0`` idiom meaning "use default 1812" —
      canonicalised to 1812 at parse time so round-trip stays stable

Out of scope (future):
    * ``config firewall policy`` — Tier 3, informational only
    * ``config firewall address`` / ``addrgrp`` — needs address-object
      model in canonical intent
    * SD-WAN, IPSec, SSL-VPN, UTM profiles — specialised subsystems
    * Multi-VDOM (``config vdom``) — no fixture coverage yet;
      single-VDOM exports assumed
    * Replacement messages / default profiles — the 80% boilerplate

Module layout:
    * ``codec.py``            — ``FortiGateCLICodec`` class (metadata,
                                delegation, probe, port-name bridges)
    * ``parse.py``            — block-model tokeniser + per-stanza
                                dispatchers (``_apply_<path>``)
    * ``render.py``           — canonical tree → FortiOS CLI text
    * ``vlan_heuristics.py``  — ifType inference + VLAN-naming helpers
    * ``port_names.py``       — cross-vendor port-name identity bridge

Certainty: ``certified`` — three real captures across FortiOS 7.2.13
(physical FG-100E, ~35K lines) and 7.6.6 (FGT-70G branch + FGT-VM hub,
26K+ combined) all round-trip clean after the implicit-VLAN-typing +
radius-port-0 grammar fixes.  See ``tests/fixtures/real/RESULTS.md``.
"""
```

**New:**
```python
"""
FortiGate CLI codec — 5th shipped codec; firewall + edge router.

Scope
-----
Parses / renders FortiOS CLI text.  FortiOS uses a recursive
``config/edit/set/next/end`` grammar — 5 keywords, arbitrary nesting
up to 3 levels in practice (``config > edit > config-subtable > edit``).

Supported / lossy / unsupported xpaths: see ``_CAPS`` on
:class:`.codec.FortiGateCLICodec`.  Top-level coverage spans
``config system {global,dns,ntp,interface,snmp,admin,dhcp}`` plus
``config router static`` and ``config user radius``.  SNMPv3 users
are NOT modelled — the codec declares ``unsupported`` for that xpath.

Structural quirks handled:
    * ``#config-version=`` banner on export (strong probe signal)
    * Quoted string values with spaces (``set alias "WAN uplink"``)
    * Multi-token set values (``set allowaccess ping https ssh``)
    * Integer ``edit`` IDs (static routes) + quoted ``edit`` IDs (ifaces)
    * ``set ip A.B.C.D M.M.M.M`` dotted-decimal mask form
    * ``set radius-port 0`` idiom meaning "use default 1812" —
      canonicalised to 1812 at parse time so round-trip stays stable

Out of scope (future):
    * ``config firewall policy`` — Tier 3, informational only
    * ``config firewall address`` / ``addrgrp`` — needs address-object
      model in canonical intent
    * SD-WAN, IPSec, SSL-VPN, UTM profiles — specialised subsystems
    * Multi-VDOM (``config vdom``) — no fixture coverage yet;
      single-VDOM exports assumed
    * Replacement messages / default profiles — the 80% boilerplate

Module layout:
    * ``codec.py``           — ``FortiGateCLICodec`` class (metadata,
                               delegation, probe, port-name bridges)
    * ``parse.py``           — block-model tokeniser + per-stanza
                               dispatchers (``_apply_<path>``)
    * ``render.py``          — canonical tree → FortiOS CLI text
    * ``vlan_heuristics.py`` — ifType inference + VLAN-naming helpers
    * ``port_names.py``      — cross-vendor port-name identity bridge

Direction: ``bidirectional``.
Certainty: ``certified`` — three real captures across FortiOS 7.2.13
    (physical FG-100E, ~35K lines) and 7.6.6 (FGT-70G branch +
    FGT-VM hub, 26K+ combined) all round-trip clean; see
    ``tests/fixtures/real/RESULTS.md``.
"""
```

---

### 4.6 `juniper_junos/__init__.py`

**Problem:** `Certainty:` line is absent entirely. `Direction:` line is present but embedded inside the Scope prose block ("`Direction: ``bidirectional``.  Render emits…`") rather than as a standalone labelled line at the end. Ordinal is "7th" (digit — good). Module layout block is present and well-formed. `certainty` ClassVar = `certified`.

**Old (lines 1–81):**
```python
"""
Juniper Junos codec — 7th shipped vendor, first hierarchical-config
grammar family in the portfolio.

Scope
-----
Bidirectional codec.  Accepts Junos ``set``-form configuration text
— the flat command-style output of ``show configuration | display
set`` — as the canonical paste form.  Block-form (``{ ... ; }``
hierarchical) input is auto-detected and converted to set-form
ahead of the normal parser, so operators with block-form exports
can paste either grammar.

Direction: ``bidirectional``.  Render emits set-form Junos that
round-trips through the parser; apply-groups statements + group
content are preserved end-to-end (GAP 9b) so the rendered output
matches the operator-paste shape rather than dumping every
inherited statement inline.

Supported grammar (Tier 1 + Tier 2):
    * ``set system host-name <name>`` /
      ``set system domain-name <domain>`` /
      ``set system name-server <ip>`` /
      ``set system ntp server <ip>`` /
      ``set system syslog host <ip> any any``
    * ``set system login user <name> class <class>``
    * ``set system login user <name> authentication encrypted-password "<hash>"``
    * ``set interfaces <iface> description "<desc>"`` /
      ``set interfaces <iface> mtu <N>`` /
      ``set interfaces <iface> disable``
    * ``set interfaces <iface> unit <N> family inet|inet6 address <ip>/<prefix>``
    * ``set interfaces <iface> unit <N> vlan-id <tag>`` (per-unit 802.1Q)
    * ``set interfaces interface-range <name> ...`` (members + shared attrs;
      structural collapse on parse + auto-synthesis on render)
    * ``set vlans <name> vlan-id <N>`` /
      ``set vlans <name> vxlan vni <VNI>``
    * ``set switch-options vtep-source-interface <iface>`` /
      ``set switch-options vxlan-port <N>`` (VXLAN switch-level globals)
    * ``set routing-instances <name> instance-type <t>`` /
      ``... route-distinguisher <rd>`` /
      ``... vrf-target [import|export] target:<rt>`` /
      ``... interface <iface>`` /
      ``... protocols evpn ip-prefix-routes vni <N>`` (EVPN Type-5 L3 VNI)
    * ``set routing-options static route <dest> next-hop <gw>``
    * ``set snmp community <name> authorization read-only|read-write``
    * ``set snmp location "<loc>"`` / ``set snmp contact "<contact>"``
    * ``set snmp trap-group <g> targets <ip>``
    * ``set snmp v3 usm local-engine user <n> authentication-<proto>
       authentication-key "<key>"`` /
      ``... privacy-<proto> privacy-key "<key>"`` /
      ``set snmp v3 vacm security-to-group security-model usm
       security-name <n> group <g>`` (SNMPv3 USM + VACM)
    * ``set groups <g> ...`` / ``set apply-groups <g>`` (two-pass
      inheritance + round-trip preservation)

Tier-3 parse-and-ignore:
    * ``set protocols bgp ...`` / ``set protocols isis ...`` /
      ``set protocols ospf ...`` / ``set protocols mpls ...``
    * ``set firewall ...`` / ``set policy-options ...`` /
      ``set security ...`` / ``set forwarding-options ...`` /
      ``set chassis ...`` / ``set services ...``

Module layout:
    * codec.py — ``JunosCodec`` class (metadata, delegation,
                 probe, port-name bridges, iter_xpaths)
    * parse.py — set-form + block-form parser; two-pass groups-
                 then-top-level dispatch + per-stanza appliers
    * render.py — canonical tree → Junos ``set``-form text
    * port_names.py — cross-vendor port-name bridge

Strategic value:
    Junos is the dominant service-provider OS (~25% SP market share
    per Omdia 2024) and widely used in mixed-vendor enterprise
    fabrics.  Bidirectional support unlocks **cross-vendor
    migration BOTH WAYS** between Junos and the Cisco / Arista /
    Aruba / OPNsense / FortiGate / MikroTik portfolio.
"""
```

**New:**
```python
"""
Juniper Junos codec — 7th shipped codec; hierarchical-config
grammar family (set-form + block-form).

Scope
-----
Accepts Junos ``set``-form configuration text — the flat
command-style output of ``show configuration | display set`` — as
the canonical paste form.  Block-form (``{ ... ; }`` hierarchical)
input is auto-detected and converted to set-form ahead of the normal
parser, so operators with block-form exports can paste either grammar.

Render emits set-form Junos that round-trips through the parser;
apply-groups statements + group content are preserved end-to-end
(GAP 9b) so the rendered output matches the operator-paste shape
rather than dumping every inherited statement inline.

Supported grammar (Tier 1 + Tier 2):
    * ``set system host-name <name>`` /
      ``set system domain-name <domain>`` /
      ``set system name-server <ip>`` /
      ``set system ntp server <ip>`` /
      ``set system syslog host <ip> any any``
    * ``set system login user <name> class <class>``
    * ``set system login user <name> authentication encrypted-password "<hash>"``
    * ``set interfaces <iface> description "<desc>"`` /
      ``set interfaces <iface> mtu <N>`` /
      ``set interfaces <iface> disable``
    * ``set interfaces <iface> unit <N> family inet|inet6 address <ip>/<prefix>``
    * ``set interfaces <iface> unit <N> vlan-id <tag>`` (per-unit 802.1Q)
    * ``set interfaces interface-range <name> ...`` (members + shared attrs;
      structural collapse on parse + auto-synthesis on render)
    * ``set vlans <name> vlan-id <N>`` /
      ``set vlans <name> vxlan vni <VNI>``
    * ``set switch-options vtep-source-interface <iface>`` /
      ``set switch-options vxlan-port <N>`` (VXLAN switch-level globals)
    * ``set routing-instances <name> instance-type <t>`` /
      ``... route-distinguisher <rd>`` /
      ``... vrf-target [import|export] target:<rt>`` /
      ``... interface <iface>`` /
      ``... protocols evpn ip-prefix-routes vni <N>`` (EVPN Type-5 L3 VNI)
    * ``set routing-options static route <dest> next-hop <gw>``
    * ``set snmp community <name> authorization read-only|read-write``
    * ``set snmp location "<loc>"`` / ``set snmp contact "<contact>"``
    * ``set snmp trap-group <g> targets <ip>``
    * ``set snmp v3 usm local-engine user <n> authentication-<proto>
       authentication-key "<key>"`` /
      ``... privacy-<proto> privacy-key "<key>"`` /
      ``set snmp v3 vacm security-to-group security-model usm
       security-name <n> group <g>`` (SNMPv3 USM + VACM)
    * ``set groups <g> ...`` / ``set apply-groups <g>`` (two-pass
      inheritance + round-trip preservation)

Tier-3 parse-and-ignore:
    * ``set protocols bgp ...`` / ``set protocols isis ...`` /
      ``set protocols ospf ...`` / ``set protocols mpls ...``
    * ``set firewall ...`` / ``set policy-options ...`` /
      ``set security ...`` / ``set forwarding-options ...`` /
      ``set chassis ...`` / ``set services ...``

Module layout:
    * codec.py      — ``JunosCodec`` class (metadata, delegation,
                      probe, port-name bridges, iter_xpaths)
    * parse.py      — set-form + block-form parser; two-pass groups-
                      then-top-level dispatch + per-stanza appliers
    * render.py     — canonical tree → Junos ``set``-form text
    * port_names.py — cross-vendor port-name bridge

Direction: ``bidirectional``.
Certainty: ``certified`` — validated against real-capture fixtures;
    see ``tests/fixtures/real/RESULTS.md`` for the per-fixture matrix.
"""
```

---

### 4.7 `mikrotik_routeros/__init__.py`

**Problem:** `Direction:` line is absent. `Certainty:` line is present and correct (`certified`). Ordinal is "third" (word — needs change to digit). Module layout block exists.

**Old (lines 1–37):**
```python
"""
MikroTik RouterOS codec — third real adapter (Session 2 of vendor-config-
research).

RouterOS stores its configuration as a line-oriented command script
produced by ``/export verbose``.  Structure is section-oriented: a
``/section path`` line sets the context, and subsequent ``add``/``set``
commands operate on that section.  The codec parses the Tier 1
canonical-intent surface (hostname, interfaces, VLANs, static routes,
DNS/NTP servers) and renders it back for cross-vendor translation.

Supported / lossy / unsupported xpaths: see ``_CAPS`` on
:class:`.codec.MikroTikRouterOSCodec`.  Coverage spans Tier 1
(hostname, interfaces, VLANs, static routes, DNS/NTP) with bridge
VLAN filtering, firewall, wireless / CAPsMAN / MPLS / routing
protocols declared unsupported.

Module layout (post-split per the codecs/README.md split-codec
convention):
    * ``codec.py``      — ``MikroTikRouterOSCodec`` class (metadata,
                          delegation, probe, port-name bridges)
    * ``parse.py``      — section dispatcher + per-section parsers;
                          hosts shared name/type helpers re-imported
                          by render
    * ``render.py``     — canonical tree → RouterOS ``/export`` text
    * ``port_names.py`` — cross-vendor port-name identity bridge

Certainty: ``certified`` — validated against real-capture fixtures
under ``tests/fixtures/real/mikrotik_routeros/``; the codec ships
filters for the default-value boilerplate RouterOS emits via
``/export verbose`` so the canonical round-trip is stable.  See
``tests/fixtures/real/RESULTS.md`` for the per-fixture matrix.
"""
```

**New:**
```python
"""
MikroTik RouterOS codec — 3rd shipped codec; section-oriented CLI
(``/export verbose`` format).

Scope
-----
RouterOS stores its configuration as a line-oriented command script
produced by ``/export verbose``.  Structure is section-oriented: a
``/section path`` line sets the context, and subsequent ``add``/``set``
commands operate on that section.  The codec parses the Tier 1
canonical-intent surface (hostname, interfaces, VLANs, static routes,
DNS/NTP servers) and renders it back for cross-vendor translation.

Supported / lossy / unsupported xpaths: see ``_CAPS`` on
:class:`.codec.MikroTikRouterOSCodec`.  Coverage spans Tier 1
(hostname, interfaces, VLANs, static routes, DNS/NTP) with bridge
VLAN filtering, firewall, wireless / CAPsMAN / MPLS / routing
protocols declared unsupported.

Module layout (post-split per the codecs/README.md split-codec
convention):
    * ``codec.py``      — ``MikroTikRouterOSCodec`` class (metadata,
                          delegation, probe, port-name bridges)
    * ``parse.py``      — section dispatcher + per-section parsers;
                          hosts shared name/type helpers re-imported
                          by render
    * ``render.py``     — canonical tree → RouterOS ``/export`` text
    * ``port_names.py`` — cross-vendor port-name identity bridge

Direction: ``bidirectional``.
Certainty: ``certified`` — validated against real-capture fixtures
    under ``tests/fixtures/real/mikrotik_routeros/``; the codec ships
    filters for the default-value boilerplate RouterOS emits via
    ``/export verbose`` so the canonical round-trip is stable.  See
    ``tests/fixtures/real/RESULTS.md`` for the per-fixture matrix.
"""
```

---

### 4.8 `opnsense/__init__.py`

**Problem:** Both `Direction:` and `Certainty:` lines are absent. Ordinal is "second" (word — needs change to digit). Module layout block exists. `certainty` ClassVar = `certified`.

**Old (lines 1–37):**
```python
"""
OPNsense adapter — second real adapter, Phase 1.

OPNsense stores its running config in a single ``config.xml`` file
whose hierarchy is already tree-shaped, so the parse/render work is
straightforward XML-to-dict-and-back.  What's interesting is the
cross-class story: OPNsense declares ``[firewall, router]`` while
``CiscoIOSXECodec`` declares ``[router, switch]``.  The
intersection is ``{router}`` so the class guard PERMITS the
migration — but the per-xpath capability matrices honestly flag
firewall rules and pf-specific bits as unsupported on the iosxe side,
so a real migration attempt surfaces the gaps via the
ValidationReport (not the class guard).  That's the intended layering.

Supported / lossy / unsupported xpaths: see ``_CAPS`` on
:class:`.codec.OPNsenseCodec`.  Coverage spans hostname / system
section, interface list (name + IP + subnet), LAN/WAN zone
membership, SNMPv3 (parser-side; see
``unsupported_rename_categories``).  Firewall rules / NAT /
gateways / FRR BGP-OSPF packages / aliases / dashboards are
declared unsupported (Tier 3 — would need the netcanon-ext YANG
augment).

Module layout:
    * ``codec.py``       — ``OPNsenseCodec`` class (metadata, delegation,
                           probe, port-name bridges, iter_xpaths)
    * ``parse.py``       — ``config.xml`` to ``CanonicalIntent``; owns
                           the bounded envelope-trim helper that rescues
                           legacy paramiko-shell backups
    * ``render.py``      — ``CanonicalIntent`` (or legacy dict) to
                           ``config.xml`` text
    * ``port_names.py``  — cross-vendor port-name identity bridge
"""
```

**New:**
```python
"""
OPNsense adapter — 2nd shipped codec; XML config.xml wire format.

Scope
-----
OPNsense stores its running config in a single ``config.xml`` file
whose hierarchy is already tree-shaped, so the parse/render work is
straightforward XML-to-dict-and-back.  What's interesting is the
cross-class story: OPNsense declares ``[firewall, router]`` while
``CiscoIOSXECodec`` declares ``[router, switch]``.  The
intersection is ``{router}`` so the class guard PERMITS the
migration — but the per-xpath capability matrices honestly flag
firewall rules and pf-specific bits as unsupported on the iosxe side,
so a real migration attempt surfaces the gaps via the
ValidationReport (not the class guard).  That's the intended layering.

Supported / lossy / unsupported xpaths: see ``_CAPS`` on
:class:`.codec.OPNsenseCodec`.  Coverage spans hostname / system
section, interface list (name + IP + subnet), LAN/WAN zone
membership, SNMPv3 (parser-side; see
``unsupported_rename_categories``).  Firewall rules / NAT /
gateways / FRR BGP-OSPF packages / aliases / dashboards are
declared unsupported (Tier 3 — would need the netcanon-ext YANG
augment).

Module layout:
    * ``codec.py``      — ``OPNsenseCodec`` class (metadata, delegation,
                          probe, port-name bridges, iter_xpaths)
    * ``parse.py``      — ``config.xml`` to ``CanonicalIntent``; owns
                          the bounded envelope-trim helper that rescues
                          legacy paramiko-shell backups
    * ``render.py``     — ``CanonicalIntent`` (or legacy dict) to
                          ``config.xml`` text
    * ``port_names.py`` — cross-vendor port-name identity bridge

Direction: ``bidirectional``.
Certainty: ``certified`` — validated against real-capture fixtures;
    see ``tests/fixtures/real/RESULTS.md`` for the per-fixture matrix.
"""
```

---

## 5. Test plan

### `test_codec_header_certainty.py` — guard behaviour after applying edits

The test parametrises over all registered codecs and:
1. Imports the codec's package `__init__` module and reads its `__doc__`.
2. Searches for `Certainty: <value>` (backtick-tolerant regex).
3. If present, asserts it equals `codec.certainty`.
4. If absent, `pytest.skip()` — the guard does not fail for missing lines.

**Before these edits:** two codecs skipped the guard (`juniper_junos` and `opnsense`).

**After these edits:** all 8 registered codecs have a `Certainty:` line. The guard will exercise all 8. Values:

| Codec | Header `Certainty:` value | ClassVar value | Match? |
|---|---|---|---|
| `arista_eos` | `certified` | `certified` | PASS |
| `aruba_aoss` | `certified` | `certified` | PASS |
| `cisco_iosxe` | `best_effort` | `best_effort` | PASS |
| `cisco_iosxe_cli` | `certified` | `certified` | PASS |
| `fortigate_cli` | `certified` | `certified` | PASS |
| `juniper_junos` | `certified` | `certified` | PASS |
| `mikrotik_routeros` | `certified` | `certified` | PASS |
| `opnsense` | `certified` | `certified` | PASS |

No skips after the edits. The test suite exercises the full set.

### Regression risk

These edits are **docstring-only**. No import lines, no code logic, no `__all__` lists, no ClassVar values are touched. The only failure path is a `Certainty:` value typo — mitigated by the table above.

---

## 6. Risk assessment

**Low.** Docstring-only changes. The one real trap — `Certainty:` / ClassVar mismatch — is explicitly checked before every value was written. The `cisco_iosxe` NETCONF codec is `best_effort` in both the ClassVar and the proposed header; `certified` was not mistakenly written there.

The ordinal renumbering (`first → 1st`, `second → 2nd`, `third → 3rd`) is cosmetic and has no semantic impact on the test suite.

---

## 7. Self-assessment

**Confidence: high.**

- All 8 `codec.py` files were read and the `certainty` ClassVar was extracted directly; no inference.
- The test file `test_codec_header_certainty.py` was read in full; the regex (`Certainty:\s*`*([a-z_]+)`*`) matches both backtick and plain forms — all proposed `Certainty:` lines use the backtick form consistent with the existing passing headers.
- The `cisco_iosxe` NETCONF codec is confirmed `best_effort` — this is the critical guard mentioned in the task spec. The new header retains `best_effort` verbatim.
- No codec was assigned a value that contradicts its ClassVar.

**Blockers:** None.
