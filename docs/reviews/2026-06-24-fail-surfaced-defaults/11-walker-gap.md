# 11 — Walker-gap census (silent capability-loss class, class 1)

**Agent:** `11-walker-gap` · Phase 1 · read-only
**Date:** 2026-06-24 · ultracode blackboard · netcanon
**Scope:** Quantify the silent-loss gap: enumerate exactly what
`_walk_canonical` yields, confirm the default-to-supported rule in
`classify()`, build the leaf denominator from `intent.py`, compute the
GAP (expressible-but-never-walked leaves), grep which codecs populate
each gap leaf, catalogue what each of the 5 existing partial guards
covers, and account for the #149 intentionally-non-walkable exemption.

---

## 0. TL;DR

- **`classify()` default-to-supported is CONFIRMED.** `netcanon/models/migration.py:221-228`: any xpath not exact-matched in `unsupported` or `lossy` returns `"supported"`. An unwalked leaf is never passed to `classify()` at all, so it can never be lossy/unsupported in the **live** report — it is structurally invisible (`migration_validate.py:80-87` only iterates `_enumerate_xpaths` → `source.iter_xpaths` → `_walk_canonical`).
- **The walker yields 64 distinct xpath strings** (counted from `xpath_walker.py:62-256`).
- **The canonical model has ~95 data-bearing leaves.** The **silent-loss GAP = ~24 leaves that are expressible (a codec parses a non-default value into them) but the walker NEVER yields** → they default `supported` in the live report → silent loss.
- **The highest-risk gap leaves** (multiple codecs populate them, real reachability/semantic loss): the **VRRP/FHRP group sub-fields** `mode` (hsrp/carp discriminator), `priority`, `preempt`, `advertisement_interval`, `authentication`, `virtual_ipv6s`; the **IPv6 `scope`** (link-local vs global); the **DHCP pool option leaves** (`network`, `start_ip`, `end_ip`, `gateway`, `dns_servers`, `lease_time`, `domain_name`); the **RADIUS port leaves** (`auth_port`, `acct_port`); and the **routing-instance `instance_type` / `l3_vni`** and **EVPN type-5 `prefix`/`rt_imports`/`rt_exports`**.
- **A mitigating fact** (do not over-state the gap): the **offline cross-mesh audit** (`tools/run_full_mesh.py`) does NOT use the walker — it compares `model_dump()` field-by-field (`run_full_mesh.py:334-335`) — so several gap leaves ARE caught at audit time even though they are blind to the **live `validate_against` UI banner**. The two surfaces have different blind spots. The walker gap is specifically a **live-report** honesty hole.
- **#149 lesson honoured:** Tier-3 routing-protocol paths (`/routing/bgp`, `/routing/ospf`, …) and the 6 `_SYNTHETIC_NONWALKABLE` per-vendor structural markers are **intentionally non-walkable**; any walk-everything rule (design-phase A) or completeness guard (design-phase B) MUST exempt them or it false-fails.

---

## 1. What `_walk_canonical` yields — exact enumeration

Source: `netcanon/migration/canonical/xpath_walker.py`. Every yield is guarded on the field being populated (truthy / `is not None`). Below is the complete yield set with the file:line of each yield site and the guard condition.

### 1.1 Tier 1 — system scalars + interfaces (lines 62-198)

| xpath | line | guard / owning field |
|---|---|---|
| `/system/hostname` | 64 | `intent.hostname` |
| `/system/domain` | 66 | `intent.domain` |
| `/system/dns-server` | 68 | per `intent.dns_servers` |
| `/system/ntp-server` | 70 | per `intent.ntp_servers` |
| `/system/timezone` | 72 | `intent.timezone` |
| `/system/syslog-server` | 74 | per `intent.syslog_servers` |
| `/interfaces/interface/name` | 76 | per `intent.interfaces` (unconditional within loop) |
| `/interfaces/interface/config/description` | 78 | `iface.description` |
| `/interfaces/interface/config/enabled` | 79 | unconditional within loop |
| `/interfaces/interface/config/type` | 81 | `iface.interface_type` |
| `/interfaces/interface/ipv4/address/ip` | 83 | per `iface.ipv4_addresses` |
| `/interfaces/interface/ipv4/address/prefix-length` | 84 | per ipv4 address |
| `/interfaces/interface/ipv4/address/secondary-ip` | 91 | `addr.is_secondary` |
| `/interfaces/interface/ipv4/address/virtual-gateway-address` | 93-95 | `addr.virtual_gateway_address` |
| `/interfaces/interface/ipv4/address/virtual-gateway-mac` | 98-100 | `addr.virtual_gateway_mac` |
| `/interfaces/interface/ipv6/address/ip` | 103 | per `iface.ipv6_addresses` |
| `/interfaces/interface/ipv6/address/prefix-length` | 104 | per ipv6 address |
| `/interfaces/interface/ipv6/address/secondary-ip` | 106 | `addr6.is_secondary` |
| `/interfaces/interface/ipv6/address/virtual-gateway-address` | 108-110 | `addr6.virtual_gateway_address` |
| `/interfaces/interface/ipv6/address/virtual-gateway-mac` | 113-115 | `addr6.virtual_gateway_mac` |
| `/interfaces/interface/dhcp-client-v6` | 118 | `iface.dhcp_client_v6` |
| `/interfaces/interface/tunnel-type` | 120 | `iface.tunnel_type` |
| `/interfaces/interface/config/mtu` | 122 | `iface.mtu is not None` |
| `/interfaces/interface/config/vrf` | 124 | `iface.vrf` |
| `/interfaces/interface/lag-member-of` | 126 | `iface.lag_member_of` |
| `/interfaces/interface/dhcp-client` | 128 | `iface.dhcp_client` |
| `/interfaces/interface/switchport-mode` | 137 | `iface.switchport_mode` |
| `/interfaces/interface/access-vlan` | 139 | `iface.access_vlan is not None` |
| `/interfaces/interface/trunk-allowed-vlans` | 141 | `iface.trunk_allowed_vlans` |
| `/interfaces/interface/trunk-native-vlan` | 143 | `iface.trunk_native_vlan is not None` |
| `/interfaces/interface/voice-vlan` | 145 | `iface.voice_vlan is not None` |
| `/interfaces/interface/vrrp-groups/group` | 147 | per `iface.vrrp_groups` |
| `/interfaces/interface/vrrp-groups/group/virtual-ips` | 154 | `len(grp.virtual_ips) > 1` |
| `/interfaces/interface/vrrp-groups/group/virtual-mac` | 156 | `grp.virtual_mac` |
| `/interfaces/interface/vrrp-groups/group/track-interfaces` | 158 | `grp.track_interfaces` |
| `/vlans/vlan/id` | 160 | per `intent.vlans` |
| `/vlans/vlan/name` | 161 | unconditional within loop |
| `/vlans/vlan/description` | 163 | `vlan.description` |
| `/vlans/vlan/tagged-ports` | 165 | per `vlan.tagged_ports` |
| `/vlans/vlan/untagged-ports` | 167 | per `vlan.untagged_ports` |
| `/vlans/vlan/ipv4/address/ip` | 179 | per `vlan.ipv4_addresses` |
| `/routing/static-route` | 181 | per `intent.static_routes` |
| `/routing/static-route/vrf` | 183 | `route.vrf` |
| `/routing/static-route/metric` | 192 | `route.metric` (truthy → 0 NOT walked) |
| `/routing/static-route/description` | 194 | `route.description` |
| `/routing/static-route/interface` | 196 | `route.interface` |
| `/anycast-gateway-mac` | 198 | `intent.anycast_gateway_mac` |

### 1.2 Tier 2 (lines 199-256)

| xpath | line | guard / owning field |
|---|---|---|
| `/snmp/community` | 202 | `intent.snmp.community` |
| `/snmp/location` | 204 | `intent.snmp.location` |
| `/snmp/contact` | 206 | `intent.snmp.contact` |
| `/snmp/trap-host` | 208 | per `intent.snmp.trap_hosts` |
| `/snmp/v3-user` | 210 | per `intent.snmp.v3_users` |
| `/snmp/v3-user/auth-passphrase` | 212 | `v3.auth_passphrase` |
| `/snmp/v3-user/engine-id` | 214 | `v3.engine_id` |
| `/dhcp-servers/pool` | 216 | per `intent.dhcp_servers` |
| `/lags/lag/name` | 218 | per `intent.lags` |
| `/lags/lag/members` | 219 | unconditional within loop |
| `/lags/lag/mode` | 220 | unconditional within loop |
| `/local-users/user/name` | 222 | per `intent.local_users` |
| `/local-users/user/role` | 224 | `user.role` |
| `/local-users/user/hashed-password` | 226 | `user.hashed_password` |
| `/local-users/user/privilege-level` | 227 | unconditional within loop |
| `/radius-servers/server/host` | 229 | per `intent.radius_servers` |
| `/radius-servers/server/key` | 230 | unconditional within loop |
| `/vxlan-vnis/vni` | 232 | per `intent.vxlan_vnis` |
| `/vxlan-vnis/source-interface` | 234 | `vx.source_interface` |
| `/vxlan-vnis/mcast-group` | 236 | `vx.mcast_group` |
| `/vxlan-vnis/flood-list` | 238 | `vx.flood_list` |
| `/vxlan-vnis/udp-port` | 239 | unconditional within loop |
| `/vxlan-vnis/vlan-id` | 240 | unconditional within loop |
| `/evpn-type5-routes/route` | 242 | per `intent.evpn_type5_routes` |
| `/routing-instances/instance` | 244 | per `intent.routing_instances` |
| `/routing-instances/instance/name` | 245 | unconditional within loop |
| `/routing-instances/instance/description` | 247 | `inst.description` |
| `/routing-instances/instance/route-distinguisher` | 249 | `inst.route_distinguisher` |
| `/routing-instances/instance/rt-imports` | 251 | `inst.rt_imports` |
| `/routing-instances/instance/rt-exports` | 253 | `inst.rt_exports` |
| `/routing-instances/instance/l3-vni` | 255 | `inst.l3_vni is not None` |

**Total distinct walker xpaths: 64.** (This matches `_WALKABLE = frozenset(_walk_canonical(_maximal_intent()))` in `test_registry_capability_honesty.py:225` — the maximal-intent kitchen-sink populates every conditional surface.)

---

## 2. The default-to-supported rule — CONFIRMED, quoted

`netcanon/models/migration.py`, `CapabilityMatrix.classify` (lines 195-228):

```python
for up in self.unsupported:
    if up.path == xpath:
        return "unsupported"
for lp in self.lossy:
    if lp.path == xpath:
        return "lossy"
# Explicit supported list OR implicit default.
return "supported"
```

The matching is **exact string equality** (docstring lines 210-219 makes this explicit). The consumer is `migration_validate.classify_tree` (`migration_validate.py:80-87`):

```python
for xpath in _enumerate_xpaths(tree, source):
    kind = caps.classify(xpath)
    ...
```

and `_enumerate_xpaths` (lines 28-45) yields **only** what `source.iter_xpaths(tree)` returns — which for every canonical codec is `_walk_canonical`. **Therefore: a leaf the walker never yields is never an argument to `classify()`.** It cannot be classified lossy/unsupported in the live report; it simply does not appear in `supported_paths`/`lossy_paths`/`unsupported_paths`. The migrate-page banner aggregates severity over the classified set (`validate_against` lines 118-153) — an unwalked dropped leaf contributes nothing and the banner stays green. **This is the silent-loss mechanism, and it is the literal "default-to-supported on an unwalked leaf" the seed describes.** Confirmed.

> **Nuance the design phase must carry:** the default is not literally "the unwalked leaf is classified supported"; it is "the unwalked leaf is classified **nothing** — it never reaches `classify()`." The *effect* is identical to supported (no warn/block contribution), but a class-1 design that reasons about "leaves classified supported" will mis-model this: the leaf is **absent**, not present-and-supported. The completeness guard (design B) must therefore check *walker coverage*, not *classification output*.

---

## 3. The leaf denominator — independent census from `intent.py`

Built independently from `netcanon/migration/canonical/intent.py` (per the brief — I run parallel to `10-model-leaf-census`; treat their table as authoritative if it differs, but this is my sufficient list to compute the gap). Leaves are scalar / list-of-scalar fields on each model. I exclude pure container references (e.g. `interfaces: list[CanonicalInterface]`) since those are walked at the child-leaf granularity.

### 3.1 `CanonicalIntent` (root) — `intent.py:790-930`

| field | type | default | walked? | IP/host | secret |
|---|---|---|---|---|---|
| hostname | str | "" | ✅ `/system/hostname` | — | — |
| domain | str | "" | ✅ | maybe | — |
| dns_servers | list[str] | [] | ✅ | ✅ | — |
| ntp_servers | list[str] | [] | ✅ | ✅ | — |
| timezone | str | "" | ✅ | — | — |
| syslog_servers | list[str] | [] | ✅ | ✅ | — |
| anycast_gateway_mac | str | "" | ✅ `/anycast-gateway-mac` | — | — |
| raw_sections | dict | {} | ❌ (Tier-3, by design) | maybe | maybe |
| dropped_tier3_sections | list[str] | [] | ❌ (notification, by design) | — | — |
| source_vendor | str | "" | ❌ (metadata) | — | — |
| source_format | str | "" | ❌ (metadata) | — | — |
| source_version | str | "" | ❌ (metadata) | — | — |
| apply_groups | list[str] | [] | ❌ **GAP** (provenance; Junos populates) | — | — |
| group_content | dict | {} | ❌ **GAP** (provenance; Junos populates) | maybe | maybe |

### 3.2 `CanonicalInterface` — `intent.py:168-281`

| field | walked? | note |
|---|---|---|
| name | ✅ `/interfaces/interface/name` | |
| default_name | ❌ **GAP** | MikroTik factory name; populated by `mikrotik_routeros` parse/render |
| description | ✅ | |
| enabled | ✅ | |
| interface_type | ✅ `/interfaces/interface/config/type` | |
| mtu | ✅ | |
| ipv4_addresses | ✅ (child leaves) | |
| ipv6_addresses | ✅ (child leaves) | |
| switchport_mode | ✅ | |
| access_vlan | ✅ | |
| trunk_allowed_vlans | ✅ | |
| trunk_native_vlan | ✅ | |
| voice_vlan | ✅ | |
| lag_member_of | ✅ | |
| dhcp_client | ✅ | |
| dhcp_client_v6 | ✅ | |
| tunnel_type | ✅ | |
| vrf | ✅ | |
| kind | ❌ **GAP** | role override; `cisco_iosxe_cli`/`cisco_nxos` set `kind="mgmt"` |
| vrrp_groups | partial (child leaves — see 3.4) | |

### 3.3 `CanonicalIPv4Address` (`:83-124`) / `CanonicalIPv6Address` (`:127-165`)

| field | walked? | note |
|---|---|---|
| ip | ✅ | |
| prefix_length | ✅ | |
| is_secondary | ✅ (`/…/secondary-ip`) | |
| virtual_gateway_address | ✅ | |
| virtual_gateway_mac | ✅ | |
| scope (IPv6 only) | ❌ **GAP** | `arista_eos` parse sets `scope="link-local"` (`parse.py:1064`) |

### 3.4 `CanonicalVRRPGroup` — `intent.py:491-597`  ← **the densest gap cluster**

| field | type | walked? | note |
|---|---|---|---|
| group_id | int | partial — only `/interfaces/interface/vrrp-groups/group` (the whole-group marker, line 147) | identity leaf walked |
| mode | str | ❌ **GAP (HIGH)** | "vrrp"/"hsrp"/"carp"; `cisco_nxos` sets `mode="hsrp"` (`parse.py:809`), `opnsense` sets `mode="carp"` (`parse.py:838`) |
| virtual_ips | list[str] | ✅ ONLY when `len>1` (line 154) | a single-VIP drop is NOT walked |
| virtual_ipv6s | list[str] | ❌ **GAP** | populated by junos/mikrotik/opnsense (`parse.py:2399`, `776`, `840`) |
| virtual_mac | str | ✅ | |
| priority | int | ❌ **GAP** | populated by every FHRP codec |
| preempt | bool | ❌ **GAP** | populated by junos/mikrotik/opnsense |
| advertisement_interval | int | ❌ **GAP** | populated by junos/mikrotik/opnsense (`parse.py:2383`, `779`, `842`) |
| authentication | str | ❌ **GAP (secret-adjacent)** | opaque `<scheme>:<value>`; junos/mikrotik/opnsense (`parse.py:780`, `843`) |
| track_interfaces | list[str] | ✅ | |
| description | str | ❌ **GAP** | operator text |

The whole-group identity (`/interfaces/interface/vrrp-groups/group`) IS walked, so a codec that drops VRRP wholesale surfaces the loss at that leaf. But a codec that **keeps the group yet drops `mode`/`priority`/`preempt`/`adv-interval`/`authentication`** silently changes the redundancy semantics with a green banner. This is exactly the silent-loss class, and it is the largest concentrated gap.

### 3.5 `CanonicalVlan` — `intent.py:284-298`

All four leaves walked (`id`, `name`, `description`, `tagged_ports`, `untagged_ports`, `ipv4_addresses/ip`). The VLAN SVI L3 prefix-length on `CanonicalVlan.ipv4_addresses[].prefix_length` is **NOT** walked (only `/vlans/vlan/ipv4/address/ip` at line 179, not `…/prefix-length`) — a minor gap.

### 3.6 `CanonicalStaticRoute` — `intent.py:301-331`

| field | walked? | note |
|---|---|---|
| destination | partial — only `/routing/static-route` (whole-route marker, line 181) | |
| gateway | ❌ **GAP (minor)** | the next-hop IP itself is never its own leaf; a route that keeps destination but mangles the gateway is not surfaced |
| interface | ✅ (when populated) | |
| metric | ✅ (when truthy — `metric=0` NOT walked) | |
| description | ✅ | |
| vrf | ✅ | |

### 3.7 `CanonicalDHCPPool` — `intent.py:339-361`  ← **second-densest gap cluster**

The walker yields ONLY `/dhcp-servers/pool` (the whole-pool marker, line 216). **Every option leaf is unwalked:**

| field | walked? | IP/host | note |
|---|---|---|---|
| interface | ❌ **GAP** | — | |
| network | ❌ **GAP** | ✅ | populated by all DHCP codecs |
| start_ip | ❌ **GAP** | ✅ | |
| end_ip | ❌ **GAP** | ✅ | |
| gateway | ❌ **GAP** | ✅ | |
| dns_servers | ❌ **GAP** | ✅ | |
| lease_time | ❌ **GAP** | — | opnsense/mikrotik populate (`parse.py:701`, `1007`) |
| domain_name | ❌ **GAP** | maybe | opnsense/junos/mikrotik populate (`parse.py:702`, `788`, `1007`) |

Because only `/dhcp-servers/pool` is walked, a codec that renders the pool envelope but drops the lease-time / domain / dns options reports `severity:ok`. (Mitigation: cross-mesh `model_dump()` audit catches these — see §6.)

### 3.8 `CanonicalSNMP` (`:450-471`) + `CanonicalSNMPv3User` (`:364-447`)

| field | walked? | note |
|---|---|---|
| snmp.community / location / contact / trap_hosts | ✅ | |
| snmp.v3_users (identity) | ✅ `/snmp/v3-user` | |
| v3.auth_passphrase | ✅ (secret) | |
| v3.engine_id | ✅ | |
| v3.group | ❌ **GAP** | VACM group; populated by arista/aoss/junos |
| v3.auth_protocol | ❌ **GAP** | md5/sha/sha256… — a protocol downgrade is a security change |
| v3.priv_protocol | ❌ **GAP** | des/aes/aes256 |
| v3.priv_passphrase | ❌ **GAP (secret)** | walked twin `auth-passphrase` IS walked but `priv-passphrase` is NOT |

The asymmetry (`auth-passphrase` walked, `priv-passphrase` not) is notable: a codec that drops the privacy key while keeping the auth key reports ok.

### 3.9 `CanonicalLAG` (`:474-488`)

`name`, `members`, `mode` all walked unconditionally. No gap.

### 3.10 `CanonicalLocalUser` (`:600-621`)

`name`, `role`, `hashed_password`, `privilege_level` all walked. No gap.

### 3.11 `CanonicalRADIUSServer` (`:624-638`)

| field | walked? | note |
|---|---|---|
| host | ✅ | |
| key | ✅ (secret) | |
| auth_port | ❌ **GAP** | opnsense/fortigate/mikrotik/iosxe/aoss populate non-default ports |
| acct_port | ❌ **GAP** | same |

### 3.12 `CanonicalVxlan` (`:641-692`)

`vni`, `source-interface`, `mcast-group`, `flood-list`, `udp-port`, `vlan-id` all walked. **`vlan_id` walked but the model also has it as the binding** — no gap.

### 3.13 `CanonicalRoutingInstance` (`:695-742`)

| field | walked? | note |
|---|---|---|
| name / description / route_distinguisher / rt_imports / rt_exports / l3_vni | ✅ | |
| instance_type | ❌ **GAP** | "vrf"/"virtual-router"/"l2vpn"/"mac-vrf"; arista sets `instance_type="mac-vrf"` (`parse.py:853`) — a mac-vrf rendered as a plain vrf is a real semantic loss |

### 3.14 `CanonicalEvpnType5Route` (`:745-782`)

The walker yields ONLY `/evpn-type5-routes/route` (whole-route marker, line 242). **`vrf`, `prefix`, `rt_imports`, `rt_exports` are all unwalked sub-leaves** → **GAP**. A codec that emits the route envelope but drops the prefix / RTs reports ok. (Like DHCP, caught by the model_dump cross-mesh audit but blind to the live report.)

---

## 4. THE GAP — expressible-but-never-walked leaves

Consolidated list of leaves that (a) a codec can populate with a non-default value AND (b) the walker never yields. Ranked by **real risk** = (# codecs that populate it) × (severity of a silent drop).

### 4.1 HIGH risk (multiple codecs populate; reachability/security/semantic loss)

| # | gap leaf (proposed walker spelling) | owning `Class.field` | populating codecs (grep-confirmed) | why it matters |
|---|---|---|---|---|
| 1 | `/interfaces/interface/vrrp-groups/group/mode` | `CanonicalVRRPGroup.mode` | cisco_nxos (`hsrp` `parse.py:809`), opnsense (`carp` `parse.py:838`), arista (`parse.py:198`) | a hsrp→vrrp or carp→vrrp silent conversion changes the redundancy protocol; operator never warned |
| 2 | `/interfaces/interface/vrrp-groups/group/priority` | `.priority` | all FHRP codecs | priority drop → master election flips silently |
| 3 | `/interfaces/interface/vrrp-groups/group/preempt` | `.preempt` | junos (`parse.py:2411`), mikrotik (`663`), opnsense | preempt flip changes failover behaviour |
| 4 | `/interfaces/interface/vrrp-groups/group/advertisement-interval` | `.advertisement_interval` | junos (`2383`), mikrotik (`779`), opnsense (`842`) | timer mismatch → flapping |
| 5 | `/interfaces/interface/vrrp-groups/group/authentication` | `.authentication` | junos (`780` area), mikrotik (`780`), opnsense (`843`) | **secret-adjacent**; auth dropped → group won't form / forms unauthenticated |
| 6 | `/interfaces/interface/vrrp-groups/group/virtual-ipv6s` | `.virtual_ipv6s` | junos (`2399`), mikrotik (`776`), opnsense (`840`) | a v6 VIP silently lost |
| 7 | `/snmp/v3-user/priv-passphrase` | `CanonicalSNMPv3User.priv_passphrase` | arista/aoss/fortigate/mikrotik/junos | **secret**; privacy key dropped (auth twin IS walked — asymmetric) |
| 8 | `/snmp/v3-user/auth-protocol` | `.auth_protocol` | same v3 codecs | algorithm downgrade is a security change |
| 9 | `/snmp/v3-user/priv-protocol` | `.priv_protocol` | same v3 codecs | cipher downgrade |
| 10 | `/interfaces/interface/ipv6/address/scope` | `CanonicalIPv6Address.scope` | arista (`parse.py:1064`) | link-local rendered as global (or dropped) breaks NDP/OSPFv3 adjacency |
| 11 | `/routing-instances/instance/instance-type` | `CanonicalRoutingInstance.instance_type` | arista (`mac-vrf` `parse.py:853`) | mac-vrf↔vrf semantic loss |

### 4.2 MEDIUM risk (single/few codecs; option-detail loss, caught by cross-mesh audit but not live report)

| # | gap leaf | owning | populating | note |
|---|---|---|---|---|
| 12-19 | `/dhcp-servers/pool/{interface,network,start-ip,end-ip,gateway,dns-servers,lease-time,domain-name}` | `CanonicalDHCPPool.*` | opnsense/mikrotik/junos/iosxe etc. | only the `/dhcp-servers/pool` envelope is walked; every option detail blind to live report |
| 20-23 | `/evpn-type5-routes/route/{vrf,prefix,rt-imports,rt-exports}` | `CanonicalEvpnType5Route.*` | arista/nxos/junos | only the `/evpn-type5-routes/route` envelope walked |
| 24-25 | `/radius-servers/server/{auth-port,acct-port}` | `CanonicalRADIUSServer.*` | opnsense/fortigate/mikrotik/iosxe/aoss | non-default ports silently lost |
| 26 | `/snmp/v3-user/group` | `.group` | arista/aoss/junos | VACM group dropped |

### 4.3 LOW risk (dead-ish / provenance / structurally-covered)

| # | gap leaf | owning | note |
|---|---|---|---|
| 27 | `/interfaces/interface/kind` | `CanonicalInterface.kind` | role override; it drives the *rename mesh*, not render fidelity — arguably correctly unwalked (it's a transform hint, not a config surface). Flag, don't necessarily walk. |
| 28 | `/interfaces/interface/default-name` | `.default_name` | MikroTik factory name; a render mechanism, not an operator-visible surface. Same-vendor round-trip only. Correctly unwalked. |
| 29 | `/routing/static-route/gateway` | `CanonicalStaticRoute.gateway` | the next-hop value; covered implicitly because a route with a wrong/dropped gateway usually drops the whole `/routing/static-route`. Minor. |
| 30 | `/vlans/vlan/ipv4/address/prefix-length` | SVI prefix | `ip` is walked; prefix nearly always travels with it. Minor. |
| 31 | `/interfaces/interface/vrrp-groups/group/description` | `.description` | operator text; low fidelity stakes |
| 32 | `apply_groups` / `group_content` | root provenance | Junos-only provenance hints; explicitly "ship-before-wire for most codecs"; arguably metadata (already in `_NON_CAPABILITY_FIELDS` of the honesty guard) |
| 33 | single-VIP `virtual_ips` drop | `CanonicalVRRPGroup.virtual_ips` | walked ONLY when `len>1`; a codec that drops the *sole* VIP keeps the group marker but the VIP is gone — a narrow hole |

**Gap headline count: ~24 leaves of genuine concern** (HIGH 11 + MEDIUM 9, treating the DHCP/EVPN clusters as single concerns gives ~20; with the LOW/structural ones ~33 total expressible-unwalked). The **~24** figure for the design phase = the HIGH + MEDIUM rows, i.e. leaves where a codec populates a non-default value and a silent drop has real consequence.

---

## 5. Catalogue of the 5 existing partial guards — what each covers / leaves open

| guard | file | what it covers | what it LEAVES OPEN |
|---|---|---|---|
| **G1** value-detail subfields | `tests/unit/migration/test_silent_loss_list_subfields.py` | A hand-curated `_CASES` list (10 cases): vxlan mcast/flood, vlan-description, snmp v3 engine-id, varp vga/vgm v4+v6, tunnel-type, vlan-svi-ipv4. For each: if a codec keeps the identity leaf but drops the sub-detail, the sub-detail MUST be declared lossy/unsupported. | **Hand-maintained `_CASES`** — a NEW sub-detail (e.g. vrrp `mode`, dhcp `lease-time`) is NOT in `_CASES` so it's uncovered. This is itself an instance of the covered-subset blind spot, one level up. |
| **G2** naming-sensitive | `tests/unit/migration/test_silent_loss_naming_sensitive.py` | LAG members + `lag-member-of` + per-interface switchport + VLAN-centric port lists, using a per-codec `_NATIVE` name map so a drop is unambiguous. | Only the L2/LAG surfaces. Pins the opnsense/mikrotik/fortigate VLAN-port-list finding. Nothing about VRRP/DHCP/RADIUS/SNMP-v3 sub-fields. |
| **G3** registry honesty (reverse-parity) | `tests/unit/migration/test_registry_capability_honesty.py` | (a) every declared `supported` xpath is walkable; (b) rendered field ⇒ not-unsupported; (c) no supported/unsupported overlap; (d) **#149** non-walkable lossy/unsupported must be documented-synthetic; (e) naming-independent total-drop must be declared; (f) static-route subfield + secondary drops declared; (g) `test_marker_dict_covers_every_data_bearing_field` — every top-level field has a marker. | These are **declaration-vs-render** and **declaration-vs-walker** consistency checks. **NONE of them assert that the walker COVERS every model leaf.** `test_marker_dict_covers_every_data_bearing_field` is the closest — but it only checks **top-level** `CanonicalIntent.model_fields`, NOT nested sub-leaves (it would never notice `CanonicalVRRPGroup.priority` going unwalked). **This is the precise hole class-1 design must fill.** |
| **G4** #149 non-walkable allowlist | (within G3) `test_lossy_unsupported_nonwalkable_is_documented_synthetic` + `_SYNTHETIC_NONWALKABLE` + `_is_legitimate_nonwalkable` | Teaches the self-justifying-exemption precedent: 6 blessed structural markers + raw-sections + Tier-3-top-segment + whole-field-marker rules. | It's a *reverse* check (declared-but-not-walkable is OK if blessed). It does NOT enforce *walked-coverage* in the forward direction. |
| **G5** per-codec walker coverage floor | `tests/unit/migration/codecs/cisco_iosxe_cli/test_walk_canonical_coverage.py` | The **forward** check, but only at **top-level** granularity: `_FIELD_TO_EXPECTED_XPATH` (18 top-level fields) must each yield ≥1 walker xpath; plus hand-listed per-interface sub-fields, vlan-svi-l3, snmp-v3 sub-fields. | **Hand-maintained `_FIELD_TO_EXPECTED_XPATH` + hand-listed sub-fields.** It proves the 18 top-level surfaces are walked, but a NEW nested leaf (vrrp `priority`, dhcp `lease-time`) added to a model is invisible to it. This is the existing closest-to-the-goal guard and the natural place to generalise — but today it relocates the blind spot into the hand-maintained dict. |

**Synthesis for the design phase:** The forward-coverage direction (every model leaf is walked-or-justified) is **the missing guard**. G5 does it for 18 top-level fields via a hand-maintained dict; G3's `test_marker_dict_covers_every_data_bearing_field` does it for top-level fields via `model_fields` reflection but doesn't recurse into nested models. **Neither recurses into the nested `CanonicalVRRPGroup` / `CanonicalDHCPPool` / `CanonicalSNMPv3User` / `CanonicalEvpnType5Route` / `CanonicalRoutingInstance` sub-leaves — which is exactly where the gap concentrates (§4.1, §4.2).** A reflection-driven guard that recurses through `model_fields` of nested models and asserts each leaf is walked-or-exempt would catch the whole class.

---

## 6. The two-surface nuance (do NOT over-state the gap)

There are **two** consumers that decide whether a dropped field is surfaced, and they have **different** blind spots:

1. **Live `validate_against` report** (the migrate-page banner) — depends 100% on `_walk_canonical`. Blind to every gap leaf in §4.
2. **Offline cross-mesh audit** `tools/run_full_mesh.py` — does **NOT** use the walker. It compares `source.model_dump()` vs `target.model_dump()` field-by-field (`run_full_mesh.py:334-335`) and reads each target's `CapabilityMatrix.unsupported` directly. The `_walk_canonical` docstring (lines 57-60) explicitly notes this. So a DHCP `lease-time` drop, an EVPN `prefix` drop, etc. **are** caught at audit/regen time as field-disposition drift — they are blind only to the *live UI banner*.

**Consequence for the design:** the class-1 fix closes the **live-report** honesty hole specifically. The HIGH-risk VRRP/SNMP-v3/IPv6-scope leaves (§4.1) are the ones where the live report is the operator's only signal before they commit a migration — those are the leaves where walking matters most. The DHCP/EVPN envelope sub-leaves (§4.2) have a partial backstop in the cross-mesh audit, so they are lower urgency even though they are real walker gaps.

---

## 7. The #149 exemption — what MUST stay non-walkable

Any "walk every leaf" rule (design A) or "every model leaf must be walked or justified" guard (design B) must NOT flag these as gaps — they are **intentionally** non-walkable:

- **Tier-3 routing-protocol paths** — `/routing/bgp`, `/routing/ospf`, `/routing/isis`, etc. The canonical model does NOT have BGP/OSPF surfaces as walkable leaves; codecs declare them `unsupported` and they're modelled only as `dropped_tier3_sections`. The `_is_legitimate_nonwalkable` predicate (`test_registry_capability_honesty.py:333-346`) handles this via the `/routing/` + not-`static-route` rule and the `_WALKABLE_TOP_SEGMENTS` top-segment check.
- **The 6 `_SYNTHETIC_NONWALKABLE` markers** (`test_registry_capability_honesty.py:323-330`): `/interfaces/interface/4th-port-segment` (IOS-XR), `/interfaces/interface/vrrp-groups/group/address-family` (IOS-XE-CLI), `/interfaces/interface/subinterfaces/subinterface` (Junos dot1q), `/interfaces/interface/subinterfaces/subinterface/ipv6` (IOS-XE-CLI), `/routing-instances/instance/table` (VyOS), `/vxlan-vnis/l2vni-route-target` (AOS-CX/VyOS). These are per-vendor structural quirks the canonical model deliberately does not represent as leaves.
- **`raw_sections`, `dropped_tier3_sections`** (root) — Tier-3 carry-through / notification surfaces; never walked by design.
- **Metadata** — `source_vendor`/`source_format`/`source_version` (already in `_NON_CAPABILITY_FIELDS`).

**Crucial distinction the design phase must respect:** #149 is about *declared-but-not-walkable* (a matrix declares a path the walker never yields → OK if blessed). The class-1 gap is the **opposite direction**: *model-leaf-exists-but-not-walked-AND-not-declared*. The `_SYNTHETIC_NONWALKABLE` set is the *precedent for the exemption mechanism* (each entry self-justifies with a comment), but the new forward-coverage guard needs its OWN exemption set keyed by `Class.field` (or model xpath), e.g. exempting `CanonicalInterface.kind` (transform hint), `CanonicalInterface.default_name` (render mechanism), `apply_groups`/`group_content` (provenance metadata), and the routing-protocol Tier-3 absence.

---

## 8. Recommendation seeds for Phase 2 (`20-design-walker-guard`)

(Phase-1 agent — I do not pick the design, but I flag what the census implies.)

1. **The gap concentrates in NESTED model sub-leaves** (VRRP group, DHCP pool, SNMPv3 user, EVPN-type5, routing-instance). The two existing forward-coverage guards (G5's `_FIELD_TO_EXPECTED_XPATH`, G3's `test_marker_dict_covers_every_data_bearing_field`) BOTH stop at top-level `CanonicalIntent` fields. **The durable fix must recurse into nested `model_fields`.** A reflection-driven completeness guard (design B) that walks `CanonicalIntent` → child models → leaf fields and asserts each leaf maps to a walked xpath or a justified exemption would have caught all 11 HIGH-risk leaves.
2. **A "walk everything" runtime change (design A) is risky here** because the walker is the input to the live report AND (indirectly via the matrices that must then declare the newly-walked leaves) would force a phase4 reclassification storm: every newly-walked leaf that a codec drops needs a per-codec lossy/unsupported declaration across up to 11 codecs, and `tests/unit/audit` reconciliation cells would move. The St3 demotion lesson in MEMORY (anycast VGA broke a `tests/unit/audit/` reconciliation test) is the precedent — quantify before shipping.
3. **A guard that maps each model leaf to its expected walker xpath spelling is the lowest-risk option** — it FAILS at CI time the moment a new leaf is added without a walker yield+declaration, with zero runtime behaviour change, but does NOT itself force every existing gap leaf to be walked (it would need an initial exemption entry per current-gap leaf, each carrying a one-line reason — which makes the gap *visible and accounted-for* rather than silent). The open question (for `30-review-correctness`/`31-review-pragmatism`): does the exemption list just relocate the blind spot? Mitigation precedent = #149's self-justifying `_SYNTHETIC_NONWALKABLE` (each entry has a rationale comment + the guard fails loudly on un-blessed additions).
4. **Prioritise walking the §4.1 HIGH leaves regardless of design choice** — the VRRP sub-fields and the SNMPv3 `priv-passphrase`/protocols are the ones where the live report is the operator's only pre-commit signal and the loss is a security/reachability change, not a cosmetic detail.

---

## 9. Citations index (file:line)

- Default-to-supported: `netcanon/models/migration.py:221-228`.
- Walker yields: `netcanon/migration/canonical/xpath_walker.py:62-256` (per-leaf lines in §1).
- Walker-is-sole-input: `netcanon/services/migration_validate.py:28-45, 80-87`.
- Cross-mesh uses model_dump not walker: `tools/run_full_mesh.py:334-335`; walker docstring `xpath_walker.py:57-60`.
- Gap-leaf population (grep-confirmed): vrrp `mode=hsrp` `cisco_nxos/parse.py:809`, `mode=carp` `opnsense/parse.py:838`, arista `parse.py:198`; vrrp adv-interval/preempt/auth/virtual_ipv6s `juniper_junos/parse.py:2379-2413`, `mikrotik_routeros/parse.py:663-780`, `opnsense/parse.py:804-843`; ipv6 scope `arista_eos/parse.py:1064`; dhcp lease/domain `opnsense/parse.py:701-702`, `mikrotik_routeros/parse.py:1007`, `juniper_junos/parse.py:788`; radius ports `opnsense/parse.py:258-259`, `fortigate_cli/parse.py:767-768`, `mikrotik_routeros/parse.py:975-976`, `cisco_iosxe_cli/parse.py:1509-1510`, `aruba_aoss/parse.py:1012-1013`; instance_type=mac-vrf `arista_eos/parse.py:853`; l3_vni `arista_eos/parse.py:1346`; kind=mgmt `cisco_iosxe_cli/parse.py:1062`, `cisco_nxos/parse.py:848`.
- Guards: G1 `tests/unit/migration/test_silent_loss_list_subfields.py`; G2 `tests/unit/migration/test_silent_loss_naming_sensitive.py`; G3+G4 `tests/unit/migration/test_registry_capability_honesty.py` (#149 allowlist lines 323-346, top-level-only marker check lines 527-541); G5 `tests/unit/migration/codecs/cisco_iosxe_cli/test_walk_canonical_coverage.py` (top-level `_FIELD_TO_EXPECTED_XPATH` lines 165-184).
