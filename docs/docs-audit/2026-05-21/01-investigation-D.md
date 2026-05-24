# Cluster D — Codec docstrings + file headers

## Summary

Audited 8 production codecs + 1 NETCONF stub + shared infrastructure
(`base.py`, `__init__.py`, `registry.py`, `_input_shape.py`) under
`netcanon/migration/codecs/`.  Total **42 findings** across 31 .py
files: **3 WRONG**, **0 MISSING**, **30 INCOMPLETE**, **9 STYLE**.

The dominant pattern is **scope-staleness in package-level
`__init__.py` module docstrings**: every codec (except
`cisco_iosxe_cli` / `juniper_junos`) ships a "Scope (Phase 1)" or
"Scope (Tier 1)" enumeration that lags substantially behind the
`_CAPS` matrix as Tier 2 + Wave A / B / C surfaces have landed.
Per-file `parse.py` / `render.py` docstrings are generally more
accurate.  Several `parse.py` modules also list "Internal helpers"
lists that have drifted as new helpers were added.

`base.py` + `registry.py` + `_input_shape.py` + the codec base
class itself have **clean and accurate** docstrings.  Both v0.1.2
defusedxml swap landing sites (`opnsense/parse.py`,
`cisco_iosxe/codec.py`) have **accurate** safe-import explanatory
comments — no drift there.

No pipeline-stage-signature drift surfaced (codecs are
NOT under `migration_pipeline.py`'s frozen-signature umbrella).

---

## Per-codec audit

### arista_eos

**Module docstring shape:** `__init__.py` enumerates Tier 1+2
grammar but does NOT mention Wave B (VRRP) or Wave C (VARP /
anycast-gateway) wire-up that landed in v0.1.1; the supported list
at codec.py:134-139 includes both.  parse.py / render.py docstrings
do mention these.  `codec.py` module docstring is accurate.

**"Public surface" list accuracy:** codec.py docstring at lines 7-17
accurately lists the four sibling modules.  No public-surface
enumeration in parse.py / render.py beyond `parse_intent` /
`render_intent`.

**Function-level audit:** 5 module-level public functions in
parse.py (`parse_intent`, plus 4 private helpers) + 3 in render.py
+ 2 in port_names.py.  `parse_intent` docstring is a 1-liner, no
Args/Returns/Raises sections.  Internal-helpers list in parse.py
docstring (lines 29-32) is INCOMPLETE — actual file also has
`_vrrp_group_for`, `_parse_dhcp_pools`, `_mask_to_prefix`.

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| D-AR-1 | `netcanon/migration/codecs/arista_eos/__init__.py:26-41` | INCOMPLETE | "Supported blocks (Tier 1 + Tier 2)" enumeration omits VRRP groups (Wave B) and VARP anycast-gateway (Wave C) that are now in `_CAPS.supported`.  Tier-2 surfaces actually wired (LAG `Port-Channel`, DHCP pools, RADIUS servers, local users, IPv6/SLAAC, tunnel-type discriminator, VRF instances, VXLAN VNIs) are also missing from the enumeration. | Add "Wave B: classic VRRP groups (multi-line form)" + "Wave C: VARP anycast-gateway (per-IP virtual + system-wide MAC)" + expand the Tier 2 bullet list to match `_CAPS.supported`. |
| D-AR-2 | `netcanon/migration/codecs/arista_eos/parse.py:29-32` | INCOMPLETE | "Internal helpers" list claims `_parse_stanzas, _parse_router_bgp, _apply_iface_subcommand, _infer_iface_type, _expand_vlan_list` but actual module also contains `_vrrp_group_for` (175), `_parse_dhcp_pools` (244), `_mask_to_prefix` (324). | Add `_vrrp_group_for`, `_parse_dhcp_pools`, `_mask_to_prefix` to the list, or convert the enumeration to a pointer (e.g. "see the module body for the dispatch helpers"). |
| D-AR-3 | `netcanon/migration/codecs/arista_eos/parse.py:351-352` | INCOMPLETE | `parse_intent` public docstring is a single-line `"""Parse Arista EOS ``show running-config`` text into a canonical tree."""` — no Args / Returns / Raises sections despite `ParseError` being raised for empty / XML / JSON input.  AGENTS.md doc-sync row "A function gains a new parameter or changes return shape" requires Google-style sections on public functions. | Add `Args: raw: ...`, `Returns: ...`, `Raises: ParseError: ...` sections matching the cisco_iosxe_cli `parse_intent` pattern (parse.py:445-450). |
| D-AR-4 | `netcanon/migration/codecs/arista_eos/render.py:148-149` | INCOMPLETE | `render_intent` public docstring is single-line `"""Render a :class:`CanonicalIntent` as Arista EOS CLI text."""` — no Args / Returns / Raises section despite `RenderError` being raised when `tree` isn't a `CanonicalIntent`. | Add Args / Returns / Raises sections; mirror cisco_iosxe_cli's render.py:62-68. |
| D-AR-5 | `netcanon/migration/codecs/arista_eos/__init__.py:36-41` | STYLE | "Silently ignored (Tier 3 — parse-tolerant)" lists ACLs as "router bgp / router ospf — neighbour tables..." but `_CAPS.unsupported` separately lists ACL (extended / standard / ipv6).  The init module mentions ACLs nowhere despite their explicit declaration in `_CAPS`. | Add an ACL bullet under "Silently ignored" or under a new "Unsupported by canonical scope" section. |

### aruba_aoss

**Module docstring shape:** `__init__.py` declares "Current scope
(Tier 1)" listing hostname / VLANs / interfaces / static routes /
SNMP-community / NTP.  Reality includes Tier 2 surfaces (DNS,
syslog, SNMP location/contact/trap-host/v3, local users, RADIUS
servers, LAG trunks, IPv6 addresses with link-local scope) + Wave
B VRRP groups, all listed in `_CAPS.supported`.  Heavy drift.
Also lists "RADIUS" under "Out of scope (future)" at line 41 —
that's WRONG, RADIUS is parsed + rendered (see
`aruba_aoss/parse.py::CanonicalRADIUSServer` at line 54 +
`_apply_user_radius` codepath).

**"Public surface" list accuracy:** codec.py docstring lines 21-25
mentions re-exports (`_format_port_list`, `_parse_port_list`)
matching `__all__` at codec.py:50-54.

**Function-level audit:** parse.py has 13 module-level functions,
render.py has 9.  `_svi_absorption.py` is a documentation-only
constant module — well-documented (no public functions).
Internal_svi_absorption module mentions paths "codec.py — see
:meth:`ArubaAOSSCodec.format_port_identity`" but post-split, the
absorption logic for codepath 3 lives in `port_names.py`
(line 186-187, `if identity.kind == "svi": return None`) — the
codec.py method is a delegator.

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| D-AA-1 | `netcanon/migration/codecs/aruba_aoss/__init__.py:19-27` | INCOMPLETE | "Current scope (Tier 1)" omits Tier 2 wire-throughs in `_CAPS.supported`: DNS, syslog, SNMP location/contact/trap-host/v3, local users, RADIUS servers, LAG trunks, IPv6 addresses, Wave-B VRRP groups. | Rename to "Current scope (Tier 1 + Tier 2)" and add the missing bullets, or convert to a pointer (`"see _CAPS.supported in codec.py"`). |
| D-AA-2 | `netcanon/migration/codecs/aruba_aoss/__init__.py:41` | WRONG | "Out of scope (future)" lists "RADIUS" but parse.py imports `CanonicalRADIUSServer` (line 54) and `_apply_user_radius` populates `intent.radius_servers` from `radius-server host` lines (parse.py:949 onward).  Render.py emits the corresponding stanzas. | Remove the RADIUS line from "Out of scope (future)" and add it under "Current scope (Tier 2)". |
| D-AA-3 | `netcanon/migration/codecs/aruba_aoss/_svi_absorption.py:53-58` | INCOMPLETE | Codepath 3 docstring says "see :meth:`ArubaAOSSCodec.format_port_identity`, the `identity.kind == "svi"` branch" but post-split the actual SVI-absorption logic lives at `port_names.py:186-187` (`if identity.kind == "svi": return None`).  The `ArubaAOSSCodec.format_port_identity` method (codec.py:298) is a one-line delegator to `_port_names.format_port_identity`. | Update the path reference: "see `port_names.py::format_port_identity`, the `identity.kind == "svi"` branch (the codec's `format_port_identity` method is a delegator)." |
| D-AA-4 | `netcanon/migration/codecs/aruba_aoss/parse.py:759-761` | INCOMPLETE | `parse_intent` docstring is 2-liner with no Args / Returns / Raises sections despite raising `ParseError` for empty input + XML/JSON shape mismatches. | Add Args / Returns / Raises sections. |
| D-AA-5 | `netcanon/migration/codecs/aruba_aoss/render.py:365-368` | INCOMPLETE | `render_intent` docstring describes emission order but lacks Args / Returns / Raises sections. | Add the missing sections. |

### cisco_iosxe (NETCONF Phase-0.5 stub)

**Module docstring shape:** `__init__.py` claims "Phase 0.5" scope
listing only `openconfig-if-ip: IPv4 address + prefix-length on
subinterfaces`.  Reality also wires IPv6 addresses (GAP-EVPN-3 —
codec.py:218-219 supported + codec.py:694-703 render path).
codec.py module docstring is also "Phase 0.5 stub" — accurate
that render coverage is narrow but stale on the IPv6 expansion.

**"Public surface" list accuracy:** No explicit public-surface
list (NETCONF stub keeps everything in `codec.py`).  Module-level
helpers `_q, _strip_ns, _find_interfaces, _parse_interface,
_parse_config, _parse_subinterface, _parse_ipv4, _parse_ipv6,
_first_child_by_tag, _render_interface, _render_subinterface,
_render_ipv4, _iface_dict_to_canonical, _synthesize_vlans_from_svis,
_walk` exist — none enumerated in any docstring (acceptable for
private helpers).

**Function-level audit:** Public methods well-docstrung
(`parse`, `render`, `iter_xpaths`, `probe`).  `_render_canonical`
has 1-line docstring with no Args/Returns description.
defusedxml import comment block (codec.py:90-99) is **accurate**
and matches the actual import + try/except wiring.

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| D-CN-1 | `netcanon/migration/codecs/cisco_iosxe/__init__.py:9-11` | INCOMPLETE | "Scope (Phase 0.5)" lists only `openconfig-if-ip: IPv4 address + prefix-length on subinterfaces` but the codec also supports IPv6 (`/interfaces/interface/ipv6/address/ip` + `/prefix-length` at codec.py:218-219; render path at codec.py:694-703).  GAP-EVPN-3 expansion is not reflected. | Add IPv6 bullet under "Scope (Phase 0.5)": `"openconfig-if-ip: IPv6 address + prefix-length on subinterfaces (GAP-EVPN-3)"`. |
| D-CN-2 | `netcanon/migration/codecs/cisco_iosxe/codec.py:624` | INCOMPLETE | `render(self, tree: dict[str, Any]) -> str:` type signature says `dict` only but body accepts `CanonicalIntent` too (line 640-641 `if isinstance(tree, CanonicalIntent)`).  Docstring at lines 625-636 only describes the dict path; doesn't mention CanonicalIntent input. | Update signature to `tree: dict[str, Any] | CanonicalIntent` (or `tree: Any`) and add a paragraph documenting that both shapes are accepted. |
| D-CN-3 | `netcanon/migration/codecs/cisco_iosxe/codec.py:666-667` | INCOMPLETE | `_render_canonical` has only a 1-line docstring; the function emits both IPv4 and IPv6 subinterface XML but doesn't document either or call out the namespace mapping. | Add a paragraph explaining the openconfig-interfaces + openconfig-if-ip namespace handling + IPv4/IPv6 coverage. |
| D-CN-4 | `netcanon/migration/codecs/cisco_iosxe/codec.py:1029-1030` | INCOMPLETE | `_first_child_by_tag` is the lowest-level helper; one-liner docstring describes purpose but not the parameters/return.  Acceptable as a private helper but contributors reading the bottom of the file may want more detail. | Optional: expand to Args / Returns. |
| D-CN-5 | `netcanon/migration/codecs/cisco_iosxe/codec.py:1113-1117` | INCOMPLETE | `_LIST_WRAPPERS` declares `{interfaces, subinterfaces, addresses}` but doesn't mention that the same wrapper is used for both IPv4 and IPv6 address lists (the dispatch in `_walk` at 1232-1239 ignores parent namespace).  Mostly self-explanatory but contributors adding new IPv6 walking may miss it. | Add a brief comment noting the shared `addresses` wrapper covers v4 + v6. |

### cisco_iosxe_cli

**Module docstring shape:** `__init__.py` is **minimal but
accurate** (5 lines, points to `codec.py`).  `codec.py` module
docstring at lines 1-47 enumerates module layout, parser strategy,
limitations.  Best-quality codec docstring in the corpus.  But:
Limitations bullet at line 44-46 says "secondary IP addresses are
ignored on parse (first address only)" — STALE.  Parse.py
explicitly handles secondaries (parse.py:782-792, comment
"IOS-XE accepts one primary + multiple secondary addresses per
interface ... The render-side companion in `:mod:.render` emits
the secondary keyword for index>=1").

**"Public surface" list accuracy:** codec.py docstring at lines
8-23 accurately lists the four sibling modules + the rationale for
keeping `_walk_canonical` at module level.  Symbol survives the
split (referenced at code.py:505 + cross-imported by other
codecs).

**Function-level audit:** parse.py has 20 public/private functions
+ entry `parse_intent`.  Render.py has 6.  parse.py "Internal
helpers" list (parse.py:30-37) **does not include**
`_parse_routing_instances` (line 626), `_parse_globals` (line 591),
`_dispatch_vrrp_line` (line 948), `_build_canonical_interface`
(line 1046), `_parse_vlan_list` (line 1119), `_normalise_mac_to_colon_hex`
(line 194), `_infer_type` (line 234), `_is_link_local_v6` (line 243),
`_is_mgmt_vrf` (line 432), `_lag_sort_key` (line 1293).

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| D-IC-1 | `netcanon/migration/codecs/cisco_iosxe_cli/codec.py:44-46` | WRONG | Limitations bullet "`secondary` IP addresses are ignored on parse (first address only)" contradicts current behaviour — parse.py:778-792 explicitly handles secondary IP addresses (multiple entries appended to `current["ipv4"]`); render.py emits the `secondary` keyword for index>=1.  Code comment at parse.py:782-789 calls this out directly. | Remove the bullet entirely, or rewrite as "Secondary IPv4 addresses round-trip via the per-interface `ipv4_addresses` list ordering (primary at index 0; render emits `secondary` keyword from index 1)." |
| D-IC-2 | `netcanon/migration/codecs/cisco_iosxe_cli/parse.py:30-37` | INCOMPLETE | "Internal helpers" enumeration omits ≥9 functions that exist in the file (`_parse_routing_instances`, `_parse_globals`, `_dispatch_vrrp_line`, `_build_canonical_interface`, `_parse_vlan_list`, `_normalise_mac_to_colon_hex`, `_infer_type`, `_is_link_local_v6`, `_is_mgmt_vrf`, `_lag_sort_key`). | Either expand the enumeration to match the actual public surface, or convert to a one-line pointer ("see `_parse_*` family in the module body"). |
| D-IC-3 | `netcanon/migration/codecs/cisco_iosxe_cli/codec.py:1-3` | STYLE | The codec.py module title line says `"CiscoIOSXECLICodec — bidirectional codec ..."` — but the sibling juniper_junos / arista_eos codec.py titles use shorter form `"JunosCodec — 7th shipped vendor"` / `"AristaEOSCodec — 6th shipped codec"`.  Cross-codec stylistic drift. | Optional: align to the shorter form for consistency. |

### fortigate_cli

**Module docstring shape:** `__init__.py` lists supported blocks
(Tier 1 + Tier 2 — system global, dns, ntp, interface, router
static, snmp sysinfo/community, system admin, user radius, system
dhcp server).  Wave-B VRRP wire-up landed in `_CAPS.supported`
(line 144-154) but `__init__.py` doesn't mention VRRP.

**"Public surface" list accuracy:** codec.py docstring at lines 6-25
accurately lists sibling modules + re-exported test-import symbols
(`_parse_blocks`, `_prefix_to_mask`, `_mask_to_prefix`); these
match `__all__` at lines 53-58.

**Function-level audit:** parse.py has 16 public/private functions
+ entry.  render.py has 6.  vlan_heuristics.py has 4 public
functions with good Args/Returns docs.  parse.py docstring at lines
22-32 lists "internal block model" symbols accurately.  `parse_intent`
docstring is brief but mentions `ParseError`.

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| D-FG-1 | `netcanon/migration/codecs/fortigate_cli/__init__.py:10-24` | INCOMPLETE | "Supported blocks (Tier 1 + Tier 2)" omits the Wave-B VRRP groups now in `_CAPS.supported` at codec.py:144-154.  IPv6 (GAP-EVPN-3) on physical/VLAN interfaces is also not mentioned despite being supported. | Add bullets for "Wave B: VRRP groups (nested `config vrrp / edit N`)" and IPv6 addresses + dhcp-client-v6. |
| D-FG-2 | `netcanon/migration/codecs/fortigate_cli/parse.py:881-885` | INCOMPLETE | `parse_intent` docstring describes raising `ParseError` but lacks Args / Returns sections. | Add Args / Returns sections matching the cisco_iosxe_cli convention. |
| D-FG-3 | `netcanon/migration/codecs/fortigate_cli/render.py:413-415` | INCOMPLETE | `render_intent` docstring is 2-liner mentioning `RenderError`; missing Args / Returns. | Add Args / Returns. |
| D-FG-4 | `netcanon/migration/codecs/fortigate_cli/vlan_heuristics.py:54-71` | STYLE | `looks_like_vlan_iface` docstring mentions a related helper `_looks_like_vlan_from_settings` at "the parser call site" but that name appears nowhere in the codebase under that exact spelling (the call site is `_apply_system_interface` in parse.py).  Mild documentation pointer drift. | Either rename the in-comment reference to match the real call-site function name or remove the forward-reference. |

### juniper_junos

**Module docstring shape:** `__init__.py` at lines 1-77 enumerates
extensive scope (set-form + block-form, Tier 1+2 grammar, apply-
groups, EVPN Type-5, routing-instances, SNMPv3 USM+VACM), module
layout, strategic value.  High-quality reference docstring.  But:
codec.py `description` ClassVar at line 85-91 says "Block-form
(hierarchical curly-brace) input is NOT parsed in v1; run `|
display set` on your Junos device to produce compatible input" —
**WRONG**.  Block-form IS auto-detected and converted to set-form
(see codec.py module docstring at line 36-39, and
`parse._looks_like_blockform` / `_blockform_to_setform` at
parse.py:831 / 922).

**"Public surface" list accuracy:** codec.py module docstring at
lines 7-24 accurately lists sibling modules.  parse.py module
docstring at lines 38-46 lists internal helpers; render.py module
docstring at lines 59-62 lists render-only helpers.

**Function-level audit:** parse.py has 26 module-level functions
(largest in codec corpus, with 25 internal helpers).  render.py
has 7.  parse.py "Internal helpers" list (parse.py:38-46) is
INCOMPLETE — actual file also has `_apply_access` (1809),
`_apply_system_services_dhcp` (1891), `_apply_vrrp_group_sub`
(2268), `_materialise_vrrp_group` (2384), `_infer_tunnel_type`
(2423).

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| D-JU-1 | `netcanon/migration/codecs/juniper_junos/codec.py:85-91` | WRONG | `description` ClassVar (operator-facing on the migrate UI) claims "Block-form (hierarchical curly-brace) input is NOT parsed in v1; run `\| display set` on your Junos device to produce compatible input."  This contradicts current behaviour: block-form is auto-detected (`parse._looks_like_blockform`) and converted to set-form (`parse._blockform_to_setform`) ahead of the normal dispatcher.  The package `__init__.py` at lines 8-12 and codec.py module docstring at lines 36-39 both correctly document the auto-detection. | Rewrite `description` to: "Paste Junos `set`-form configuration text — the output of `show configuration \| display set`.  Block-form (hierarchical curly-brace `\{ ... ; \}`) input is also accepted — the codec auto-detects and converts to set-form before parsing." |
| D-JU-2 | `netcanon/migration/codecs/juniper_junos/parse.py:38-46` | INCOMPLETE | "Internal helpers" enumeration omits 5 helpers present in the file: `_apply_access` (1809), `_apply_system_services_dhcp` (1891), `_apply_vrrp_group_sub` (2268), `_materialise_vrrp_group` (2384), `_infer_tunnel_type` (2423).  All are part of the Wave B (VRRP) / DHCP / access-grammar wire-ups. | Either add the 5 missing helpers to the enumeration or rephrase to a one-line pointer ("see the `_apply_*` family in the module body for the dispatch surface"). |
| D-JU-3 | `netcanon/migration/codecs/juniper_junos/parse.py:77-78` | INCOMPLETE | `parse_intent` docstring is one-liner.  No Args / Returns / Raises sections despite raising `ParseError` for XML / unknown shape. | Add Args / Returns / Raises. |
| D-JU-4 | `netcanon/migration/codecs/juniper_junos/__init__.py:20` | STYLE | "Supported grammar (Tier 1 + Tier 2):" list at lines 20-54 is detailed and accurate, but does not call out which features landed in which Wave (e.g. VRRP-group nested-under-address grammar in Wave B, virtual-gateway-address in Wave C).  Other codecs (mikrotik_routeros, opnsense, fortigate_cli) explicitly stamp `Wave B` / `Wave C` on the relevant features in their inline comments. | Optional: add `(Wave B)` / `(Wave C)` annotations on the corresponding bullets for cross-codec consistency. |

### mikrotik_routeros

**Module docstring shape:** `__init__.py` at lines 12-25 has
"Scope (current)" listing hostname, ethernet, VLAN, IPv4, static
routes, DNS/NTP — a 6-bullet list.  Reality has substantial Tier 2
+ Wave-B additions in `_CAPS.supported` (SNMP v1/v2c+v3, local
users, RADIUS, DHCP servers, bridge, bonding, tunnels, IPv6 + Wave
B VRRP).  Scope claim significantly understates reality.  Also
declares `certainty: certified` (codec.py:100) but
`__init__.py:37` says "`best_effort` — validated against synthetic
fixtures; not yet tested against a real device capture" — WRONG /
STALE (the codec was promoted to certified, but the __init__
comment didn't update).

**"Public surface" list accuracy:** codec.py module docstring at
lines 5-19 accurately lists sibling modules.  parse.py docstring
notes the parse-to-render directional edge for `_is_ethernet_name`
etc. (lines 27-30).

**Function-level audit:** parse.py has 25 module-level functions.
render.py has 11.  port_names.py has 4 public functions.  Some
docstrings present, but coverage is patchy on Args / Returns.

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| D-MT-1 | `netcanon/migration/codecs/mikrotik_routeros/__init__.py:36-39` | WRONG | "Certainty: `best_effort` — validated against synthetic fixtures; not yet tested against a real device capture (RouterOS emits a lot of default-value boilerplate via `verbose` that we filter out)."  But codec.py:100 declares `certainty: ClassVar[str] = "certified"`.  The codec has been promoted (see real-capture coverage in `tests/fixtures/real/mikrotik_routeros/`) but the __init__ note didn't get the update. | Update to "Certainty: `certified` — round-trip stable across ≥3 real captures (see `tests/fixtures/real/RESULTS.md`)." |
| D-MT-2 | `netcanon/migration/codecs/mikrotik_routeros/__init__.py:12-19` | INCOMPLETE | "Scope (current)" omits the substantial Tier 2 + Wave-B wire-ups now in `_CAPS.supported`: SNMP (community / location / contact / trap-host / v3-user), local users, RADIUS servers, DHCP server pools, IPv6 addresses, tunnel-type, bridge / bonding / tunnel interface families, Wave-B VRRP groups (`/interface vrrp`). | Expand "Scope (current)" to include the Tier 2 + Wave-B surfaces, or rewrite as a pointer to `_CAPS.supported`. |
| D-MT-3 | `netcanon/migration/codecs/mikrotik_routeros/__init__.py:20-25` | INCOMPLETE | "Out of scope (future)" lists "Wireless, CAPsMAN, MPLS, routing protocols" — but the codec is also missing VXLAN, anycast-gateway, per-VRF static-routes (the `_CAPS.unsupported` entries at codec.py:191-256).  Not strictly wrong, but partial. | Add VXLAN / anycast / per-VRF static routes to the "Out of scope" list, or note that the full list lives in `_CAPS.unsupported`. |
| D-MT-4 | `netcanon/migration/codecs/mikrotik_routeros/parse.py:65-72` | INCOMPLETE | `parse_intent` docstring mentions `ParseError` but lacks Args / Returns sections. | Add Args / Returns. |
| D-MT-5 | `netcanon/migration/codecs/mikrotik_routeros/render.py:100-104` | INCOMPLETE | `render_intent` docstring mentions `RenderError` raise but lacks Args / Returns. | Add Args / Returns. |

### opnsense

**Module docstring shape:** `__init__.py` at lines 1-34 declares
"Phase 1" scope listing only "Hostname / system section, Interface
list, LAN/WAN zone membership."  Reality includes DHCP server
pools, VLANs, SNMP, LAGs, local users, RADIUS servers, IPv6
addresses, Wave-B CARP groups, and more — all listed in
`_CAPS.supported`.  "Deliberately NOT in scope (Phase 2+)" lists
firewall / NAT / FRR — these are still genuinely Tier 3.

**"Public surface" list accuracy:** codec.py docstring at lines
6-26 accurately lists sibling modules + re-exported test-import
helpers (`_trim_xml_envelope`, `_trim_xml_prologue`).  `__all__`
matches.  defusedxml import comment (parse.py:71-78) is **accurate**
and matches the actual import wiring.

**Function-level audit:** codec.py has the module-level `_walk`
helper for legacy dict-tree paths — acceptable; parse.py has 7
public/private functions; render.py has 11.  parse.py
docstring at lines 10-32 enumerates the public surface accurately
and calls out the Wave-B CARP-group wire-up details.

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| D-OP-1 | `netcanon/migration/codecs/opnsense/__init__.py:15-19` | INCOMPLETE | "Scope (Phase 1)" lists only hostname/interfaces/zones but `_CAPS.supported` at codec.py:132-166 now includes domain, DNS, NTP, IPv6 addresses + dhcp-client-v6, VLANs, SNMP (community/location/contact/trap-host), local users, Wave-B CARP groups.  "Phase 1" framing is stale. | Either rename "Phase 1" → "Tier 1 + Tier 2 + Wave-B" and expand the bullet list to match `_CAPS.supported`, or rewrite as a one-line pointer ("see `_CAPS.supported` in codec.py"). |
| D-OP-2 | `netcanon/migration/codecs/opnsense/codec.py:328-337` | STYLE | `classify_port_name` and `format_port_identity` are the ONLY codec methods with non-trivial docstrings explaining the delegation (the analogous methods on every other codec are bare delegators with no docstring).  Inconsistent across codecs. | Optional: either propagate the explanation to every other codec's port-name delegator methods, or drop the OPNsense ones to match the prevailing minimal style.  (Recommend propagate — the docstring is useful.) |
| D-OP-3 | `netcanon/migration/codecs/opnsense/parse.py:162-176` | INCOMPLETE | `parse_intent` docstring is good (covers envelope-trim + ParseError) but lacks an explicit Args / Returns section.  Mixed-style relative to cisco_iosxe_cli which DOES use Google-style sections. | Add `Args:` + `Returns:` sections explicitly. |
| D-OP-4 | `netcanon/migration/codecs/opnsense/render.py:55-66` | INCOMPLETE | `render_intent` docstring describes accepted shapes (`CanonicalIntent` + legacy dict) but lacks explicit Args / Returns / Raises sections. | Add the missing sections. |

---

## Cross-cutting observations

### Pattern 1: `__init__.py` "Scope" enumerations are systematically stale

Six of the eight codec packages
(`arista_eos`, `aruba_aoss`, `cisco_iosxe`, `fortigate_cli`,
`mikrotik_routeros`, `opnsense`) declare a "Scope (Phase 1)" /
"Scope (Tier 1)" / "Scope (Phase 0.5)" / "Supported blocks (Tier
1 + Tier 2)" enumeration in their package-level `__init__.py`
docstring.  In every case, the enumeration lags behind the actual
`_CAPS.supported` declared in `codec.py` by 1-3 Tiers / Waves
worth of wire-throughs.  This is the single most common drift
pattern in the cluster.

Recommended Stage-2 fix shape: rather than maintain two parallel
enumerations (one in prose, one in `_CAPS.supported`), convert the
init docstring to a one-line pointer: `"See _CAPS.supported in
codec.py for the canonical scope list."`  This matches the
prevailing AGENTS.md rule
("Exhaustive inventories that enumerate every file become a
maintenance tax — prefer one-line pointers unless the enumeration
carries load-bearing explanation").  The same `__init__.py` can
keep the "Structural quirks handled" / "Out of scope" sections —
those convey orientation, not inventory.

The well-curated counterexample is `cisco_iosxe_cli/__init__.py`,
which is 28 lines, doesn't enumerate `_CAPS`, and just points to
`codec.py`.  Use that as the template.

### Pattern 2: "Internal helpers" enumerations in parse.py drift as helpers land

`arista_eos/parse.py:29-32`, `cisco_iosxe_cli/parse.py:30-37`,
and `juniper_junos/parse.py:38-46` all list "Internal helpers"
inline in the module docstring.  All three lists are now
INCOMPLETE — new helpers have been added over time (typically as
part of Wave-B/C wire-ups) without docstring updates.  Same
remediation as pattern 1 applies: convert to a pointer, or keep the
enumeration but cite it as a sample rather than exhaustive list.

### Pattern 3: `parse_intent` / `render_intent` Google-style sections are absent on most codecs

Per AGENTS.md doc-sync row "A function gains a new parameter or
changes return shape | Its docstring (Google-style sections for
Args / Returns / Raises)" — these are *public* entry functions, so
the row applies.  Coverage:

| Codec | parse_intent Args/Returns/Raises | render_intent Args/Returns/Raises |
|---|---|---|
| arista_eos | none | none |
| aruba_aoss | none | none |
| cisco_iosxe_cli | Raises only | none |
| fortigate_cli | Raises only (prose) | Raises only (prose) |
| juniper_junos | none | partial (no Args; Returns implicit) |
| mikrotik_routeros | Raises only | Raises only |
| opnsense | none (Raises in prose) | none |

Only `cisco_iosxe_cli/parse.py:444-450` is close to the AGENTS.md
template.  Recommended Stage 2: pick that pattern, propagate to
all 7 codecs in one mechanical pass.

### Pattern 4: Wave annotations are inconsistent

Wave annotations (`Wave A`, `Wave B`, `Wave C`) for v0.2.0 work
appear in:

* `_CAPS.supported` / `_CAPS.lossy` / `_CAPS.unsupported` inline
  comments in every codec.py: **consistently present**.
* `parse.py` module docstrings for some codecs (junos, aruba,
  fortigate, mikrotik, opnsense) — present.  For others (arista,
  cisco_iosxe_cli): inconsistent.
* `__init__.py` package docstrings: **mostly absent**.  Only the
  `_CAPS` declarations and some `parse.py` modules reflect the
  Wave-B/C wire-ups.

Stage 2 could either (a) propagate Wave annotations to every
__init__.py in scope lists, or (b) drop the explicit Wave naming
from prose (keep only in `_CAPS` declarations).  Either is
self-consistent; the current half-and-half state is the drift.

### Pattern 5: Codec class-method docstrings absent on `parse` / `render`

Every codec's `parse(self, raw)` and `render(self, tree)` methods
(`AristaEOSCodec.parse`, `ArubaAOSSCodec.parse`,
`FortiGateCLICodec.parse`, etc.) lack docstrings — they inherit
from the abstract `CodecBase.parse` / `CodecBase.render` whose
docstrings are accurate.  This is acceptable Python style for
trivial overrides, but the cisco_iosxe NETCONF stub `parse()` DOES
have its own docstring (codec.py:532-549) — inconsistent across
codecs.

Stage 2 could standardise — either remove the NETCONF stub
override docstrings, or add docstrings to every codec's
`parse`/`render` delegators noting where the work actually happens
("Delegates to `parse_intent` in `:mod:.parse`").  Recommendation:
keep delegators bare; the codec.py module docstring already calls
out the delegation pattern.

### Pattern 6: defusedxml safe-import comments are correct (v0.1.2 work)

The two affected codecs (`opnsense/parse.py:71-80` and
`cisco_iosxe/codec.py:90-101`) have **accurate** explanatory
comments matching the actual import + try/except wiring.  Both
reference `docs/security-triage/2026-05-21/01-investigation-A.md`
alerts #14/#15.  Both comments cite that stdlib `ET.fromstring`
expands internal entities by default on Python 3.14.4.  Both
explain why generation-side ET use stays on stdlib.  No drift.

### Pattern 7: Sibling-module layout consistency is high

Every CLI/XML codec follows the post-split convention:
`__init__.py`, `codec.py`, `parse.py`, `render.py`, `port_names.py`.
Outliers:

* `aruba_aoss/` has an extra `_svi_absorption.py` (well-documented
  as a documentation-only single-constant module — see its 100-line
  docstring at `_svi_absorption.py:1-98`).
* `fortigate_cli/` has an extra `vlan_heuristics.py` (well-documented
  at `vlan_heuristics.py:1-31` for why it lives there).
* `cisco_iosxe/` (NETCONF stub) has only `__init__.py` + `codec.py`
  — codec.py module docstring + README explain why
  (XML-tree traversal differs enough from CLI-text codecs that the
  split offered no clarity win).

This layout regularity is a strength; the codec-corpus shape is
consistent enough that a contributor who learns one codec can read
any other.

### Pattern 8: Cross-references to v0.2.0-planning docs all resolve

`_CAPS.unsupported` entries in every codec cite
`docs/v0.2.0-planning/01-vrrp-canonical/` and
`docs/v0.2.0-planning/02-anycast-gateway/`.  Both paths exist with
the expected child files (01-canonical-model.md through
06-fixture-targets.md plus README.md and IMPLEMENTED.md).  No
broken cross-refs.

### Pipeline-stage signature compliance

The codec base class `CodecBase.parse(raw)` and
`CodecBase.render(tree)` are de-facto contracts but live in
`netcanon/migration/codecs/base.py`, NOT in
`netcanon/services/migration_pipeline.py`.  Therefore the AGENTS.md
"Pipeline-stage signature changes — DON'T (frozen)" hard rule does
NOT apply to anything in this cluster.  **No frozen-signature
docstring drift identified.**

(Cross-check: the only `migration_pipeline.py` reference in this
cluster's surface is its docstring, which the codecs do not modify.
Stage 2 fixes can touch any docstring in any codec file without
risk of breaking the pipeline-stage signature invariant.)

---

## Files audited

```
netcanon/migration/codecs/
├── README.md                                  (out-of-scope for D; cited only)
├── __init__.py                                (clean — minimal, accurate)
├── _input_shape.py                            (clean — well-documented)
├── base.py                                    (clean — accurate)
├── registry.py                                (clean — accurate)
├── arista_eos/
│   ├── __init__.py                            (D-AR-1, D-AR-5)
│   ├── codec.py                               (clean)
│   ├── parse.py                               (D-AR-2, D-AR-3)
│   ├── port_names.py                          (clean)
│   └── render.py                              (D-AR-4)
├── aruba_aoss/
│   ├── __init__.py                            (D-AA-1, D-AA-2)
│   ├── codec.py                               (clean)
│   ├── parse.py                               (D-AA-4)
│   ├── port_names.py                          (clean)
│   ├── render.py                              (D-AA-5)
│   └── _svi_absorption.py                     (D-AA-3)
├── cisco_iosxe/  (NETCONF Phase-0.5 stub)
│   ├── __init__.py                            (D-CN-1)
│   └── codec.py                               (D-CN-2, D-CN-3, D-CN-4, D-CN-5)
├── cisco_iosxe_cli/
│   ├── __init__.py                            (clean — reference template)
│   ├── codec.py                               (D-IC-1, D-IC-3)
│   ├── parse.py                               (D-IC-2)
│   ├── port_names.py                          (clean)
│   └── render.py                              (clean)
├── fortigate_cli/
│   ├── __init__.py                            (D-FG-1)
│   ├── codec.py                               (clean)
│   ├── parse.py                               (D-FG-2)
│   ├── port_names.py                          (clean)
│   ├── render.py                              (D-FG-3)
│   └── vlan_heuristics.py                     (D-FG-4)
├── juniper_junos/
│   ├── __init__.py                            (D-JU-4)
│   ├── codec.py                               (D-JU-1)
│   ├── parse.py                               (D-JU-2, D-JU-3)
│   ├── port_names.py                          (clean)
│   └── render.py                              (clean)
├── mikrotik_routeros/
│   ├── __init__.py                            (D-MT-1, D-MT-2, D-MT-3)
│   ├── codec.py                               (clean)
│   ├── parse.py                               (D-MT-4)
│   ├── port_names.py                          (clean)
│   └── render.py                              (D-MT-5)
├── opnsense/
│   ├── __init__.py                            (D-OP-1)
│   ├── codec.py                               (D-OP-2)
│   ├── parse.py                               (D-OP-3)
│   ├── port_names.py                          (clean)
│   └── render.py                              (D-OP-4)
└── _mock/                                     (out of scope per cluster D brief)
```

Total: **42 findings** across **8 codecs** (3 WRONG, 30 INCOMPLETE,
9 STYLE, 0 MISSING).

## See also

* [`README.md`](../README.md) — audit process + cluster taxonomy
* [`00-snapshot.md`](00-snapshot.md) — broader-run context
* [`cluster-D-codec-docstrings-scope.md`](cluster-D-codec-docstrings-scope.md) — methodology this report follows
* `netcanon/migration/codecs/README.md` — codec-writing cookbook (cited but not audited here)
* `AGENTS.md` § "Documentation Sync Checklist" — doc-sync rows that frame the finding criteria
