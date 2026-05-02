# Phase 4b findings — source codec ``cisco_iosxe_cli``

Investigation of every ``CODEC_BUG`` field-cell where ``source_codec ==
"cisco_iosxe_cli"`` in
``tests/fixtures/real/_phase4_runs/latest.json`` (run timestamp
``20260502T065410Z``).

* Total cells investigated: **37** ``CODEC_BUG`` field-cells across
  **3 source fixtures** and **5 target codecs**.
* ``METHODOLOGY_ISSUE_under`` skepticism check: **0** cells with
  ``source_count == 0`` — nothing to demote.

| Target codec       | CODEC_BUG count |
|--------------------|----------------:|
| ``juniper_junos``      | 25 |
| ``opnsense``           |  5 |
| ``arista_eos``         |  4 |
| ``aruba_aoss``         |  2 |
| ``cisco_iosxe`` (NETCONF) |  1 |

Every ``CODEC_BUG`` triages to a **render-side gap on the target
codec**, not a parse-side bug in ``cisco_iosxe_cli``.  The cisco IOS-XE
CLI parser correctly extracts ``switchport``, ``trunk native vlan``,
``channel-group``, ``radius server``, IPv6 link-local, and SVI L3
state from every fixture; the drift surfaces because the chosen target
codec doesn't emit a corresponding native form.  No source-side
expectation YAML changes are warranted — these are real codec gaps,
not false positives.

---

## Top fixes (ranked by impact)

| Rank | Fix | Findings unblocked |
|---:|---|---:|
| 1 | Add LAG / switchport / trunk emission to ``juniper_junos`` render | 25 |
| 2 | Add ``radius_servers`` emission to ``arista_eos`` render | 1 |
| 3 | Set ``scope="link-local"`` for ``fe80::/10`` addresses in ``cisco_iosxe`` NETCONF parse | 1 |
| 4 | Fix ``aruba_aoss`` ``_expand_port_range`` to leave hyphenated LAG names like ``Port-channel1`` intact | 2 |
| 5 | Use case-preserving zone tags on ``opnsense`` round-trip (or document the lossy lower-case as ``EXPECTED_LOSSY``) | 5 |

---

## Findings by target codec

### Target: ``juniper_junos``  (25 findings — rank 5 of top 5)

#### Pattern A — switchport / L2 attributes never emitted

* **Affected fields:** ``interfaces[].switchport_mode`` (4),
  ``interfaces[].access_vlan`` (2),
  ``interfaces[].trunk_allowed_vlans`` (3),
  ``vlans[].tagged_ports`` (2),
  ``vlans[].untagged_ports`` (2),
  ``vlans[].ipv4_addresses`` (2 — VLAN SVI L3, "irb" form).
* **Affected fixtures:** ``cisco_iosxe/batfish_cisco_interface.txt``,
  ``cisco_iosxe/cml_saumur_iosxe1712_pvrstp.txt``,
  ``cisco_iosxe/user_contrib_cat9300_iosxe1712.txt``,
  ``synthetic/cisco_iosxe_cli/kitchen_sink.txt``.
* **Source codec behaviour (correct):**
  ``netconfig/migration/codecs/cisco_iosxe_cli/parse.py`` extracts
  ``switchport mode trunk`` / ``switchport access vlan N`` / ``switchport
  trunk allowed vlan ...`` / ``switchport trunk native vlan N`` per
  interface and ``project_switchport_to_vlan`` mirrors them onto
  ``vlans[].tagged_ports`` / ``untagged_ports``.  All five field paths
  are populated in the source canonical tree.
* **Render-side bug (juniper_junos):**
  ``netconfig/migration/codecs/juniper_junos/render.py`` does not emit
  any ``family ethernet-switching`` block.  Lines 144–308 cover only
  L3 (description, mtu, disable, family inet/inet6, sub-interface
  unit splits).  The L2 keyword family (``set interfaces <iface> unit
  0 family ethernet-switching interface-mode trunk``,
  ``... vlan members ...``,
  ``set vlans <name> l3-interface irb.<vid>`` for SVI L3) is
  missing entirely.  Reparsing the rendered text produces a tree with
  ``switchport_mode = None``, no ``trunk_allowed_vlans``, and no
  ``vlans[].tagged_ports`` membership.
* **Likely fix location:**
  ``netconfig/migration/codecs/juniper_junos/render.py`` — extend the
  per-interface emission loop (around line 205) to render
  ``family ethernet-switching`` for any iface with
  ``switchport_mode``, ``access_vlan``, or ``trunk_allowed_vlans``;
  emit ``set interfaces <iface> native-vlan-id <native>`` from
  ``trunk_native_vlan``; emit
  ``set vlans <name> l3-interface irb.<id>`` plus a synthetic
  ``set interfaces irb unit <id> family inet address ...`` block when
  the canonical VLAN carries an ``ipv4_addresses`` entry.  Mirror the
  behaviour already present in
  ``netconfig/migration/codecs/arista_eos/render.py`` (lines
  159–171) — both EOS and Junos use a per-interface vlan-membership
  model.
* **Test that catches it:** add a synthetic-fixture round-trip case
  in ``tests/integration/migration/test_juniper_junos_codec.py`` (or
  the cross-vendor mesh round-trip suite) that parses a Cisco IOS-XE
  CLI snippet with ``switchport mode trunk`` + native VLAN, renders to
  Junos, re-parses, and asserts ``trunk_allowed_vlans`` /
  ``vlans[].tagged_ports`` survive.

#### Pattern B — ``CanonicalLAG`` → Junos ``ae<N>`` aggregated-ethernet emission missing

* **Affected fields:** ``lags`` (3 cells:
  ``batfish_cisco_interface.txt``, ``user_contrib_cat9300``,
  ``kitchen_sink.txt``); ``interfaces[].lag_member_of`` (1 cell:
  ``batfish_cisco_interface.txt``).
* **Drift signature:** ``"drift": "all N lags dropped",
  source_count=N, target_count=0`` for every fixture.
* **Render-side bug (juniper_junos):**
  ``juniper_junos/render.py`` has no LAG emission whatsoever — a grep
  for ``lag|aggregat|ae[0-9]`` matches only a comment on line 127
  ("not LAG members") in the interface-range collapse helper.  Junos
  expresses LAGs via ``set chassis aggregated-devices ethernet
  device-count N`` + ``set interfaces ae<N> aggregated-ether-options
  lacp active`` + ``set interfaces <member> ether-options 802.3ad
  ae<N>``; none of those lines are produced.  Reparse therefore sees
  zero LAGs and zero ``lag_member_of`` linkage.
* **Likely fix location:**
  ``netconfig/migration/codecs/juniper_junos/render.py`` — add a new
  block before the interface emission loop (around line 200) that
  iterates ``tree.lags``, picks/maps a Junos ``ae<N>`` index per
  ``CanonicalLAG.name`` (Cisco ``Port-channelN`` → ``aeN`` is the
  natural mapping; preserve in the identity bridge so re-parse can
  invert) and emits ``aggregated-ether-options lacp active`` /
  ``passive`` based on ``lag.mode``.  Per-interface emission (around
  line 280) needs to emit
  ``set interfaces <member> ether-options 802.3ad <ae_name>`` when
  ``iface.lag_member_of`` is set.
* **Companion parse work:**
  ``netconfig/migration/codecs/juniper_junos/parse.py`` must already
  ingest the new emission shape, otherwise round-trip will still
  show empty ``lags``.  Verify by running the full ingest after the
  render change — Junos parser for ``ae<N>`` reportedly already
  exists for same-vendor round-trip; if not, that's a coupled fix.
* **Test that catches it:** add a Cisco-source round-trip case to
  ``tests/integration/migration/test_juniper_junos_codec.py`` that
  asserts ``intent.lags`` non-empty after Junos render → Junos parse.

#### Pattern C — ``interfaces[]`` count drift on ``batfish_cisco_interface.txt``

* **Affected fields:** ``interfaces[].description``, ``.enabled``,
  ``.mtu``, ``.ipv4_addresses``, ``.ipv6_addresses``, ``.dhcp_client``
  (6 cells, ``batfish_cisco_interface.txt`` only).
* **Drift signature:** ``"count drift: 24 → 23 (interfaces)"`` on
  every subfield — i.e. one interface is dropped on Junos round-trip.
* **Root cause:** the source fixture contains
  ``interface ethernet 1/12`` (lower-case + space) on line 335.  Junos
  render emits a placeholder ``set interfaces ethernet 1/12``
  (``has_renderable_attr=False`` path on
  ``juniper_junos/render.py`` line 306–307), which the Junos parser
  cannot reingest because the space splits the line at the
  ``interfaces`` lexeme — Junos identifiers don't permit embedded
  spaces.  The reparse drops the interface, hence 24 → 23.
* **Likely fix location:** either (a) ``juniper_junos/render.py``
  rejects/sanitises space-bearing iface names at emission time
  (replace space with ``_`` and stash the original via the identity
  bridge), or (b) the canonical port-name normaliser used by the
  Junos render path canonicalises ``ethernet 1/12`` → ``ethernet1/12``
  earlier.  Choice (a) is more defensible because preserving the
  original surface form for cross-vendor renaming is explicit.
* **Test that catches it:** parametrised round-trip in
  ``tests/unit/migration/codecs/test_juniper_junos_render.py`` over
  the set of awkward Cisco port-name forms (``ethernet 1/12``,
  ``Modular-Cable1/2/3:4``, ``Wlan-GigabitEthernet0``) asserting the
  rendered text round-trips without dropping the interface.

---

### Target: ``opnsense``  (5 findings)

#### Pattern D — ``Ethernet0`` interface drops on round-trip

* **Affected fields:** ``interfaces[].description`` (1),
  ``interfaces[].mtu`` (1), ``interfaces[].ipv4_addresses`` (1),
  ``interfaces[].ipv6_addresses`` (2:
  ``batfish_cisco_interface.txt`` + ``kitchen_sink.txt``).
* **Drift signature:** ``per_record: interfaces[4] {'name':
  'Ethernet0'}: {source: <data>, target: None}``.  Source has the
  Ethernet0 row populated; target reparse has ``Ethernet0`` missing
  entirely.
* **Render-side issue (opnsense):**
  ``netconfig/migration/codecs/opnsense/render.py`` line 129 calls
  ``_zone_tag_for(iface.name)`` which lower-cases everything (line
  293: ``c.lower() if (c.isalnum() or c == "_") else "_"``) — so
  ``Ethernet0`` becomes the XML tag ``<ethernet0>``.  The reparse on
  ``opnsense/parse.py`` line 360 then sets
  ``iface.name = el.tag = "ethernet0"`` (lowercase).  The Phase 4
  per-record join keys interfaces by ``name``, so ``Ethernet0`` !=
  ``ethernet0`` and the entire Ethernet0 record looks "missing" on
  the target side.
* **Triage:** this is a debatable ``CODEC_BUG`` vs.
  ``EXPECTED_LOSSY``.  XML NCName rules genuinely disallow most
  Cisco-ish iface names, so opnsense MUST mangle the surface form.
  However, opnsense already has the identity bridge / port-name
  layer that other codecs use to round-trip case + non-XML chars.
  The fix is to **store the original Cisco-cased name in the
  identity bridge keyed by the sanitised XML tag**, then restore on
  reparse.
* **Likely fix location:**
  ``netconfig/migration/codecs/opnsense/render.py`` — when
  ``_zone_tag_for(iface.name) != iface.name``, emit
  ``<descr>``-prefixed metadata or a parallel
  ``<original_name>Ethernet0</original_name>`` element under the
  zone, and have ``opnsense/parse.py`` ``_parse_interface_zone_canonical``
  prefer the original-name element when present.  Alternative: route
  through the canonical port-name identity bridge.
* **Companion expectation YAML question:** if the team chooses NOT
  to fix this and treats opnsense iface-name lossiness as inherent,
  ``tests/fixtures/cross_vendor_expectations/cisco_iosxe_cli__opnsense.yaml``
  should classify these five fields under ``expected_lossy`` rather
  than ``good`` — but that's a Phase 3 expectation correction, not a
  Phase 4 reclassification.  Recommendation: fix the codec.
* **Test that catches it:** ``tests/integration/migration/`` round-
  trip case asserting an interface named ``Ethernet0`` retains
  ``name == "Ethernet0"`` after opnsense render → parse.

---

### Target: ``arista_eos``  (4 findings)

#### Pattern E — VLAN ``untagged_ports`` from ``trunk native vlan`` drops

* **Affected field:** ``vlans`` (3 cells:
  ``batfish_cisco_interface.txt`` — VLAN 6 ``untagged_ports`` drop;
  ``user_contrib_cat9300`` and ``kitchen_sink`` — VLAN
  ``ipv4_addresses`` + ``tagged_ports`` / ``untagged_ports`` drops).
* **Drift signature for ``batfish_cisco_interface.txt``:**
  ``vlans[8] {'id': 6, 'name': ''}: untagged_ports: source:
  ['Ethernet0'], target: []``.  Source: Ethernet0 has
  ``switchport mode trunk`` + ``switchport trunk native vlan 6``,
  which ``project_switchport_to_vlan`` correctly stores as
  ``vlans[6].untagged_ports = ['Ethernet0']``.
* **Render-side bug (arista_eos):**
  ``netconfig/migration/codecs/arista_eos/render.py`` (grepped — no
  matches for ``native|trunk_native``) does not emit
  ``switchport trunk native vlan <id>``.  The reparse therefore can
  never reconstruct the native-vlan untagged membership.  The
  ``trunk_native_vlan`` canonical field is silently dropped on
  arista render.
* **Likely fix location:**
  ``netconfig/migration/codecs/arista_eos/render.py`` lines 165–171
  (the ``elif iface.switchport_mode == "trunk":`` block) — add
  ``if iface.trunk_native_vlan is not None: out.append(f"   switchport
  trunk native vlan {iface.trunk_native_vlan}")``.  Companion: verify
  ``arista_eos/parse.py`` already understands the keyword (it
  presumably does for same-vendor round-trip; if not, both sides
  need work).
* **Drift signature for ``user_contrib_cat9300`` + ``kitchen_sink``:**
  these are subsumed by the same gap PLUS Pattern A / B for arista —
  EOS render does not emit per-vlan SVI L3 (``interface Vlan<N>`` +
  ``ip address``) when the canonical L3 lives on
  ``vlans[].ipv4_addresses`` rather than a separate
  ``CanonicalInterface(name="VlanN")`` row.  Same fix family: add
  SVI synthesis from ``CanonicalVlan.ipv4_addresses`` to arista
  render.

#### Pattern F — ``radius_servers`` not emitted

* **Affected field:** ``radius_servers`` (1 cell:
  ``kitchen_sink.txt``).
* **Drift signature:** ``"all 2 radius_servers dropped",
  source_count=2, target_count=0``.
* **Render-side bug (arista_eos):**
  ``netconfig/migration/codecs/arista_eos/render.py`` has no
  ``radius_server host`` emission (grep for ``radius`` returns no
  matches).  ``cisco_iosxe_cli/parse.py`` line 249 correctly invokes
  ``_parse_radius_servers(raw)`` and the canonical tree carries two
  ``CanonicalRADIUSServer`` rows, but EOS render drops them on the
  floor.
* **Likely fix location:**
  ``netconfig/migration/codecs/arista_eos/render.py`` — emit
  ``radius-server host <ip> auth-port <p> acct-port <p> key 7 <key>``
  per ``CanonicalRADIUSServer`` row (EOS uses ``radius-server host``
  one-liners similarly to IOS-XE).  Mirror the existing
  ``cisco_iosxe_cli/render.py`` block (lines emitting
  ``radius server NAME`` modern form OR ``radius-server host`` legacy
  form depending on platform setting).
* **Test that catches it:** add ``radius_servers`` round-trip
  assertion to ``tests/unit/migration/codecs/test_arista_eos_render.py``.

---

### Target: ``aruba_aoss``  (2 findings)

#### Pattern G — ``Port-channel1`` shredded by AOS-S port-list parser

* **Affected field:** ``vlans`` (2 cells:
  ``batfish_cisco_interface.txt`` and
  ``user_contrib_cat9300_iosxe1712.txt``).
* **Drift signature:** ``source: ['Port-channel1', ...] target:
  ['Port', 'channel1', ...]`` — the LAG name is split on the hyphen.
* **Render-side bug (aruba_aoss):**
  ``netconfig/migration/codecs/aruba_aoss/render.py`` line 285 emits
  ``trunk Port-channel1 trk1 lacp`` (the LAG name passed through
  ``_format_port_list``).  The vlan body emits
  ``tagged Port-channel1,TenGigabitEthernet1/0/1,...`` on line 305.
  On reparse, ``aruba_aoss/parse.py`` line 365 calls
  ``_parse_port_list(text)``, which splits the comma-separated list.
  ``Port-channel1`` is one token; line 250 detects the ``-`` and
  routes through ``_expand_port_range("Port", "channel1")`` (line
  265).  The ``re.match(r"^(.*?)(\d+)$", "Port")`` returns ``None``
  (no trailing digits) so the helper falls through to
  ``return [lo, hi]`` (line 292), producing
  ``["Port", "channel1"]``.  The ``Port-channel1`` token is destroyed.
* **Likely fix location:**
  ``netconfig/migration/codecs/aruba_aoss/parse.py`` lines 250 and
  265 — only treat ``-`` as a range-separator when **both** sides
  match the trailing-digit pattern.  Concrete: in
  ``_parse_port_list`` line 250, change the ``"-" in token``
  short-circuit so a token like ``Port-channel1`` (where the right
  side has no leading numeric or the regex doesn't match) is treated
  as a single port name.  Equivalent inverse on the format side
  (line 112 in ``aruba_aoss/render.py`` — the regex
  ``re.match(r"^([A-Za-z]*)(\d+)$", p)`` already correctly fails on
  ``Port-channel1`` and stashes it whole, so the bug is
  parse-symmetric only).
* **Test that catches it:** add to
  ``tests/unit/migration/codecs/test_aruba_aoss_parse.py`` —
  ``_parse_port_list("Port-channel1,1/1,1/2")`` should return
  ``["Port-channel1", "1/1", "1/2"]``.

---

### Target: ``cisco_iosxe`` (NETCONF)  (1 finding)

#### Pattern H — IPv6 ``link-local`` scope flattened to ``global``

* **Affected field:** ``interfaces[].ipv6_addresses`` (1 cell:
  ``kitchen_sink.txt``).
* **Drift signature:** ``per_record: interfaces[1] {'name':
  'GigabitEthernet0/0/0'}: source: [...
  {'ip': 'fe80::1', 'prefix_length': 64, 'scope': 'link-local'}],
  target: [..., {'ip': 'fe80::1', 'prefix_length': 64, 'scope':
  'global'}]``.
* **Source codec behaviour (correct):** cisco_iosxe_cli parser
  preserves ``scope="link-local"`` for ``ipv6 address fe80::1/64
  link-local`` lines.
* **Render-side bug (cisco_iosxe NETCONF codec):**
  ``netconfig/migration/codecs/cisco_iosxe/codec.py`` line 840
  hard-codes ``scope="global"`` when materialising every parsed
  IPv6 address from the OpenConfig payload, with the comment on line
  649 ("Link-local scope is not yet inferred from the wire").  The
  underlying NETCONF schema does carry this distinction (separate
  ``link-local-addresses`` container under ``ietf-ip``); the parser
  just isn't reading it.
* **Likely fix location:**
  ``netconfig/migration/codecs/cisco_iosxe/codec.py`` line 840 —
  infer ``scope="link-local"`` when ``ip.startswith("fe80")`` or when
  the address sits under the ``link-local-addresses`` schema branch.
  The render path to NETCONF should emit under the matching schema
  branch when ``scope == "link-local"``.
* **Test that catches it:** add a
  ``test_ipv6_link_local_scope_preserved`` case to
  ``tests/integration/migration/test_cisco_iosxe_codec.py`` covering
  both the ``fe80::`` heuristic and the explicit schema-branch path.

---

## Cross-cutting patterns (sorted by appearance)

1. **L2 switching emission gap on Junos** (Patterns A + B + part of E):
   Junos render is L3-only.  The single largest codec-bug source for
   ``cisco_iosxe_cli`` (and almost certainly the dominant source for
   ANY L2-bearing source codec into Junos).  Adding ``family
   ethernet-switching`` + ``ae<N>`` aggregated-ethernet emission would
   resolve **22 of the 25** Junos findings here, plus likely
   most of the 32 ``juniper_junos → mikrotik_routeros`` findings and
   parts of the cross-vendor mesh that flow through Junos.
2. **Native-vlan suppression on Arista render** (Pattern E):
   ``trunk_native_vlan`` round-trips cleanly through Arista parse
   but the render side discards it.  One-line fix.
3. **Hyphen-bearing port-name parsing on Aruba** (Pattern G):
   port-range detection over-eagerly splits any token containing
   ``-``.  Affects every cross-vendor source whose LAG name (or
   non-trivial port name) contains a hyphen.
4. **IPv6 link-local scope discarding on Cisco NETCONF parse**
   (Pattern H): one-line constant.
5. **opnsense interface-name case folding** (Pattern D): codec
   choice — fix or reclassify as ``EXPECTED_LOSSY``.

## See also

* ``tests/fixtures/real/PHASE4_RECONCILIATION.md`` — the parent report.
* ``tests/fixtures/real/_phase4_runs/latest.json`` — raw input.
* ``tests/fixtures/cross_vendor_expectations/cisco_iosxe_cli__*.yaml``
  — the seven Phase-3 pair expectation YAMLs that drove the
  classifier; none require corrections off the back of this
  investigation (every CODEC_BUG is a real codec gap, not a
  doc-grounding error).
