# Phase 4b — opnsense source CODEC_BUG findings

Investigation of every cell in `tests/fixtures/real/_phase4_runs/latest.json`
where `source_codec == "opnsense"` and at least one
`field_variances[*].variance == "CODEC_BUG"`.

## Scope and totals

48 cells (8 targets x 6 fixtures, including the no-op intra-vendor target).
Per-target CODEC_BUG totals (matches PHASE4_RECONCILIATION.md row "opnsense"):

| Target | Fixtures | CODEC_BUG fields | Notes |
|---|---:|---:|---|
| arista_eos | 6 | 5 | All on `kitchen_sink.xml` |
| aruba_aoss | 6 | 19 | Interface drift on every fixture except `core_default`; one radius row |
| cisco_iosxe | 6 | 0 | clean |
| cisco_iosxe_cli | 6 | 5 | `domain` only, every non-default fixture |
| fortigate_cli | 6 | 11 | `domain` (5) + interface count drift on `kitchen_sink` + vlan drop on `supergate` |
| juniper_junos | 6 | 0 | clean |
| mikrotik_routeros | 6 | 30 | **Rank 3 globally** — interface count drift on every fixture |
| opnsense | 6 | 0 | intra-vendor self-pair (no Phase 3 YAML) |

Six opnsense fixtures are exercised: five real captures (`opnsense_acl_test_config.xml`,
`opnsense_core_default.xml`, `opnsense_paramiko_shell_capture.xml`,
`opnsense_service_test_config.xml`, `user_contrib_supergate_opn25.xml`) and one
synthetic kitchen-sink (`tests/fixtures/synthetic/opnsense/kitchen_sink.xml`).

## Root-cause synthesis

Three distinct bug classes account for all 70 CODEC_BUG findings.  No
finding belongs to the OPNsense parser itself: every drifted field is one
the OPNsense parser DOES populate.  The parse-side wire-up gaps anticipated
by `opnsense__mikrotik_routeros.yaml` (DNS / NTP / syslog / timezone /
static routes / DHCP pool) are correctly classified as
`METHODOLOGY_ISSUE_under` because the YAML pre-declares them `lossy` and
the Phase 1 mechanical baseline reports `preserved` for them — those are
not bugs, they're stale reconciliation against a YAML that's pessimistic
about a parser surface that DID get wired up.  See "METHODOLOGY_ISSUE_under
demotion" below.

### B1. mikrotik_routeros render drops IP-less interfaces; re-emits VLAN/LAG as fresh interfaces

**Severity: high.  30/30 of the opnsense → mikrotik_routeros bugs.**

Mechanism (verified by repro):

1. `netconfig/migration/codecs/mikrotik_routeros/render.py:85-110` filters
   `tree.interfaces` through `_is_ethernet_name(i.name) or _is_ethernet_name(i.default_name)
   or (i.interface_type == "ianaift:ethernetCsmacd" and i.default_name)`.
   `_is_ethernet_name` is `^ether\d` (parse.py:832-834).  OPNsense parse
   emits zone names like `wan`, `lan`, `opt1`, `lo0` with empty
   `default_name` and empty `interface_type`, so the entire
   `/interface ethernet` block is skipped.

2. `/ip address` (render.py:194-205) only emits a row per `(iface, addr)`
   pair, so an interface with no IPv4 / IPv6 (e.g. OPNsense `wan` zone
   when WAN is DHCP-client) emits NO line and disappears from the
   round-trip.  The mikrotik parser has no top-level inventory line
   to recover it from.

3. Conversely, `/interface vlan` (render.py:147-192) emits one row per
   `tree.vlans` entry that doesn't already have a matching VLAN
   interface.  When mikrotik re-parses these rows it materialises one
   `CanonicalInterface` per VLAN id (parse path: any `/interface vlan
   add ... name=vlan10` becomes a fresh interface).  Same pattern for
   `/interface bonding` lagg rows: re-parsed as a `ianaift:ieee8023adLag`
   interface.  These over-emit because OPNsense doesn't populate a
   `CanonicalInterface` for a VLAN tag (it's a list-of-tags only) and
   doesn't distinguish a LAG aggregate from its members the way RouterOS
   does.

Drift detail observed:

| Fixture | source ifaces | reparse ifaces | drift_summary |
|---|---:|---:|---|
| opnsense_acl_test_config.xml | 2 | 1 | `count drift: 2 → 1` (wan dropped, no IP) |
| opnsense_core_default.xml | 2 | 1 | same |
| opnsense_paramiko_shell_capture.xml | 2 | 1 | same |
| opnsense_service_test_config.xml | 3 | 2 | one IP-less zone dropped |
| user_contrib_supergate_opn25.xml | 8 | 12 | wan dropped (1) + 5 VLANs synthesised |
| kitchen_sink.xml | 7 | 12 | wan dropped (1) + 5 VLANs synthesised + 1 lagg synthesised |

All five sub-fields (`description`, `enabled`, `mtu`, `ipv4_addresses`,
`ipv6_addresses`) report `count drift: X → Y` because the cross-mesh
audit emits the same drift summary for every per-interface sub-field
when the list cardinality changes.  Five drifts per fixture × six
fixtures = 30, matching the matrix.

**Likely fix location.** Two cooperating render-side changes in
`netconfig/migration/codecs/mikrotik_routeros/render.py`:

* Emit an `/interface ethernet` row for any `CanonicalInterface` that
  isn't a VLAN tag, isn't a bridge, isn't a LAG aggregate (regardless
  of whether `_is_ethernet_name` matches).  RouterOS treats a non-
  default port name as a rename; a `set [ find default-name=ether1 ]
  name=wan disabled=no` row is harmless when `default_name` is empty
  by falling back to the canonical name as the find key (the existing
  `find_key = iface.default_name or iface.name` line covers it).  The
  current filter is the load-bearing source of dropped IP-less zones.
* Render `/interface vlan` and `/interface bonding` rows IDEMPOTENTLY
  with `default_name`/`type` annotations that round-trip through the
  parser without spawning new `CanonicalInterface` records — or, more
  surgically, only count interfaces by `name` AND `interface_type`
  in the cross-mesh comparator (Phase 1 mechanical fix in
  `tools/run_full_mesh.py`).  The cleaner fix is render-side though:
  the round-trip should not invent interfaces that didn't exist in
  the source.

**Test that would catch the fix.** Add a unit test at
`tests/unit/migration/codecs/mikrotik_routeros/test_round_trip_iface_list.py`
that constructs a `CanonicalIntent` with three interfaces (`wan` no IP,
`lan` with IP, `opt1` no IP), renders to RouterOS, parses it back, and
asserts `len(parsed.interfaces) == 3` and all three names round-trip.
Today that test fails with `1 == 3`.  Add a second case with
`tree.vlans=[10,20]` and zero VLAN-typed interfaces, asserting
`len(parsed.interfaces) == len(intent.interfaces)` (no synthesised
VLAN interfaces) and `len(parsed.vlans) == 2`.

### B2. cisco_iosxe_cli parser missing `ip domain name` recogniser

**Severity: high.  5/5 of the opnsense → cisco_iosxe_cli bugs.
Same pattern likely accounts for cisco_iosxe_cli rank-2/4/5 bugs from
other sources (out of scope for this report).**

Mechanism (verified):

* `netconfig/migration/codecs/cisco_iosxe_cli/render.py:88-89` correctly
  emits `ip domain name {tree.domain}`.
* `netconfig/migration/codecs/cisco_iosxe_cli/parse.py` contains zero
  occurrences of the literal `ip domain` (grepped exhaustively); the
  only `domain` parses are scoped to inside `ip dhcp pool` blocks
  (parse.py:711, 768).  The top-level domain line round-trips to
  empty.

Affected fixtures: every opnsense fixture that carries a `<domain>`
element (5 of 6; `opnsense_core_default.xml` is the only one with no
domain).

**Likely fix location.** Add a regex (e.g.
`r"^ip\s+domain\s+name\s+(\S+)"`) to the top-level loop in
`cisco_iosxe_cli/parse.py` that sets `intent.domain = match.group(1)`.
Mirror handling for `ip domain-name` (legacy form) for parity with
existing render coverage.

**Test that would catch the fix.** Extend
`tests/unit/migration/codecs/cisco_iosxe_cli/test_parse.py` (or sibling)
with `test_parse_ip_domain_name_top_level()` asserting that
`parse("ip domain name example.com\n").domain == "example.com"`.

### B3. fortigate_cli renderer emits no top-level domain line

**Severity: high.  5 of the 11 opnsense → fortigate_cli bugs (the
`domain` field on every fixture that has it).**

Mechanism (verified):

* `netconfig/migration/codecs/fortigate_cli/render.py` emits no
  `config system dns` block and no `set domain` at the global level.
  The only `domain` strings in the renderer scope are inside
  `config system dhcp server` (render.py:318-319).
* The parser DOES recognise the FortiGate top-level domain field
  (it's used on the source side of fortigate → other-vendor pairs)
  but there's no render path back, so opnsense → fortigate drops the
  field.

Affected fixtures: same 5 as B2.

**Likely fix location.**  Add a `config system global` `set hostname`
... `set alias`/`set domain` emission OR a `config system dns / set
domain` block in `fortigate_cli/render.py` whenever `tree.domain` is
truthy.  FortiGate's documented surface is `config system dns / set
domain "example.com"` (top-level resolver domain), aligning with how
the codec's parser consumes it.

**Test that would catch the fix.**
`tests/unit/migration/codecs/fortigate_cli/test_render.py::test_render_top_level_domain`
that asserts a `CanonicalIntent(domain="example.com")` produces output
containing `set domain "example.com"`.

### B4. fortigate_cli interface count drift on `kitchen_sink.xml`

**Severity: high.  4 sub-fields × 1 fixture = 4 of the 11 fortigate
bugs.**  `count drift: 7 → 8 (interfaces)`.  Likely a fortigate-side
parser side-effect from synthetic VLAN entries (analogous to but
narrower than B1 on mikrotik).  Did not deep-trace within scope; flag
for fortigate-source-side investigation pass when that agent runs.

### B5. fortigate_cli VLAN drop on `user_contrib_supergate_opn25.xml`

**Severity: high.  2 of the 11 fortigate bugs (id sub-field; appears
twice in the matrix because of how the audit unfolds list-vs-list
deltas).**  `all 5 vlans dropped`.  Likely fortigate render does not
materialise standalone VLAN definitions when there's no parent
interface to attach them to (FortiGate VLANs are
`config system interface / edit vlan10 / set vlanid 10 / set
interface "wan"`).  The OPNsense source carries `<vlans>/<vlan>`
entries with a parent device that doesn't survive port-rename mesh
projection cleanly.

### B6. arista_eos drops radius_servers entirely on `kitchen_sink.xml`

**Severity: high.  1/5 of the arista bugs (the `radius_servers` row;
the other 4 are the kitchen_sink-only interface count drift `7 → 8`,
similar to B4).**

Mechanism: `netconfig/migration/codecs/arista_eos/{render,parse}.py`
have ZERO mentions of the string `radius` (grepped both case-
sensitive and case-insensitive).  arista_eos has no RADIUS surface
at all; the canonical list is render-dropped.  Pair YAML
`opnsense__arista_eos.yaml` should classify `radius_servers` as
`unsupported` (target gap) rather than `good`; this is a
**Phase 3 expectation YAML fix**, not a code fix.

**Likely fix location.**  Either:
* (preferred) implement an arista RADIUS render path — EOS uses
  `radius-server host A.B.C.D auth-port 1812 acct-port 1813 key X`,
  trivial to mirror on parse.
* (cheaper) flip the YAML disposition to `unsupported` with
  reference `arista_eos has no canonical radius surface today`.

### B7. aruba_aoss radius_servers preserves only standard ports

**Severity: high.  1 of the 19 aruba bugs (radius_servers on
`kitchen_sink.xml`).  Auth-port 11812 / acct-port 11813 collapse to
1812 / 1813 on the second server.**

Mechanism: `netconfig/migration/codecs/aruba_aoss/render.py:225-231`
emits ONLY `radius-server host {host} key "{key}"` — no `auth-port`
or `acct-port` clause.  Non-default ports drop to AOS-S defaults on
re-render → re-parse.  Parser parse.py:154-165 also only matches the
host+key form.

**Likely fix location.**  Render: emit `radius-server host {host}
auth-port {auth_port} acct-port {acct_port} key "{key}"` whenever
the canonical record carries non-default port numbers.  Parser:
extend the regex at parse.py:157 to optionally capture `auth-port`
and `acct-port` tokens.

**Test.**
`tests/unit/migration/codecs/aruba_aoss/test_render.py::test_radius_non_default_ports`
asserting that a `CanonicalRADIUSServer(auth_port=11812)` emits
the explicit `auth-port 11812` clause and round-trips through the
parser.

### B8. aruba_aoss drops every interface on opnsense → aruba round-trip

**Severity: high.  18 of the 19 aruba bugs (3 sub-fields × 6
fixtures).**  Drift summary mixes `all N interfaces dropped` (3
fixtures) and `count drift: N → M` (3 fixtures with partial
recovery).

Mechanism (verified by repro of `opnsense_acl_test_config.xml`): the
aruba renderer emits `interface wan / enable / exit` and
`interface lan / enable / routing / ip address 192.168.1.1/24 / exit`
correctly, but `aruba_aoss/parse.py` then recovers ZERO interfaces.
AOS-S parse expects names matching the `<port>/<n>/<m>` slot pattern
and short tokens like `wan`/`lan` are silently ignored.  This is a
parse-side gap on the aruba codec, surfaced cross-pair only because
opnsense supplies BSD-style zone names that don't pass aruba's port
classifier.

**Likely fix location.** `aruba_aoss/parse.py` interface-block
recogniser should accept any token after `interface ` (not just
slot patterns) and let the canonical name carry the verbatim string.
The existing `aruba_aoss/port_names.py` `classify_port_name` should
do the work of telling slot vs alias apart, but the parser block
shouldn't refuse alias-style names outright.

**Test.**
`tests/unit/migration/codecs/aruba_aoss/test_parse.py::test_parse_alias_interface_name`
asserting `parse("interface wan\n   enable\n   exit\n")` produces
one interface with `name == "wan"`.

## METHODOLOGY_ISSUE_under demotion review

The opnsense → mikrotik cells carry 16-22 `METHODOLOGY_ISSUE_under`
findings each (matrix totals: 114 across the 6 fixtures).  Spot-
checked breakdown for `opnsense_acl_test_config.xml`:

| Field | source_count | demote? |
|---|---:|---|
| dns_servers | 0 (parsed empty in this fixture) | YES — demote-to-aligned |
| ntp_servers | 0 | YES |
| timezone | 0 (no `<timezone>` element) | YES |
| syslog_servers | 0 | YES |
| static_routes | 0 (no `<staticroutes>` block) | YES |
| snmp | 0 (no `<snmpd>` block) | YES |
| lags | 0 | YES |
| vlans | 0 (this fixture has no VLANs) | YES |

Per the constraint ("apply skepticism for METHODOLOGY_ISSUE_under:
demote if source_count=0"): in the bullet of fixtures where the
source XML genuinely has no element for the field, the YAML's
`lossy` declaration is still correct (it captures the codec gap when
data IS present), but the Phase 1 mechanical record reporting
`preserved` for an empty list is not actually drift.  The
reconciliation script could short-circuit empty-vs-empty as
`ALIGNED`.  This is a cross-cutting tooling note, not an opnsense-
codec bug — flagging here for completeness.  Eight fields × six
fixtures × demotion would shed roughly 30-40 of the 114
`METHODOLOGY_ISSUE_under` rows in the opnsense → mikrotik cell
without changing any CODEC_BUG count.

## Top 3 actionable fix locations (priority order)

1. **`netconfig/migration/codecs/mikrotik_routeros/render.py`** —
   B1.  Emit `/interface ethernet` for every non-VLAN, non-bridge,
   non-LAG `CanonicalInterface` regardless of name pattern; ensure
   `/interface vlan` and `/interface bonding` rows don't materialise
   fresh canonical interfaces on reparse.  Single render fix, kills
   30 of the 70 opnsense-source CODEC_BUG findings (43%).

2. **`netconfig/migration/codecs/cisco_iosxe_cli/parse.py`** —
   B2.  Add a top-level `ip domain name X` recogniser.  Five lines
   of regex; clears 5 opnsense-source bugs and likely contributes to
   the 25 juniper_junos → cisco_iosxe_cli bugs and similar from other
   sources (rank 2 globally for cisco_iosxe_cli as a target).

3. **`netconfig/migration/codecs/aruba_aoss/parse.py`** —
   B8.  Loosen the `interface ` block recogniser to accept any
   following token, not only port-slot patterns.  Clears 18 of 19
   aruba-target bugs.  Likely also fixes a chunk of the 40 juniper
   → aruba findings (rank 1 globally), though that needs the juniper
   investigation to confirm.

## See also

- `tests/fixtures/real/PHASE4_RECONCILIATION.md` — overall matrix and
  ranking that brought opnsense → mikrotik to attention
- `tests/fixtures/real/_phase4_runs/latest.json` — per-cell raw data
  read by this report
- `tests/fixtures/cross_vendor_expectations/opnsense__mikrotik_routeros.yaml`
  — the YAML this report reconciles against
- `netconfig/migration/codecs/mikrotik_routeros/render.py:85-110` —
  the load-bearing filter for B1
- `netconfig/migration/codecs/cisco_iosxe_cli/parse.py` — site of B2
- `netconfig/migration/codecs/aruba_aoss/parse.py:154-165` — sites of
  B7 (radius port omission) and B8 (interface name filter)
