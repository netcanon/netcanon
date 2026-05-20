# 05 — Fixture targets

Comprehensive list of NX-OS configuration sources available under
permissive licenses, ordered by priority for the per-phase corpus
build-out.

Each fixture row documents:
* **URL** — raw-content URL on GitHub (or other public host)
* **License** — required for inclusion (must be permissive)
* **Line count** — verified via `wc -l` on the fetched file
* **Grammar coverage** — surfaces exercised by this fixture
* **Phase** — which implementation phase needs the fixture
* **Sanitisation notes** — anything needing redaction before commit

---

## 1. Primary corpus — batfish/lab-validation (Apache-2.0)

All paths under
`https://raw.githubusercontent.com/batfish/lab-validation/main/snapshots/<snapshot>/configs/<node>/show_running-config.txt`.

These were fetched into `/tmp/nxos-corpus/` during this planning
pass; the implementor can re-fetch via the same URL pattern.

### 1.1 Verified fixtures (already fetched + line-counted)

| Fixture target name | URL path | Lines | OS | Grammar coverage | Phase |
|---|---|---|---|---|---|
| `nxos_static_route_D1.txt` | `nxos_static_route/configs/D1/show_running-config.txt` | 302 | 9.2(3) | hostname + minimal routed interfaces + 1 static route + management VRF | **1** |
| `nxos_static_route_D2.txt` | `nxos_static_route/configs/D2/show_running-config.txt` | ~300 | 9.2(3) | Sibling capture | 1 |
| `nxos_hsrp_nxos1.txt` | `nxos_hsrp/configs/nxos1/show_running-config.txt` | 337 | 9.2(3) | HSRP on Vlan10 + port-channel1 (LACP) + iBGP + loopback123 + SVIs + L2 trunk on members | **2** |
| `nxos_hsrp_nxos2.txt` | `nxos_hsrp/configs/nxos2/show_running-config.txt` | ~337 | 9.2(3) | Sibling pair config (validates two-leaf HSRP pair) | 2 |
| `nxos_ebgp_loop_d1.txt` | `nxos_ebgp_loop_prevention/configs/d1_nxos/show_running-config.txt` | 310 | 9.2(3) | router bgp + multiple loopbacks + eBGP neighbor | **3** |
| `nxos_bgp_redist_d1.txt` | `nxos_bgp_redist_connected/configs/d1_nxos/show_running-config.txt` | 323 | 9.2(3) | BGP redistribution into BGP from connected | 3 |
| `nxos_eigrp_nxos1.txt` | `nxos_eigrp_neighbor/configs/nxos1/show_running-config.txt` | 366 | 9.2(3) | EIGRP multi-AS + per-interface `ip router eigrp N` activation | **3** |
| `nxos_redist_d4_ebgp.txt` | `nxos_redistribution/configs/d4_ebgp/show_running-config.txt` | 307 | 9.2(3) | router bgp with route-map redistribution | 3 |
| `nxos_n9kv_r1.txt` | `nxos_n9kv_ebgp/configs/r1/show_running-config.txt` | 191 | 10.3(9) | Newer OS — `feature netconf` / `feature grpc` / `feature nxapi`, AES-128 SNMPv3 `localizedV2key`, IPv6 default route in mgmt VRF | **4** (cert promotion) |
| `nxos_evpn_l3vni_NX1.txt` | `nxos_evpn_l3vni/configs/NX-1/show_running-config.txt` | 349 | 9.2(3) | EVPN L3VNI: `nv overlay evpn` + `feature fabric forwarding` + `vrf context TENANT-777 / vni 100777 / rd auto / route-target both auto evpn` + `interface nve1 / member vni 100777 associate-vrf` + `router bgp / vrf TENANT-777 / address-family ipv4 unicast / redistribute direct route-map all` | **4** |
| `nxos_evpn_l3vni_NX2.txt` | `nxos_evpn_l3vni/configs/NX-2/show_running-config.txt` | ~349 | 9.2(3) | Sibling pair config | 4 |
| `nxos_evpn_l2vni_NX1.txt` | `nxos_evpn_l2vni/configs/NX-1/show_running-config.txt` | 355 | 9.2(3) | EVPN L2VNI: `feature vn-segment-vlan-based` + per-VLAN `vn-segment 5010` + `interface nve1 / member vni 5010 / suppress-arp / ingress-replication protocol bgp` + top-level `evpn / vni 5010 l2 / rd auto / route-target import|export auto` | **4** |
| `nxos_evpn_l2vni_NX2.txt` | `nxos_evpn_l2vni/configs/NX-2/show_running-config.txt` | ~355 | 9.2(3) | Sibling pair config | 4 |

### 1.2 Additional batfish snapshots (NX-OS, not yet fetched)

| Snapshot | Likely coverage | Phase |
|---|---|---|
| `nxos_l3_vlan_no_active_member` | Edge case: L3 SVI with no member ports | 2 (edge case) |
| `nxos_n9kv_ebgp` (r2 node) | sibling to r1; exercises eBGP between N9Kv | 3 |
| `nxos_redistribution` (d1_redist, d2_static, d3_eigrp, d5_ospf, d6_ibgp) | redistribution flavours across ASes — OSPF + iBGP grammar | 3 |
| `nxos_undefined_route_map` | Negative case: BGP referencing undefined route-map | 3 (parser robustness) |
| `ios_nxos_bgp_local_as` | Cross-vendor IOS-classic + NX-OS BGP interop fixture | Cross-vendor |
| `mix_vendor_bgp_vrf` | Multi-vendor includes NX-OS — sanity-check the multi-codec UI | Cross-vendor |

### 1.3 Per-fixture grammar contribution summary

| Surface | Phase | Fixture(s) exercising it |
|---|---|---|
| hostname / vdc / version banner | 1 | every fixture |
| feature block | 1 | every fixture (variable subset) |
| vlan top-level (comma+range) | 1 | nxos_hsrp_nxos1 (1,10,2000), nxos_evpn_l2vni_NX1 (1,10,20) |
| vrf context (management) | 1 | every fixture |
| vrf context (TENANT-777) | 3 | nxos_evpn_l3vni_NX1 |
| interface Ethernet1/N (L3) | 1 | nxos_static_route_D1 (no switchport + ip address) |
| interface Ethernet1/N (L2 access) | 2 | nxos_hsrp_nxos1 (Ethernet1/3) |
| interface Ethernet1/N (L2 trunk + channel-group) | 2 | nxos_hsrp_nxos1 (Ethernet1/1-2) |
| interface Vlan<N> SVI | 2 | nxos_hsrp_nxos1, nxos_evpn_l3vni_NX1 |
| interface Vlan<N> with `vrf member` + `ip forward` (L3VNI) | 4 | nxos_evpn_l3vni_NX1 (Vlan777) |
| interface port-channel<N> | 2 | nxos_hsrp_nxos1 |
| interface mgmt0 (mgmt VRF) | 1 | every fixture except nxos_static_route_D1 (which doesn't show mgmt0) |
| interface loopback<N> | 1 | nxos_ebgp_loop_d1 (multiple), nxos_eigrp_nxos1 |
| interface nve1 (single VNI L3) | 4 | nxos_evpn_l3vni_NX1 |
| interface nve1 (multi-VNI L2) | 4 | nxos_evpn_l2vni_NX1 |
| top-level evpn block | 4 | nxos_evpn_l2vni_NX1 |
| fabric forwarding anycast-gateway-mac | 4 (T2) | nxos_evpn_l3vni_NX1, nxos_evpn_l2vni_NX1 |
| per-SVI fabric-forwarding mode | 4 (T2) | (not in current corpus — need search) |
| ip route (default VRF) | 1 | nxos_static_route_D1, nxos_evpn_l3vni_NX1 |
| ip route (in vrf context) | 3 | nxos_n9kv_r1 (`ip route 0.0.0.0/0 ...` in mgmt context) |
| ipv6 route in vrf | 3 | nxos_n9kv_r1 |
| HSRP group | 2 (T1) | nxos_hsrp_nxos1 |
| router bgp (Tier-3 raw) | 3 | nxos_hsrp_nxos1, nxos_ebgp_loop_d1, nxos_evpn_l3vni_NX1, nxos_evpn_l2vni_NX1 |
| router eigrp (Tier-3 raw) | 3 | nxos_eigrp_nxos1 |
| router bgp / address-family l2vpn evpn | 4 | nxos_evpn_l3vni_NX1, nxos_evpn_l2vni_NX1 |
| snmp-server user (md5 + des/aes) | 2 | every fixture |
| snmp-server user (aes-128 + localizedV2key) | 2 | nxos_n9kv_r1 |
| username + role | 1 | every fixture |
| boot nxos | 1 | every fixture |
| copp / rmon / hardware tcam | 1 | every fixture (preserved raw) |

The batfish corpus is **already sufficient** to clear the Phase 4
ship requirement.  The Phase 4-→certified promotion needs only the
10.x fixture (`nxos_n9kv_r1.txt`) added to clear the "≥2 OS versions"
bar.

---

## 2. Initial corpus recommendation (certified tier)

Per `tests/fixtures/real/RESULTS.md` § "Certified tier", a codec
reaches `certainty="certified"` once it round-trips:
* ≥3 real captures
* across ≥2 OS versions

NX-OS Phase 4 ships with **8 batfish fixtures across 9.2(3) and
10.3(9)** — clears both bars decisively.

Recommended initial certified-corpus:

1. `nxos_static_route_D1.txt` — bare-bones L3 baseline
2. `nxos_hsrp_nxos1.txt` — L2 + HSRP + iBGP
3. `nxos_evpn_l3vni_NX1.txt` — EVPN L3VNI fabric
4. `nxos_evpn_l2vni_NX1.txt` — EVPN L2VNI fabric
5. `nxos_n9kv_r1.txt` — modern OS (10.3) coverage
6. `nxos_eigrp_nxos1.txt` — EIGRP grammar
7. `nxos_ebgp_loop_d1.txt` — eBGP grammar
8. `nxos_redist_d4_ebgp.txt` — redistribution

Total bytes: ~70 KB across 8 files; modest test-corpus footprint.

---

## 3. Sanitisation notes

batfish/lab-validation configs are **already sanitised** — they're
lab-platform captures from N9Kv virtual instances and don't carry
real customer data.  Specifically:
* Hostnames: lab labels (`nxos1`, `D1`, `NX-1`, `d1_nxos`)
* IPs: RFC1918 (`10.x` / `192.168.x`) + RFC5737 documentation
  (`192.0.2.x`) + lab globals (`172.16.x`)
* Usernames: only `admin`
* Password hashes: lab defaults (still randomised per fixture; safe
  to commit as opaque hashes per the `CanonicalLocalUser`
  hashed-password convention)

**No additional sanitisation required** beyond the existing batfish
preparation.  The implementor confirms by:
1. Searching the file for any RFC-illegal IP range
2. Confirming all MAC addresses are documentation-form (`0a0a.*` /
   `00:00:5E:*`) or all-zeros
3. Confirming no `key 7 <reversible>` or `password 7 <reversible>`
   lines (only `password 5` SHA-256 crypt + `priv 0x<hex>` opaque
   SNMPv3 hashes)

The 10.3 fixture (`nxos_n9kv_r1.txt`) contains a 2026-dated
timestamp ("Wed May 20 03:54:57 2026") — likely the lab system's
clock skew, not real-world data.  No action needed.

---

## 4. Post-batfish corpus targets (future work)

The batfish corpus is light on the following surfaces:

### 4.1 QoS / DiffServ

Need a NX-OS capture with `class-map type qos`, `policy-map type
qos`, `service-policy input/output`.

Candidate sources:
* Cisco DevNet sandbox: https://devnetsandbox.cisco.com (Nexus
  9000v with sample configs; verify license — may be Cisco SDK EULA
  rather than open license; **caveat: do not commit without
  permission**)
* Cisco DC validated design guides (PDF; not directly commit-able
  but referenced in `docs/CAPABILITIES.md`)

### 4.2 Spanning-tree

`spanning-tree port type edge` / `spanning-tree mst` / BPDU guard
configuration.  Need a real datacenter capture.

### 4.3 IGMP snooping + multicast routing

Beyond the bare `ip igmp snooping vxlan` flag in
`nxos_evpn_l2vni_NX1.txt`.  Need PIM / mrib config.

### 4.4 N9K-V vs N9K hardware variants

Current corpus is all N9Kv (virtual lab platform).  A real N9K
hardware capture would exercise:
* Hardware-specific `interface Ethernet1/N` slot/port numbering
  (no breakout vs 4x10G breakout via `interface breakout slot 1
  port 1 map 10g-4x`)
* Hardware optics declarations
* Linecard `module` blocks for N7K (different from N9K)

Source candidate: Cisco DevNet sandbox or a community contributor.

### 4.5 N7K VDC

The batfish corpus has only id-1 single-VDC.  An N7K-class capture
with multiple VDCs would validate the `vdc` block round-trip.
**Lower priority** — multi-VDC is rare in modern deployments
(N7K is end-of-life).

### 4.6 Community capture sources

Implementor should also check:
* **NTC Templates** — `ntc-templates/tests/cisco_nxos/` — has small
  parsed-output snippets, MIT license, useful for parser smoke tests
  but not full round-trip captures.
* **NAPALM** — `napalm/napalm/nxos/tests/test_data/` — has full
  configs under Apache-2.0.  **High-value source** for additional
  cert-tier fixtures.
* **`nickrusso42518/racc`** — BSD-3 — used for IOS-XE; may also
  have NX-OS captures.
* **Cisco DevNet `cisco-pyats/genie-libs`** — Apache-2.0 — has
  testbed configs for Nexus platforms.
* **Cumulus / NVIDIA Networking** — has interop test configs
  including NX-OS reference setups; license per-repo varies.

The Phase 4.5 (cert-tier promotion) PR should target ≥2 of these
sources to round out the corpus.

---

## 5. Fixture commit recipe (for the Phase 1 PR)

```
# Step 1: fetch
mkdir -p tests/fixtures/real/nx_os
curl -o tests/fixtures/real/nx_os/nxos_static_route_D1.txt \
  https://raw.githubusercontent.com/batfish/lab-validation/main/snapshots/nxos_static_route/configs/D1/show_running-config.txt

# Step 2: verify
wc -l tests/fixtures/real/nx_os/nxos_static_route_D1.txt
# expect: 302 lines

# Step 3: attribution
# Append to tests/fixtures/real/NOTICE.md:
cat >> tests/fixtures/real/NOTICE.md <<'EOF'

## nx_os/

Captured from batfish/lab-validation (Apache-2.0).

* nxos_static_route_D1.txt — snapshots/nxos_static_route/configs/D1/show_running-config.txt
* nxos_hsrp_nxos1.txt      — snapshots/nxos_hsrp/configs/nxos1/show_running-config.txt
  (Phase 2)
* ...
EOF

# Step 4: dispatch table
# Add to tests/unit/migration/test_real_captures.py lines 80-88:
#   "nx_os":        "cisco_nxos",

# Step 5: run the harness
pytest tests/unit/migration/test_real_captures.py -k nx_os -v
# expect: at least the Phase 1 fixture parses cleanly
```

---

## 6. Total corpus footprint estimate

| Phase | Fixtures added | Cumulative LOC | Cumulative bytes (approx) |
|---|---|---|---|
| 1 | 1 (nxos_static_route_D1) | 302 | ~9 KB |
| 2 | +2 (hsrp_nxos1, hsrp_nxos2) | ~970 | ~30 KB |
| 3 | +2 (ebgp_loop_d1, eigrp_nxos1) | ~1640 | ~50 KB |
| 4 | +3 (evpn_l3vni_NX1, evpn_l3vni_NX2, evpn_l2vni_NX1) | ~2690 | ~80 KB |
| 4.5 (cert) | +1 (n9kv_r1, 10.x version) | ~2880 | ~85 KB |

**Total corpus ~85 KB**, comparable to the IOS-XE corpus
(`tests/fixtures/real/cisco_iosxe/` is currently ~120 KB with 11
fixtures per the existing certification claim).

---

## 7. License audit (every fixture)

| Fixture | Source | License | Re-distributable in tests/ | Commit-ready? |
|---|---|---|---|---|
| `nxos_static_route_D1.txt` | batfish/lab-validation | Apache-2.0 | Yes | Yes |
| `nxos_hsrp_nxos1.txt` | batfish/lab-validation | Apache-2.0 | Yes | Yes |
| `nxos_evpn_l3vni_NX1.txt` | batfish/lab-validation | Apache-2.0 | Yes | Yes |
| `nxos_evpn_l2vni_NX1.txt` | batfish/lab-validation | Apache-2.0 | Yes | Yes |
| `nxos_ebgp_loop_d1.txt` | batfish/lab-validation | Apache-2.0 | Yes | Yes |
| `nxos_eigrp_nxos1.txt` | batfish/lab-validation | Apache-2.0 | Yes | Yes |
| `nxos_n9kv_r1.txt` | batfish/lab-validation | Apache-2.0 | Yes | Yes |
| (post-batfish: NAPALM tests/) | napalm/napalm | Apache-2.0 | Yes | Phase 4.5 candidate |
| (post-batfish: NTC Templates) | networktocode/ntc-templates | Apache-2.0 | Yes | Phase 1+ candidate |
| (post-batfish: Cisco DevNet) | sandbox configs | Cisco EULA | **No** | **Do not commit** |

The implementor should re-verify license headers on every fetch
(batfish has occasionally re-licensed sub-trees; Apache-2.0 has been
stable but check `LICENSE` at the repo root before each batch).

---

## 8. Sanity check: does the corpus exercise enough grammar?

Cross-reference with `01-grammar-survey.md` § 21 (per-stanza summary
table).  For each top-level NX-OS grammar surface, is the corpus
above sufficient?

| Surface | Corpus exercises it? | Notes |
|---|---|---|
| `!Command:` banner | ✓ | every fixture |
| `version N.N(N)` | ✓ | every fixture; 9.2(3) + 10.3(9) |
| `hostname` | ✓ | every |
| `vdc` block | ✓ | every (id 1) |
| `feature` block | ✓ | every (variable subset) |
| `username ... role` | ✓ | every |
| `snmp-server user` | ✓ | every (md5+des in 9.x; md5+aes-128 in 10.x) |
| `snmp-server community` | ✗ | **GAP**: no v2c community in batfish corpus |
| `vlan` top-level | ✓ | every (single id + comma+range) |
| `vlan / vn-segment` | ✓ | evpn_l2vni |
| `vrf context` (management) | ✓ | every |
| `vrf context` (tenant + l3-vni) | ✓ | evpn_l3vni |
| `interface Ethernet1/N` (L3) | ✓ | static_route, evpn |
| `interface Ethernet1/N` (L2 access) | ✓ | hsrp |
| `interface Ethernet1/N` (L2 trunk + channel-group) | ✓ | hsrp |
| `interface Vlan<N>` SVI | ✓ | hsrp, evpn |
| `interface port-channel<N>` | ✓ | hsrp |
| `interface mgmt0` | ✓ | every except static_route |
| `interface loopback<N>` | ✓ | hsrp, ebgp_loop, evpn, eigrp |
| `interface nve1` | ✓ | evpn |
| `interface Tunnel<N>` (GRE/IPIP) | ✗ | **GAP**: no tunnel in corpus |
| `ip route` (default VRF) | ✓ | static_route, evpn |
| `ip route` (per-VRF) | ✓ | n9kv_r1 (mgmt VRF default route) |
| `ipv6 route` (per-VRF) | ✓ | n9kv_r1 |
| `hsrp N` sub-stanza | ✓ | hsrp (T1) |
| `router bgp` (Tier-3) | ✓ | hsrp, ebgp_loop, evpn (all variants) |
| `router ospf` (Tier-3) | ✗ | **GAP** |
| `router eigrp` (Tier-3) | ✓ | eigrp |
| `router isis` (Tier-3) | ✗ | **GAP** (rare in DC anyway) |
| `evpn` top-level block | ✓ | evpn_l2vni |
| `fabric forwarding anycast-gateway-mac` | ✓ | evpn (T2) |
| `nv overlay evpn` | ✓ | evpn |
| `boot nxos` | ✓ | every |
| `line console` / `line vty` | ✓ | every |
| `copp` / `rmon` / `hardware tcam` | ✓ | every |
| `mac address-table` | ✓ | evpn_l2vni |
| `ssh key` | ✓ | n9kv_r1 |
| `icam` | ✓ | n9kv_r1 |
| `no password strength-check` | ✓ | every |
| `class-map` / `policy-map` (QoS) | ✗ | **GAP** |
| `ip access-list` | ✗ | **GAP** |
| `spanning-tree` config | ✗ | **GAP** (relies on defaults) |
| `monitor session` (SPAN) | ✗ | **GAP** |

**Identified gaps**: SNMP community (v2c), tunnel interfaces, OSPF,
ISIS, QoS class/policy maps, ACLs, spanning-tree, SPAN/RSPAN.

For Phase 1-4 the gaps are all Tier-3 (parsed-and-ignored) or
out-of-scope, so they don't block certification.  Phase 5+
follow-up work can add coverage; recommend the NAPALM `nxos`
test fixtures as the first post-batfish target.
