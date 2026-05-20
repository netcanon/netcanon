# Cisco NX-OS — fixture catalogue (2015+)

> **Tier**: Tier-D (codec design complete; implementation queued for v0.3.0)
> **Codec**: not yet implemented; design at
> [`docs/v0.2.0-planning/03-nxos-codec/`](../v0.2.0-planning/03-nxos-codec/)
> **Existing corpus**: 0 fixtures (no `tests/fixtures/real/nx_os/`
> directory yet; needs creation alongside Phase 1 PR + a new row in
> `_DIR_TO_CODEC_NAME` at
> [`tests/unit/migration/test_real_captures.py:80`](../../tests/unit/migration/test_real_captures.py))

This catalogue **extends** the concrete pull list at
[`docs/v0.2.0-planning/03-nxos-codec/05-fixture-targets.md`](../v0.2.0-planning/03-nxos-codec/05-fixture-targets.md)
(the planning artifact already enumerates 13 batfish-derived NX-OS
fixtures across two OS versions).  Where the planning doc names
specific files, this catalogue does **not** repeat the table — it
points there and adds the **non-batfish** pull-targets the planning
doc flags as "post-batfish" / "future work" (§ 4.6 of the planning
doc): NAPALM tests, NTC Templates, Cisco DevNet sandbox, ContainerLab
EVPN labs, vendor docs, forum threads, university lab handouts.

Per the source taxonomy in
[`00-source-analysis.md`](00-source-analysis.md), every entry below
notes its source class + apparent license + sanitisation effort
expected.

---

## Version timeline

NX-OS shipping versions and their relevance to the v0.3.0 codec
corpus.  The trains are platform-specific in NX-OS — unlike IOS-XE's
single linear train, the OS forked per Nexus chassis family early
on and then began consolidating around 9.x (single-image) from
2014 onward.

| NX-OS train | Years | Platforms (primary) | In planned corpus | Pull priority |
|---|---|---|---|---|
| **10.x** | 2022–present (10.1 → 10.5 GA) | N9K (single-image — N3K + N9K share image) | ✓ `nxos_n9kv_r1.txt` (10.3) | **P0** — current GA |
| **9.x** | 2014–present (9.2 → 9.3 → 9.4 → 9.5) | N9K + N3K | ✓ all batfish snapshots (9.2(3)) | **P0** — production majority |
| **8.x** | 2017–2024 | N7K (last N7K train) | ✗ | **P3** — rare; N7K-only |
| **7.x** | 2014–2020 | N5K + N6K + N7K + N9K (the bridge train) | ✗ | **P1** — most heavily-deployed legacy |
| **6.x** | 2013–2018 | N5K + N6K + N7K + early N9K | ✗ | **P2** — pre-EVPN, brownfield retrofit only |
| ≤ 5.x | pre-2013 | N5K + N7K | n/a (out of 2015+ window) | — |

Modern enterprise reality circa 2026:
* Greenfield datacenters: NX-OS 10.x on N9K (vPC + EVPN-VXLAN fabric)
* In-service production: NX-OS 9.3 / 9.4 dominates — the codec's
  primary target
* Brownfield / pre-EVPN: NX-OS 7.x on N7K + N5K (legacy STP / vPC
  designs, no VXLAN)
* End-of-life: NX-OS 6.x on N5K / older N7K — relevant only for
  retro-migration cases.  N7K hardware itself is end-of-sale.

The "8.x is rare" line is non-obvious to outsiders: 8.x was a
**N7K-only** branch parallel to 9.x's N9K-only branch — the
single-image consolidation that 10.x represents had not yet
happened.  Most operators on 7.x N7K either skipped 8.x entirely
(replacing the N7K with N9K + 9.x/10.x) or moved through 8.4 ⇒
End-of-Software-Maintenance.

---

## Pull-target inventory

> The batfish corpus + planning-doc § 1 already covers the bulk
> of the 9.2(3) + 10.3(9) requirements.  This catalogue focuses
> on **extending across more NX-OS versions** (7.x / 6.x / 8.x
> brownfield) and **filling the grammar gaps** the planning doc
> § 8 identifies (SNMP v2c, tunnels, OSPF, ISIS, QoS class/policy,
> ACLs, spanning-tree, SPAN/RSPAN, multi-VDC, hardware-N9K-specific
> breakout).

### 10.x (current modern N9K)

#### GitHub repositories

* **`batfish/lab-validation`** — Apache-2.0 —
  `https://github.com/batfish/lab-validation`
  * Already inventoried by planning doc § 1.  The 10.3(9) capture
    is `nxos_n9kv_ebgp/configs/r1/show_running-config.txt`.
  * **Extension target** (not in planning doc): the **r2** sibling
    in the same snapshot — symmetric pair, ~190 lines, validates
    eBGP peer-side rendering on the same OS version.
  * Source class: 1.1 (open-source repo, Apache-2.0).
  * Sanitisation: none — lab corpus, RFC1918 + RFC5737 only.

* **`yakiimo-bsp/n9kv-evpn-vxlan-lab`** — BSD-3-Clause —
  `https://github.com/yakiimo-bsp/n9kv-evpn-vxlan-lab`
  * 5 `.cfg` files under `/configs/`: `spine1.cfg`, `spine2.cfg`,
    `leaf1.cfg`, `leaf2.cfg`, `leaf3.cfg`.
  * 2-spine / 3-leaf Clos with iBGP underlay (OSPF reachability)
    + EVPN-over-VXLAN with ingress replication for BUM.
  * Apparent NX-OS version: 10.x (n9kv kind in ContainerLab; lab
    targets modern image).
  * Grammar coverage: complements batfish EVPN snapshots with a
    **3-leaf** scenario (batfish has only 2-leaf pairs) — useful
    for spine-side rendering invariants and route-reflector form.
  * Source class: 1.3 (lab platform — ContainerLab fixture).
  * Sanitisation: light — verify RFC1918 only, no PII expected.
  * **Priority: P0** for cert-tier promotion (gives an
    independent-author 10.x capture beyond batfish).

* **`netascode/nx-as-code`** (cisco/cisco-DevNet-affiliated) —
  apparent open-source — `https://developer.cisco.com/codeexchange/github/repo/netascode/nx-as-code/`
  * Mostly Terraform / YAML model files for declarative NX-OS;
    NOT raw `show running-config` output.
  * Source class: 1.2 / 1.3 (vendor-affiliated repo).
  * Use-as-input: low — would need transcoding via NX-API to get
    a `show running-config` capture; effort > batfish refetch.
  * **Discovery-only**, not a direct fixture target.

#### Forum / community posts

* **Cisco Community — Nexus 9000** subforum filtered for 10.x posts:
  * `https://community.cisco.com/t5/data-center-switches/bd-p/4561-discussions-dc-switches`
  * Examples (10.x discussion + `show running-config` snippets):
    * "Nexus 9000 show tech-support" thread (NX-OS 10.x — partial
      runs cited): `https://community.cisco.com/t5/network-management/nexus-9000-show-tech-support/td-p/3760616`
    * "Nexus 9K VRF Lite" (9.3 + 10.x discussion):
      `https://community.cisco.com/t5/routing/nexus-9k-vrf-lite/td-p/4689934`
  * Source class: 2.1 — forum-share precedent (operator-paste).
  * Sanitisation: **heavy** — re-verify all hostnames, IPs,
    password hashes per `NOTICE.md` workflow.
  * Quality signal: medium-high (operators usually paste partial
    runs, not full configs; reconstruction effort moderate).

#### Vendor docs / lab guides

* **Cisco Nexus 9000 Series NX-OS Fundamentals Configuration Guide
  Release 10.4** — vendor docs (CC-BY-style "example use" — verify
  per § 1.2).
  * `https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/104x/configuration/fundamentals/cisco-nexus-9000-nx-os-fundamentals-configuration-guide-104x/`
  * Embedded fragments in chapter "Working with Configuration Files".
  * Discovery-only — vendor doc fragments are short (10-30 line
    snippets); useful for grammar reference, not full round-trip
    fixtures.

* **Cisco Nexus 9000v Guide, Release 10.2** — virtual platform
  startup-config samples.
  * `https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/102x/configuration/n9000v/cisco-nexus-9000v-guide-102x/m-cisco-nexus-9000v.html`
  * Discovery-only — same caveat as above.

#### Other

* **Cisco DevNet "Open NX-OS Programmability" AlwaysOn Sandbox** —
  pre-provisioned Nexus 9000v on 10.x; SSH/HTTPS accessible without
  reservation.
  * `https://developer.cisco.com/docs/nx-os/`
  * Source class: 1.3 with Tier-4 caveat — sandbox EULA may forbid
    re-distribution of captured config.  Per planning doc § 4.1:
    **"do not commit without permission"**.  Operator should verify
    Cisco DevNet terms before checking in any captured config.
  * Use: discovery + grammar-validation only.

### 9.x (production majority — most operator captures)

#### GitHub repositories

* **`batfish/lab-validation`** — Apache-2.0 — primary source.
  * Planning doc § 1.1 enumerates 13 fixtures (8 verified + 5
    unfetched).  See planning doc for the per-snapshot grammar
    coverage; **do not duplicate the table here**.
  * Snapshots discovered (full list via web-fetch of GitHub tree):
    `nxos_static_route`, `nxos_hsrp`, `nxos_ebgp_loop_prevention`,
    `nxos_bgp_redist_connected`, `nxos_eigrp_neighbor`,
    `nxos_redistribution`, `nxos_evpn_l3vni`, `nxos_evpn_l2vni`,
    `nxos_l3_vlan_no_active_member`, `nxos_undefined_route_map`,
    `nxos_n9kv_ebgp`.

* **`napalm-automation/napalm`** — Apache-2.0 —
  `https://github.com/napalm-automation/napalm`
  * Per planning doc § 4.6: "high-value source for additional cert-
    tier fixtures".
  * Test data tree: `tests/nxos/mocked_data/test_get_facts/...` +
    `tests/nxos_ssh/mocked_data/test_get_facts/N93180/...`.
  * Note: test fixtures are predominantly **structured outputs**
    (`expected_result.json`) used to verify the driver's parsed
    return-shape, plus selected `show <command>` raw inputs.
    Full `show running-config` raw captures are limited — verify
    on a fixture-by-fixture basis before committing.
  * Apparent NX-OS version: 7.0(3) → 9.x range across fixtures
    (N93180 platform-name in path → N9K hardware).
  * Source class: 1.1, Apache-2.0.
  * Sanitisation: light — already structured lab data.
  * **Priority: P1** — would extend the corpus into N93180
    hardware vs. batfish's N9Kv.

* **`networktocode/ntc-templates`** — Apache-2.0 —
  `https://github.com/networktocode/ntc-templates`
  * 80+ command-specific test directories under
    `tests/cisco_nxos/` including `show_version`,
    `show_interface`, `show_vlan`, `show_vpc`, etc.
  * **No `show running-config` raw data** — fixtures are per-command
    text inputs paired with TextFSM templates + expected parsed
    YAML.  Useful for verifying individual stanza shapes but
    **not** for codec round-trip testing.
  * Source class: 1.1 (also referenced from § 3.6 — community
    awesome-list curation).
  * Use: **grammar validation** (e.g., confirm an
    `interface Ethernet1/1` line shape matches what real devices
    emit).  Not a round-trip fixture source.
  * **Priority: P3** — discovery / grammar reference only.

* **`CiscoTestAutomation/genieparser`** — Apache-2.0 —
  `https://github.com/CiscoTestAutomation/genieparser`
  * Cisco-maintained pyATS parser library; vast NX-OS test corpus
    under `src/genie/libs/parser/nxos/tests/`.
  * Test data is **per-command** like ntc-templates — same caveat.
  * Cross-reference value: confirm grammar surfaces match official
    Cisco-maintained parser expectations.
  * Source class: 1.1.
  * Use: grammar validation reference.
  * **Priority: P3** — discovery only.

* **`christung16/vxlan_in_a_box`** — BSD-3-Clause —
  `https://github.com/christung16/vxlan_in_a_box`
  * Vagrant-based lab; 2 × NX-OSv 9.2.3 instances with CVAC
    (Cisco Virtual Appliance Configuration) startup-config
    injection via CD-ROM.
  * Startup configs under `2_switches_cvac/`.
  * Grammar coverage: 2-node VXLAN (no EVPN — pre-9.3 cleartext
    VXLAN with manual multicast group config).  Complementary to
    batfish's BGP-EVPN VXLAN.
  * Source class: 1.3 (lab platform).
  * Sanitisation: light.
  * **Priority: P1** — fills a non-EVPN VXLAN gap.

* **`mpenning/ciscoconfparse`** — **GPL-3.0** — NOT compatible.
  * Has a `tests/fixtures/configs/sample_01.nxos` test file.
  * **Discovery-only**; do not commit (GPL-3 incompatible with
    permissive fixture pool).

* **`ansible-collections/cisco.nxos`** — **GPL-3.0+** — NOT compatible.
  * `https://github.com/ansible-collections/cisco.nxos`
  * Has unit-test fixtures under `tests/unit/modules/network/nxos/`.
  * **Discovery-only**; do not commit.  Useful as a grammar
    reference (the test fixtures show what Ansible expects to
    see from real NX-OS devices), but the license blocks import.

* **`nickrusso42518/racc`** — BSD-3 —
  `https://github.com/nickrusso42518/racc`
  * Per planning doc § 4.6 candidate.  Tested on "Cisco Nexus 3172T,
    version 6.0.2.U6.4a" + "Cisco Nexus 9000v, version 9.3(3)".
  * Repo is an Ansible-driven config-backup playbook — the **input**
    NX-OS configs are operator-provided; the repo itself does not
    ship sample running configs.
  * Use: tooling reference; not a fixture source directly.

#### Forum / community posts

* **Cisco Community Nexus subforums** (`community.cisco.com`):
  * Data Center Switches — Nexus 9000:
    `https://community.cisco.com/t5/data-center-switches/bd-p/4561-discussions-dc-switches`
  * Sample threads with operator-paste 9.x configs:
    * "Nexus 9K VXLAN evpn Help":
      `https://community.cisco.com/t5/data-center-switches/nexus-9k-vxlan-evpn-help/td-p/4007020`
    * "Nexus 9K - VRF Lite":
      `https://community.cisco.com/t5/routing/nexus-9k-vrf-lite/td-p/4689934`
    * Nexus OSPF passive interface (9.3(10) example):
      `https://community.cisco.com/t5/switching/nexus-ospf-passive-interface/td-p/3373851`
  * Source class: 2.1 (forum-share precedent — operator paste).
  * Sanitisation: **heavy** (15-30 min/fixture per § 00-source-
    analysis.md table).  Re-verify hostnames, IPs, hashes.
  * Quality signal: medium — operators typically paste
    `interface ...` / `router bgp ...` fragments, not full
    configurations.  Reconstruction effort = moderate.
  * **Priority: P2** — only worth it if it fills a grammar gap
    not covered by batfish (e.g., OSPF, multicast PIM, ACL,
    QoS class/policy-map).

* **`r/cisco`** + **`r/networking`** on Reddit:
  * `https://reddit.com/r/cisco`, `https://reddit.com/r/networking`
  * Source class: 2.2 — Reddit posts.
  * Sanitisation: heavy.
  * **Priority: P3** — discovery / inspiration only, per § 00-
    source-analysis.md guidance (Tier 2.2 = use as inspiration,
    draft synthetic).

* **Network Engineering Stack Exchange**:
  * `https://networkengineering.stackexchange.com/questions/tagged/nexus`
  * Source class: 2.3 — CC-BY-SA-licensed (attribution required).
  * Sanitisation: heavy but achievable.
  * **Priority: P3** — fragments only.

#### Vendor docs / lab guides

* **Cisco Nexus 9000 Series NX-OS VXLAN Configuration Guide,
  Release 9.3(x)** — VXLAN + EVPN reference (one of Cisco's
  primary cookbook sources):
  * `https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus9000/sw/93x/vxlan/configuration/guide/`
  * Embedded chapter snippets ~30-100 lines each.
  * Use: grammar reference; not commit-able as a full fixture.

* **Cisco DC validated design guides** (e.g., VXLAN BGP EVPN
  Multi-Site, Storage Networking with Nexus + ACI co-existence):
  * Available via Cisco.com (no login required for download).
  * Source class: 1.2 — vendor docs (CC-BY example use).
  * Discovery / reference only; PDF text, not raw config.

#### Other

* **packetcoders.io / packetswitch.co.uk / firewall.cx / aboutnetworks.net**
  — operator blogs (source class 2.4):
  * `https://www.packetcoders.io/how-to-build-a-nxos-9000v-based-evpn-vxlan-fabric/`
  * `https://www.packetswitch.co.uk/cisco-nexus-useful-commands/`
  * `https://www.firewall.cx/cisco/cisco-data-center/nexus-nx-os-commands-scripting-hints-and-tips.html`
  * `https://jtnetwork.io/cisco-nxos-tips-and-tricks/`
  * Use: discovery / synthetic-fixture inspiration only.

* **kd9cpb.com** — small-scale operator blog (e.g., NX-OS 10.1.2
  two-stage commit-confirm with Netmiko):
  * `https://kd9cpb.com/nxos-commit-confirm`
  * Tier 2.4 — use as inspiration only.

### 7.x (legacy N7K / N5K still in production)

Most operationally-relevant brownfield version.  No 7.x captures in
the batfish corpus (batfish only ships 9.2 + 10.3).

#### GitHub repositories

* **`napalm-automation/napalm`** — covered above; some fixtures
  predate the 9.x rewrite and target 7.x N9K (e.g., 7.0(3)I7.2
  shown in NX-OSv 9000 install guides — same bootstrap image is
  in early NAPALM test data).
  * **Priority: P1** for 7.x bracketing.

* **`jedelman8/nxos-ansible`** — Apache-2.0 —
  `https://github.com/jedelman8/nxos-ansible`
  * Historical (pre-Cisco-collection-fork) Ansible modules; some
    `tests/` fixtures from 7.x N9K targets.
  * **Likely outdated**; library archived as `cisco.nxos` collection
    superseded it.  Test fixtures may still be present.
  * Source class: 1.1.
  * **Priority: P2** — exploration warranted.

#### Forum / community posts

* **Cisco Community Nexus 7K subforum** — heavy 7.x discussion;
  N7K platform is N7K-only home for 7.x → 8.x trains:
  * `https://community.cisco.com/t5/data-center-switches/bd-p/4561-discussions-dc-switches`
    (filter for N7K)
  * Source class: 2.1.
  * **Priority: P2** — operator-paste reconstruction.

#### Vendor docs / lab guides

* **Cisco Nexus 9000 Series NX-OS Fundamentals Config Guide,
  Release 7.x** —
  `https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus9000/sw/7-x/fundamentals/configuration/guide/b_Cisco_Nexus_9000_Series_NX-OS_Fundamentals_Configuration_Guide_7x/`
  * Discovery only.

* **Cisco Nexus 7000 Series Virtual Device Context Configuration
  Guide 7.x / 8.x** —
  `https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus7000/sw/vdc/`
  * Has VDC-section snippets — addresses the **multi-VDC grammar gap**
    that planning doc § 4.5 flags.
  * Discovery only; full multi-VDC config still needs a real-world
    capture.

#### Other

* **`networkgeekstuff.com`** — operator blog with hands-on N7K
  walkthroughs:
  * `https://networkgeekstuff.com/networking/nexus-getting-started-examples-guide-part1-basics-vdc-vpc/`
  * Contains 7.x-style examples of VDC + vPC.  Synthetic-fixture
    inspiration for the **multi-VDC gap** (planning doc § 4.5).
  * Tier 2.4; use as inspiration only.

### 8.x (rare; N7K-only)

Single-platform train (N7K).  Low real-world deployment density
in 2026; mostly visible in archived configs from the N7K
end-of-software-maintenance migrations.

#### GitHub repositories

* No direct hits.  8.x configs found exclusively on vendor docs +
  operator forums (when they appear at all).

#### Forum / community posts

* Cisco Community Nexus 7K subforum — search for "8.4" + "N7K".
  Source class: 2.1.
  * **Priority: P3** — only pursue if a specific gap (e.g., FabricPath
    on N7K, multi-VDC under 8.x) needs validation.

#### Vendor docs / lab guides

* **Cisco Nexus 7000 Series VDC Configuration Guide 8.x**:
  `https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus7000/sw/vdc/config/cisco_nexus7000_vdc_config_guide_8x/managing-vdc.html`
  * Discovery only.

### 6.x retrospective

Earliest in-window train (2013–2018); pre-EVPN / pre-VXLAN era.
N5K and early N9K use cases.  Relevant only for retro-migration
work.

#### GitHub repositories

* **`napalm-automation/napalm`** — some early test fixtures
  reference 6.x device-class output (`Nexus 3172T, version
  6.0.2.U6.4a` per `nickrusso42518/racc` test history).
  * Source class: 1.1.
  * **Priority: P3** — only useful for codec defensive parsing
    (proving the codec handles version banners like `version
    6.0(2)`).

#### Vendor docs / lab guides

* **Cisco Nexus 9000 Series NX-OS Fundamentals Config Guide,
  Release 6.x**:
  `https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus9000/sw/6-x/fundamentals/configuration/guide/b_Cisco_Nexus_9000_Series_NX-OS_Fundamentals_Configuration_Guide/`
  * Discovery only.

#### Other

* **Internet Archive Wayback Machine** (`web.archive.org`) — for
  pre-2018 operator blogs that have since lapsed.
  * Source class: 3.4.
  * **Priority: P3** — discovery only.

---

## Grammar gaps to specifically target via this catalogue

Planning doc § 8 identifies these surfaces as **not present** in
the batfish corpus.  The non-batfish targets in this catalogue
should prioritise filling these:

| Gap | Best-fit source | Priority |
|---|---|---|
| `snmp-server community` (v2c) | Cisco Community 9.x threads + NAPALM tests | P1 |
| `interface Tunnel<N>` (GRE/IPIP) | Cisco Community + Cisco DC design guides | P2 |
| `router ospf` | Cisco Community Nexus OSPF threads | P1 |
| `router isis` | Cisco DC design guide PDFs | P3 (rare in DC) |
| `class-map` / `policy-map` (QoS) | Cisco Community + Cisco QoS design guide | P2 |
| `ip access-list` | Cisco Community + NAPALM tests | P1 |
| `spanning-tree` (BPDU guard, MST) | Cisco Community DC switches subforum | P1 |
| `monitor session` (SPAN/RSPAN/ERSPAN) | Cisco DC design guides | P2 |
| Multi-VDC | N7K-specific operator captures (community.cisco.com) | P3 (N7K EOL) |
| N9K hardware breakout | Real N9K vs. N9Kv — operator capture | P2 |

---

## Recommended pull priority order

Top 10 across versions.  Aligns with planning doc § 1 (which lists
the 8 batfish snapshots already verified + line-counted) — this
list **extends beyond** that, focusing on what the planning doc
calls "Phase 4.5" / post-batfish targets.

1. **`batfish/lab-validation` `nxos_static_route/D1`** (Apache-2.0,
   302 lines, 9.2(3)) — planning doc Phase 1 baseline.  Already
   verified.  **First fixture to commit**.
2. **`batfish/lab-validation` `nxos_hsrp/nxos1`** (Apache-2.0,
   337 lines, 9.2(3)) — planning doc Phase 2.  L2 + HSRP + iBGP
   surface.
3. **`batfish/lab-validation` `nxos_evpn_l3vni/NX-1`** (Apache-2.0,
   349 lines, 9.2(3)) — planning doc Phase 4.  EVPN L3VNI fabric.
4. **`batfish/lab-validation` `nxos_evpn_l2vni/NX-1`** (Apache-2.0,
   355 lines, 9.2(3)) — planning doc Phase 4.  EVPN L2VNI fabric.
5. **`batfish/lab-validation` `nxos_n9kv_ebgp/r1`** (Apache-2.0,
   191 lines, **10.3(9)**) — planning doc Phase 4 cert-tier.
   Sole 10.x capture in batfish — critical for 2-OS-version cert bar.
6. **`yakiimo-bsp/n9kv-evpn-vxlan-lab`** — 5 × n9kv `.cfg`
   (BSD-3-Clause, ~10.x).  Independent-author 10.x capture cluster
   — strengthens cert-tier corpus per `tests/fixtures/real/RESULTS.md`.
7. **`napalm-automation/napalm` `tests/nxos_ssh/mocked_data/...`**
   (Apache-2.0, 7.x-9.x N93180 hardware) — only N9K-hardware
   fixture available; closes the N9Kv-vs-N9K gap planning doc § 4.4
   flags.
8. **`christung16/vxlan_in_a_box`** (BSD-3-Clause, 9.2.3) —
   non-EVPN multicast VXLAN.  Complementary to batfish EVPN-only
   captures.
9. **Cisco Community Nexus OSPF / ACL / QoS threads** (forum-share,
   9.x) — fills grammar gaps that batfish leaves open (OSPF, ACL,
   class/policy-map).  Per-fixture heavy sanitisation required.
10. **`batfish/lab-validation` additional snapshots from § 1.2 of
    planning doc** (`nxos_redistribution/d3_eigrp`, `nxos_undefined_
    route_map`, etc.) — depth on redistribution + parser robustness
    edge cases.

Items 1-5 alone clear the planning-doc Phase-4 ship bar (≥3 captures
across ≥2 OS versions per `tests/fixtures/real/RESULTS.md` § "Certified
tier").  Items 6-10 are post-Phase-4 expansion targets.

---

## Out-of-scope

* **`mpenning/ciscoconfparse`** — GPL-3.0, has NX-OS test fixtures
  but **license incompatible**; reference-only.
* **`ansible-collections/cisco.nxos`** — GPL-3.0+, vast NX-OS
  fixture corpus under `tests/unit/modules/...`; **license
  incompatible**; reference-only.
* **`allenrobel/ndfc-evpn`** — GPL-3.0; **license incompatible**.
* **Cisco DevNet sandbox configurations** — sandbox-EULA may
  forbid commit per planning doc § 4.1 / § 7 license-audit table.
* **Production captures from operator consulting** — Tier 4 per
  `00-source-analysis.md`; off-limits without explicit consent.
* **NX-OS versions < 6.x** — outside the 2015+ window.
* **NX-OS ACI mode (APIC-managed)** — different management plane
  (REST + JSON to APIC, not CLI to switch).  Out of scope for
  the v0.3.0 CLI codec; planning doc § 8 Q1 defers NX-API/NETCONF
  variants entirely.
* **`netascode/nx-as-code`** — declarative YAML / Terraform input
  for NX-OS, not raw `show running-config` output.

---

## See also

* [`docs/v0.2.0-planning/03-nxos-codec/05-fixture-targets.md`](../v0.2.0-planning/03-nxos-codec/05-fixture-targets.md)
  — **primary fixture-pull manifest**.  Lists 13 batfish snapshots
  with per-file line counts, grammar coverage, phase assignment,
  and the fixture-commit recipe (curl URL + `wc -l` verification
  + `NOTICE.md` template + `_DIR_TO_CODEC_NAME` wire-up).
* [`docs/v0.2.0-planning/03-nxos-codec/01-grammar-survey.md`](../v0.2.0-planning/03-nxos-codec/01-grammar-survey.md)
  — per-stanza grammar inventory + IOS-XE delta table.  Useful
  for verifying that a community-sourced fragment exercises a
  novel grammar surface before sanitising / committing it.
* [`docs/v0.2.0-planning/03-nxos-codec/06-capabilities-matrix.md`](../v0.2.0-planning/03-nxos-codec/06-capabilities-matrix.md)
  — capability matrix; per-fixture-import the matrix should grow
  by the surfaces the fixture exercises.
* [`docs/fixture-research-2015/00-source-analysis.md`](00-source-analysis.md)
  — source-class taxonomy (Tier 1 / 2 / 3 / 4) with sanitisation
  expectations + license-confidence ranking.
* [`docs/fixture-research-2015/01-cisco_iosxe.md`](01-cisco_iosxe.md)
  — sister Cisco catalogue; many cross-vendor sources (batfish,
  NAPALM, NTC-Templates, Cisco Community) overlap.
* [`tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — provenance ledger; new `nx_os/` section needed when the first
  fixture lands.  Use planning doc § 5 "Fixture commit recipe" for
  the cookbook.
* [`tests/fixtures/real/WANTED.md`](../../tests/fixtures/real/WANTED.md)
  — operator-facing fixture-submission gap list; the NX-OS row
  here should mirror the gap table above.
* [`tests/unit/migration/test_real_captures.py:80`](../../tests/unit/migration/test_real_captures.py)
  — `_DIR_TO_CODEC_NAME` mapping; needs a new
  `"nx_os": "cisco_nxos"` row when the first fixture lands (the
  `test_every_fixture_dir_has_codec_mapping` guard will trip
  otherwise).
