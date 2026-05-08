# Phase 4b findings — source codec ``cisco_iosxe_cli``

Triage of every ``CODEC_BUG`` field-cell where ``source_codec ==
"cisco_iosxe_cli"`` in
``tests/fixtures/real/_phase4_runs/latest.json`` (Phase 4 run
2026-05-03T20:35:17Z).

* **Total CODEC_BUG findings:** 19 across 3 source fixtures and
  6 target codecs.
* **Source fixtures:**
  ``tests/fixtures/real/cisco_iosxe/batfish_cisco_interface.txt`` (3),
  ``tests/fixtures/real/cisco_iosxe/racc_cat8000v_iosxe179_netconf.txt`` (1),
  ``tests/fixtures/real/cisco_iosxe/user_contrib_cat9300_iosxe1712.txt`` (5),
  ``tests/fixtures/synthetic/cisco_iosxe_cli/kitchen_sink.txt`` (10).

| Target codec  | CODEC_BUG count |
|---|---:|
| ``juniper_junos`` | 7 |
| ``arista_eos`` | 4 |
| ``opnsense`` | 3 |
| ``fortigate_cli`` | 2 |
| ``aruba_aoss`` | 2 |
| ``cisco_iosxe`` (NETCONF) | 1 |

## Bucket totals

| Bucket | Definition | Count |
|---|---|---:|
| **A — real codec bug** | Symmetric round-trip should preserve the field; locus identifiable in a target codec's parse or render. | 11 |
| **B — stale YAML** | Field genuinely degrades cross-vendor; YAML disposition should be ``lossy`` / ``unsupported`` (or sub-fielded). | 6 |
| **C — acceptable / methodology** | Drift is by-design (documented rename, structural collapse) and the comparator should not flag it. | 2 |

The dominant finding is a single **A** root-cause: every non-cisco_iosxe_cli target codec parser fails to call ``project_switchport_to_vlan(intent)`` after parsing per-interface ``switchport`` state. The cisco_iosxe_cli parser projects per-interface switchport into the VLAN-centric ``vlans[].tagged_ports`` / ``untagged_ports`` lists; the target codecs (arista_eos, aruba_aoss, juniper_junos) only populate per-interface fields on re-parse, leaving the VLAN-centric list empty even though the L2 graph survived. Six of the eleven A-bucket findings collapse to that single missing call.

---

## ``cisco_iosxe_cli → arista_eos`` (4 CODEC_BUG)

| Fixture | Field | Drift detail | Bucket | Recommendation |
|---|---|---|---|---|
| ``user_contrib_cat9300_iosxe1712.txt`` | ``vlans`` | All ``tagged_ports`` / ``untagged_ports`` lists empty on target; per-interface switchport survives. | A | Add ``project_switchport_to_vlan(intent)`` to ``codecs/arista_eos/parse.py`` after the interface loop. |
| ``batfish_cisco_interface.txt`` | ``vlans`` | Same root cause: VLAN-centric port lists drop on re-parse. | A | Same as above. |
| ``kitchen_sink.txt`` | ``vlans`` | VLAN-centric ``tagged_ports`` / ``untagged_ports`` AND ``vlans[].ipv4_addresses`` (SVI absorption) drop on target. | A (ports) + A (SVI) | Same projection fix; additionally ``arista_eos`` parse must absorb ``interface Vlan<N> / ip address`` into ``CanonicalVlan.ipv4_addresses`` (mirror the aruba_aoss ``absorbs_svi_into_vlan`` pattern). |
| ``kitchen_sink.txt`` | ``radius_servers`` | Source has 2 RADIUS servers; target has 0. Arista codec has no radius parse / render at all. | B | YAML ``cisco_iosxe_cli__arista_eos.yaml`` line 244 says ``radius_servers: good``. Demote to ``unsupported`` until Arista codec wires ``radius-server host`` parse + render. |

## ``cisco_iosxe_cli → juniper_junos`` (7 CODEC_BUG)

| Fixture | Field | Drift detail | Bucket | Recommendation |
|---|---|---|---|---|
| ``batfish_cisco_interface.txt`` | ``lags`` | ``Port-channel1`` → ``ae1`` rename flagged as drift on whole-record name comparison. | C | YAML lags note (line 538) explicitly documents this rename. Either split ``lags[].name`` into a sub-field ``lossy`` (consistent with ``interfaces[].name`` shape) so the rename doesn't poison the whole-record comparison, OR teach the comparator to skip ``name`` on records whose ``members`` set is identical. |
| ``user_contrib_cat9300_iosxe1712.txt`` | ``vlans[].tagged_ports`` | All tagged_ports drop on target (junos parse doesn't project switchport). | A | Add ``project_switchport_to_vlan(intent)`` to ``codecs/juniper_junos/parse.py``. |
| ``user_contrib_cat9300_iosxe1712.txt`` | ``vlans[].untagged_ports`` | Same root cause as above. | A | Same fix. |
| ``user_contrib_cat9300_iosxe1712.txt`` | ``lags`` | Port-channel<N> → ae<N> rename. | C | Same as batfish lags above. |
| ``kitchen_sink.txt`` | ``vlans[].tagged_ports`` | All tagged_ports drop. | A | Same projection fix. |
| ``kitchen_sink.txt`` | ``vlans[].untagged_ports`` | All untagged_ports drop. | A | Same projection fix. |
| ``kitchen_sink.txt`` | ``lags`` | Port-channel<N> → ae<N> rename. | C — duplicate of above. | Same as batfish lags. |

## ``cisco_iosxe_cli → opnsense`` (3 CODEC_BUG)

| Fixture | Field | Drift detail | Bucket | Recommendation |
|---|---|---|---|---|
| ``batfish_cisco_interface.txt`` | ``interfaces[].ipv6_addresses`` | Source has 2 v6 addresses (global + link-local); target has 1. | B | OPNsense's ``<ipaddrv6>``/``<subnetv6>`` schema accepts only one IPv6 per zone. YAML ``cisco_iosxe_cli__opnsense.yaml`` line 251 says ``good``; demote to ``lossy`` with rationale "single-address-per-zone XML schema". |
| ``user_contrib_cat9300_iosxe1712.txt`` | ``interfaces[].description`` | Source description is empty; target carries ``"Management"``. | B | Cisco source's ``vrf forwarding Mgmt-vrf`` correctly promotes ``iface.kind="mgmt"``; opnsense render then synthesises ``<descr>Management</descr>`` (commit ``b0a9596``). The synthesis is intentional. YAML line 212 says ``good``; either demote to ``lossy`` ("kind=mgmt cascade synthesises a Management description") or teach the comparator to ignore description drift on records with ``kind="mgmt"``. |
| ``kitchen_sink.txt`` | ``interfaces[].ipv6_addresses`` | Same single-v6-per-zone schema limit. | B — duplicate. | Same demote. |

## ``cisco_iosxe_cli → fortigate_cli`` (2 CODEC_BUG)

| Fixture | Field | Drift detail | Bucket | Recommendation |
|---|---|---|---|---|
| ``racc_cat8000v_iosxe179_netconf.txt`` | ``domain`` | Source ``cisco.com`` → target empty. | A | FortiGate render emits ``set domain "<x>"`` (render.py line 450) but FortiGate parse doesn't read it back into ``intent.domain`` (parse.py only handles per-DHCP-pool ``set domain``, line 707). Add a ``config system dns`` → ``set domain`` parse branch to populate ``intent.domain``. |
| ``kitchen_sink.txt`` | ``domain`` | Same root cause: ``kitchensink.example.com`` round-trip drops on FortiGate re-parse. | A — duplicate. | Same fix. |

## ``cisco_iosxe_cli → aruba_aoss`` (2 CODEC_BUG)

| Fixture | Field | Drift detail | Bucket | Recommendation |
|---|---|---|---|---|
| ``user_contrib_cat9300_iosxe1712.txt`` | ``vlans`` | All VLAN-centric port lists drop on target. | A | Aruba's ``absorbs_svi_into_vlan`` infrastructure suggests its parse already projects switchport, but evidence here says otherwise — add / verify ``project_switchport_to_vlan(intent)`` in ``codecs/aruba_aoss/parse.py``. |
| ``kitchen_sink.txt`` | ``vlans`` | Same root cause. | A — duplicate. | Same fix. |

## ``cisco_iosxe_cli → cisco_iosxe`` NETCONF (1 CODEC_BUG)

| Fixture | Field | Drift detail | Bucket | Recommendation |
|---|---|---|---|---|
| ``kitchen_sink.txt`` | ``interfaces[].ipv6_addresses`` | ``fe80::1`` round-trips with ``scope="global"`` instead of ``"link-local"``. | B | YAML ``cisco_iosxe_cli__cisco_iosxe.yaml`` line 280 says ``good``, but the same YAML's note (lines 286-288) explicitly states "Link-local scope discriminator is not yet inferred from the wire by either codec (treated as global)". Demote disposition to ``lossy`` and split into ``interfaces[].ipv6_addresses[].scope`` once that sub-field shape is supported by the comparator. |

---

## Top 3 recommended fixes

1. **Add ``project_switchport_to_vlan(intent)`` to non-cisco_iosxe_cli parsers**
   (``arista_eos``, ``aruba_aoss``, ``juniper_junos`` parse modules).
   Single one-line addition each; collapses 6 of 11 A-bucket findings to
   zero. Also unblocks ``cisco_iosxe_cli__arista_eos`` SVI absorption when
   paired with the next fix.

2. **Wire FortiGate ``config system dns`` → ``set domain`` parse branch**
   to populate ``intent.domain`` symmetrically with render.  Currently
   only DHCP-pool ``set domain`` is parsed.  Two-line fix in
   ``codecs/fortigate_cli/parse.py`` collapses 2 of the 11 A-bucket
   findings.

3. **Either teach the comparator to ignore documented LAG name renames
   (``Port-channel<N>`` ↔ ``ae<N>``) or split ``lags[].name`` into a
   sub-field ``lossy`` cell.**  The current whole-record comparator
   poisons three otherwise-clean cells with a rename that every YAML
   already documents.  Methodology-tier change, not a codec fix.

Stale-YAML batch (B) follow-ups: demote ``radius_servers`` to
``unsupported`` for the arista target; demote ``interfaces[].ipv6_addresses``
to ``lossy`` for opnsense + cisco_iosxe targets; carve out a
``kind="mgmt"`` description-synthesis exemption for opnsense.

## See also

- ``tests/fixtures/real/PHASE4_RECONCILIATION.md`` — Phase 4 cross-mesh
  matrix (top-20 pair-codec table; cisco_iosxe_cli row totals 19).
- ``tests/fixtures/real/_phase4_runs/latest.json`` — per-cell field
  variances (read this for the full ``drift_detail`` JSON behind every
  row above).
- ``tests/fixtures/cross_vendor_expectations/cisco_iosxe_cli__*.yaml`` —
  Phase 3 per-pair expectations (one per target).
- ``tests/fixtures/real/phase4_findings_arista_eos.md``,
  ``…_aruba_aoss.md``,
  ``…_cisco_iosxe.md``,
  ``…_fortigate_cli.md``,
  ``…_juniper_junos.md``,
  ``…_mikrotik_routeros.md``,
  ``…_opnsense.md`` — sibling source-vendor findings (parallel agents).
- ``netcanon/migration/canonical/transforms.py`` —
  ``project_switchport_to_vlan`` reference (the helper the non-cisco
  parsers should be calling).
