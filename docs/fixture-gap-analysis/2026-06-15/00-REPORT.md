# Fixture-Gap Acquisition Report

_Generated 2026-06-15 by the `fixture-gap-hunt` multi-agent workflow (run wf_be87c53c-c67): 57 agents, 3.88M tokens, ~25 min._

> **⚠️ Verification caveat (post-run review by Claude).** These findings are agent-generated and
> **candidate URLs / licenses / grammar claims must be re-verified before any fixture is committed.**
> One specific claim repeated below is **contradicted by the code**: the executive summary asserts an
> `aruba_aoss` "parser bug" at `parse.py:278` ("requires `ip vrrp vrid N` but every real capture uses
> `vrrp vrid N`"). The code at that line uses `ip vrrp vrid` **deliberately**, with the docstring citing
> the *AOS-S 16.10 Advanced Traffic Management Guide*. Treat this as a **grammar discrepancy to confirm
> against the vendor CLI reference**, NOT a confirmed bug — do not patch the regex on this claim alone.
> Always smoke-test a candidate through `codec.parse()` before adding it to the corpus.

## Methodology

1. **Gap computation (ground-truth):** parsed every existing real fixture, ran each through its codec's `iter_xpaths()`, and diffed the union against each `CapabilityMatrix.supported` list. A *gap* = a surface the codec declares **supported** (or **lossy**) but **no real fixture exercises**.
2. **Search wave:** 11 per-codec mission planners -> ~34 targeted search missions -> web search + fetch + grammar-confirm, license-vetted against the Apache/MIT/BSD/CC0 + forum-share precedent (GPL / Juniper-DayOne / proprietary rejected).
3. **Synthesis:** per-codec dedup+rank, then a cross-cutting executive layer.

> Legend: **fetch** = license-clean + grammar-confirmed + sanitizable, ready to add; **investigate** = promising lead, not fully confirmed; **reject** = found but unusable.

---

## Fixture-Gap Acquisition — Executive Summary

Across the 11 codecs, **96 canonical surfaces are currently unverified** (no real-config fixture exercises them). The cross-codec hunt found license-clean, grammar-confirmed configs that make **58 of 96 (60%) addressable now**; the remaining **38 are blocked**, the large majority by license rather than non-existence (operators scrub SNMP/secrets; permissive VRF/IPv6-static captures are scarce).

### Cross-cutting themes (one config class unblocks many codecs)
- **SNMPv3 USM** (`v3-user` / `auth-passphrase` / `engine-id`) was the single most pervasive gap — unverified in **9 codecs** (arista, aoscx, aoss, iosxe, nxos, fortigate, junos, mikrotik, vyos). Now fillable in all but aoss (snippet-only) and opnsense (modern `<netsnmp>` grammar the parser can't read).
- **Management plane (SNMP community/contact/location/trap + NTP + DNS)** clusters together: MikroTik `quangproo/fpt/switch.rsc` and NX-OS `nautobot/demo-gc-backups` each hit 4–6 of these in one file.
- **VRRP / FHRP** unverified in 5 codecs (arista, aoss, fortigate, junos, mikrotik). FortiGate and Junos are cleanly fillable; **aoss is hard-blocked by a codec parser bug** (parse.py:278 requires `ip vrrp vrid N` but every real capture uses `vrrp vrid N`).
- **Static IPv6 address (`ip` + `prefix-length`)** unverified in 5 codecs — filled for aoscx (canu) and nxos (batfish), but **durably blocked for aoss / fortigate / mikrotik** (only snippets, CC-BY-SA, or unlicensed).
- **DHCPv6 client** (`dhcp-client-v6`) unverified in 6 codecs — fillable for iosxe, junos, vyos; blocked for arista (AVD only emits SLAAC), fortigate (redacted forum paste), mikrotik (unlicensed only).
- **EVPN type-5 routes** (lossy parse surface) in arista, junos, nxos — fillable for arista and junos (same `TsG8139` and AVD repos), open for nxos.
- **Tunnel-type** unverified in 5 codecs (arista, fortigate, junos, mikrotik, opnsense) — only junos (MNHA `st0`) and arista (AVD) are clean; the rest are unlicensed/rate-limited.

### Coverage scoreboard

| Codec | Gaps | Addressable | Blocked |
|---|---|---|---|
| cisco_iosxr | 1 | 1 | 0 |
| aruba_aoscx | 9 | 9 | 0* |
| arista_eos | 11 | 10 | 1 |
| cisco_nxos | 15 | 10 | 5 |
| juniper_junos | 10 | 8 | 2 |
| mikrotik_routeros | 12 | 6 | 6 |
| fortigate_cli | 11 | 6 | 5 |
| vyos | 11 | 5 | 6 |
| cisco_iosxe_cli | 6 | 3 | 3 |
| aruba_aoss | 6 | 0 | 6 |
| opnsense | 4 | 0 | 4 |
| **Total** | **96** | **58** | **38** |

\* aaoscx surfaces are individually covered but the default-VRF static-route + newer-train-campus *combination* has no clean banner-bearing capture.

### Best vs worst covered
- **Best:** `cisco_iosxr` (1/1, the lone gap closed by `ios-xr/design`), `aruba_aoscx` (9/9 surfaces individually covered), `arista_eos` (10/11 from a single AVD kitchen-sink), `cisco_nxos` (10/15).
- **Worst:** `opnsense` (0/4 — every gap requires a synthetic fixture or codec extension to `<netsnmp>`) and `aruba_aoss` (0/6 importable — the strongest blocker is the **`ip vrrp vrid` parser bug**, not source availability; SNMPv3/IPv6/NTP are snippet- or GPL-only). `cisco_iosxe_cli` (3/6) is held back by the anycast-gateway surfaces being NX-OS-dominated and SNMPv3 full-subtree files being scrubbed/proprietary.

### Headline takeaways for action
1. A handful of **multi-surface kitchen-sink files** (AVD `host1.cfg`, mikrotik `switch.rsc`, nxos SNMP + DAG files, fortigate VRRP pair, vyos SNMPv3) close ~35 of the 58 addressable surfaces — fetch these first.
2. **License cleanliness varies sharply:** arista (Apache-2.0), iosxe/junos (MIT/Apache), aoscx (MIT/Apache) are clean; the richest nxos and mikrotik fills are *unlicensed device-output* (factual-output precedent, lower preference) and several VRRP/IPv6 wins are forum-share — acceptable per NOTICE.md precedent but flag-and-sanitize.
3. **One codec fix unlocks a whole codec:** patching the aoss VRRP regex would convert grammar-confirmed forum captures from blocked → fetchable, materially improving the worst-covered codec.

---

## Prioritized acquisition actions

| # | Codec | Action | Rationale |
|---:|---|---|---|
| 1 | arista_eos | Fetch arista_avd_host1.cfg (raw.githubusercontent.com/aristanetworks/avd .../intended/configs/host1.cfg) for arista_eos | Maximum leverage x cleanest license x low effort: a single Apache-2.0 file closes 8 of arista's 11 gaps (SNMPv3 subtree, VRRP, IPv6 VARP, virtual-gateway-mac x2, DHCP pool, tunnel-type). Direct raw URL available; sanitization is mechanical (banner/secret/key-string/IPs). |
| 2 | mikrotik_routeros | Fetch quangproo/fpt/switch.rsc for mikrotik_routeros | Closes all 6 of MikroTik's addressable management-plane gaps (SNMP community/contact/location/trap + NTP + DNS) in one ROS7 export — converts the codec from 6/12 with scattered blocks to a single fetch. Effort low (direct raw URL). License is unlicensed device-output (lower preference): flag per NOTICE.md factual-output precedent and sanitize public IPs/email. |
| 3 | aruba_aoscx | Fetch cray_canu sw-spine-001-ipv6.cfg + batfish_nxos_ebgp_n9kv_r1.txt as the clean-license backbone for aoscx and nxos IPv6/VRF/static-route | canu (MIT) fills 5 aoscx surfaces and batfish r1 (Apache-2.0) fills 3 nxos surfaces — both top-tier licenses, direct raw URLs, minimal sanitization. Knocks out the static-IPv6 + VRF cluster cleanly for two codecs at once. Prefer these over the unlicensed nxos picks wherever surfaces overlap. |
| 4 | fortigate_cli | Extract fortinet_community VRRP pair (community.fortinet.com ta-p/197015) into a fixture for fortigate_cli | Strongest VRRP capture in the hunt — one PRIMARY/SECONDARY pair lights all four VRRP sub-fields (group/virtual-ips/track-interfaces/virtual-mac). Forum-share (acceptable precedent). Slightly higher effort because raw_file_url is empty (must transcribe from thread body) and vrdst placeholder needs RFC5737 sanitization, but the surface payoff is high. |
| 5 | juniper_junos | Fetch the three clean iosxe/junos DHCPv6+VRRP+SNMP snippets (epiecs VRRP-AFI + epiecs ipv6 autoconfig + networklore SNMPv3) for cisco_iosxe_cli, and TsG8139 evpn leaf02 + jnprautomate MNHA for juniper_junos | All MIT/Apache-2.0, direct raw URLs, low effort. junos jumps to 8/10 (dhcp-client-v6, evpn-type5, tunnel-type+groups, VRRP+subinterface, snmpv3+location). iosxe closes its 3 addressable gaps (vrrp address-family, dhcp-client-v6, snmp v3-user). Clean licenses make these zero-controversy fetches. |
| 6 | vyos | Fetch vyos forum SNMPv3 (forum.vyos.io t/6881) + Hou-dev DHCPv6-PD config.boot for vyos | Closes 5 vyos gaps (SNMPv3 user/auth/engine-id/location + dhcp-client-v6). Effort moderate: SNMPv3 must be hand-wrapped from a `show service snmp v3` fragment into a config.boot, and Hou-dev is unlicensed (flag/drop-if-objects) with xxxx:: placeholders to normalize. Add /snmp/contact synthetically while wrapping. |
| 7 | cisco_nxos | Fetch the unlicensed nxos VXLAN/DAG/SNMP/native-vlan set (akarneliuk mcast, goldenbyte static-IR, networklessons DAG symmetric-IRB, busterswt native-vlan, microsoft SDN MIT fallback) for cisco_nxos | Closes the remaining nxos addressable surfaces (vxlan mcast-group/source-iface/vni, flood-list, IPv4 DAG virtual-gateway, trunk-native-vlan). Lower in rank because most are unlicensed device-output (factual-output precedent, lower preference) requiring per-file sanitization of hashes/passwords; microsoft SDN is the only MIT-clean diversifier but partial. Fetch after the Apache/MIT-clean batfish r1 already taken in rank 3. |
| 8 | cisco_iosxr | Fetch the four ios-xr/design CST/Agile-Metro configs to close the lone cisco_iosxr 4th-port-segment gap | Closes iosxr to 1/1. Low effort (direct raw URLs) but ranked lower because it is a single surface already near-covered and the source has no LICENSE file (unlicensed device-output, factual-output precedent). Take pa3.cfg as primary; the others are diversity-only. |
| 9 | aruba_aoss | Defer aruba_aoss VRRP until the codec parser regex is fixed; in the interim fetch only the hpe_community 2920 DHCP-server-pool forum-share | aoss is the worst-covered codec but its biggest win (VRRP) is blocked by a CODE bug, not a source gap — parse.py:278 requires `ip vrrp vrid N` while every real capture uses `vrrp vrid N`. The only fetch-ready clean fill is the DHCP-server-pool forum-share (fills /dhcp-servers/pool). Flag the regex fix as a prerequisite engineering task that unlocks grammar-confirmed forum captures. |

---

## Cross-cutting picks (one file -> many gaps)

### arista_avd_host1.cfg (`arista_eos`)

- **Raw URL:** https://raw.githubusercontent.com/aristanetworks/avd/8510268901d4371ef636eae470ad4bc890a42fdc/ansible_collections/arista/avd/extensions/molecule/eos_cli_config_gen/intended/configs/host1.cfg
- **Fills:** `/snmp/v3-user`, `/snmp/trap-host`, `/snmp/contact`, `/snmp/location`, `/interfaces/interface/vrrp-groups/group`, `/interfaces/interface/ipv6/address/virtual-gateway-address`, `/interfaces/interface/ipv4/address/virtual-gateway-mac`, `/interfaces/interface/ipv6/address/virtual-gateway-mac`, `/dhcp-servers/pool`, `/interfaces/interface/tunnel-type`
- **Note:** Highest-leverage single file in the entire hunt: one Apache-2.0 AVD kitchen-sink closes 8 of arista's 11 gaps (SNMPv3 user/host/contact/location, classic VRRP, IPv6 VARP virtual-gateway-address, IPv4/IPv6 virtual-gateway-mac, DHCP server pool, tunnel-type). Clean license (repo-root + collection LICENSE both verbatim Apache-2.0, /license API spdx Apache-2.0). Sanitize AVD test banner, boot secret, vrrp peer auth key-string, and synthetic non-RFC5737 IPs before commit.

### quangproo_fpt_mgmt_plane_snmpv3_ntp_dns_ros7.rsc (`mikrotik_routeros`)

- **Raw URL:** https://raw.githubusercontent.com/quangproo/fpt/main/switch.rsc
- **Fills:** `/snmp/community`, `/snmp/contact`, `/snmp/location`, `/snmp/trap-host`, `/system/ntp-server`, `/system/dns-server`
- **Note:** Closes all 6 MikroTik management-plane gaps in one ROS7 /export — the densest single-file fill for mikrotik. License caveat: unlicensed public repo (factual device-output precedent, lower preference — flag, drop if author objects). Sanitize public IPs 92.92.92.x->RFC5737, contact email; confirm privacy-password= alias is accepted by the parser.

### ntc_goldenconfig_nxos_snmp_mgmt_jcyspine01_fos93.conf (`cisco_nxos`)

- **Raw URL:** https://raw.githubusercontent.com/nautobot/demo-gc-backups/main/jersey-city/jcy-spine-01.infra.ntc.com.cfg
- **Fills:** `/snmp/community`, `/snmp/contact`, `/snmp/location`, `/snmp/trap-host`
- **Note:** Only NX-OS source hitting all four SNMP surfaces in one block (9.3(3)). Unlicensed (factual device-output precedent). Sanitize SNMP-user hash lines + engineID before commit. Pairs with batfish_nxos_ebgp_n9kv_r1 (Apache-2.0, fills ipv6 addr + static-route/vrf) to cover most of nxos's management/IPv6 gaps.

### fortinet_community_vrrp_pair_197015.conf (`fortigate_cli`)

- **Fills:** `/interfaces/interface/vrrp-groups/group`, `/interfaces/interface/vrrp-groups/group/virtual-ips`, `/interfaces/interface/vrrp-groups/group/track-interfaces`, `/interfaces/interface/vrrp-groups/group/virtual-mac`
- **Note:** Strongest VRRP candidate across all codecs: a per-interface PRIMARY/SECONDARY pair (priority 255 vs 50) lights every VRRP sub-field (group, virtual-ips, track-interfaces, virtual-mac) in one forum-share capture (community.fortinet.com Technical-Tip). Forum-share license (acceptable per NOTICE.md precedent). raw_file_url empty — must be extracted from the thread body; sanitize vrdst placeholder x.x.x.x to RFC5737 (vrip is RFC1918, no plaintext auth).

### vyos_forum_snmpv3_user_eq13.conf (`vyos`)

- **Fills:** `/snmp/v3-user`, `/snmp/v3-user/auth-passphrase`, `/snmp/v3-user/engine-id`, `/snmp/location`
- **Note:** The unverified SNMPv3 USM prize for vyos, confirmed in BOTH curly and set-form (forum.vyos.io thread 6881). Forum-share license. raw_file_url empty — hand-wrap the `show service snmp v3` fragment into a service{} config.boot and sanitize the demo hash/engineid. Does NOT carry /snmp/contact (add synthetically when wrapping).

### cray_canu_aoscx_spine_vrf_dualstack_ipv6.cfg (`aruba_aoscx`)

- **Raw URL:** https://raw.githubusercontent.com/Cray-HPE/canu/main/tests/data/golden_configs/full_configs_custom_1.7/sw-spine-001-ipv6.cfg
- **Fills:** `/routing-instances/instance/name`, `/interfaces/interface/config/vrf`, `/routing/static-route`, `/interfaces/interface/ipv6/address/ip`, `/interfaces/interface/ipv6/address/prefix-length`
- **Note:** MIT golden-config closing 5 aoscx gaps at once (VRF instance + per-iface vrf attach + static-route + IPv6 SVI address/prefix). Caveat: it is a TEMPLATE (no !Version banner), so its default-VRF static route is the only license-clean source for that surface — pair with oxidized/datadog real captures for banner-bearing diversity.

### batfish_nxos_ebgp_n9kv_r1.txt (`cisco_nxos`)

- **Raw URL:** https://raw.githubusercontent.com/batfish/lab-validation/main/snapshots/nxos_n9kv_ebgp/configs/r1/show_running-config.txt
- **Fills:** `/interfaces/interface/ipv6/address/ip`, `/interfaces/interface/ipv6/address/prefix-length`, `/routing/static-route/vrf`
- **Note:** Best-license nxos pick (Apache-2.0, trusted batfish org, NEW 10.3(9) snapshot vs the 9.2(3) corpus). Confirms ipv6 address on mgmt0 + vrf-context management default-route. Prefer over the unlicensed nxos picks where surfaces overlap.

### jnprautomate_mnha_vsrx_st0_groups_junos.set (`juniper_junos`)

- **Raw URL:** https://raw.githubusercontent.com/JNPRAutomate/mnha-ipsec-and-multiple-routing-instances/main/full-configurations/mnha-vsrx-a.set
- **Fills:** `/interfaces/interface/tunnel-type`, `/groups`
- **Note:** MIT vSRX MNHA full-config filling two distinct junos gaps (tunnel-type via st0 + the /groups apply-groups surface) in one clean file. Clean MIT license, minimal sanitization.

---

## Donor-blocked surfaces (no permissive real config found)

| Codec | Surface | Why |
|---|---|---|
| vyos | `/routing-instances/instance/name` | DURABLE NEGATIVE (precedent-grade): a prior 2026-06 hunt found NO permissive curly-brace `vrf name` capture — all sources are GPL-3.0 vyos-1x or unlicensed. VRF stays synthetic; do not re-hunt without a new donor. This is the canonical donor-block precedent. |
| vyos | `/interfaces/interface/config/vrf` | Same VRF durable negative: per-interface `vrf` only appears inside the (unavailable) permissive `vrf name` captures. |
| opnsense | `/snmp/contact` | No public legacy <snmpd> file carries a non-empty <syscontact>; the only populated example uses the modern <netsnmp> grammar the parser does not read. Requires a synthetic fixture or a codec extension to <netsnmp>. |
| opnsense | `/snmp/location` | Same root cause as /snmp/contact — all real legacy <snmpd> exports have empty <syslocation/> stubs. Synthetic required. |
| opnsense | `/snmp/trap-host` | No public file emits <traphost>, and the modern <netsnmp> grammar has no trap-host element at all — so even a codec extension would not unlock it from a real config. Synthetic required. |
| cisco_nxos | `/routing-instances/instance/description` | DURABLE NEGATIVE: gh regex `vrf context <name>` + nested `description` = 0 hits across ~10 real configs; NX-OS operators rarely describe VRFs. The only nested-description source is a CLI cheatsheet (rejected). Source synthetically (kitchen_sink has it) or accept as NX-OS-rare. |
| cisco_nxos | `/system/raw-sections/vdc` | No VDC (`vdc … id` / `limit-resource`) block exists in any lab capture — n9kv/containerlab images are single-VDC. Likely needs a physical multi-VDC chassis capture; synthetic-only for now. |
| cisco_nxos | `/interfaces/interface/ipv4/address/virtual-gateway-address (license-clean form)` | LICENSE hard-negative: NX-OS DAG grammar `fabric forwarding anycast-gateway-mac` returns TOTAL=0 under apache/mit/bsd/isc filters — zero permissively-licensed DAG configs on GitHub. The surface IS addressable via the networklessons UNLICENSED candidate; only the permissive-license variant is donor-blocked. |
| cisco_iosxe_cli | `/anycast-gateway-mac and /interfaces/interface/ipv4/address/virtual-gateway-address` | No OSS IOS-XE file emits `fabric forwarding mode anycast-gateway`; the token is NX-OS-dominated (all ~28 code hits carry feature/nve1/member-vni = cisco_nxos). IOS-XE SD-Access/LISP-VXLAN running-configs are absent from code-searchable OSS; web hits are © Cisco docs only. Do not re-hunt the bare token without an IOS-XE-exclusive co-marker (l2vpn evpn instance / dynamic-eid / instance-id). |
| aruba_aoss | `/snmp/v3-user (full auth-sha/priv-aes USM form)` | The full USM form is confirmed only in a partial airheads snippet (not a full running-config); license-clean full configs carry only the bare noAuthNoPriv form. Promotable only via a hand-authored fixture seeded from the airheads grammar. |
| aruba_aoss | `/interfaces/interface/ipv6/address/ip + /prefix-length` | Grammar confirmed only in a oneuptime one-line snippet; no source combines an IPv6 SVI with anything importable into a full running-config. Snippet-only, no full-config capture exists publicly. |
| fortigate_cli | `/interfaces/interface/ipv6/address/ip + /prefix-length` | Only a forum-share KB block (vendor Technical-Tip, not a running-config) or CC-BY/blog (rejected) carries the IPv6 grammar; no fetch-grade clean-licensed full config exists. |
| mikrotik_routeros | `/interfaces/interface/ipv6/address/ip + /prefix-length` | Addressable only via investigate-grade leads: unlicensed pool-derived ::1 (kcleong/valeriansaliou) or CC-BY-SA-4.0 static 2001:db8 GUA (feichay10). No permissive-license static-GUA-on-plain-interface capture. |
| mikrotik_routeros | `/interfaces/interface/tunnel-type` | DURABLE NEGATIVE (2026-06-15): no license-clean /export with a real gre/eoip/ipip tunnel — only a marginal 6to4/6rd lead (unlicensed) or GPL-3.0 script libs (eworm/floeff). Synthesize or accept the 6to4 marginal fill. |
| juniper_junos | `/dhcp-servers/pool` | DOCUMENTED NEGATIVE for a license-clean source: the only dhcp-local-server config found is unlicensed (KSkrede/Networking); Batfish (Apache-2.0) has no dhcp-local-server in any junos testconfig (relay-only / vyos). |
| arista_eos | `/interfaces/interface/dhcp-client-v6` | No permissive Arista source emits the literal `ipv6 address dhcp` (DHCPv6 client prefix pull); AVD only emits SLAAC `ipv6 address auto-config` or static IPv6. Needs a real branch/CPE/edge capture (forum-share or unlicensed device-output), not AVD-generated lab output. |

---

## Per-codec detail

## arista_eos

11 gap surfaces unverified by the existing fixture corpus (9 supported-but-unverified + 2 lossy-unverified). A single Apache-2.0 source — the AVD `eos_cli_config_gen` molecule kitchen-sink `host1.cfg` — covers 8 of the 11 across SNMPv3, VRRP/VARP, DHCP-server, and tunnel surfaces; two dedicated AVD example leaves add EVPN type-5 and the IPv6 underlay. The lone genuinely-unfilled sub-surface is the literal `ipv6 address dhcp` (DHCPv6 client prefix pull), which no permissive Arista source carries.

### Gap surface → best candidate

| Gap surface | Best candidate | Rec | License |
|---|---|---|---|
| `/snmp/v3-user` | `arista_avd_host1.cfg` (AVD) | fetch | Apache-2.0 |
| `/snmp/trap-host` | `arista_avd_host1.cfg` (AVD) | fetch | Apache-2.0 |
| `/snmp/contact` | `arista_avd_host1.cfg` (AVD) | fetch | Apache-2.0 |
| `/snmp/location` | `arista_avd_host1.cfg` (AVD) | fetch | Apache-2.0 |
| `/interfaces/interface/vrrp-groups/group` | `arista_avd_host1.cfg` (AVD) | fetch | Apache-2.0 |
| `/interfaces/interface/ipv6/address/virtual-gateway-address` | `arista_avd_host1.cfg` (AVD) | fetch | Apache-2.0 |
| `/interfaces/interface/ipv4/address/virtual-gateway-mac` *(lossy)* | `arista_avd_host1.cfg` (AVD) | fetch | Apache-2.0 |
| `/interfaces/interface/ipv6/address/virtual-gateway-mac` *(lossy)* | `arista_avd_host1.cfg` (AVD) | fetch | Apache-2.0 |
| `/dhcp-servers/pool` | `arista_avd_host1.cfg` (AVD) | fetch | Apache-2.0 |
| `/interfaces/interface/tunnel-type` | `arista_avd_host1.cfg` (AVD) | fetch | Apache-2.0 |
| `/evpn-type5-routes/route` *(lossy)* | `arista_avd_dual_dc_l3ls_dc1leaf1a.cfg` (AVD) | fetch | Apache-2.0 |
| `/interfaces/interface/dhcp-client-v6` | `arista_avd_host1.cfg` (`ipv6 address auto-config`) — **SLAAC, not literal `ipv6 address dhcp`** | investigate | Apache-2.0 |

> Note: `/interfaces/interface/dhcp-client-v6` is listed in the gap set and is the only surface with **no clean fetch-grade match**. The closest permissive grammar is AVD's `ipv6 address auto-config` (SLAAC) in `host1.cfg` and static IPv6 underlay in `single-dc-l3ls-ipv6`; neither emits the literal DHCPv6-client `ipv6 address dhcp` keyword. See dead ends.

### Ranked candidates (grammar-confirmed, fetch-recommended first)

**1. `arista_avd_host1.cfg`** — the prize file (covers 8 surfaces) *(de-duplicated: appeared in M1, M2, M3)*
- Source: https://github.com/aristanetworks/avd/blob/devel/ansible_collections/arista/avd/extensions/molecule/eos_cli_config_gen/intended/configs/host1.cfg
- Raw (pin a commit SHA, M1 used `8510268901d4371ef636eae470ad4bc890a42fdc`): https://raw.githubusercontent.com/aristanetworks/avd/8510268901d4371ef636eae470ad4bc890a42fdc/ansible_collections/arista/avd/extensions/molecule/eos_cli_config_gen/intended/configs/host1.cfg
- License: **Apache-2.0** — repo-root `LICENSE` + collection `ansible_collections/arista/avd/LICENSE`, both verbatim "Apache License Version 2.0, January 2004"; GitHub `/license` API → `Apache-2.0`.
- OS version: EOS feature set 4.27+ (version-agnostic AVD-generated `intended` config; no `!Software image version` banner).
- Surfaces filled: `/snmp/v3-user`, `/snmp/trap-host`, `/snmp/contact`, `/snmp/location`, `/interfaces/interface/vrrp-groups/group`, `/interfaces/interface/ipv6/address/virtual-gateway-address`, `/interfaces/interface/ipv4/address/virtual-gateway-mac`, `/interfaces/interface/ipv6/address/virtual-gateway-mac`, `/dhcp-servers/pool`, `/interfaces/interface/tunnel-type`.
- Confirmation: carries `snmp-server contact/location` + both cleartext and `localized <engineid>` v3 USM users + v3-priv/v3-auth/v2c trap hosts; modern multi-line `vrrp <id> ipv4 / priority-level / preempt / tracked-object` on SVIs + routed Ethernet/Port-Channel; `ipv6 address virtual` + global `ip virtual-router mac-address`; full `dhcp server` mode block (subnet/range/dns server/lease/default-gateway) across VRFs; `tunnel mode ipsec`/`tunnel mode gre`. 7833-line kitchen-sink — harvest focused slices. Sanitize: AVD test-comment banner, `boot secret 5 …`, `vrrp … peer authentication … key-string 0 auth_key`, and synthetic non-RFC5737 lab IPs (1.1.1.1/4.4.4.4/6.6.6.6/42.42.42.42) → published lab placeholders before commit.

**2. `arista_avd_dual_dc_l3ls_dc1leaf1a.cfg`** — EVPN type-5 IP-VRF (lossy parse fixture)
- Source: https://github.com/aristanetworks/avd/blob/devel/ansible_collections/arista/avd/examples/dual-dc-l3ls/intended/configs/dc1-leaf1a.cfg
- Raw: https://raw.githubusercontent.com/aristanetworks/avd/devel/ansible_collections/arista/avd/examples/dual-dc-l3ls/intended/configs/dc1-leaf1a.cfg
- License: **Apache-2.0** — same `aristanetworks/avd` repo-root + collection `LICENSE`, verified verbatim.
- OS version: EOS 4.24+ (EVPN type-5 / symmetric IRB mature 4.24+; AVD-generated).
- Surfaces filled: `/evpn-type5-routes/route` *(lossy — render-side drops; value is a PARSE fixture that populates the surface)*.
- Confirmation: `router bgp 65101` `vrf VRF10/VRF11` with `rd`, `route-target import/export evpn`, `redistribute connected`, plus IRB binding `vxlan vrf VRF10 vni 10` + `ip routing vrf VRF10`. Distinct from the L2-only corpus leaf. Clean RFC1918/RFC5737 addressing; only synthetic `password 7 …` BGP hashes to scrub.

### Investigate-only / lower-preference leads (do NOT promote to fetch)

- **`gns3_autodeploy_arista_leaf1` (M1 SNMPv3)** — https://github.com/evanrogers15/gns3_auto_deploy/blob/master/modules/configs/arista/Old/arista-leaf1 · **unlicensed** (GitHub `/license` 404; factual-device-output precedent only, lower preference). Fills `/snmp/v3-user`, `/snmp/trap-host`, `/snmp/location` but **MISSING `/snmp/contact`** so it does not fill all four SNMP surfaces; carries real-looking sha256/aes hashes + default `public`/`private` communities to scrub. Superseded by AVD `host1.cfg` on every surface. **investigate.**
- **`ceoslab_vrrp_gateway_pair_s1` (M2 VRRP)** — https://github.com/pd1608/ANAproject/blob/master/netapp/golden_configs/s1_golden_20251013_205730.cfg · **unlicensed** (`.license == null`; factual-output precedent only). A realistic cEOS gateway PAIR (s1+s2, shared VIP, active/standby priorities) on EOS-4.34.2F — *above* the 4.21-4.30 window though grammar is identical. IPv4 VRRP only (no IPv6 VARP, no `ip virtual-router mac-address`), so fills fewer surfaces than AVD. Contains a **real `secret sha512 $6$…` credential hash that MUST be scrubbed**. **investigate** — use only if a realistic VRRP-pair capture is wanted beyond the AVD slice.
- **`arista_avd_single_dc_l3ls_ipv6_dc1leaf1a.cfg` (M3)** — https://github.com/aristanetworks/avd/blob/devel/ansible_collections/arista/avd/examples/single-dc-l3ls-ipv6/intended/configs/dc1-leaf1a.cfg · **Apache-2.0**. Static IPv6 underlay (`ipv6 address 2001:db8::…/64`) — does NOT emit `ipv6 address dhcp` or `auto-config`, so it does not fill the DHCPv6-client surface; useful only as a static-IPv6 EOS fixture. **investigate.**

### Dead ends / blocked

- **`/interfaces/interface/dhcp-client-v6` (literal `ipv6 address dhcp`)** — NOT FOUND in any Apache/MIT Arista source across all 3 missions. AVD only emits `ipv6 address auto-config` (SLAAC) or static IPv6; the literal DHCPv6-client upstream-prefix-pull keyword likely needs a real branch/CPE/edge capture (forum-share / unlicensed device-output), not AVD-generated lab output. **Genuinely unfilled — needs a new hunt with a real-capture donor.**
- **GPL-3.0 hard reject — `ansible-collections/arista.eos`** (M1): perfect SNMPv3 grammar (`snmp-server host … version 3 priv`, `contact`, `group … v3`) but LICENSE is GNU GPL v3 (web summaries calling it Apache-2.0 are wrong — verified directly). On the codec's no-list; mirror copies under `deepin-community/ansible` and `AA-Turner/top-pypi-sdists-2000` inherit the same GPL. **Do not re-hunt this source.**
- **Proprietary docs/blogs** — Arista official `um-eos` VRRP/VARP/Sample-Configurations pages and oneuptime.com show ideal grammar (incl. dual-stack `ipv6 address virtual` SVIs) but are all-rights-reserved docs/blog prose. Usable as grammar reference only, **reject for import.** The `um-eos` Sample Configurations page has no dhcp-server/tunnel/ipv6-dhcp examples (EVPN/MLAG only).
- **`ntc-templates` arista_eos** — test data is `show snmp` / `show snmp community` / `show vrrp` COMMAND OUTPUT, not running-config `snmp-server`/`interface … vrrp` syntax → wrong grammar for this codec; no `show running-config`/`show ip dhcp`/`show interfaces tunnel` dirs.
- **Legacy `ip dhcp pool` (Cisco-style)** — GitHub code-search for the token returned only Cisco IOS/IOS-XE configs; modern EOS 4.22+ uses the `dhcp server` mode block (correctly captured in AVD `host1.cfg`), so this axis is a non-issue, not a gap.
- **Partial exhaustion (non-blocking):** GitHub `search/code` API hit punishing rate limits (~10/min, frequent 403) — the IPv6-VARP-on-SVI code-search axis (`"ipv6 address virtual"` + `"ip virtual-router mac-address"` + `"interface Vlan"`) was blocked before returning and is only partially exhausted; AVD already fills those surfaces, so a future authenticated pass is optional, not required.

## cisco_nxos

15 supported-but-unverified canonical surfaces (12 supported + 3 lossy-unverified). Of these, **10 are addressable** with at least one grammar-confirmed, fetch-recommended candidate; 5 remain blocked (no real-capture source located — durable negatives for VRF description, EVPN type-5, and the two raw-section lossy surfaces).

### Gap surfaces → best candidate

| Gap surface | Best candidate | License | OS ver | Status |
|---|---|---|---|---|
| `/snmp/community` | `ntc_goldenconfig_nxos_snmp_mgmt_jcyspine01_fos93.conf` (nautobot/demo-gc-backups) | none (device-output) | 9.3(3) | fetch |
| `/snmp/contact` | `ntc_goldenconfig_nxos_snmp_mgmt_jcyspine01_fos93.conf` (nautobot/demo-gc-backups) | none (device-output) | 9.3(3) | fetch |
| `/snmp/location` | `ntc_goldenconfig_nxos_snmp_mgmt_jcyspine01_fos93.conf` (nautobot/demo-gc-backups) | none (device-output) | 9.3(3) | fetch |
| `/snmp/trap-host` | `ntc_goldenconfig_nxos_snmp_mgmt_jcyspine01_fos93.conf` (nautobot/demo-gc-backups) | none (device-output) | 9.3(3) | fetch |
| `/interfaces/interface/ipv6/address/ip` | `batfish_nxos_ebgp_n9kv_r1.txt` (batfish/lab-validation) | Apache-2.0 | 10.3(9) | fetch |
| `/interfaces/interface/ipv6/address/prefix-length` | `batfish_nxos_ebgp_n9kv_r1.txt` (batfish/lab-validation) | Apache-2.0 | 10.3(9) | fetch |
| `/routing/static-route/vrf` | `batfish_nxos_ebgp_n9kv_r1.txt` (batfish/lab-validation) | Apache-2.0 | 10.3(9) | fetch |
| `/interfaces/interface/trunk-native-vlan` | `busterswt_nxos_evpn_xk32_1.txt` (busterswt/spine-leaf-lab) | none (device-output) | 9.3(12) | fetch |
| `/vxlan-vnis/mcast-group` | `akarneliuk_nexus_vxlan_mcast_underlay_nxos93.conf` (akarneliuk/multivendor-network-labs) | none (device-output) | 9.3(9) | fetch |
| `/vxlan-vnis/flood-list` | `goldenbyte_nexus_vxlan_static_ir_leaf1.conf` (GoldenbyteGH/GB_NetRepos) | none (device-output) | unversioned fragment | fetch |
| `/interfaces/interface/ipv4/address/virtual-gateway-address` | `networklessons_labs_nxos_dag_symmetric_irb_fos1027.cfg` (networklessons/labs) | none (device-output) | 10.2(7) | fetch |
| `/routing-instances/instance/description` | — none found | — | — | **blocked** (durable negative) |
| `/evpn-type5-routes/route` (lossy) | — none found | — | — | **blocked** |
| `/system/raw-sections/features` (lossy) | — none found (incidental in fetched configs only) | — | — | **blocked** |
| `/system/raw-sections/vdc` (lossy) | — none found | — | — | **blocked** |

> Note: `/anycast-gateway-mac` is filled by the DAG candidates but is not in the supplied gap list (already verified); it is carried as a bonus on the M4 picks.

### Ranked candidates (grammar-confirmed, fetch-recommended first)

1. **`batfish_nxos_ebgp_n9kv_r1.txt`** — BEST LICENSE
   - Source: https://github.com/batfish/lab-validation/tree/main/snapshots/nxos_n9kv_ebgp/configs/r1
   - Raw: https://raw.githubusercontent.com/batfish/lab-validation/main/snapshots/nxos_n9kv_ebgp/configs/r1/show_running-config.txt
   - License: **Apache-2.0** (repo LICENSE; gh api spdx_id Apache-2.0). Trusted org, NEW snapshot (nxos_n9kv_ebgp) distinct from the 6 existing 9.2(3) HSRP/L2VNI/L3VNI fixtures.
   - OS: NX-OS 10.3(9). Surfaces: `/interfaces/interface/ipv6/address/ip`, `/interfaces/interface/ipv6/address/prefix-length`, `/routing/static-route/vrf`.
   - Confirms: `interface mgmt0 / ipv6 address 2001:db8::2/64` (RFC3849) and `vrf context management / ip route 0.0.0.0/0 10.0.0.2`. No native-vlan, no VRF description. Sibling r2 is an identical-grammar second file.

2. **`ntc_goldenconfig_nxos_snmp_mgmt_jcyspine01_fos93.conf`** — PRIZE (only all-four-SNMP source)
   - Source: https://github.com/nautobot/demo-gc-backups/blob/main/jersey-city/jcy-spine-01.infra.ntc.com.cfg
   - Raw: https://raw.githubusercontent.com/nautobot/demo-gc-backups/main/jersey-city/jcy-spine-01.infra.ntc.com.cfg
   - License: **none** — unlicensed public repo (gh api license=null; root = README + config dirs only). Official Nautobot org Golden-Config demo data, verbatim `show running-config`. Acceptable under factual device-output precedent; LOWER preference; drop-if-author-objects.
   - OS: NX-OS 9.3(3). Surfaces: `/snmp/community`, `/snmp/contact`, `/snmp/location`, `/snmp/trap-host` (all four in one mgmt block).
   - Confirms: `snmp-server community secure group network-admin` / `snmp-server contact John Smith` / `snmp-server location Network to Code - NYC | NY` / `snmp-server host 10.1.1.1 traps version 2c networktocode`. SANITIZE: two SNMP-user md5/priv localizedkey hash lines + engineID (not target surfaces). Paired spine-02 is a redundant second file.

3. **`busterswt_nxos_evpn_xk32_1.txt`** — native-vlan incl. port-channel case
   - Source: https://github.com/busterswt/spine-leaf-lab/tree/main/with_ospf_bgp_evpn
   - Raw: https://raw.githubusercontent.com/busterswt/spine-leaf-lab/main/with_ospf_bgp_evpn/ospf-bgp-evpn-xk32-1.txt
   - License: **none** (gh api license 404; factual device-output precedent, lower preference, drop-if-author-objects).
   - OS: NX-OS 9.3(12). Surfaces: `/interfaces/interface/trunk-native-vlan`, `/routing/static-route/vrf`.
   - Confirms: `switchport trunk native vlan 999` on Ethernet1/6, Ethernet1/7 AND port-channel999 (exercises both Ethernet and port-channel) + `vrf context management / ip route 0.0.0.0/0 ...`. RFC1918 lab. 13 sibling configs available.

4. **`akarneliuk_nexus_vxlan_mcast_underlay_nxos93.conf`** — strongest multicast underlay
   - Source: https://github.com/akarneliuk/multivendor-network-labs/blob/main/labs/cisco/04-nexus-evpn-vxlan/final_configs/c-1-l1.txt
   - Raw: https://raw.githubusercontent.com/akarneliuk/multivendor-network-labs/main/labs/cisco/04-nexus-evpn-vxlan/final_configs/c-1-l1.txt
   - License: **none** (gh api spdx_id null; README-only; factual device-output precedent, lower preference).
   - OS: NX-OS 9.3(9). Surfaces: `/vxlan-vnis/mcast-group`, `/vxlan-vnis/source-interface`, `/vxlan-vnis/vni`.
   - Confirms inline form: `interface nve1 / source-interface loopback0 / member vni 100010 mcast-group 239.11.11.10` (+ .20/.30) with `feature nv overlay` + `vn-segment` L2 bindings. SANITIZE one type-3 OSPF key-chain hash. RFC1918 lab.

5. **`networklessons_clab_vxlan_mcast_leaf2_nxos.conf`** — multicast, OTHER syntactic form (grammar diversity)
   - Source: https://github.com/networklessons/labs/blob/main/containerlab/labs/vxlan/cisco/vxlan-underlay-ebgp-two-as/clab-vxlan-underlay-ebgp-two-as/leaf2/config/startup-config.cfg
   - Raw: https://raw.githubusercontent.com/networklessons/labs/main/containerlab/labs/vxlan/cisco/vxlan-underlay-ebgp-two-as/clab-vxlan-underlay-ebgp-two-as/leaf2/config/startup-config.cfg
   - License: **none** (gh api spdx_id null; factual device-output precedent, lower preference).
   - OS: NX-OS (n9kv; version banner not in excerpt — VERIFY full-file header). Surfaces: `/vxlan-vnis/mcast-group`, `/vxlan-vnis/source-interface`, `/vxlan-vnis/vni`.
   - Confirms own-sub-line form: `member vni 10010 / mcast-group 239.1.1.1` (vs akarneliuk inline) under `interface nve1 / source-interface loopback0`. Scan full file for lab passwords before commit.

6. **`goldenbyte_nexus_vxlan_static_ir_leaf1.conf`** — ONLY static ingress-replication / flood-list
   - Source: https://github.com/GoldenbyteGH/GB_NetRepos/tree/main/VXLAN/Static_Ingress_Replication_NLS
   - Raw: https://raw.githubusercontent.com/GoldenbyteGH/GB_NetRepos/main/VXLAN/Static_Ingress_Replication_NLS/LEAF1
   - License: **none** (gh api spdx_id null; factual device-output precedent, lower preference).
   - OS: NX-OS, **CLI config FRAGMENT** (no version / no `!Command:`/`feature nv overlay` header). Surfaces: `/vxlan-vnis/flood-list`, `/vxlan-vnis/source-interface`, `/vxlan-vnis/vni`.
   - Confirms: `member vni 10010 / ingress-replication protocol static / peer-ip 2.2.2.2` (LEAF1) ↔ `peer-ip 1.1.1.1` (LEAF2). CAVEAT: fragment provenance — grab BOTH LEAF1+LEAF2; may need a synthetic version/feature header for NX-OS auto-detect. This is the sole flood-list source found.

7. **`networklessons_labs_nxos_dag_symmetric_irb_fos1027.cfg`** — strongest IPv4 DAG / virtual-gateway-address
   - Source: https://github.com/networklessons/labs/blob/main/containerlab/labs/vxlan/cisco/research/vxlan-evpn-inter-vni-symmetric-irb/clab-vvxlan-evpn-inter-vni-symmetric-irb/leaf1/config/startup-config.cfg
   - Raw: https://raw.githubusercontent.com/networklessons/labs/main/containerlab/labs/vxlan/cisco/research/vxlan-evpn-inter-vni-symmetric-irb/clab-vvxlan-evpn-inter-vni-symmetric-irb/leaf1/config/startup-config.cfg
   - License: **none** (gh api spdx_id null; factual device-output precedent, lower preference).
   - OS: NX-OS 10.2(7). Surfaces: `/interfaces/interface/ipv4/address/virtual-gateway-address` (+ bonus `/anycast-gateway-mac`).
   - Confirms: `fabric forwarding anycast-gateway-mac 0001.0001.0001` + TWO SVIs (Vlan10/Vlan20) each `vrf member CUST1` + `ip address` + `fabric forwarding mode anycast-gateway` (non-default VRF, >1 SVI) + `vrf context CUST1 / vni 100100` L3VNI. SANITIZE any username/snmp hashes. Real `!Command: show running-config`.

#### Lower-tier / fallback fetch-recommended (license-clean but partial, or older version)

8. **`microsoft_sdn_nxos3132_snmp_tor1_fos60.conf`** — MIT, but only 2/4 SNMP surfaces, OLD version
   - Source: https://github.com/microsoft/SDN/blob/master/SwitchConfigExamples/Cisco%20Nexus%203132%20-%20Redundant%20TOR/Cisco%20Nexus%203132-TOR1.cfg
   - Raw: https://raw.githubusercontent.com/microsoft/SDN/master/SwitchConfigExamples/Cisco%20Nexus%203132%20-%20Redundant%20TOR/Cisco%20Nexus%203132-TOR1.cfg
   - License: **MIT** (verbatim License.txt at /master/License.txt; gh classifier reports NOASSERTION only because of the product-name preamble — text is unambiguous MIT).
   - OS: NX-OS 6.0(2)U6(1). Surfaces: `/snmp/community`, `/snmp/trap-host` only (NO contact, NO location).
   - Confirms: `snmp-server community cloud_rw group network-admin` + `snmp-server host 10.0.2.254 traps version 2c msft`. Use as license-clean diversifier for community+trap-host; does NOT close contact/location. Also a native-vlan source (`switchport trunk native vlan 12` on ~32 ifaces) at the same old version. Sibling TOR2 identical.

9. **`microsoft_sdn_nexus3132_tor1.conf`** — MIT native-vlan (same file as #8, native-vlan lens)
   - Same source/raw URL as #8; License MIT; OS 6.0(2)U6(1). Surface: `/interfaces/interface/trunk-native-vlan`.
   - Confirms: `switchport mode trunk / switchport trunk native vlan 12` (Eth1/3/1..1/10/4). Best ONLY if an MIT-clean native-vlan is preferred over the unlicensed busterswt/Thada-Saket; version-anchoring is poor (6.0). (Same physical file as candidate #8 — pick one filename.)

### Investigate-only (NOT upgraded to fetch)

- **`thadasaket_nxos_3548x_core1.txt`** (Thada-Saket/3-Tier-Network-lab, N3548X, 9.3(8), unlicensed) — single file with BOTH `switchport trunk native vlan 99` AND `vrf context management / ip route 0.0.0.0/0 ...`; investigate purely on unlicensed status. https://raw.githubusercontent.com/Thada-Saket/3-Tier-Network-lab/main/configurations/Core-1-CiscoNexus3548X.txt
- **`racc_nxos_n9k1_sbxao.txt`** (nickrusso42518/racc, n9k, 9.3(3), **BSD-3-Clause**) — clean license but fills only `/routing/static-route/vrf` (already well covered). License-clean fallback. https://raw.githubusercontent.com/nickrusso42518/racc/master/samples_hash/n9k1_20230811T074823/show_running-config.txt
- **`dejavudf_titanium_vxlan_mcast_l3vni_leaf01.conf`** (dejavudf, unlicensed) — mcast + associate-vrf mix; backup multicast diversifier; verify version banner + secrets.
- **`atr399_vxlan_evpn_journey_nxos_dag_fos1055.cfg`** (atr399, 10.5(5), unlicensed) — DAG second-source for version diversity; personal learning journal, verify round-trip + hashes.
- **`kousei_nxos_dag_tenant_a_fos1032.cfg`** (mmerioles/kousei, 10.3(2), unlicensed) — DAG third-source; provenance unclear (it is itself a `fixtures/` dir) AND per-SVI `ip address` lines were NOT confirmed present — must verify the primary IP exists before virtual_gateway_address mirrors anything.

### Dead ends / blocked

- **`/routing-instances/instance/description` — DURABLE NEGATIVE.** Targeted gh regex `/vrf context <name>\n  description/` + `!Command: show running-config` = 0 hits across ~10 fetched real configs (batfish, busterswt, Thada-Saket, racc, opennxos, EVPN-blog, git_ansible, atr399). NX-OS operators almost never describe VRFs (unlike IOS-XR/Junos). The only source with a nested VRF description (catherinevee/networkreview) is a CLI cheatsheet, NOT a real capture, and its static route is the global `ip route ... vrf X` form — **rejected**. Recommend sourcing this surface synthetically (kitchen_sink already has it) or accepting it as NX-OS-rare. Do not re-hunt without a new lead.
- **`/evpn-type5-routes/route` (lossy)** — no dedicated mission; no real capture isolating this surface located. The DAG/L3VNI configs (#7, investigate-tier dejavudf/atr399/kousei) carry `member vni … associate-vrf` symmetric IRB but none was confirmed to exercise the type-5 route surface. Blocked pending a targeted hunt.
- **`/system/raw-sections/features` (lossy)** — appears incidentally as `feature …` lines in nearly every fetched config but no candidate was selected to verify this raw-section surface specifically; treat as covered-incidentally if any of the fetched configs lands, otherwise blocked.
- **`/system/raw-sections/vdc` (lossy)** — no VDC (`vdc … id` / `limit-resource`) block found in any fetched lab config (lab n9kv/containerlab images are single-VDC). Blocked — likely needs a physical multi-VDC chassis capture; synthetic-only for now.
- **License hard-negatives (do not re-hunt without a new donor):** (1) NX-OS DAG grammar `fabric forwarding anycast-gateway-mac` returned TOTAL=0 under explicit apache-2.0/mit/bsd-3-clause/isc license filters — zero permissively-licensed DAG configs exist on GitHub; all 10.x DAG sources are unlicensed device-output. (2) batfish/lab-validation has NO multicast or static-IR VXLAN (only `ingress-replication protocol bgp`, same as existing corpus) — confirmed via full recursive tree + raw fetch. (3) BSD-3-Clause containerlab repos (yakiimo-bsp / tsubuan365 n9kv-evpn-vxlan-lab) are clean-license but wrong grammar (BGP head-end) — fill no gap. (4) StrategicUser/TTI2 has all four SNMP surfaces but is **rejected**: unlicensed personal repo + real operator PII (real email tti-it@totalterminals.com, real-looking shared secret 'DPSNMPG3T!'). scotttyso/iac-easy-aci and richtechguy/NexusVXLAN are GPL-3.0 — **rejected**.

### Sanitization summary (before any commit)
- nautobot SNMP configs: strip SNMP-user md5/priv localizedkey hash lines + engineID.
- akarneliuk: replace one type-3 OSPF key-chain hash.
- networklessons DAG + leaf2 multicast: replace `username admin password 5 $5$…` + `snmp-server user … auth md5 … priv aes-128 …` hashes (present on sibling spine-leaf leaves; verify the symmetric-IRB/leaf2 file specifically).
- All confirmed candidates use RFC1918/RFC3849 addressing — benign, low sanitization burden.

## aruba_aoscx

9 supported/lossy canonical surfaces unverified by the existing corpus (7 supported + 2 lossy). License-clean (Apache-2.0/MIT) public captures cover every surface except the default-VRF `/routing/static-route` real-capture caveat noted below; the synthetic `/routing-instances/instance/name` + per-iface `vrf` + dual-stack IPv6 are all addressable from one Cray-HPE/canu MIT fixture.

### Gap surface coverage

| Gap surface | Best candidate | Status |
|---|---|---|
| `/interfaces/interface/config/vrf` | `cray_canu_aoscx_spine_vrf_dualstack_ipv6.cfg` (Cray-HPE/canu, MIT) | fetch |
| `/interfaces/interface/ipv6/address/ip` | `cray_canu_aoscx_spine_vrf_dualstack_ipv6.cfg` (Cray-HPE/canu, MIT) | fetch |
| `/interfaces/interface/ipv6/address/prefix-length` | `cray_canu_aoscx_spine_vrf_dualstack_ipv6.cfg` (Cray-HPE/canu, MIT) | fetch |
| `/routing-instances/instance/name` | `cray_canu_aoscx_spine_vrf_dualstack_ipv6.cfg` (Cray-HPE/canu, MIT) | fetch |
| `/routing/static-route` | `cray_canu_aoscx_spine_vrf_dualstack_ipv6.cfg` (default-VRF `ip route 0.0.0.0/0`) | fetch |
| `/snmp/community` | `oxidized_aruba6410_snmp_v2c_foscx1010.conf` (ytti/oxidized, Apache-2.0) | fetch |
| `/snmp/v3-user` | `netutils_aoscx_snmpv3_usm_glcx1009.conf` (networktocode/netutils, Apache-2.0) | fetch |
| `/snmp/v3-user/auth-passphrase` (lossy) | `netutils_aoscx_snmpv3_usm_glcx1009.conf` (ciphertext blob, pre-sanitized `xxxxx`) | fetch |
| `/system/raw-sections/version-banner` (lossy) | `oxidized_aruba6410_snmp_v2c_foscx1010.conf` (`!Version ArubaOS-CX FL.10.10.1100`) | fetch |

### Ranked candidates (grammar-confirmed, fetch-recommended)

1. **`cray_canu_aoscx_spine_vrf_dualstack_ipv6.cfg`** — Cray-HPE/canu (Aruba 8325 CSM mgmt spine)
   - Source: https://github.com/Cray-HPE/canu/blob/main/tests/data/golden_configs/full_configs_custom_1.7/sw-spine-001-ipv6.cfg
   - Raw: https://raw.githubusercontent.com/Cray-HPE/canu/main/tests/data/golden_configs/full_configs_custom_1.7/sw-spine-001-ipv6.cfg
   - License: **MIT** — repo-root LICENSE `MIT License (C) Copyright 2022-2023 Hewlett Packard Enterprise Development LP`; `gh api .license.spdx_id == MIT`.
   - OS: CSM 1.7 golden config (AOS-CX 10.x grammar; **no embedded `!Version` banner**)
   - Surfaces: `/routing-instances/instance/name`, `/interfaces/interface/config/vrf`, `/routing/static-route`, `/interfaces/interface/ipv6/address/ip`, `/interfaces/interface/ipv6/address/prefix-length`
   - Note: hits every functional target including the hard default-VRF static route (`ip route 0.0.0.0/0 10.103.15.185`, distinct from non-default `vrf attach CSM` SVIs); RFC3849 `2001:db8:100::2/64` + RFC1918 v4 already clean. **CAVEAT: no `!Version ArubaOS-CX` banner (opens with comment block then `hostname`)** — codec probe accepts structural→90 (`vrf attach`, `interface vlan N`, `active-gateway`, CIDR `ip route`), but prepend a synthetic banner during prep if banner detection is required; this fixture does NOT cover `/system/raw-sections/version-banner`.

2. **`oxidized_aruba6410_snmp_v2c_foscx1010.conf`** — ytti/oxidized (real Aruba 6410 R0X25A capture)
   - Source: https://github.com/ytti/oxidized/blob/master/spec/model/data/aoscx%23R0X25A-6410_FL.10.10.1100%23output.txt
   - Raw: https://raw.githubusercontent.com/ytti/oxidized/master/spec/model/data/aoscx%23R0X25A-6410_FL.10.10.1100%23output.txt
   - License: **Apache-2.0** — repo-root LICENSE `Apache License Version 2.0`; `spdx_id=Apache-2.0`.
   - OS: ArubaOS-CX FL.10.10.1100
   - Surfaces: `/snmp/community`, `/system/raw-sections/version-banner` (+ bonus `/snmp/location`, `/snmp/contact`)
   - Note: BEST community match — two community strings (`readonlycom` RO + `rwsnmpcom` with `access-level rw`); `system-location`/`system-contact` use AOS-CX `system-` prefix. **SNMPv2c-only — no v3 user (pair with netutils for v3).** Lab placeholders + RFC1918 trap targets; quick scrub-check before commit; trim ~1300-line full config to snmp block + banner.

3. **`netutils_aoscx_snmpv3_usm_glcx1009.conf`** — networktocode/netutils (aruba_aoscx parser mock)
   - Source: https://github.com/networktocode/netutils/blob/develop/tests/unit/mock/config/parser/base/aruba_aoscx/aoscx_full_sent.txt
   - Raw: https://raw.githubusercontent.com/networktocode/netutils/develop/tests/unit/mock/config/parser/base/aruba_aoscx/aoscx_full_sent.txt
   - License: **Apache-2.0** — LICENSE body is verbatim Apache-2.0 (`Apache Software License 2.0 / Copyright (c) 2021-2025, Network to Code, LLC`); GitHub auto-detect shows NOASSERTION due to a custom header line, but the grant text is standard Apache-2.0. (Verify the header before commit.)
   - OS: ArubaOS-CX GL.10.09.0010
   - Surfaces: `/snmp/v3-user`, `/snmp/v3-user/auth-passphrase`, `/system/raw-sections/version-banner`
   - Note: COMPLEMENT to oxidized — carries the exact v3 USM grammar (`snmpv3 user testuser auth md5 auth-pass ciphertext xxxxx priv des priv-pass ciphertext xxxxx`) the v2c fixtures lack; ciphertext already sanitized to literal `xxxxx`, clean to import. No community/location/contact line. Trim ~360-line config to banner + snmp block.

4. **`datadog_aoscx_running_pl1013.cfg`** — DataDog/datadog-agent (NCM fixture, PL. 6000-family)
   - Source: https://github.com/DataDog/datadog-agent/blob/main/pkg/networkconfigmanagement/profile/fixtures/aoscx/running/initial.txt
   - Raw: https://raw.githubusercontent.com/DataDog/datadog-agent/main/pkg/networkconfigmanagement/profile/fixtures/aoscx/running/initial.txt
   - License: **Apache-2.0** — `gh api repos/DataDog/datadog-agent/license` → spdx_id=Apache-2.0, path=LICENSE.
   - OS: ArubaOS-CX PL.10.13.0005 (newer 10.13 train)
   - Surfaces: `/system/raw-sections/version-banner`, `/snmp/community`, `/routing/static-route` (default-VRF `ip route 0.0.0.0/0 192.168.0.1`), SVI `/interfaces/interface/ipv4/address`
   - Note: SECONDARY/optional — re-covers (not extends) surfaces above but adds a distinct newer OS-train datapoint. **Mission-disagreement flagged honestly: Mission A rated this `investigate` (near-dup of an oxidized PL.10.13 fixture, same dummy community `AAAA...CCCC`); Mission C rated it `fetch` for the 10.13 anchor + default-VRF static route.** No `vrf`/`vrf attach`, no IPv6. Already sanitized (placeholder ciphertext, RFC1918, synthetic community → scrub to `public`/`private`). Fetch only if a clean 10.13 snmp/static-route anchor is wanted.

### Dead ends / blocked

- **`/routing/static-route` real-capture (default-VRF)** — the only *real operator* capture with `vrf attach` + IPv6 (`oxidized_aoscx_8325_vrf_external_v6.txt`, ISNIC, Apache-2.0) carries its static route as **`ip route 0.0.0.0/0 192.168.1.1 vrf external` (non-default VRF)**, so the default-VRF static-route surface would NOT fire. Default-VRF static-route coverage therefore comes only from the Cray-HPE/canu *golden-config template* (candidate 1), not a banner-bearing real capture. The ISNIC file also reads `!Version AOS-CX` not `!Version ArubaOS-CX` (verify probe spelling) and its `2001::1/64` is real space (rewrite to 2001:db8::/32). Logged as `investigate` only.
- **Newer-train (10.13/10.14) campus 6300/6400 with BOTH `vrf attach` AND `ipv6 address 2001:db8::`** — genuinely ABSENT from license-clean public GitHub. Code searches `"!Version ArubaOS-CX" "ipv6 address" "vrf attach"` and `"!Version ArubaOS-CX FL.10.1" "ipv6 address"` returned ONLY netcanon's own repo (synthetic kitchen_sink + codec source). Real-world AOS-CX configs are mostly older Virtual./ML.10.04-10.09 trains, 8320/8325 DC-family rather than campus 6300/6400, or jinja2 templates. **Do not re-hunt without a new donor.**
- **HARD license rejects (do not re-hunt):** `dservais0427/config-parse` (GPL-3.0, three AOS-CX sample files off-limits); official HPE techdocs `arubanetworking.hpe.com` SNMP/IP-Routing/Fundamentals 10.13/10.14 pages (proprietary, confirm grammar only).
- **Unlicensed device-output (lower preference, investigate-only — fetch only after scrub + author-objection check):** `laketec/ansible-lab/leaf1` (only single file with REAL v3 USM `auth sha`/`priv aes` + system-location/contact, but device-key ciphertext + real-looking `noc@laketec.com` need scrubbing; Apache pair preferred); `tchiapuziowong/atm22-roseville-cx` Access-6200 (campus shape + `ntp vrf mgmt`/`ubt zone ... vrf` but ML.10.09 older train, no IPv6, no `ip route 0.0.0.0/0`, no `snmp-server community`, and REAL radius/clearpass secrets + embedded CA cert); `Joe-Neville/CX-IPv6-Address-Options` (clean RFC3849 IPv6 SVI fragments but markdown writeup not a full running-config, 8320 DC not campus).
- **Rejected as fixture material:** `Shajeervu/arubavsx` (`vrf KEEPALIVE` VSX-keepalive only, no banner/ipv6/static); `tjbalzer/clab-aoscx-labs` (unlicensed + only non-default-VRF `ip route ... vrf VRF1/VRF2`); `aruba/aoscx-ansible-dcn-workflows` (banner-only, ZERO vrf/route/ipv6 — confirmed barren and already the corpus's source family); `BrettVerney/cliSnips`, `napalm-aruba-cx`, `aruba/central-sample-bulk-configurations` (AOS-S not AOS-CX), `AndrewP-Roc/ProjectA`/`aruba/central-python-workflows` (templates, no rendered configs).
- **Tooling note:** GitHub code-search drops the leading `!` token, so literal `"!Version ArubaOS-CX"` returns 0 hits — search `ArubaOS-CX` + a co-occurring token instead. Code-search is a separate ~10-req/min bucket from core search.

## juniper_junos

10 canonical surfaces unverified (7 supported-but-unverified + 3 lossy-unverified); 8 are addressable with a grammar-confirmed fetch-recommended candidate, 2 remain blocked (`/snmp/contact`, `/dhcp-servers/pool`).

### Gap surface coverage

| Gap surface | Class | Best candidate | Rec |
|---|---|---|---|
| `/snmp/v3-user` | supported | `saidvandeklundert_rust_snmpv3_usm_fos172.conf` (MIT) | fetch |
| `/snmp/location` | supported | `saidvandeklundert_rust_snmpv3_usm_fos172.conf` (MIT) | fetch |
| `/snmp/contact` | supported | — only in unlicensed `junos_vsrx_snmpv3_usm_contact_fos232.conf` | investigate (no clean source) |
| `/interfaces/interface/vrrp-groups/group` | supported | `batfish_juniper_vrrp_authkey.set` (Apache-2.0) | fetch |
| `/interfaces/interface/tunnel-type` | supported | `jnprautomate_mnha_vsrx_st0_groups_junos.set` (MIT) | fetch |
| `/interfaces/interface/dhcp-client-v6` | supported | `tsg8139_evpn_leaf_dhcpv6client_fos232.set` (MIT) | fetch |
| `/dhcp-servers/pool` | supported | — only in unlicensed `kskrede_junos_ex_dhcp_local_server_irb.set` | investigate (no clean source) |
| `/evpn-type5-routes/route` | lossy | `tsg8139_evpn_type5_ipprefixroutes_junos.set.conf` (MIT) | fetch |
| `/groups` | lossy | `jnprautomate_mnha_vsrx_st0_groups_junos.set` (MIT) | fetch |
| `/interfaces/interface/subinterfaces/subinterface` | lossy | `batfish_juniper_vrrp_authkey.set` (Apache-2.0, dot1q unit 3440) | fetch |

### Ranked candidates — grammar-confirmed, fetch-recommended (license-clean)

1. **`tsg8139_evpn_leaf_dhcpv6client_fos232.set`** — MIT
   - Source: https://github.com/TsG8139/evpn-vxlan-implementation/blob/main/srx/leaf02.txt
   - Raw: https://raw.githubusercontent.com/TsG8139/evpn-vxlan-implementation/main/srx/leaf02.txt
   - License evidence: LICENSE file at repo root ("MIT License / Copyright (c) 2026 TsG8139"); `gh api .license.spdx_id => MIT`.
   - OS: Junos 23.2R1.14 (`set version 23.2R1.14`)
   - Surfaces filled: `/interfaces/interface/dhcp-client-v6` (+ routing-instances)
   - Note: Real stateful `family inet6 dhcpv6-client` block on fxp0 unit 0 (client-type stateful / ia-na / duid-ll); grammar identical to a WAN unit. File mixes a set block + a `show configuration` curly block — slice the set-form section (~lines 1-46) on import. `$6$` SHA512 lab hash, RFC3849 (2001:db8::) addresses.

2. **`tsg8139_evpn_type5_ipprefixroutes_junos.set.conf`** — MIT
   - Source: https://github.com/TsG8139/evpn-vxlan-implementation/blob/main/DC1%20and%20DC2%20configs/DC-2_POD-1_Leaf_01.set.conf
   - Raw: https://raw.githubusercontent.com/TsG8139/evpn-vxlan-implementation/main/DC1%20and%20DC2%20configs/DC-2_POD-1_Leaf_01.set.conf
   - License evidence: same repo LICENSE; spdx_id MIT.
   - OS: Junos 23.2R1.14-class
   - Surfaces filled: `/evpn-type5-routes/route` (lossy) (+ routing-instances)
   - Note: `routing-instances Tenant-1_ipvrf protocols evpn ip-prefix-routes vni 50000` (advertise direct-nexthop / encapsulation vxlan). Clean `.set.conf` set-form, importable as-is; tenant VNIs 50000/50001/10100/20100, no real WAN IPs.

3. **`jnprautomate_mnha_vsrx_st0_groups_junos.set`** — MIT
   - Source: https://github.com/JNPRAutomate/mnha-ipsec-and-multiple-routing-instances/blob/main/full-configurations/mnha-vsrx-a.set
   - Raw: https://raw.githubusercontent.com/JNPRAutomate/mnha-ipsec-and-multiple-routing-instances/main/full-configurations/mnha-vsrx-a.set
   - License evidence: LICENSE at repo root, first line "MIT License"; `gh api .license.spdx_id => MIT`. Repo under Juniper's official JNPRAutomate org.
   - OS: Junos vSRX MNHA (feature set = 22.x+ via ha-link-encryption; no explicit version line)
   - Surfaces filled: `/interfaces/interface/tunnel-type` (st0 → ipsec secure-tunnel), `/groups` (lossy; `set groups MNHA-SYNC` + `set apply-groups MNHA-SYNC`) (+ routing-instances)
   - Note: `set interfaces st0 unit 100/200` + `set groups MNHA-SYNC` + `set apply-groups MNHA-SYNC` + `bind-interface st0.200`. PSK is published `$9$` lab-vault form; no real public WAN IPs (ICL is local-link). No RFC5737 rewrite needed.

4. **`batfish_juniper_vrrp_authkey.set`** — Apache-2.0
   - Source: https://github.com/batfish/batfish/blob/master/projects/batfish/src/test/resources/org/batfish/grammar/juniper/testconfigs/juniper-vrrp
   - Raw: https://raw.githubusercontent.com/batfish/batfish/master/projects/batfish/src/test/resources/org/batfish/grammar/juniper/testconfigs/juniper-vrrp
   - License evidence: `gh api .license.spdx_id => Apache-2.0` (repo-level LICENSE); same license as the existing junos2541 corpus fixture.
   - OS: version-agnostic Batfish grammar testconfig
   - Surfaces filled: `/interfaces/interface/vrrp-groups/group`, `/interfaces/interface/subinterfaces/subinterface` (lossy; dot1q unit 3440)
   - Note: Only license-clean VRRP source found and the only one with `authentication-type md5|simple` + `authentication-key`. Set-form; `xe-2/3/0 unit 3440` = subinterface surface. Caveat: VRRP on `xe-` physical (NOT irb-typed), no priority/track. Key `kkkkkk` is a published Batfish lab key (safe), 10.x IPs clean.

5. **`saidvandeklundert_rust_snmpv3_usm_fos172.conf`** — MIT
   - Source: https://github.com/saidvandeklundert/rust/blob/main/projects/jsc/config_17_set.txt
   - Raw: https://raw.githubusercontent.com/saidvandeklundert/rust/main/projects/jsc/config_17_set.txt
   - License evidence: `gh api repos/saidvandeklundert/rust/license` returns spdx_id MIT; LICENSE file at repo root.
   - OS: Junos 17.2R3.4 (`set version 17.2R3.4`) — just below the 19-22 preferred window, explicitly acceptable (15.1→24.x grammar stable)
   - Surfaces filled: `/snmp/v3-user`, `/snmp/location`
   - Note: Full `set snmp v3 usm local-engine user POLLER-1/POLLER-2` (authentication-sha + privacy-aes128) + vacm security-to-group binding + `set snmp location DAL09`. Auth/priv keys already neutralized to `/* SECRET-DATA */` — no key sanitization needed. Does NOT carry `set snmp contact`.

### Investigate-only leads (no license-clean source for the surface)

- **`junos_vsrx_snmpv3_usm_contact_fos232.conf`** (unlicensed device-output) — https://github.com/meadows123/automation-test/blob/main/network-backups/2026-03-16/vsrx-1773645999.cfg — the ONLY file carrying all three SNMP surfaces in one config (`set snmp location` + `set snmp contact` + full `/snmp/v3-user`), Junos 23.2R2.21. Unlicensed (no LICENSE; 404 on `gh api .../license`) → factual-output precedent only, LOWER preference. Requires mandatory sanitization: real `$9$` hashes on auth+priv keys, real-looking `admin@conxiea.com` contact, `"DC, Bolton, Bl1 1EU"` location, 192.168.x IPs, community strings public/private. Kept as the only known `/snmp/contact` source.
- **`kskrede_junos_ex_dhcp_local_server_irb.set`** (unlicensed) — https://github.com/KSkrede/Networking/blob/master/Juniper/Lab/Lab%204/lab%204%20switch%202%20config.txt — the only on-box DHCP-server gap-clearer: `dhcp-local-server group` + `access address-assignment pool` (network / range low+high / dhcp-attributes router+name-server+maximum-lease-time) across 4 irb SVIs + vlan→l3-interface irb mapping (subinterface). Unlicensed (`.license = null`) → factual lab device-output, LOWER preference. SANITIZE: 2 encrypted password hashes (root + user 'skrede'). RFC1918 10.4.x clean; `name-server 8.8.8.8` is public DNS not a secret.
- **`agantonov_junos_mx_irb_vrrp_bridgedomain.set`** / **`agantonov_junos_mx_vrrp_track_dot1q.set`** (unlicensed) — https://github.com/agantonov/juniper_config_example — densest *irb-typed* VRRP grammar (full IPv4 vrrp-group + IPv6 vrrp-inet6-group; second file adds `track interface`/`track route priority-cost` on a dot1q unit). Unlicensed (`.license = null`). The Apache-2.0 batfish file covers the VRRP + subinterface surfaces cleanly (though on `xe-` not irb), so these are fallbacks only.
- **`jcoeder_qfx5100_mclag_irb_vrrp.set`** (unlicensed) — https://github.com/jcoeder/juniper-configurations/blob/master/qfx5100-mc-lag — real QFX5100 MC-LAG irb.10 VRRP pair; redundant with the clean batfish VRRP candidate, lower grammar breadth.
- **`fabferri_azpattern_srx_gre_st0_tunnel_junos.set`** (unlicensed/forum-share) — https://github.com/fabferri/az-pattern/blob/master/overlay-network-srx/srx1-config.txt — best SINGLE-FILE tunnel-type match naming BOTH `gr-0/0/0` (gre) and `st0` (ipsec) in one file. No LICENSE (404). Requires sanitization: REAL public Azure WAN IP `13.68.203.192` and PLAINTEXT PSK `"Mysharedpwd*01"`. The MIT mnha file already covers tunnel-type (st0) cleanly, so this is a fallback for gre+st0-in-one-file only.

### Dead ends / blocked

- **`/snmp/contact`** — BLOCKED for a license-clean source. No MIT/Apache file carries `set snmp contact`; the MIT `saidvandeklundert/rust` config has location + v3-user but no contact, and the only file with all three SNMP surfaces (`meadows123/automation-test`) is unlicensed + needs heavy sanitization. The rendoaw gist with block-form v3 usm + location is REJECTED (bare gist = all-rights-reserved, also no contact). Re-hunt fallback: `gh api search/code q='"local-engine" repo:networktocode/ntc-templates'` once code-search quota resets — a `tests/juniper_junos/show_snmp_v3/*.raw` Apache-2.0 factual-output fixture likely exists but could not be enumerated (GitHub `/tree/` 404 + code-search 403 rate-limit).
- **`/dhcp-servers/pool`** — BLOCKED for a license-clean source. DOCUMENTED NEGATIVE: no single licensed file combining irb-VRRP + on-box DHCP server exists; the combined `vrrp-group`+`dhcp-local-server` code-search returned only netcanon's own source, ANTLR FlatJuniperLexer.g4 grammar (+forks), and LLM-distilled training material. The Batfish Apache-2.0 org has NO `dhcp-local-server` in any junos testconfig (DHCP coverage is relay-only/vyos). Only known dhcp-local-server config is the unlicensed `KSkrede/Networking` file. artofrf.com EX4600 blog rejected (all-rights-reserved authored prose). No Juniper-forum display-set paste pairs the surface cleanly.
- **REJECTED leads (reported to avoid re-hunt):** `rendoaw_gist_snmpv3_usm_blockform.conf` (bare gist, all-rights-reserved; also weaker md5/des crypto, no contact); `tplisson_evpnmpls_srx_st0_groups_junos.set` (NO LICENSE + Junos 15.1X49 out of range + real public peer IPs in st0 descriptions); `tigelane/system_utilities/juniper_1.txt` (GPL-2.0 hard reject).
- **No single file carries the full mission trios** — M2's irb-VRRP + on-box DHCP must be assembled from two files; M3's tunnel + dhcpv6-client + apply-groups + EVPN type-5 has no single co-located capture (real edges put dhcpv6-client on a WAN/fxp0 unit and tunnels on a separate unit; lab EVPN-DCI uses vxlan encap not gr-/st0). The 4 fetch-recommended MIT/Apache files collectively cover 8 of 10 surfaces.

## fortigate_cli

**Gap summary:** 11 supported/lossy canonical surfaces are unverified by the existing 4-fixture corpus (`kevinguenay_fgt_70g_branch.conf`, `kevinguenay_fgt_vm_hub.conf`, `user_contrib_fg100e_fos7213.conf`, synthetic `kitchen_sink.conf`) — 7 supported-but-unverified + 4 lossy-unverified, clustered into three coverage themes: VRRP/HA, SNMPv3+NTP mgmt-plane, and IPv6/MTU/tunnel dual-stack edge. **3 surface-clusters are addressable with grammar-confirmed fetch candidates** (VRRP pair, SNMPv3+NTP+DNS triad); the IPv6/MTU/tunnel cluster has only `investigate`/`reject` leads (no single clean-licensed full config exists).

### Gap surface → best candidate

| Gap surface | Kind | Best candidate | Rec |
|---|---|---|---|
| `/interfaces/interface/vrrp-groups/group` | supported | `fortinet_community_vrrp_pair_197015.conf` (forum-share) | **fetch** |
| `/interfaces/interface/vrrp-groups/group/virtual-ips` | lossy | `fortinet_community_vrrp_pair_197015.conf` (forum-share) | **fetch** |
| `/interfaces/interface/vrrp-groups/group/track-interfaces` | lossy | `fortinet_community_vrrp_pair_197015.conf` (`set vrdst`) | **fetch** |
| `/interfaces/interface/vrrp-groups/group/virtual-mac` | lossy | `fortinet_community_vrrp_pair_197015.conf` (`vrrp-virtual-mac enable`) | **fetch** |
| `/snmp/v3-user` | supported | `jqproject_fgt40f_snmpv3_ntp_dns_fos744.conf` (unlicensed, factual-output) | **fetch** |
| `/system/ntp-server` | supported | `jqproject_fgt40f_snmpv3_ntp_dns_fos744.conf` (`config ntpserver`) | **fetch** |
| `/interfaces/interface/ipv6/address/ip` | supported | `fortinet_techtip_internal6_static_ipv6.conf` (forum-share) | investigate |
| `/interfaces/interface/ipv6/address/prefix-length` | supported | `fortinet_techtip_internal6_static_ipv6.conf` (forum-share) | investigate |
| `/interfaces/interface/dhcp-client-v6` | supported | `fortinet_forum_dhcpv6pd_wan_ip6mode_dhcp.conf` (forum-share) | investigate |
| `/interfaces/interface/config/mtu` | supported | `mylesagray_fgt_jumbo_mtu_override.conf` (license UNVERIFIED) | investigate |
| `/interfaces/interface/tunnel-type` | lossy | `misc_oneliners_fgt_gre_tunnel_mtu.conf` (unlicensed) | investigate |

### Ranked fetch-recommended candidates (grammar-confirmed)

1. **`fortinet_community_vrrp_pair_197015.conf`** — fills the entire VRRP cluster (`group`, `virtual-ips`, `track-interfaces`, `virtual-mac`).
   - Source: https://community.fortinet.com/t5/FortiGate/Technical-Tip-FortiGate-VRRP-configuration-and-debug/ta-p/197015
   - Raw: — (forum thread; reconstruct config block from page, capture URL as provenance)
   - License: forum-share — Fortinet-authored Technical-Tip; embedded CLI is factual device-output config dump (same precedent as the existing Aruba/Fortinet fixtures). Import only the config block, not prose.
   - OS version: FortiOS (version-agnostic; grammar stable 6.4–7.6)
   - Confirms: per-interface `config vrrp` under `config system interface`; PRIMARY/SECONDARY pair (priority 255 vs 50) lighting `vrgrp`/`vrip`/`vrdst`/`vrrp-virtual-mac enable`/`adv-interval`/`start-time`/`preempt`/`status`. SANITIZE: `vrdst` is already `x.x.x.x` placeholder → set RFC5737 (e.g. 198.51.100.1); `vrip 10.31.101.120` is RFC1918 lab (OK). No plaintext auth.

2. **`jqproject_fgt40f_snmpv3_ntp_dns_fos744.conf`** — fills `/snmp/v3-user` + `/system/ntp-server` (+ already-supported `/system/dns-server`).
   - Source: https://github.com/cqngzhi/JQ-project/blob/a3c5352547b199159e0771794ff632bb1d140fa7/GIP%20Cybersecurity/FW/fortigate.conf
   - Raw: https://raw.githubusercontent.com/cqngzhi/JQ-project/a3c5352547b199159e0771794ff632bb1d140fa7/GIP%20Cybersecurity/FW/fortigate.conf
   - License: unlicensed (repo `/license` API → 404) — factual-device-OUTPUT full-backup precedent; LOWER preference, drop-if-author-objects. Matches the existing `user_contrib_fg100e` posture.
   - OS version: FortiOS 7.4.4 (build2662-240514), FortiGate-40F
   - Confirms: real backup with SNMPv3 USM user `snmpadmin` (`security-level auth-priv` + `auth-pwd ENC` + `priv-pwd ENC`), nested `config system ntp`→`config ntpserver`/`edit 1`/`set server "be.pool.ntp.org"`, `config system dns set primary 8.8.8.8`. SANITIZE: clean — RFC1918 ifaces, public DNS/NTP, ENC-encrypted lab hashes (no plaintext). CAVEAT: `auth-proto`/`priv-proto` not explicitly set (inherits defaults) — less dense than an explicit-proto sample; 268 KB full config.

3. **`fortinet_community_vrrp_linkmon_214419.conf`** — second VRRP pair (complements #1 with minimal-backup + `ignore-default-route` variant; fills `group`/`virtual-ips`/`track-interfaces`).
   - Source: https://community.fortinet.com/t5/FortiGate/Technical-Tip-VRRP-Active-failover-with-link-monitor/ta-p/214419
   - Raw: — (forum thread)
   - License: forum-share — Fortinet Technical-Tip KB; factual config output. Capture URL.
   - OS version: FortiOS (version-agnostic)
   - Confirms: two-unit pair on named iface `lan1` with SVI `set ip 10.0.0.252` (good vrip-vs-iface-ip distinction), `vrdst 1.1.1.1` + `vrdst-priority 10`. SANITIZE: `vrdst 1.1.1.1` is a real public IP → replace with 198.51.100.1; vrip/iface IPs are RFC1918 (OK). Lower-priority than #1 (overlaps the VRRP cluster) — fetch only if a second VRRP shape is wanted.

### Investigate-only leads (grammar-confirmed but blocked — NOT upgraded to fetch)

- **`fortinet_techtip_internal6_static_ipv6.conf`** (forum-share) — cleanest static-IPv6: `config ipv6 / set ip6-address 2001:db8:abcd:1::1/64` (RFC3849, zero sanitization). Fills `ipv6/address/ip` + `prefix-length`. Investigate: vendor KB (not operator running-config); no dhcp/mtu/tunnel in same block — would need assembly. Source: https://community.fortinet.com/t5/FortiGate/Technical-Tip-How-to-setup-the-FortiGate-to-assign-IPv6/ta-p/194156
- **`fortinet_forum_dhcpv6pd_wan_ip6mode_dhcp.conf`** (forum-share) — ONLY source with literal `set ip6-mode dhcp` (the only mode that populates `dhcp-client-v6`). Investigate: delegated prefixes redacted by poster (`xxxxa`/`xxxe`) so not a clean copy-paste; multi-IAID PD edge-case bug report. Extract WAN `set ip6-mode dhcp / set dhcp6-prefix-delegation enable` as a grammar seed. Source: https://community.fortinet.com/support-forum-92/incorrect-router-announcement-with-prefix-delegation-160935
- **`mylesagray_fgt_jumbo_mtu_override.conf`** (license UNVERIFIED) — verbatim `set mtu-override enable / set mtu 9208`; `[interfacename]` placeholder (nothing to sanitize). Investigate: repo LICENSE not confirmed (API rate-limited) — must verify before import. Source: https://github.com/mylesagray/blog/blob/master/content/posts/2013-09-09-change-mtu-support-jumbo-frames-fortios/index.md
- **`misc_oneliners_fgt_gre_tunnel_mtu.conf`** (unlicensed) — best `tunnel-type` source: `set type tunnel` GRE pair + `config system gre-tunnel` + `set type aggregate`, all RFC1918 (no sanitization), plus non-default `set mtu 1300`. Investigate: unlicensed (LICENSE blob 404) — use as grammar-seed for a synthetic GRE branch. Source: https://github.com/Simone-Zabberoni/misc-one-liners/blob/master/FORTIGATE.md
- **`ensappinfra_fortiswitch_s124e_snmpv3_ntp_dns_fsw702.conf`** (unlicensed) — adds the EXPLICIT `auth-proto sha1`/`priv-proto aes128` density #2 lacks, plus ntp/dns. Investigate: device is a **FortiSwitch** (FortiSwitchOS 7.0.2, S124EN header) not a FortiGate — confirm codec tolerance of the FortiSwitch header/switch tables or excerpt just the system snmp/ntp/dns blocks. Source: https://github.com/SyahdanAzizITNS/EnsAppInfra/blob/aac1ca7b47f75b2d156fa9f3b21a4d37a8daa78e/Samples/2026-02-04/DRC-DISTRI-SW_2026-02-04_15-24.conf
- **`chermet90_kb_vrrp_fortinet_example.conf`** (unlicensed, LICENSE 404) — two VRRP edits with multi-IP `set vrdst 1.1.1.1 8.8.8.8` (exercises multi-destination track-interfaces) + pre-sanitized RFC5737 virtual IPs. Investigate: no LICENSE + the shown snippet lacks the enclosing `edit <iface>` header (re-fetch full block first). Already covered by #1/#3.
- **`fyzethh_blog_vrrp_pair_fortinet.conf`** (MIT — only license-clean VRRP *repo*) — master/backup pair with `vrrp-virtual-mac`. Investigate: grammar is DEFECTIVE as transcribed (`config vrrp` is commented out `# config vrrp`; blocks close `end`/`End` instead of `next`+`end`) — needs manual repair before it parses; `set vrdst 200.100.50.31` is a public-looking IP → RFC5737. Source: https://raw.githubusercontent.com/Fyzethh/fyzethh.github.io/main/_posts/2024-07-16-vrrp-firewalls-fortinet.md
- **`fortinet_community_vrrp_vrdst_191882.conf`** (forum-share) — single-unit (not a pair) but fuller iface context (vdom/type physical/allowaccess/role). Investigate: single unit, thinner than #1; promote only if a single-unit rich-context fixture is wanted. Source: https://community.fortinet.com/t5/FortiGate/Technical-Tip-VRRP-Active-failover-with-VRDST-with-blackhole-routing/ta-p/191882
- **`fortinet_community_98184_snmpv3_aes256cisco_fos623.conf`** (forum-share) — v3 USM block with `priv-proto aes256cisco` edge grammar. Investigate: SNMP-user-block ONLY (no ntp/dns), fragment not full backup, FortiOS 6.2.3 (below 6.4 floor). Keep only for the aes256cisco edge case.

### Dead ends / rejected

- **`scitodk_fortigate_baseline_snmpv3_ntp_dns_fos76.conf`** — REJECT. Densest grammar of all (explicit `auth-proto sha512`/`priv-proto aes256`, all three surfaces, FOS 7.6) but a proprietary copyrighted blog (scito.dk, "Copyright (c) 2026 ScitoDK") with authored commentary — not in the MIT/Apache/BSD/ISC/CC0/Unlicense/forum-share allowlist. Grammar reference only, do not import.
- **`superiorsphere_fortios_generator_snmpv3_ntp.conf`** — REJECT. Only MIT-licensed SNMP hit, but it is JavaScript SOURCE of a config *generator* (`buildFortiOS()` pushes form-variable lines), not a device capture; pwds are plaintext template interpolations and there is no `config system dns`. Not importable as a fixture.
- **`OneUptime/blog` IPv6 dual-stack** — REJECT. Perfect static-IPv6 grammar (`set ip6-address 2001:db8.../64`, RFC3849) but CC-BY-4.0 — attribution-required, NOT in the acceptable allowlist. Source: https://github.com/OneUptime/blog/blob/master/posts/2026-03-20-ipv6-fortinet-fortigate/README.md
- **`pizzamoltobene/mike-netman`** — REJECT as a repo: AGPLv3. Its VRRP docs are copies of community.fortinet.com originals (went to those directly instead).
- **Durable negatives (don't re-hunt without a new donor):**
  - `KevinGuenay/fortinet-resources` (sibling org of the existing FGT-70G fixture) verified file-by-file to contain ZERO `config vrrp`/`set vrip` grammar — does NOT cover the VRRP surface.
  - No permissively-LICENSED FortiGate full-config with a real `config system snmp user` v3 block exists in public GitHub as of 2026-06; the only MIT hit is a JS generator. Realistic acceptable sources = (a) unlicensed full-backup repos (factual-output) and (b) community.fortinet.com forum-share (which tend to be SNMP-only fragments lacking NTP/DNS).
  - No single clean-licensed config bundles all five IPv6/MTU/tunnel surfaces (static-IPv6 + `ip6-mode dhcp` + jumbo-MTU + GRE) — `ip6-mode dhcp` appears only in redacted operator forum pastes; jumbo-MTU+GRE only in MIT-or-unlicensed snippets. A SYNTHETIC composite seeded from the grammar-confirmed fragments above is the practical path for the IPv6/MTU/tunnel cluster.
  - GitHub code-search API rate-limited (403 after ~10 queries) in M1/M2/M3 — refinement passes (`"config vrrp" "set vrgrp" extension:conf`, `fortinet.fortios` Ansible collection test data, `set ip6-mode dhcp set mtu`) are open for a future hunt with fresh quota.

**Note on existing coverage:** the v2c SNMP corpus (FG100E community fixture) is correctly NOT duplicated — every SNMP candidate here carries the `config system snmp user` v3 USM block.

## mikrotik_routeros

**Gap summary:** 12 supported/lossy canonical surfaces unverified (11 supported + 1 lossy `dhcp-client-v6`). Two clean **fetch** candidates (both unlicensed/device-output) cover the management-plane + early-v7 IPv6/DHCPv6 surfaces; the VRRP, IPv4 static-route, and IPv6-on-tunnel surfaces are reachable only via **investigate**-grade leads (CC-BY-SA-4.0 or unlicensed). One surface — a true `gre/eoip/ipip` `tunnel-type` — is a **durable negative** (no license-clean all-in-one capture found as of 2026-06-15).

### Gap surface → best candidate

| Gap surface | Best candidate | Rec | License |
|---|---|---|---|
| `/interfaces/interface/ipv6/address/ip` | kcleong_kpn_fiber_v6_fos716.rsc (ROS 7.16) | investigate | unlicensed (device-output) |
| `/interfaces/interface/ipv6/address/prefix-length` | kcleong_kpn_fiber_v6_fos716.rsc (ROS 7.16) | investigate | unlicensed (device-output) |
| `/interfaces/interface/tunnel-type` | mtrimarchi_fastweb_6rd_v6.rsc (6to4/6rd only — NOT gre/eoip/ipip) | investigate (weak) | unlicensed (device-output) |
| `/interfaces/interface/vrrp-groups/group` | samsara_esnet_ha_vrrp_edge1_master.rsc (IPv4) / feichay10 (IPv6) | investigate | unlicensed / CC-BY-SA-4.0 |
| `/routing/static-route` | marfillaster_dualwan_routes_fos7.rsc (richest `/ip route` corpus) | investigate | unlicensed (device-output) |
| `/snmp/community` | quangproo_fpt_mgmt_plane_snmpv3_ntp_dns_ros7.rsc | **fetch** | unlicensed (device-output) |
| `/snmp/contact` | quangproo_fpt_mgmt_plane_snmpv3_ntp_dns_ros7.rsc | **fetch** | unlicensed (device-output) |
| `/snmp/location` | quangproo_fpt_mgmt_plane_snmpv3_ntp_dns_ros7.rsc | **fetch** | unlicensed (device-output) |
| `/snmp/trap-host` | quangproo_fpt_mgmt_plane_snmpv3_ntp_dns_ros7.rsc | **fetch** | unlicensed (device-output) |
| `/system/dns-server` | quangproo_fpt_mgmt_plane_snmpv3_ntp_dns_ros7.rsc | **fetch** | unlicensed (device-output) |
| `/system/ntp-server` | quangproo_fpt_mgmt_plane_snmpv3_ntp_dns_ros7.rsc | **fetch** | unlicensed (device-output) |
| `/interfaces/interface/dhcp-client-v6` (lossy) | kcleong_kpn_fiber_v6_fos716.rsc (ROS 7.16) | investigate | unlicensed (device-output) |

### Ranked candidates

**FETCH-recommended (grammar-confirmed, first):**

1. **quangproo_fpt_mgmt_plane_snmpv3_ntp_dns_ros7.rsc** — `fetch`
   - Source: https://github.com/quangproo/fpt/blob/main/switch.rsc
   - Raw: https://raw.githubusercontent.com/quangproo/fpt/main/switch.rsc
   - License: **none / unlicensed public repo** — `gh api repos/quangproo/fpt` → `"license": null`, `/license` endpoint 404. Genuine RouterOS `/export` device-output → factual-output precedent (drop-if-author-objects), LOWER preference than an explicitly-permissive source.
   - OS version: RouterOS 7.x (`/system ntp client servers add address=` multi-server form + SNMPv3 `authentication-protocol=SHA256`, both ROS7-era)
   - Surfaces filled: `/snmp/community`, `/snmp/location`, `/snmp/contact`, `/snmp/trap-host`, (`/snmp/v3-user`), `/system/ntp-server`, `/system/dns-server`
   - Confirmation: `/snmp community add name=zabbix-iser … authentication-protocol=SHA256 encryption-protocol=AES` + `/snmp set … contact=… location=… trap-version=3 trap-target=…` + `/system ntp client servers add address=…` + `/ip dns set servers=…` — all 6 mgmt-plane gap surfaces in one ROS7 file.
   - **Sanitize before commit:** replace public-range IPs `92.92.92.13` (trap-target) / `92.92.92.1` (ntp+dns) with RFC5737 (198.51.100.13 / 203.0.113.1); contact `contact@quang.pro` → admin@example.com; auth/priv passwords are already placeholders (`<switch_sha256>`/`<switch_aes>`). Confirm codec accepts the `privacy-password=` alias else rename to `encryption-password=`.

2. **quangproo_fpt_ntp_servers_dns_dualstack_ros7.rsc** — `fetch` (companion, optional)
   - Source: https://github.com/quangproo/fpt/blob/main/router.rsc
   - Raw: https://raw.githubusercontent.com/quangproo/fpt/main/router.rsc
   - License: **none / unlicensed** (same repo as switch.rsc — `"license": null`, `/license` 404). Device-output precedent, lower preference.
   - OS version: RouterOS 7.x (`/system ntp client servers add … iburst=yes` multi-server + dual-stack `/ip dns set servers=` with IPv6 resolvers)
   - Surfaces filled: `/system/ntp-server`, `/system/dns-server`
   - Confirmation: 6-server `/system ntp client servers add` (incl. FQDN `time.cloudflare.com`/`*.pool.ntp.org`) + dual-stack `/ip dns set servers=1.1.1.1,8.8.8.8,2001:4860:4860::8888,2606:4700:4700::1111`. Exercises the IPv6-DNS + FQDN-NTP code paths switch.rsc does not; redundant on surfaces switch.rsc already fills (only fetch if the extra grammar coverage is wanted). Public well-known NTP/DNS values are lab-safe; bare IPs `20.189.79.72`/`208.75.88.4` may be normalized.

**INVESTIGATE-grade (grammar-confirmed but license/grammar caveats — do NOT upgrade to fetch):**

3. **kcleong_kpn_fiber_v6_fos716.rsc** — `investigate`
   - Source: https://gist.github.com/kcleong/426ae7a5c3c5ecb4870bb82966e80ef4
   - Raw: https://gist.githubusercontent.com/kcleong/426ae7a5c3c5ecb4870bb82966e80ef4/raw
   - License: **none / unlicensed gist** — real `/export` (`# 2024-12-06 … by RouterOS 7.16`), device-output precedent.
   - OS version: RouterOS 7.16
   - Surfaces filled: `/interfaces/interface/ipv6/address/ip`, `/interfaces/interface/ipv6/address/prefix-length`, `/interfaces/interface/dhcp-client-v6` (lossy), `/system/dns-server`, `/system/ntp-server`
   - Confirmation: `/ipv6 dhcp-client add … pool-name= pool-prefix-length=48` + `/ipv6 address add address=::1 from-pool=… ` + `/ip dns set servers=…`. BEST real DHCPv6-client + IPv6-address fill, but IPv6 addr is **pool-derived `::1`**, not a static `2001:db8` GUA. No `/ip route`, no tunnel. Verify no real PPPoE credential before commit.

4. **samsara_esnet_ha_vrrp_edge1_master.rsc** — `investigate`
   - Source: https://github.com/samsara-02/POC_ESNET_MikroTik_Proxmox_HA/blob/ee1e1d73f09bdae044260e43054185c216cc7822/configs/mikrotik/edge-1.rsc
   - Raw: https://raw.githubusercontent.com/samsara-02/POC_ESNET_MikroTik_Proxmox_HA/ee1e1d73f09bdae044260e43054185c216cc7822/configs/mikrotik/edge-1.rsc
   - License: **none / unlicensed repo** (`gh api` → no LICENSE, `/license` → NO-LICENSE). Device-output precedent, drop-if-author-objects.
   - OS version: RouterOS 7.x (CHR; `/ip route add … check-gateway=ping distance=`)
   - Surfaces filled: `/interfaces/interface/vrrp-groups/group`, `/routing/static-route`
   - Confirmation: `/interface vrrp add … vrid=10 priority=110` + `/ip address add … interface=vrrp-mgmt` VIP + `/ip route add dst-address=0.0.0.0/0 gateway=203.0.113.1`. Strongest single-file IPv4 coverage (3 of 4 target surfaces); already RFC5737/RFC1918-clean, no secrets. IPv4-only (no IPv6). Paired backup `edge-2.rsc` verified (priority=100). Sole blocker = no LICENSE.

5. **feichay10_finaldegree_vrrp_ipv6_ros7.rsc** — `investigate`
   - Source: https://github.com/feichay10/Final-Degree-Project/blob/5888bce9147682140dce4f35a5beb030cf55624b/config_devices/oficina_central_ipv6/CE1.rsc
   - Raw: https://raw.githubusercontent.com/feichay10/Final-Degree-Project/5888bce9147682140dce4f35a5beb030cf55624b/config_devices/oficina_central_ipv6/CE1.rsc
   - License: **CC-BY-SA-4.0** — repo root `LICENCE` file (British spelling → GitHub SPDX reports NOASSERTION); content confirmed CC-BY-SA-4.0 via `gh api`. NOT on the clean list (MIT/Apache/BSD/ISC/CC0/Unlicense); ShareAlike copyleft. `.rsc` is factual device-style output (precedent may cover), but requires a policy call + NOTICE.md attribution + ShareAlike notice if accepted.
   - OS version: RouterOS 7.x (`version=3 v3-protocol=ipv6` VRRPv3)
   - Surfaces filled: `/interfaces/interface/vrrp-groups/group`, `/interfaces/interface/ipv6/address/ip`, `/interfaces/interface/ipv6/address/prefix-length`
   - Confirmation: 3 VRRPv3 IPv6 groups (`vrid 10/20/30`, `priority=150`, `version=3 v3-protocol=ipv6`) each with a `/ipv6 address add address=2001:db8:1234:01NN::2/64 interface=vrrp-…` VIP. Already RFC3849-clean. BEST IPv6-VRRP fill; pairs with the same-repo IPv4 master/backup CE1 set. License is the gating question.

6. **feichay10_finaldegree_vrrp_ipv4_master_ros7.rsc** — `investigate`
   - Source: https://github.com/feichay10/Final-Degree-Project/blob/5888bce9147682140dce4f35a5beb030cf55624b/config_devices/oficina_central/CE1.rsc
   - Raw: https://raw.githubusercontent.com/feichay10/Final-Degree-Project/5888bce9147682140dce4f35a5beb030cf55624b/config_devices/oficina_central/CE1.rsc
   - License: **CC-BY-SA-4.0** (same repo `LICENCE`).
   - OS version: RouterOS 7.x (`/routing bgp connection add`)
   - Surfaces filled: `/interfaces/interface/vrrp-groups/group`
   - Confirmation: textbook IPv4 master/backup PAIR (CE1.rsc priority=150 + CE1_backup.rsc priority=100, shared vrid 10/20/30, VIPs 192.168.1.3/.67/.131 on vrrp-datos/voz/dmz). **Sanitize** non-RFC5737 public IPs `192.170.0.1`/`192.170.0.6` (loopback/BGP router-id) → 203.0.113.x. Routes via BGP not `/ip route` (does not fill static-route). Same CC-BY-SA caveat.

7. **marfillaster_dualwan_routes_fos7.rsc** — `investigate`
   - Source: https://gist.github.com/marfillaster/7a136ea826815ac22f2849e099a1c6a1
   - Raw: https://gist.githubusercontent.com/marfillaster/7a136ea826815ac22f2849e099a1c6a1/raw
   - License: **none / unlicensed gist** — paste-script (command-form, no `# by RouterOS` header). Device-output precedent.
   - OS version: RouterOS 7 (v7 routing-table syntax; build not in header)
   - Surfaces filled: `/routing/static-route`, `/system/dns-server`
   - Confirmation: ~12 `/ip route add dst-address=… gateway=…` lines incl. default `0.0.0.0/0` + per-routing-table recursive routes, plus `/ip dns set … servers=1.1.1.1,8.8.8.8`. RICHEST real `/ip route` corpus. No IPv6, no tunnel. Confirm codec accepts command-form input (it should — `/export` emits the same grammar). Gateways are public resolver IPs (note presence).

8. **mtrimarchi_fastweb_6rd_v6.rsc** — `investigate` (weak / tunnel-type only marginally)
   - Source: https://gist.github.com/mtrimarchi/c0381d694350ede974f00cea76f8781c
   - Raw: https://gist.githubusercontent.com/mtrimarchi/c0381d694350ede974f00cea76f8781c/raw
   - License: **none / unlicensed gist** — device-output precedent.
   - OS version: RouterOS (6rd/6to4 form; build not surfaced)
   - Surfaces filled: `/interfaces/interface/ipv6/address/ip`, `/interfaces/interface/ipv6/address/prefix-length`, `/interfaces/interface/tunnel-type` (6to4 only)
   - Confirmation: `/ipv6 address add address=2001:b07::/32 … interface=6rd` + `/interface 6to4 … local-address=2.230.192.193`. The tunnel is **`/interface 6to4` (IPv6-transition), NOT gre/eoip/ipip** — only marginally satisfies a generic `tunnel-type`. **Sanitize** REAL public IPs `2.230.192.193`/`81.208.50.214` (Fastweb WAN) → RFC5737 + GUA `2001:b07::…` → RFC3849. Only pursue if 6to4/6rd counts as tunnel-type.

9. **valeriansaliou_orange_livebox_v6_fos646.rsc** — `investigate` (fallback for DHCPv6)
   - Source: https://gist.github.com/valeriansaliou/380ca483e295dc96efc51a2142187260
   - Raw: https://gist.githubusercontent.com/valeriansaliou/380ca483e295dc96efc51a2142187260/raw
   - License: **none / unlicensed gist** — real `/export` (`# jan/13/2020 … by RouterOS 6.46.1`), device-output precedent.
   - OS version: RouterOS 6.46.1
   - Surfaces filled: `/interfaces/interface/dhcp-client-v6` (lossy), `/interfaces/interface/ipv6/address/ip`, `/system/ntp-server`
   - Confirmation: `/ipv6 dhcp-client add add-default-route=yes dhcp-options=… request=prefix` + `/ipv6 address add address=::1 from-pool=…` + `/system ntp client …`. Confirmed DHCPv6 fallback, but ROS6 (not the missing ROS7 0–10 bridge) and lacks a route + tunnel → less router-shaped than kcleong; lower priority for the same surfaces.

10. **forum_mikrotik_t52181_snmp_export_trap.rsc** — `investigate` (forum-share SNMP fallback)
    - Source: https://forum.mikrotik.com/viewtopic.php?t=52181
    - Raw: — (paste fragment; must be reconstructed by hand from the thread)
    - License: **forum-share** — operator `/export` paste while troubleshooting; factual device-output, same class as existing community.cisco.com/forum.vyos.io fixtures. Capture thread URL.
    - OS version: RouterOS 6.x-era (SHA1/DES; one legacy variant ROS 5.3-or-earlier)
    - Surfaces filled: `/snmp/community`, `/snmp/location`, `/snmp/contact`, `/snmp/trap-host`, (`/snmp/v3-user`)
    - Confirmation: `/snmp set contact=… location=… trap-community=… trap-target=… trap-version=3` + `/snmp community set … authentication-protocol=SHA1 encryption-protocol=DES security=private`. Only the **license-clean (forum-share)** fallback for SNMP if the unlicensed quangproo source is rejected; no NTP/DNS, ROS6 SHA1/DES grammar, and it is a fragment (normalize `0.0.0.0`/`0.0.0.0/0` placeholders to RFC5737).

### Dead ends / blocked

- **`/interfaces/interface/tunnel-type` (true gre/eoip/ipip):** DURABLE NEGATIVE as of 2026-06-15. No license-clean public `/export` contains a real `/interface gre|eoip|ipip` tunnel co-located with the other router surfaces. Tunnel material is either vendor docs (help.mikrotik.com / wiki — proprietary), tutorial guides (not an `/export`), or IPv6-transition tunnels (`/interface 6to4`/6rd — mtrimarchi, johnelliott — not gre/eoip/ipip). REJECTED on license: `eworm-de/routeros-scripts` (GPL-3.0, `update-gre-address.rsc`), `floeff/routeros-configuration` (GPL-3.0). The only generic `tunnel-type` lead (mtrimarchi 6to4) does not satisfy a strict gre/eoip/ipip ask. **Recommendation:** synthesize the gre/eoip/ipip surface, or accept the marginal 6to4 fill, rather than re-hunt.
- **Static IPv6 GUA literal on an interface (preferred `2001:db8` form):** All real captures use **pool-derived `::1`** (kcleong, valeriansaliou) or a tunnel-bound 6rd prefix (mtrimarchi). The only clean static `2001:db8::/64` VIP literals are the CC-BY-SA feichay10 VRRP files (license-gated). No unlicensed/permissive static-GUA-on-plain-interface capture found.
- **License-clean (MIT/Apache/BSD/ISC/CC0) all-surfaces file:** none found. Every all-in-one or rich file is either unlicensed (device-output precedent only — quangproo, samsara, marfillaster, the gists) or copyleft (CC-BY-SA feichay10; GPL-3.0 eworm/floeff/amit-nz). `alani4837/mikrotik-templates` claims MIT in README but has **no LICENSE file** (404) and is a hand-authored `<PLACEHOLDER>` template (not device-output) → REJECTED. `svlsResearch/ha-mikrotik` HA_init.rsc REJECTED (no LICENSE + authored parametric `$var` template, no concrete vrid).
- **Tooling negatives:** Batfish has no MikroTik parser/test configs; containerlab/netlab repos configure CHR at runtime (no committed `/export` fixtures). GitHub code-search hit the API rate limit (403) before SNMPv3 grammar queries could be exhausted in M3.

## vyos

11 supported surfaces unverified (+7 lossy-unverified). Of the 11 supported gaps, only 3 have a grammar-confirmed **fetch**-grade candidate (the SNMPv3 USM cluster + DHCPv6-PD client); the LAG/VRF/MTU/VXLAN-mcast surfaces are either forum-share/unlicensed **investigate**-only leads or fully blocked. Two genuinely strong fetch leads emerged: the **forum.vyos.io SNMPv3** paste (curly + set-form, fills the v3-user prize) and the **Hou-dev DHCPv6-PD** curly `config.boot`.

### Gap-surface → best candidate

| Gap surface | Best candidate | Rec | License |
|---|---|---|---|
| `/snmp/v3-user` | forum.vyos.io 6881 (curly `show service snmp v3` + set-form) | **fetch** | forum-share |
| `/snmp/v3-user/auth-passphrase` (lossy) | forum.vyos.io 6881 | **fetch** | forum-share |
| `/snmp/v3-user/engine-id` (lossy) | forum.vyos.io 6881 | **fetch** | forum-share |
| `/snmp/location` | forum.vyos.io 6881 (set-form `set service snmp location 'HOME'`) | **fetch** | forum-share |
| `/snmp/contact` | — none found (not in any located permissive source) | — | — |
| `/interfaces/interface/dhcp-client-v6` | Hou-dev/Vyos-Config `config.boot` (curly, pre-sanitized) | **fetch** | unlicensed-public-repo |
| `/vxlan-vnis/mcast-group` | forum.vyos.io 14422 (set-form `group '239.1.1.1'`) | investigate | forum-share |
| `/vxlan-vnis/source-interface` (lossy) | forum.vyos.io 14422 (`source-interface 'dum0'`) | investigate | forum-share |
| `/lags/lag/name` | forum.vyos.io 15774 (`bonding bond0/bond1 mode 802.3ad`) | investigate | forum-share |
| `/lags/lag/members` | forum.vyos.io 15774 | investigate | forum-share |
| `/lags/lag/mode` (lossy) | forum.vyos.io 15774 | investigate | forum-share |
| `/interfaces/interface/lag-member-of` | forum.vyos.io 15774 | investigate | forum-share |
| `/interfaces/interface/config/mtu` | vanwerkhoven.org (set-form pppoe `mtu '1492'/'1500'`) | investigate | unlicensed-blog |
| `/interfaces/interface/config/vrf` | — none found (durable negative; per-iface `vrf` ships with the VRF block) | — | — |
| `/routing-instances/instance/name` | — none found (durable negative — no permissive curly `vrf name` capture) | — | — |
| `/routing-instances/instance/table` (lossy; synthesised) | — none found | — | — |
| `/interfaces/interface/config/type` (lossy; inferred) | n/a — derived field, no donor needed | — | — |
| `/system/raw-sections/version-banner` (lossy) | covered by any 1.4/1.5 fixture header (`// vyos-config-version`) | — | — |

### Ranked candidates (fetch-recommended first)

**1. forum_vyos_snmpv3_user (FETCH)** — the unverified PRIZE grammar, confirmed in BOTH curly and set-form.
- Proposed filename: `vyos_forum_snmpv3_user_eq13.conf`
- Source: https://forum.vyos.io/t/snmp-v3-unable-to-connect/6881
- Raw URL: (none — forum paste; assemble from the `Witchy` curly `show service snmp v3` block + `jack9603301` set-form block)
- License: forum-share — operator troubleshooting paste on forum.vyos.io (approved forum-share list, sibling to forum.opnsense.org / community.cisco.com per NOTICE.md). Factual device-output, not creative authorship.
- OS version: VyOS 1.3 equuleus build 202103 (curly paste) + VyOS 1.4-rolling-20210327 (set-form paste)
- Surfaces filled: `/snmp/v3-user`, `/snmp/v3-user/auth-passphrase`, `/snmp/v3-user/engine-id`, `/snmp/location`
- Confirmation: `user vyos { auth { encrypted-password <hex> type sha } privacy { encrypted-password <hex> type aes } }` (curly) + full set-form `set service snmp v3 user vyos auth/privacy ... type sha/aes` with `engineid` and `location 'HOME'`.
- ⚠️ Caveat: the curly paste is a `show service snmp v3` *fragment* (service-subtree only) — must be hand-wrapped into a `service { snmp { ... } }` config.boot, like the synthetic-kitchen-sink approach. SANITIZE the demo hash `4e52fe…` and engineid `000…0002` to published lab values before commit. Does NOT carry `/snmp/contact` — add synthetically or pair with the scottlaird NTP/community fixture.

**2. houdev_dhcpv6_pd_client (FETCH)** — strongest match for the DHCPv6-PD client gap; native curly config.boot, author-pre-sanitized.
- Proposed filename: `houdev_dhcpv6_pd_client_wan.config.boot`
- Source: https://github.com/Hou-dev/Vyos-Config/blob/main/config.boot
- Raw URL: https://raw.githubusercontent.com/Hou-dev/Vyos-Config/main/config.boot
- License: unlicensed-public-repo — repo root has only README.md + config.boot, NO LICENSE/SPDX. Falls under factual-device-output precedent; **LOWER preference, flag clearly, drop if author objects.**
- OS version: VyOS (no header; `address "dhcpv6"` quoted-value + `rapid-commit { }` + offload block ⇒ 1.4/1.5-compatible)
- Surfaces filled: `/interfaces/interface/dhcp-client-v6`
- Confirmation: `ethernet eth0 { address "dhcpv6" dhcpv6-options { pd 0 { interface eth1 { address "1" sla-id "0" } length "64" } rapid-commit { } } ipv6 { address { autoconf { } } } }`
- ⚠️ Caveat: author masked MACs (`xx:xx:…`)/IPv4 (`192.168.1.xxx`)/IPv6 (`xxxx::…`) — normalise placeholders to valid RFC5737/RFC3849 literals so the codec parses (`xxxx::` is not a valid address). MTU NOT bagged (only `link-mtu` inside an RA block — wrong surface; reachable via M2/vanwerkhoven). License is the only weakness.

### Investigate-grade (logged so we don't re-hunt; do NOT upgrade to fetch)

- **forum_vyos_vxlan_mcast_leaf (investigate)** — https://forum.vyos.io/t/spine-leaf-vxlan-multicast-not-working/14422 — forum-share, VyOS 1.5.x; fills `/vxlan-vnis/mcast-group` + `/vxlan-vnis/source-interface` via `set interfaces vxlan vxlan10 group '239.1.1.1' source-interface 'dum0' vni '10010'`. Fragments not a full config.boot; fills only the multicast half — LAG/jumbo would need synthesis.
- **forum_vyos_bonding_lacp (investigate)** — https://forum.vyos.io/t/could-you-help-me-review-the-following-lacp-code-where-i-added-vlan-configurations/15774 — forum-share, VyOS 1.3.3; fills `/lags/lag/{name,members,mode}` + `/interfaces/interface/lag-member-of` via `bonding bond0/bond1 mode 802.3ad`. Disjoint from VXLAN; older 1.3.3 (bonding grammar is version-stable).
- **vanwerkhoven_pppoe_dhcpv6_pd_mtu (investigate)** — https://www.vanwerkhoven.org/blog/2024/vyos-from-scratch-with-vlan-and-zone-based-firewall/ — unlicensed-blog, VyOS 1.5-rolling; the ONLY hit pairing `dhcpv6-options pd` with explicit `mtu '1492'/'1500'`, but on a **pppoe** iface (verify pppoe→canonical mtu xpath), set-form tutorial narrative (needs assembly), redundant on dhcp-client-v6 vs Hou-dev.
- **scottlaird_vyos_parser_ntp_community (investigate)** — https://github.com/scottlaird/vyos-parser/blob/main/parser/testdata/config.boot.1 (raw: https://raw.githubusercontent.com/scottlaird/vyos-parser/main/parser/testdata/config.boot.1) — **Apache-2.0** (clean), VyOS 1.5-rolling; confirms block-form `service { ntp { server <host> { } } }` + SNMPv2 `community public`. Misses the v3 prize. NOTE: scottlaird already a corpus donor (VXLAN) — VERIFY config.boot.1 not already imported. Useful clean-license donor for `/system/ntp-server` and a possible `/snmp/contact` add-on.
- **forum_vyos_snmpv3_trap_target (investigate)** — https://forum.vyos.io/t/snmp-v3-trap-target-is-busted/17161 — forum-share; re-confirms auth/privacy/engineid set-form on a `trap-target` (which Netcanon keeps `trap_hosts` EMPTY — unsupported). Supplementary only; mostly re-confirms candidate #1's surfaces.
- **siketyan_flets_dhcpv6_pd (investigate)** — https://gist.github.com/siketyan/a5d02d4c5d4f9118412748903087a02c — unlicensed gist, /56 PD variant; redundant with Hou-dev, has REAL duid/MAC to sanitize.
- **problemofnetwork_fiber7_dhcpv6_pd (investigate)** — https://www.problemofnetwork.com/posts/updating-my-fiber7-vyos-config-to-1dot5/ — unlicensed-blog, VyOS 1.5 set-form /48; REAL Init7 PD prefix `2a02:168:4047::/48` + MAC must be redacted to RFC3849. Redundant on the gap vs Hou-dev.

### Dead ends / blocked

- **`/snmp/contact`** — NO located permissive source carries `contact` alongside the v3-user prize. The scottlaird Apache fixture has NTP+community but no contact/v3; the forum 6881 paste has location but not contact. Add synthetically when wrapping the SNMPv3 fixture.
- **`/routing-instances/instance/name`, `/routing-instances/instance/table`, `/interfaces/interface/config/vrf`** — DURABLE NEGATIVE (re-confirmed this hunt): no permissive curly-brace `vrf name` capture exists. All real `vrf name` configs are GPL `vyos-1x` or unlicensed. VRF remains the lone SYNTHETIC surface — do NOT re-hunt without a new donor.
- **VXLAN multicast + LACP bonding + jumbo MTU in ONE file** — GitHub code-search is conclusive: all three curly/set-form token combos return total_count=1, the sole hit being netcanon's OWN test_vyos.py. No third-party permissive repo pairs multicast VXLAN with 802.3ad bonding. The richest grammar (vyos/vyos-documentation: group 239.x + bonding + mtu) is **unlicensed** (404 on /license, GPL-project-associated) → inspiration-only. vyos-legacy/vyos-vxlan has perfect curly `group 239.0.0.1`+`vni` grammar but is **GPL-2.0** → HARD REJECT. The combined LAG+jumbo+mcast leaf must be SYNTHESIZED from the two disjoint forum-share leads (14422 + 15774).
- **onedr0p/vyos-config** — the only Apache-2.0 VyOS config repo found, but archived 2024-07-10 with a LICENSE-only commit (config.boot never committed) → no importable content.
- **uwwisaca/CCDC STIG guide** — has well-formed v3-user set-form grammar but is an UNLICENSED hardening template with PLACEHOLDER values (`<snmp-auth-password>`) — not a device capture, not factual-output → REJECT (corroborates P6 set-form grammar only).

**Honesty note:** GitHub code-search + targeted license-scoped web queries proved the multicast-VXLAN+LACP+jumbo combo and the curly `vrf name` capture are simply not available under a permissive license — both remain synthesis-only. Of the supported gaps, only the SNMPv3 USM cluster and DHCPv6-PD client clear the fetch bar.

## cisco_iosxe_cli

6 unverified canonical surfaces (4 supported-but-unverified + 2 lossy-unverified). 3 are addressable now with grammar-confirmed, license-clean fetch candidates; the 2 anycast surfaces and `/snmp/v3-user` (full subtree) remain effectively unfillable from OSS.

### Gap surfaces -> best candidate

| Gap surface | Class | Best candidate | Status |
|---|---|---|---|
| `/anycast-gateway-mac` | supported | — none found (OSS token dominated by NX-OS) | blocked |
| `/interfaces/interface/ipv4/address/virtual-gateway-address` | supported | — none found (same NX-OS domination) | blocked |
| `/interfaces/interface/dhcp-client-v6` | supported | `epiecs/cisco-config-snippets` ipv6/interface.ios (MIT) + `beasleymd/Ansible_Workshop_Demo` rtr1 17.14 (literal `ipv6 address dhcp`) | fetch / investigate |
| `/snmp/v3-user` | supported | `networklore/ansible-cisco-snmp` README (Apache-2.0) — v3 USM user line only, partial subtree | fetch (partial) |
| `/evpn-type5-routes/route` | lossy | `imanassypov/CatalystCenter-BGP-EVPN-VXLAN` Leaf01.cfg 17.15 (unlicensed device-output) | investigate |
| `/interfaces/interface/vrrp-groups/group/address-family` | lossy | `epiecs/cisco-config-snippets` fhrp/vrrp.ios (MIT) | fetch |

### Ranked candidates — grammar-confirmed, fetch-recommended first

1. **`epiecs_snippets_vrrp_afi_iosxe17.conf`** — fetch
   - Source: https://github.com/epiecs/cisco-config-snippets/blob/master/fhrp/vrrp.ios
   - Raw: https://raw.githubusercontent.com/epiecs/cisco-config-snippets/master/fhrp/vrrp.ios
   - License: MIT (repo root LICENSE, "Copyright (c) 2022 Gregory Bers", fetched verbatim HTTP 200)
   - OS: IOS-XE 17.x-era (VRRPv3 `fhrp version vrrp v3` + nested address-family)
   - Surfaces: `/interfaces/interface/vrrp-groups/group/address-family`
   - Note: Contains exact modern grammar `vrrp 20 address-family ipv4`/`ipv6` + `address ... primary`/`priority` on SVI; RFC1918/RFC3849 pre-sanitized. Minor lift (snippet, not full `show run`).

2. **`epiecs_snippets_ipv6_autoconfig_iosxe.conf`** — fetch
   - Source: https://github.com/epiecs/cisco-config-snippets/blob/master/ipv6/interface.ios
   - Raw: https://raw.githubusercontent.com/epiecs/cisco-config-snippets/master/ipv6/interface.ios
   - License: MIT (same repo as #1)
   - OS: IOS 15.x / IOS-XE 16.x/17.x (stable grammar)
   - Surfaces: `/interfaces/interface/dhcp-client-v6` (SLAAC/autoconfig branch)
   - Note: `ipv6 unicast-routing` + `interface g0/0 / ipv6 address autoconfig`; covers the SLAAC variant, not the stateful `ipv6 address dhcp` literal (see #3). Pair with #1 into one dual-stack stub.

3. **`networklore_ansible_cisco_snmp_v3usm_iosxe.conf`** — fetch (PARTIAL subtree only)
   - Source: https://github.com/networklore/ansible-cisco-snmp/blob/master/README.md
   - Raw: https://raw.githubusercontent.com/networklore/ansible-cisco-snmp/master/README.md
   - License: Apache-2.0 (LICENSE file = standard Apache-2.0 text fetched verbatim; GitHub API reports NOASSERTION auto-detector quirk, content unambiguous)
   - OS: any IOS-XE 16.x/17.x (SHA/AES-128 grammar)
   - Surfaces: `/snmp/v3-user` (+ group/view/community)
   - Note: `snmp-server user ansible ANSIBLEGRP v3 auth sha ... priv aes 128 ...` confirms the prize grammar with lab-placeholder passwords (no scrub). CAVEATS: lines live in README prose (hand-lift, not a standalone .cfg); MISSING `/snmp/trap-host`, location, contact; uses aes-128 not the richer sha256/aes256. Honest classification: clean fallback that confirms the v3 USM grammar but does NOT cover the full snmp subtree.

### Investigate-only leads (NOT upgraded to fetch)

- **`ansible_workshop_c8000v_vrf_tunnel_fos1714.conf`** — investigate. `beasleymd/Ansible_Workshop_Demo` rtr1 (C8000V, IOS-XE 17.14, real `sh run`). Source: https://github.com/beasleymd/Ansible_Workshop_Demo/tree/main/Original%20RTR%20Configs%20-%20Workshop%20Labs ; Raw: https://raw.githubusercontent.com/beasleymd/Ansible_Workshop_Demo/main/Original%20RTR%20Configs%20-%20Workshop%20Labs/Orig_Golden_Configs_rtr1_02-12-2026.rtf . License: unlicensed-public-repo (factual device-output precedent, lower preference, drop-if-author-objects). Grammar-confirmed: carries the literal `ipv6 address dhcp` (stateful DHCPv6-client -> dhcp6) + `interface Tunnel0` GRE + `ip route vrf GS ... global`. Held at investigate because: (1) .RTF — must strip RTF control words; (2) HIGH sanitization burden — real AWS WAN dest IP `3.12.151.75`, device serial `9YXMF1TE722`, ssh key-hash for `ec2-user`, two self-signed cert chains all need scrubbing first.

- **`imanassypov_catc_evpn_leaf_iosxe1715.cfg`** — investigate. Catalyst 9000V EVPN-VXLAN leaf, IOS-XE 17.15. Source: https://github.com/imanassypov/CatalystCenter-BGP-EVPN-VXLAN/blob/main/Node%20Configs/Config-Backup-032626/Leaf01.cfg ; Raw: https://raw.githubusercontent.com/imanassypov/CatalystCenter-BGP-EVPN-VXLAN/main/Node%20Configs/Config-Backup-032626/Leaf01.cfg . License: unlicensed-device-output (license API 404; factual device-output precedent, lower preference, drop-if-author-objects). Grammar-confirmed: per-VRF `address-family ipv4 vrf <vrf>` with `advertise l2vpn evpn` fills the lossy `/evpn-type5-routes/route` surface; does NOT contain `fabric forwarding` tokens. Held at investigate due to unlicensed status + REQUIRED sanitization (enable/username plaintext `C1sco12345`, SNMP communities, RADIUS/syslog hosts, key-7 hashes, PKI chains). Companion `Border01.cfg` is a same-repo alternative for the EVPN address-family/ASN-rewrite border surface.

- **`ciscolive_brkops1104_evpn_leaf_fos1715.conf` / `..._border_fos1715.conf`** — investigate (out-of-target surfaces). `StayFresh-NetworkBytes/CiscoLive-BRKOPS-1104-Lab`, real IOS-XE 17.15 CML EVPN configs. Fill vlan/id + vrf-definition + per-vrf static (`ip route vrf cml_demo`) — useful for OS-version diversification but NOT the specific gap surfaces here; do NOT contain `snmp-server user` or `anycast-gateway-mac`. Unlicensed (404), one type-9 secret hash to swap.

- **`ciscocommunity_snmpv3_sha2_iosxe.conf`** / **`cisccomm_asr920_vrrpv3_ipv6_forumshare.conf`** — investigate (BLOCKED this session). community.cisco.com forum-share threads (SNMPv3 SHA-256 td-p/3768326; ASR920 VRRPv3-IPv6 td-p/3887996) are the strongest precedent-clean route to a COMPLETE operator-pasted running-config (would cover the full snmp subtree incl. trap-host, and a real modern-VRRP-AF capture). Grammar NOT confirmed — community.cisco.com returns HTTP 403 to WebFetch and no Chrome browser was connected. Needs a browser-class re-fetch to verify verbatim grammar + scrub before commit.

## cisco_iosxr

**Gap summary:** 0 supported-but-unverified canonical surfaces; 1 lossy-unverified surface (`/interfaces/interface/4th-port-segment`). The codec corpus is in strong shape — every *supported* surface is already exercised by an existing fixture. The lone lossy gap (4-segment port numbering, e.g. `Gi0/0/0/N`) is trivially fillable, and the search surfaced license-clean candidates that also opportunistically reinforce LAG/dot1q/MTU coverage and add OS-version diversity.

### Gap surfaces → best candidate

| Gap surface | Class | Best candidate | Recommendation |
|---|---|---|---|
| `/interfaces/interface/4th-port-segment` | lossy-unverified | `iosxr_design_cst_v5_pa3_bundle_active_on_dot1q_mtu_fos752.conf` (ios-xr/design, Gi/Te `0/0/0/N`, XR 7.5.2) | **fetch** |

> Note: the ground-truth lists no *supported* surfaces as unverified. The 4-segment-port surface is the only declared gap, and it has multiple grammar-confirmed fetch candidates. The additional surfaces below (LAG mode, dot1q VLAN, MTU, IPv6, local-users) are **not** in the gap list — they are already verified by the existing corpus — but the candidates touch them as a bonus, which is recorded for honesty.

### Ranked candidates (fetch-recommended, grammar-confirmed)

1. **`iosxr_design_cst_v5_pa3_bundle_active_on_dot1q_mtu_fos752.conf`** — *BEST for the 4-segment gap*
   - Source: https://github.com/ios-xr/design/blob/master/Converged-SDN-Transport/v5/pa3.cfg
   - Raw: https://raw.githubusercontent.com/ios-xr/design/master/Converged-SDN-Transport/v5/pa3.cfg
   - License: **unlicensed-device-output** (factual-device-output precedent; lower preference, "drop if author objects"). Evidence: `gh api repos/ios-xr/design/license` → 404; root `/contents` has no LICENSE file. Org is Cisco's own ios-xr design org.
   - OS: IOS-XR 7.5.2
   - Surfaces filled: `/interfaces/interface/4th-port-segment` (Gi/Te `0/0/0/N`) — **the gap** — plus (bonus, already-verified) LAG mode active **and** the rare `mode on`→static, LAG members, MTU 9216 jumbo on multiple Bundle-Ether, VLAN id via `encapsulation dot1q 200`.
   - Confirmation: `interface TenGigE0/0/0/18 / bundle id 321 mode active`; `bundle id 500 mode on`; `Bundle-Ether321 mtu 9216`; `GigabitEthernet0/0/0/12.200 / encapsulation dot1q 200`. **Must sanitize before commit** (hostname `cst-pa3`; root/lab/admin users + password hashes; SNMP `cisco`/`public` RW; rewrite non-RFC5737 IPs `1.86.24.x`/`101.0.x.x` → 192.0.2/198.51.100/203.0.113 + 2001:db8::).

2. **`iosxr_design_cst_v5_ag3_bundle_dot1q_qinq_mtu9216_fos752.conf`** — *complements #1 with Q-in-Q + physical-port subifaces*
   - Source: https://github.com/ios-xr/design/blob/master/Converged-SDN-Transport/v5/ag3.cfg
   - Raw: https://raw.githubusercontent.com/ios-xr/design/master/Converged-SDN-Transport/v5/ag3.cfg
   - License: **unlicensed-device-output** (same ios-xr/design repo, no LICENSE; factual-device-output precedent). 
   - OS: IOS-XR 7.5.2
   - Surfaces filled: `/interfaces/interface/4th-port-segment` (Te `0/0/0/N` + physical-port `.unit` subifaces) — the gap — plus (bonus) LAG active, members, MTU 9216 on three Bundle-Ether, VLAN id incl. `second-dot1q` Q-in-Q.
   - Confirmation: `TenGigE0/0/0/30.2000 / encapsulation dot1q 2000 second-dot1q 1000`; `Bundle-Ether2123 / mtu 9216`. Sanitize: hostname `cst-ag3`; ISIS key hash `password 00071A150754`; SNMP cisco/public RW; non-RFC5737 IPs `1.86.24.23`/`101.0.2.3`.

3. **`iosxr_design_agilemetro_a_pe2_ncs540_bundle_dot1q_mtu_fos2541.conf`** — *OS-version diversity (modern 25.4.1 train)*
   - Source: https://github.com/ios-xr/design/blob/master/Agile-Metro/cst-a-pe2
   - Raw: https://raw.githubusercontent.com/ios-xr/design/master/Agile-Metro/cst-a-pe2
   - License: **unlicensed-device-output** (ios-xr/design, no LICENSE; factual-device-output precedent).
   - OS: **IOS-XR 25.4.1 (25.4.1.23I)** on a real NCS 540 (N540X) — newest-train capture vs the 7.5.2 / 6.x corpus.
   - Surfaces filled: `/interfaces/interface/4th-port-segment` (Gi/Te/HundredGigE `0/0/0/N`) — the gap — plus (bonus) LAG active, members, MTU 9216, VLAN id via `Bundle-Ether8000.8500 l2transport / encapsulation dot1q 500`.
   - Confirmation: `TenGigE0/0/0/10 / bundle id 8000 mode active`; `Bundle-Ether8000 / lacp system mac aaaa.aaaa.0008`. Sanitize: hostname `cst-a-pe2`; admin password hash; SNMP CROSSWORK/cisco/public; RFC1918 mgmt IPs `172.21.23.x`/`172.27.227.x`; **real Cisco NTP `171.68.38.66` → replace**.

4. **`ios_xr_cli2yang_ncs5500_users_mgmt_fxr652.config`** — *clean Apache multi-user/multi-secret round-trip (not a gap-filler)*
   - Source: https://github.com/ios-xr/cli2yang-tools/blob/netconf_ztp_mix/ncs5500_final.config
   - Raw: https://raw.githubusercontent.com/ios-xr/cli2yang-tools/netconf_ztp_mix/ncs5500_final.config
   - License: **Apache-2.0** (cleanest license here). Evidence: repo-root LICENSE = Apache 2.0, "Copyright 2018 Akshat Sharma".
   - OS: IOS-XR 6.5.2.28I
   - Surfaces filled (all already-verified, **not** the declared gap): `/local-users/user/name`, `/local-users/user/role`, `/local-users/user/hashed-password`.
   - Confirmation: two username blocks (`vagrant` + `root`), both `group root-lr` + `group cisco-support`, type-5 `$1$` secrets; `MgmtEth0/RP0/CPU0/0`. Verify the `$1$` hashes are throwaway lab (vagrant-style) before commit. **Does NOT fill the gap** and adds no IPv6/MTU/newer-OS — include only if a clean multi-user round-trip fixture is independently wanted; otherwise lower priority than #1–#3.

### Investigate-only (do NOT upgrade to fetch)

- **`xrdtools_srv6_pe2.conf`** (ios-xr/xrd-tools srv6-l3vpn/pe2.cfg, Apache-2.0) — grammar-partial single-VRF; near-duplicate of already-mined `xrdtools_srv6_pe1`; RD admin == ASN (100) so it does NOT hit the ASN-normalisation lossy path. L3VPN already maximally covered by `batfish_vpnv4_pe1/2/3`. Low incremental value.
- **`ios_xr_xrdtools_srv6l3vpn_p1_ipv6.cfg`** (ios-xr/xrd-tools srv6-l3vpn/p1.cfg, Apache-2.0) — only fills already-verified IPv6 (`2001:db8::/127`); HIGH risk of being already-in-corpus (P4 pulled 3 xrd-tools SR/SRv6/IS-IS configs). No users/mgmt/MTU. Verify against `tests/fixtures/real/cisco_iosxr/` first.
- **`ios_xr_karneliuk_batfishmvp_xr1_mtu_ipv6.cfg`** (karneliuk-com/batfish-mvp, BSD-3-Clause) — fills already-verified MTU (`mtu 1514`) + ULA IPv6; XRv9k single-RP `MgmtEth0/0/CPU0/0` (not the target form); OS 6.5.1, not newer. No local-users. Investigate only if corpus somehow lacks MTU coverage.
- **`iosxr_design_cst_v5_a_pe1_bundle_dot1q_mtu9216.conf`** (ios-xr/design a-pe1.cfg) — solid access-PE but functionally redundant with #1/#2 (same v5 train, mode active only). Keep as a 4th-file backup only.

### Dead ends / blocked

- **No declared *supported* surface is unverified** — there is nothing to hunt on the supported axis. The corpus is complete for supported surfaces (confirmed by ground-truth empty list).
- **L3VPN multi-VRF + RD/RT + per-VRF static + ASN-differs**: batfish/lab-validation `cisco_xr_ios_vpnv4` is the single best L3VPN source and is **fully mined** (PE1/PE2/PE3 already in corpus as `batfish_vpnv4_pe1/2/3.txt`). The only other batfish XR snapshots (`iosxr_ebgp_basic`, `iosxr_ibgp_rr_over_ospf`) and their devices are also fully consumed. No un-mined license-clean L3VPN file improves on the corpus — do not re-hunt batfish/xrd-tools for this surface without a brand-new donor.
- **LAG `bundle id <N> mode passive`**: genuine real-capture gap — ZERO permissive/forum captures found. The only `mode passive` grammar lives in GPL-3.0 ansible-collections/cisco.iosxr `.rst` docs (HARD REJECT) or proprietary Cisco config-guides. community.cisco.com forum-share threads returned HTTP 403 to WebFetch (un-verifiable without a browser/authenticated fetch). Leave `passive` as synthetic-only/UNSUP unless a forum paste can later be browser-fetched. (Note: `mode active` + `mode on` are now sourced via #1.)
- **Modern XR-7.x with non-root task-group (netadmin/operator) + type-10 `$6$` secret + RFC3849 dual-stack + `MgmtEth0/RP0/CPU0/0` in one file**: not found in any license-clean (Apache/MIT/BSD) file. The single best grammar match — CiscoDevNet/XRd-Sandbox `xrd-1-startup*.cfg` (exact `secret 10 $6$…` + AAA variants) — is **REJECTED on license** (Cisco Sample Code License v1.1, redistribution-restricted; not on the acceptable list). CiscoDevNet/cml-community likely shares the same taint. All located clean XR captures are 6.5.x-era. The type-10 `$6$` prefix path in `_fmt_secret` therefore remains un-validated by any real capture — synthetic-only for now. Do not re-hunt CiscoDevNet/XRd-Sandbox for import.

## aruba_aoss

6 supported surfaces unverified (+3 lossy unverified). After 3 missions (38 web + 14 GitHub code searches) only ONE surface — `/dhcp-servers/pool` — has a license-clean, grammar-confirmed, fetch-ready real capture. The richest target combos (VRRP+IPv6, full SNMPv3 USM + `snmp-server location`) do not exist in any accessible permissively-licensed source; two lossy surfaces (tunnel-type, VRF/routing-instances) are platform-dry durable negatives. NOTE: `dhcp-client-v6` is already covered by an existing corpus fixture, so it is not a true gap.

### Gap-surface coverage

| Gap surface | Best candidate | Status |
|---|---|---|
| /interfaces/interface/ipv6/address/ip | oneuptime.com IPv6 how-to (snippet only) | investigate (grammar-confirmed, no full config, no raw file) |
| /interfaces/interface/ipv6/address/prefix-length | oneuptime.com IPv6 how-to (snippet only) | investigate (same as above) |
| /interfaces/interface/vrrp-groups/group | community.hpe.com E5406 K.15.03 thread | investigate (grammar blocker — needs codec parser fix; IPv4-only) |
| /snmp/location | — none found (clean) | blocked — only source is GPL-3.0 cheatsheet w/ placeholders |
| /snmp/v3-user | airheads.hpe.com 2930F WC.16.11 thread | investigate (partial snippet, fills v3-user only, no location/NTP) |
| /system/ntp-server | — none found (clean, fetch-ready) | blocked — confirmed grammar only in GPL-3.0 sources |
| /dhcp-servers/pool (lossy) | community.hpe.com 2920 DHCP thread | **fetch** (grammar-confirmed, forum-share, 2 verbatim variants) |
| /system/domain (lossy) | HPE techdoc `ip dns domain-name` (snippet) | investigate (pair w/ DHCP fixture; vendor-doc grammar only) |
| /interfaces/interface/tunnel-type (lossy) | — none found | blocked — platform-dry (no AOS-S interface-tunnel grammar) |
| /interfaces/interface/vrrp-groups/group/virtual-ips (lossy) | — none found | blocked — no multi-VIP AOS-S capture exists publicly |
| /interfaces/interface/dhcp-client-v6 (lossy) | already in corpus (user_contrib_2930m_wc1611.cfg) | NOT A GAP — pre-covered |

### Ranked candidates

**FETCH-recommended (grammar-confirmed, license-clean, ready to import):**

1. **`hpe_community_2920_dhcp_server_pool_wb16.conf`**
   - Source: https://community.hpe.com/t5/aruba-provision-based/how-to-create-dhcp-server-in-2920-procurve-switch/td-p/6752040
   - Raw URL: none (forum HTML — assemble from verbatim paste)
   - License: forum-share (community.hpe.com operator troubleshooting paste; OP `rka61` pasted a non-working pool, `EricAtHP` replied with the corrected working block — matches the NOTICE.md community.hpe.com forum-share precedent already used for the 4 existing Aruba fixtures)
   - OS version: AOS-Switch WB.16.xx (HP 2920, ProVision/WB train)
   - Surfaces filled: `/dhcp-servers/pool` (lossy)
   - Confirmation: two distinct verbatim pool variants in ONE thread — `dhcp-server pool "Lab"` with `authoritative`/`default-router`/`dns-server`/`domain-name`/`network`/`range`, plus a `Managment` pool with `lease 07:00:00` + `option 43 ip`; also shows the VLAN-context `dhcp-server` directive + global `dhcp-server enable` idiom the codec drops. Minor sanitize: move dns-server/option-43 IPs to RFC5737 before commit.

**INVESTIGATE leads (grammar-confirmed but NOT fetch — blocker noted):**

2. **`hpe_community_e5406_k1503_vrrp_intervlan.cfg`** — Source: https://community.hpe.com/t5/hpe-aruba-networking-provision/vrrp-not-working-with-e5406/m-p/4777887/highlight/true (root: td-p/4777885). License: forum-share. OS: K.15.03.0007 (older than WC.16.10 target). Surfaces: `/interfaces/interface/vrrp-groups/group` (+ partial `virtual-ips` — single VIP only). Confirmation: `router vrrp` / `vlan 1` / `vrrp vrid 1` / `owner` / `virtual-ip-address 10.40.0.1 255.255.255.0` / `priority 255` / `enable`. **CRITICAL BLOCKER:** every real AOS-S capture emits `vrrp vrid N` (no leading `ip`) under `vlan N`+`router vrrp`, but the live codec regex `_VRRP_VRID_HEADER_RE = r"^ip\s+vrrp\s+vrid\s+(\d+)\s*$"` (netcanon/migration/codecs/aruba_aoss/parse.py:278-279) REQUIRES `ip vrrp vrid N`. Confirmed across 4 independent sources (E5406 thread, airheads 5406R-ZL2, mybenke E5400, official AOS-S 16.11 docs). Any VRRP fixture import MUST be paired with a parser fix (drop/optionalize the `ip ` prefix). IPv4-only, single VIP — does not exercise IPv6 or `virtual-ips>1`.

3. **`airheads_2930f_snmpv3_wc1611.conf`** — Source: https://airheads.hpe.com/discussion/aruba-2930f-snmpv3-anomaly. License: forum-share (airheads.hpe.com operator/HPE-employee paste). OS: WC.16.11.0012 (good version diversity vs existing engineid fixture). Surfaces: `/snmp/v3-user` (full auth-sha/priv-aes USM form). Confirmation: `snmpv3 group managerpriv user "airwave" sec-model ver3` / `snmpv3 user "airwave" auth sha "<removed>" priv aes "<removed>"` / `snmpv3 enable`/`only`/`restricted-access` (secrets already redacted). **BLOCKER:** partial snippet, not a full running-config; carries NO `snmp-server location` (the primary /snmp/location gap) and NO `sntp server priority`/`timesync sntp` (the /system/ntp-server gap). On its own fills only v3-user. Best used as inspiration/lead for a hand-authored fixture. No raw file URL.

**Grammar-reference only (cannot import — snippet/no full config):**

4. **oneuptime.com IPv6 how-to** — https://oneuptime.com/blog/post/2026-03-20-ipv6-hpe-aruba-switches/view. License: forum-share/third-party blog (lower preference). Confirms static IPv6 SVI grammar `ipv6 address 2001:db8:1:100::1/64` (RFC3849 prefix) inside VLAN context — exactly matches the codec's `_IPV6_ADDR_RE` for `/interfaces/interface/ipv6/address/ip`+`prefix-length`. BUT command snippet only, no VRRP, no full config — not importable; grammar confirmation only.

5. **mybenke.org E5400 VRRP** — https://www.mybenke.org/2012/configure-vrrp-on-hp-networking-e5400-family/. License: forum-share/personal blog. Second independent confirmation of the real `vrrp vrid`/`owner`/`backup`/`virtual-ip-address <ip> <mask>`/`enable` token form (same `vrrp vrid` grammar blocker). Illustrative snippets, not a full export — lower preference than the HPE-community thread.

6. **HPE techdoc `ip dns domain-name`** — https://arubanetworking.hpe.com/techdocs/central/2.5.7/content/nms/aos-switch/cfg/conf_sys_params.htm. License: proprietary (do NOT import the doc). Confirms the `/system/domain` global directive is `ip dns domain-name <name>` (DISTINCT from the per-pool DHCP `domain-name` option). Suggested use: add the single verbatim global line to the assembled forum-share 2920 DHCP fixture so one fixture exercises both `/dhcp-servers/pool` and `/system/domain`.

**Corroborating DHCP secondaries (investigate — verbatim text not yet locked):**

7. **`hpe_community_5406zl_dhcp_server_pool_k15.conf`** — https://community.hpe.com/t5/Aruba-ProVision-based/DHCP-Server-service-on-5406zl-switch/td-p/4276859. forum-share. K15.14 (5406zl). Shows the INLINE `dhcp-server pool "name" <attr>` single-line form (vs the indented block in the 2920 thread). investigate: WebFetch reconstruction may be paraphrased — re-fetch raw to lock casing/quoting.

8. **`hpe_community_2930f_branch_multivlan_dhcp_wc16.conf`** — https://community.hpe.com/t5/aruba-provision-based/2930f-dhcp-server-vlan-setup/td-p/7084768. forum-share. WC.16.xx 2930F branch L3 edge (4 VLANs/SVIs, per-VLAN pools, default static route). grammar_confirmed=FALSE — WebFetch paraphrased; re-fetch raw to capture literal pool blocks, then promotable to fetch.

### Dead ends / blocked surfaces

- **`/snmp/location` and `/system/ntp-server`** (both clean/non-lossy): NO license-clean real config combines `snmp-server location` with the SNMPv3 USM clause and `sntp server priority`. The only source carrying the full combination is GPL-3.0 (`galminyana/CheatSheets` — also placeholders-only, not real output). The only REAL dumps with the snmpv3+sntp grammar (`dservais0427/config-parse` KB.16.04, `NetNeutralNetworks` TTP template) are GPL-3.0 hard-rejects and lack `snmp-server location`. Forum-share threads show snmpv3 but never `snmp-server location` or `sntp server priority`. RECOMMENDATION: hand-author an AOS-S synthetic/lab fixture (WC.16.10/16.11) modeled on the confirmed real grammar, OR pair the DHCP fixture with the techdoc-confirmed global lines. (M2 gh code-search hit secondary rate-limit — 2 contact+location+USM combos could be retried in a fresh session, but the licensing wall is the real blocker, not search coverage.)
- **`/interfaces/interface/vrrp-groups/group/virtual-ips` (lossy, multi-VIP)**: no AOS-S capture with >1 `virtual-ip-address` per single vrid exists anywhere. Uncovered.
- **`/interfaces/interface/tunnel-type` (lossy)**: platform-dry durable negative. AOS-Switch has NO Cisco-style `interface tunnel`/`tunnel mode gre`/`tunnel source`. Its only GRE is `tunneled-node-server` (controller user-tunneling, per-VLAN, not an interface-tunnel object). Do not re-hunt.
- **VRF (`/routing-instances/instance`, static-route vrf)** [not in this gap list but confirmed during M3]: platform-dry durable negative — HPE's own VRF-Lite Support Matrix (td-p/6969928) states NO ProCurve/E-Series/ProVision/ArubaOS-Switch device supports VRF/VRF-Lite (AOS-CX-only feature). The one VRF config found is Comware/H3C grammar (wrong codec). Mark unsupported-by-platform; do not re-hunt without a new donor.
- **GitHub is DRY for AOS-S VRRP**: no repo (licensed or not) carries a genuine ArubaOS-Switch config with `vrrp vrid`. All gh code-search hits are Huawei VRP (`vrpcfg.cfg`), H3C, or Cisco/CCNA — wrong vendor, would fail the codec probe. `ntc-templates aruba_os` is ArubaOS-WIRELESS (controller), not AOS-Switch — no running-config fixtures. `aruba/aruba-switch-ansible` is 404; `aruba/aos-switch-ansible-collection` ships no golden running-config.
- **NO combined VRRP+IPv6 AOS-S config exists publicly**: not a single source carries both a `vrrp vrid` block AND a static `ipv6 address <colon-hex>/<prefix>` SVI. The IPv6 SVI surfaces (`ipv6/address/ip`+`prefix-length`) are grammar-confirmed (oneuptime) but only as command snippets, never a full running-config share.

## opnsense

Gap summary: 3 supported SNMP surfaces remain unverified (`/snmp/contact`, `/snmp/location`, `/snmp/trap-host`) plus 1 lossy-unverified surface (`/interfaces/interface/tunnel-type`). No grammar-confirmed, fetch-recommended real capture was found for any of them; both missions hit documented exhaustion.

### Gap surfaces → best candidate

| Gap surface | Status | Best candidate (rec) | Why |
|---|---|---|---|
| `/snmp/contact` | — none found | zakaria-hammal/PFE_2026 (reject) | Populated `syscontact=admin`, but lives in the modern `<netsnmp>/<general>` block the parser never reads (parse.py:448-466 only reads `<snmpd>`). |
| `/snmp/location` | — none found | zakaria-hammal/PFE_2026 (reject) | Populated `syslocation=proxmox-cluster`, same wrong-grammar block. Every legacy `<snmpd>` file found has EMPTY `<syslocation/>`. |
| `/snmp/trap-host` | — none found | (none) | No public legacy `<snmpd>` file with a `<traphost>` exists; GUI never emits one unless traps are actively configured, and the modern `<netsnmp>` grammar has no trap-host element at all. |
| `/interfaces/interface/tunnel-type` (lossy) | — none found | (none) | No license-clean, grammar-confirmed file with a `<gifs>`/`<gres>` tunnel block located; GitHub code-search for the tokens was hard rate-limited (403) before the needle query could run. |

### Ranked candidates

No candidate is both grammar-confirmed AND fills an unverified gap surface, so there are zero fetch-recommended picks. The two grammar-confirmed leads below are license-pristine but only fill `/interfaces/interface/dhcp-client-v6`, which the corpus already covers — listed for completeness, both ranked "investigate" (low marginal value), NOT fetch.

1. **opnsense_docs_carp_master_bsd.xml** — investigate (low value)
   - Source: https://docs.opnsense.org/manual/how-tos/carp.html
   - Raw: https://raw.githubusercontent.com/opnsense/docs/master/source/manual/how-tos/resources/Carp_example_master.xml
   - License: BSD-2-Clause (opnsense/docs repo root LICENSE; official OPNsense publication) — impeccable provenance, already RFC1918-addressed (172.18.0.x / 192.168.1.x), ~zero sanitization
   - OS version: config schema `version` 11.2 (not the release stamp); generic modern OPNsense
   - Surfaces filled: `/interfaces/interface/dhcp-client-v6` (track6) — already corpus-covered (this is almost certainly the upstream origin of the existing carp_ha_master fixture)
   - Confirms: CARP `<vip>` on WAN/LAN + LAN `track6`; NO `<vlans>`, NO static `<ipaddrv6>`, NO `<gifs>` tunnel → does NOT touch any unverified gap surface.

2. **techknowledgeman_opnsense_dhcp6_track6.xml** — investigate (low value)
   - Source: https://github.com/Techknowledgeman/OPNsense/blob/main/config.xml
   - Raw: https://raw.githubusercontent.com/Techknowledgeman/OPNsense/main/config.xml
   - License: CC0-1.0 (repo root LICENSE; public-domain dedication) — cleanest possible
   - OS version: not stamped at config root; plugin versions (Nginx 1.20.0 etc.) suggest ~23.x/24.x, unconfirmed
   - Surfaces filled: `/interfaces/interface/dhcp-client-v6` (dhcp6 on WAN + track6 on LAN) — already corpus-covered
   - Confirms: WAN `dhcp6` + LAN `track6`; NO `<vlans>`, NO static `<ipaddrv6>`, NO `<gifs>`/`<gres>`. SANITIZATION REQUIRED if ever used: plaintext influx_password, wireless `<passphrase>`, real Azure public IPs (52.170.57.27 / 20.190.142.171), SSH authorized_keys.

### Rejected (grammar-mismatch or stub)

- **zakaria-hammal/PFE_2026** (`OPNSenseConfig.xml`, unlicensed) — populated `syslocation`/`syscontact`/`community` but in the MODERN `<netsnmp>/<general>` plugin block; the codec parser only reads the legacy `<snmpd>` block (`<rocommunity>`/`<syslocation>`/`<syscontact>`/`<traphost>` — verified at parse.py:448-466), and `<netsnmp>` has no trap-host element. Would not be parsed at all today. Future lead only if the codec is extended to read `<netsnmp>`.
- **mcree/vagrant-opnsense** (`config.xml`, unknown license) — correct legacy `<snmpd>` grammar but GUI stub: `<syslocation/>`/`<syscontact/>` empty, no `<traphost>`. Identical to existing `opnsense_docs_carp_ha_master.xml`.
- **Xieonie/secure-smart-home-infrastructure** (`opnsense-config.xml.example`, unknown license) — legacy `<snmpd>` grammar with OPNsense-specific `<bindlan>`/`<enable>`, but `syslocation`/`syscontact` empty and no `<traphost>`; only `<rocommunity>public</rocommunity>` populated. Hand-authored `.example` template, not a real export.

### Dead ends / blocked

- **`/snmp/contact`, `/snmp/location`, `/snmp/trap-host`** — DOCUMENTED NEGATIVE. A populated LEGACY `<snmpd>` block (non-empty `<syslocation>` AND `<syscontact>` AND >=1 `<traphost>`) is essentially absent from public GitHub/forums. Two confirmed root causes: (1) the OPNsense GUI writes `<syslocation/>`/`<syscontact/>` as empty stubs and never emits `<traphost>` unless an operator configures traps; (2) modern OPNsense (22.x+, os-net-snmp) moved SNMP to a `<netsnmp>/<general>` block with different grammar (`<community>` not `<rocommunity>`, no trap-host) — confirmed via opnsense/plugins #3680. Every public default config.xml fetched (mcree, Knightfall-Systems, Techknowledgeman, EugenMayer, Xieonie, opnsense/core sample) is a GUI stub matching the existing carp_ha_master fixture. Targeted code searches `<snmpd>`+`<bindlan>`+`<traphost>` and `<pollport>`+`<traphost>`+`<rocommunity>` returned ZERO hits; `<theme>opnsense</theme>`+`<traphost>` matched only netcanon's own kitchen_sink.xml. forum.opnsense.org topic=43312 is discussion-only. CONSTRAINT: GitHub code_search throttled to 10 req/hr (exhausted twice); grep.app returned 429. RECOMMENDED PATH: hand-author a synthetic legacy `<snmpd>` fixture with location/contact/traphost populated (grammar fully known; kitchen_sink already demonstrates it) — the real-world artifact is genuinely rare. Alternative: extend the codec to parse `<netsnmp>/<general>`, which would unlock zakaria-hammal/PFE_2026 for contact+location (but trap-host would still need a synthetic).
- **`/interfaces/interface/tunnel-type`** (lossy) — UNFOUND in any license-clean, grammar-confirmed file. The headline diversification grammar (parent-iface VLAN `<vlans><vlan><tag>` + static `<ipaddrv6>` + `<gifs>`/`<gres>` tunnel together) could not be located. The highest-value query (GitHub REST code-search for `<gifif>`/`<vlanif>`/`ipaddrv6` extension:xml) was HARD rate-limited (HTTP 403) on every attempt and never ran — this is the single biggest gap and the top retry once quota resets. Homelab repos with rich VLAN docs (charlesX0101, vushueh, Vinetos) do NOT commit the XML backup; Ansible test fixtures (Rosa-Luxemburgstiftung-Berlin/ansible-opnsense, Apache-2.0) are minimal single-feature stubs with no vlan/gif/static-ipv6 file; O-X-L and AndyX90 repos are GPL-3.0 (rejected); forum topic 29654 (GRE/GIF IPv6) is discussion-only; HE 6in4 gist 304b8fe0 returned HTTP 400.

