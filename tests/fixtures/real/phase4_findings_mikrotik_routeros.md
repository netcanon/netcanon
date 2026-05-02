# Phase 4b findings — source codec `mikrotik_routeros`

Investigation of every cell where ``source_codec == "mikrotik_routeros"`` in
``tests/fixtures/real/_phase4_runs/latest.json`` (run started 2026-05-02T06:54:10Z,
joining the 2026-05-01 cross-mesh drift matrix against the 7 Phase-3
``mikrotik_routeros__<target>.yaml`` expectation files).

Scope: 40 cells (5 fixtures × 8 targets, intra-vendor self-pair has no Phase-3
YAML and shows empty ``field_variances``).  Source fixtures reconciled:

| Fixture | Tier |
|---|---|
| ``tests/fixtures/real/mikrotik/ntc_ip_address_export.rsc`` | real |
| ``tests/fixtures/real/mikrotik/routeros_diff_verbose_export.rsc`` | real |
| ``tests/fixtures/real/mikrotik/taqavi_initial_provisioning.rsc`` | real |
| ``tests/fixtures/real/mikrotik/user_contrib_crs310_ros7.rsc`` | real |
| ``tests/fixtures/synthetic/mikrotik_routeros/kitchen_sink.rsc`` | synthetic |

Aggregate variance counts across these 40 cells:

| Variance | Count |
|---|---:|
| ALIGNED | 184 |
| METHODOLOGY_ISSUE_under | 763 |
| EXPECTED_LOSSY | 106 |
| EXPECTED_UNSUPPORTED | 29 |
| MISSING_PHASE1 | 105 |
| METHODOLOGY_ISSUE_over | 7 |
| **CODEC_BUG** | **6** |

All six CODEC_BUG findings are severity=high and surface on cells whose
``render_status=ok`` and ``roundtrip_parse_status=ok`` — i.e. the bytes shipped
clean but a piece of canonical content disappeared somewhere along the
parse → render → re-parse arc.

---

## 1. Per-finding triage

### Finding A — hostname truncated/dropped on whitespace (2 cells)

**Drift**

| # | Fixture | Target | Drift |
|---|---|---|---|
| A1 | ``mikrotik/routeros_diff_verbose_export.rsc`` | ``arista_eos`` | ``hostname: 'Quinta Router' -> ''`` |
| A2 | ``mikrotik/routeros_diff_verbose_export.rsc`` | ``cisco_iosxe_cli`` | ``hostname: 'Quinta Router' -> 'Quinta'`` |

**Source line** (``routeros_diff_verbose_export.rsc:424``):

```
/system identity
set name="Quinta Router"
```

**Root cause — render-side bug on the *target* codecs.**

The mikrotik parse side is correct: ``_parse_kv`` strips the surrounding
quotes (``parse.py:244-246``), so ``intent.hostname == "Quinta Router"`` is
populated faithfully.

The bug is in the target render paths emitting an unquoted, unsanitised
hostname token:

- ``netconfig/migration/codecs/arista_eos/render.py:42-44`` emits
  ``f"hostname {tree.hostname}"`` -> ``hostname Quinta Router``.  When the
  same string is then handed back to ``arista_eos/parse.py:53``, the
  pattern ``re.compile(r"^hostname\s+(\S+)\s*$", re.MULTILINE)`` *fails to
  match at all* — the trailing ``\s*$`` anchor doesn't accept the space and
  ``Router`` token, so the second-parse hostname comes back empty.
- ``netconfig/migration/codecs/cisco_iosxe_cli/render.py:85-87`` emits the
  same way.  The IOS-XE CLI parser pattern is more permissive
  (``r"^hostname\s+(\S+)"`` with no ``$`` anchor — ``parse.py:127``), so it
  recovers ``Quinta`` but silently drops ``Router``.

Real Arista EOS / Cisco IOS-XE CLI **do not** accept whitespace in
``hostname`` — both vendors require a single token.  The right fix is
target-render sanitisation: replace whitespace runs with ``-`` (or ``_``)
before the ``f"hostname …"`` line, and log a debug-level note that the
source's free-form name was normalised.

**Likely fix locations**

- ``netconfig/migration/codecs/arista_eos/render.py`` (the ``if tree.hostname:`` block at line 42-44).
- ``netconfig/migration/codecs/cisco_iosxe_cli/render.py`` (the ``if tree.hostname:`` block at line 85-87).
- Optionally tighten ``arista_eos/parse.py:53`` to either drop the ``\s*$``
  anchor or accept the rest-of-line so the whitespace-tolerant *render*
  doesn't double-fail in legacy configs an operator pasted in.  This is a
  follow-up, not the primary fix — real EOS rejects the input upstream.

**Test that would catch the fix**

A ``tests/unit/migration/test_real_captures.py`` (or new
``tests/unit/migration/codecs/test_hostname_sanitisation.py``) parametrise
that builds a ``CanonicalIntent(hostname="Quinta Router")``, calls each
target render, and asserts the rendered config (a) contains exactly one
``hostname`` line and (b) re-parses to a *non-empty* hostname.  Today both
of these would fail for arista_eos and the second would partially fail for
cisco_iosxe_cli.

---

### Finding B — system DNS / NTP servers dropped on cisco_iosxe_cli round-trip (2 cells)

**Drift**

| # | Fixture | Target | Drift |
|---|---|---|---|
| B1 | ``synthetic/mikrotik_routeros/kitchen_sink.rsc`` | ``cisco_iosxe_cli`` | ``all 2 dns_servers dropped`` (``['1.1.1.1', '8.8.8.8']`` -> ``[]``) |
| B2 | ``synthetic/mikrotik_routeros/kitchen_sink.rsc`` | ``cisco_iosxe_cli`` | ``all 2 ntp_servers dropped`` (``['10.0.0.123', 'pool.ntp.org']`` -> ``[]``) |

**Source lines** (``kitchen_sink.rsc:123-127``):

```
/system dns
set servers=1.1.1.1,8.8.8.8

/system ntp client
set enabled=yes servers=10.0.0.123,pool.ntp.org
```

**Root cause — target parse-side bug in cisco_iosxe_cli.**

The mikrotik parse side correctly populates ``intent.dns_servers`` and
``intent.ntp_servers`` (verified locally — comma-split in ``parse.py:262-279``).
The cisco_iosxe_cli render path correctly emits ``ip name-server <addr>``
(``render.py:122-125``) and ``ntp server <addr>`` (``render.py:126-129``)
lines — confirmed by direct exec: the rendered text contains all four
lines verbatim.

The drop happens on the **second parse** in the cross-mesh harness:
``cisco_iosxe_cli/parse.py`` does NOT extract top-level ``ip name-server``
or ``ntp server`` stanzas into ``intent.dns_servers`` / ``intent.ntp_servers``.
Searching ``parse.py`` for ``name-server`` / ``ntp server`` returns only
*nested* DHCP-pool DNS handling at line 760-764 (``current.dns_servers`` on
a DHCP pool, NOT system-level).  ``intent.dns_servers`` and
``intent.ntp_servers`` are never populated by this parser.

This is a coverage gap (parser doesn't read its own renderer's output),
not a bug only visible from a foreign source — every codec that round-
trips through ``cisco_iosxe_cli`` would surface it.

**Likely fix location**

``netconfig/migration/codecs/cisco_iosxe_cli/parse.py`` — add module-level
regex constants and call sites alongside the existing ``_extract_hostname``
/ ``_parse_static_routes`` / etc. block at line 219-249:

```python
_DNS_SERVER_RE = re.compile(r"^ip name-server\s+(?:vrf\s+\S+\s+)?(\S+)\s*$", re.MULTILINE)
_NTP_SERVER_RE = re.compile(r"^ntp server\s+(?:vrf\s+\S+\s+)?(\S+)", re.MULTILINE)
```

(Mirror the patterns in ``arista_eos/parse.py:54-60`` — same vendor family,
same wire syntax, prior art.)

**Test that would catch the fix**

A round-trip test in ``tests/unit/migration/test_cisco_iosxe_cli_codec.py``
(or augment the synthetic-kitchen-sink round-trip suite) that builds an
intent with non-empty ``dns_servers`` / ``ntp_servers``, runs
``render_intent`` then ``parse_intent``, and asserts the lists survive.
This same gap probably explains a chunk of CODEC_BUG cells from other
sources targeting cisco_iosxe_cli — a single fix here would clear several
cross-mesh entries.

---

### Finding C — fortigate_cli static-route ``description`` not emitted (1 cell, 4 routes)

**Drift**

| # | Fixture | Target | Drift |
|---|---|---|---|
| C1 | ``synthetic/mikrotik_routeros/kitchen_sink.rsc`` | ``fortigate_cli`` | All 4 ``static_routes[].description`` source values dropped (``'Default route to ISP'`` ... -> ``''``) |

**Source lines** (``kitchen_sink.rsc:65-69``):

```
/ip route
add comment="Default route to ISP" dst-address=0.0.0.0/0 gateway=198.51.100.1
add comment="Branch network via core" dst-address=10.50.0.0/16 gateway=10.0.0.254
...
```

**Root cause — render-side bug in fortigate_cli.**

Mikrotik ``_parse_ip_route`` correctly maps ``comment="…"`` to
``CanonicalStaticRoute.description``.  FortiGate's render block
(``netconfig/migration/codecs/fortigate_cli/render.py:333-345``) emits
``set dst`` / ``set gateway`` / ``set device`` but never emits
``set comments "..."``.  FortiGate config syntax for ``config router
static`` supports a ``set comments`` line — it's just missing.

**Likely fix location**

``netconfig/migration/codecs/fortigate_cli/render.py:333-345`` — add an
``if route.description:`` clause after the existing optional-field clauses
that emits ``set comments "<description>"`` (FortiGate quotes string
values containing spaces).

**Test that would catch the fix**

Either (a) a new dedicated unit test for fortigate static-route render in
``tests/unit/migration/test_fortigate_cli_codec.py`` asserting that
``CanonicalStaticRoute(description="Default route to ISP", ...)``
round-trips through render, or (b) a kitchen-sink-style unit test that
diffs the rendered fortigate config against an expected snippet.  The
former is cheaper and easier to attribute.

---

### Finding D — opnsense drops the IPv6 link-local alongside global (1 cell)

**Drift**

| # | Fixture | Target | Drift |
|---|---|---|---|
| D1 | ``synthetic/mikrotik_routeros/kitchen_sink.rsc`` | ``opnsense`` | ``ether1.ipv6_addresses``: source has ``[2001:db8:0:1::2/64 (global), fe80::1/64 (link-local)]``, target has ``[2001:db8:0:1::2/64]`` only |

**Source lines** (``kitchen_sink.rsc:60-61``):

```
/ipv6 address
add address=2001:db8:0:1::2/64 interface=ether1
add address=fe80::1/64 interface=ether1 advertise=no
```

**Root cause — render-side schema limit in opnsense.**

``netconfig/migration/codecs/opnsense/render.py:142-144`` deliberately
emits only ``ipv6_addresses[0]`` because the OPNsense ``<interfaces>``
XML schema has exactly one ``<ipaddrv6>`` / ``<subnetv6>`` per zone.
Additional v6 addresses on the same interface land in the OPNsense GUI as
*virtual IPs* (``<virtualip><vip>...``), not as repeated zone children.

Whether this is a *bug* or *expected lossy* is a judgement call:

- If the expectation YAML treats per-interface multi-v6 as ``lossy`` (which
  it should given the OPNsense schema), this finding should reclassify to
  EXPECTED_LOSSY.  Recommend updating
  ``tests/fixtures/cross_vendor_expectations/mikrotik_routeros__opnsense.yaml``
  to set ``interfaces[].ipv6_addresses`` expectation to ``lossy`` with a
  ``mode: SINGLE_V6_PER_ZONE_PLUS_VIRTUALIP`` note rather than fixing the
  render path.
- If the YAML deliberately demands full preservation (because OPNsense
  *can* model this via ``<virtualip>``), the right fix is in
  ``opnsense/render.py:142-144`` — emit ``ipv6_addresses[0]`` to the zone
  and emit ``ipv6_addresses[1:]`` as ``<virtualip><vip>`` records under a
  parallel ``<virtualip>`` element.

**Recommended fix:** start with the YAML correction (downgrade to
EXPECTED_LOSSY).  The ``<virtualip>`` extension is a worthwhile but
distinct change with its own parser counterpart in
``opnsense/parse.py:407-420`` to read ``virtualip``/``vip`` records back
into ``CanonicalInterface.ipv6_addresses``.

**Test that would catch a render-side fix**

If the ``<virtualip>`` route is taken: a unit test on
``opnsense/render.py`` rendering an interface with two IPv6 addresses,
asserting both survive a round-trip through ``opnsense/parse.py``.

---

## 2. METHODOLOGY_ISSUE_under skepticism (source_count=0 demotion)

Per the prompt's directive: demote findings where the source had zero of
the field in question.

The 763 ``METHODOLOGY_ISSUE_under`` rows in mikrotik-source cells consist
mostly of **non-list scalar fields** (``apply_groups``, ``group_content``,
``evpn_type5_routes``, ``domain``, ``raw_sections``, ``timezone``,
``source_format``, ``source_vendor``, etc.) where the source codec
populates these as ``"preserved"`` *because the canonical placeholder
exists with a default value*, and the YAML expected ``"not_applicable"`` /
``"unsupported"``.

These are genuine **YAML-side methodology drift** (the expectation YAML
should mark them ``lossy``-with-zero-count or ``not_applicable`` with an
explicit-zero source side), not target codec bugs.

For the **list-shaped** fields (``dhcp_servers``, ``radius_servers``,
``snmp``, ``static_routes``, ``vlans``, ``lags``, ``local_users``,
``syslog_servers``, ``ntp_servers``, ``dns_servers``) where source content
is non-empty (verified — ``kitchen_sink.rsc`` populates all of them) the
``METHODOLOGY_ISSUE_under`` classification is correct in shape: the
expectation YAML claims the target loses these (``expected: lossy`` /
``unsupported``) but the harness observes ``preserved``.  The fix is to
upgrade the expectation YAMLs to ``"good"`` for those fields where the
target codec actually preserves them.

No CODEC_BUG demotions arise from the source_count=0 check — all 6
CODEC_BUG cells have non-zero source content.

---

## 3. METHODOLOGY_ISSUE_over rows (7 cells)

For completeness — these are low-severity drift signals where the
expectation YAML claimed the field would be ``not_applicable`` but the
target rendered something:

- ``interfaces[].default_name`` -> ``cisco_iosxe`` on 5 fixtures.
  ``default_name`` is mikrotik-internal (``ether2`` original-name vs.
  ``name=`` user-rename).  Cisco_iosxe canonical retains the field name
  but populates the empty string; the YAML's ``not_applicable`` is more
  accurate than ``drifted``.  **Recommended:** update the YAMLs to mark
  the field with an ``ignored: true`` flag or filter it out at the
  reconciliation layer (this is a pure scoping/expectation issue, not a
  codec bug).
- ``vlans[].description`` -> ``juniper_junos`` on 2 fixtures.  Same
  pattern — the canonical field is preserved but the YAML predicted
  ``not_applicable``.  Update the expectation YAML.

These are all severity=low; no urgent action required.

---

## 4. Bond-interface ``description`` propagation check

The integrator agent flagged that mikrotik render drops bond-interface
``description`` (whitelisted in
``tests/unit/migration/test_synthetic_kitchen_sink_round_trips.py
::_KNOWN_ROUNDTRIP_GAPS["mikrotik_routeros::kitchen_sink.rsc"]``).

I checked whether this propagates to other targets as a CODEC_BUG.  It
does **not**.  The drop is observed inside the ``interfaces`` /
``lags`` field on every target's kitchen_sink cell, but in every case
the field's ``variance`` is either ``EXPECTED_LOSSY`` (where the YAML
already classifies the lag/interface complex as lossy — arista_eos,
aruba_aoss, cisco_iosxe_cli, juniper_junos), ``EXPECTED_UNSUPPORTED``
(cisco_iosxe), or ``METHODOLOGY_ISSUE_under`` (fortigate_cli, opnsense
where the YAML undersells preservation but the bond-description piece is
absorbed inside the broader interfaces+lags drift).

So the bond-description gap is a **mikrotik-internal round-trip TODO**
(parse mikrotik -> intent -> render mikrotik drops description), not a
cross-vendor CODEC_BUG.  Fix would live in
``netconfig/migration/codecs/mikrotik_routeros/render.py`` — the
``/interface bonding`` emission stanza must add the ``comment="…"``
key when ``CanonicalInterface.description`` is non-empty.  Once fixed,
the entry can be removed from
``test_synthetic_kitchen_sink_round_trips.py::_KNOWN_ROUNDTRIP_GAPS``.

---

## 5. Top three actionable fix locations

Ranked by leverage (number of cross-mesh cells cleared per fix):

1. **``cisco_iosxe_cli/parse.py`` — add system-level ``ip name-server`` /
   ``ntp server`` parsing.**  Single drop-in pair of regex+loop additions
   in the parse function around line 219-249.  Mirrors arista_eos
   precedent (``arista_eos/parse.py:54-60``).  Clears Findings B1, B2 and
   likely several CODEC_BUG cells from other sources targeting
   cisco_iosxe_cli.
2. **``arista_eos/render.py:42-44`` and ``cisco_iosxe_cli/render.py:85-87``
   — sanitise ``tree.hostname`` whitespace before emission.**  Two-line
   change in each codec; clears Findings A1, A2 and any future cell where
   a multi-word hostname round-trips through these targets.
3. **``fortigate_cli/render.py:333-345`` — emit ``set comments "..."``
   for ``CanonicalStaticRoute.description``.**  Single ``if`` clause;
   clears Finding C1 (4 routes in the kitchen-sink fixture) and any other
   source whose static routes carry comments.

Finding D (opnsense IPv6 multi-address) is more naturally a YAML
correction than a render fix — recommend the YAML route first.

---

## See also

- ``tests/fixtures/real/PHASE4_RECONCILIATION.md`` — overall Phase 4b skeleton
- ``tests/fixtures/real/_phase4_runs/latest.json`` — per-cell raw data
- ``tests/fixtures/cross_vendor_expectations/mikrotik_routeros__*.yaml`` — Phase 3 expectations under audit
- ``netconfig/migration/codecs/mikrotik_routeros/`` — source codec under investigation
- ``tests/unit/migration/test_synthetic_kitchen_sink_round_trips.py`` — ``_KNOWN_ROUNDTRIP_GAPS`` for the bond-description gap
