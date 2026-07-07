# 98a — Codec-fidelity promotion lens: PARSE/MODEL side

Target: main @ 8598d74 (v0.5.3). Read-only; all probes were in-memory `py -c` parse/render round-trips (no mesh runs, no file writes under tracked dirs).

## Method

1. Dumped every `CapabilityMatrix.lossy` / `.unsupported` declaration across the 12 public codecs via the live registry (560 lines; scratchpad `matrix_dump.txt`).
2. Bucketed each into: platform limitation (grammar genuinely absent on the vendor) / deliberate scope (Tier-3, stub, settled memory decisions) / donor-blocked (no corpus) / **unfinished parse-or-model gap** — only the last bucket survives.
3. Cross-checked survivors against `intent.py` fields and the real corpus under `tests/fixtures/real/<vendor>/`, then live-verified the top candidates with `py -c` parse probes (4 candidates reproduced end-to-end, incl. 2 on real fixtures).
4. De-duplicated against the render-half sibling report (`98b-promotion-render.md`): its R2 (static-route metric ×6 codecs incl. mikrotik `distance=`/junos `preference`), R3 (nxos system basics), R6 (nxos tunnel-type) are NOT re-claimed here; cross-reference ledger at the bottom.

## Verified reproductions

### V1 — fortigate_cli: modern nested `config ipv6` IPv6 addresses silently dropped on a DECLARED-SUPPORTED surface (fail-open-silent)

```
config system interface / edit "port1" / config ipv6 / set ip6-address fe80::1/64 / end
  -> parse: port1.ipv6_addresses == []            (address gone entirely)
caps.classify('/interfaces/interface/ipv6/address') -> 'supported'
supported list carries /interfaces/interface/ipv6/address/{ip,prefix-length}
```

`parse.py:361` reads `ip6-address` only from `edit.settings` — the legacy DIRECT `set ip6-address` form. FortiOS 7.x exports nest ALL interface IPv6 under a `config ipv6` sub-block: the repo's own reference doc says so (`docs/vendor-references/cisco_iosxe_cli_to_fortigate_cli/ip_addressing.md:66-67`), and the real corpus confirms it (29 `config ipv6` blocks in `user_contrib_fg100e_fos7213.conf`, 2 in `kevinguenay_fgt_70g_branch.conf`; every corpus `set ip6-address` line is nested/indented). The mesh never caught it because every corpus value is the `::/0` placeholder, which the parser would filter anyway. A real FortiOS 7.x box with a global v6 address loses it with zero warning — classified *supported*.

Bonus in the same block: `scope` is hardcoded `"global"` (`parse.py:375`) — the fe80::/10 inference that already shipped on cisco_iosxe_cli (Wave 10 γ-3, `parse.py:800-806`) and aruba_aoscx (`parse.py:124`) was never ported.

### V2 — fortigate_cli: `config secondaryip` sub-table dropped — two whole subnets vanish

```
edit "port1" / set ip 10.1.1.1 255.255.255.0 / set secondary-IP enable /
  config secondaryip / edit 1 set ip 10.1.1.2 255.255.255.0 / edit 2 set ip 192.168.50.1 255.255.255.0
  -> parse: ipv4_addresses == [('10.1.1.1', 24, False)]
  -> re-render: no 'secondaryip', no 10.1.1.2, no 192.168.50.1
```

The matrix's own reason text calls this "a whole-subnet reachability loss". The nested `sub_blocks` machinery needed to fix it already exists **in the same file** — used for `config vrrp` (`parse.py:460-520`) and snmp trap `hosts` (`parse.py:564-575`). `CanonicalIPv4Address.is_secondary` exists (ship-before-wire v0.2.0) and 6+ codecs round-trip it.

### V3 — juniper_junos: static (non-LACP) bundle re-parses as `active`; same-vendor re-render INJECTS `lacp active`

```
set interfaces xe-0/0/0 ether-options 802.3ad ae0     (NO lacp line = static bundle)
  -> parse: [('ae0', 'active', ...)]
  -> render: 'set interfaces ae0 aggregated-ether-options lacp active'   <- invented line
```

Deploying that output against a static-bonded peer (server NIC teaming, non-LACP switch) takes the bundle DOWN — a protocol-changing loss, not cosmetic. Root cause is purely parse-side: both `lag_state.setdefault(..., {"mode": "active"})` sites (`parse.py:1289`, `parse.py:1302`) default to `active`, and `parse.py:1287-1288` coerces any non-active/passive token (e.g. `lacp periodic fast`) to `active`. The RENDER side is already correct — `render.py:822-829` emits no lacp line for `mode="static"` — so flipping the parse default closes the loop symmetrically.

### V4 — arista_eos: `ip route vrf MGMT 0.0.0.0/0 192.168.2.1` silently dropped on 2 of 5 REAL fixtures

```
batfish_eos_evpn_vlan_based_leaf.txt (line 209) + batfish_labval_dc1_leaf2a_eos4230.txt (line 295)
  -> parse: static_routes == []   (the device's ONLY static route)
  -> routing_instances == ['MGMT', 'Tenant_A_OPZone', ...]   (the VRF itself parses fine)
```

`_IP_ROUTE_RE` (`parse.py:88-92`) anchors on `^ip route\s+(\d+\.` so the `vrf <name>` infix form never matches. The migrated device loses its management default route. Schema field `CanonicalStaticRoute.vrf` exists; the donor wire-up shipped for cisco_iosxe (PR #24) and nxos, and the phantom-instance trap is already documented in standing memory (harvest onto `route.vrf`, do NOT auto-create an instance).

Also confirmed on the same regex, same probe: `ip route 10.99.0.0/16 Null0` is parse-IGNORED (`parse.py:421-428` explicit `continue`) and trailing admin-distance is uncaptured (metric=0) — the latter is 98b's R2.

### V5 (live, smaller) — vyos fe80 scope + opnsense default gateway

```
vyos:  address fe80::1/64            -> scope='global'   (parse.py:884 hardcodes)
opnsense docs_carp_ha_master.xml:    <gateway_item> 172.18.0.250 defaultgw=1
  -> parse: static_routes == [];  '172.18.0.250' nowhere in the canonical tree
```

## Candidates (parse/model half) — ranked

### P1. fortigate_cli — harvest nested `config ipv6` sub-block (+ fe80 scope inference)
- **xpath:** `/interfaces/interface/ipv6/address` (anchor; declared supported ⇒ fail-open-silent) + `/interfaces/interface/ipv6/address/scope` (lossy)
- **payoff: high / risk: low.** Restores a surface the matrix already promises. FortiOS 7.x is the shipping corpus form.
- **why improvable:** pure parse gap; the sub_blocks walker already parses the nested block — nobody reads it.
- **wiring:** in `_apply_system_interface` (`parse.py:~361`), before the direct-form read, resolve the v6 source: `v6_settings = next((s.settings for s in edit.sub_blocks if s.config_path == "ipv6"), None) or edit.settings`; read `ip6-address`, `ip6-mode`, and `config ip6-extra-addr` (secondary v6) from it. Set `scope="link-local"` when the first hextet masks to fe80::/10 (share/port the iosxe_cli Wave-10-γ-3 helper into `codecs/_helpers.py`). Render half: fortigate render should emit the nested `config ipv6` form for v6 addresses (today it emits the legacy direct form — verify against a 7.x device doc; 98b handoff).
- **verification:** V1 probe above; add a fixture-shaped unit round-trip with a real (non-`::/0`) nested address.

### P2. fortigate_cli — `config secondaryip` → `is_secondary` addresses
- **xpath:** `/interfaces/interface/ipv4/address/secondary-ip` (unsupported)
- **payoff: high / risk: low.** Matrix's own reason: whole-subnet reachability loss. Cisco/Arista/Junos donors all populate `is_secondary`, so the cross-vendor inbound direction (cisco secondary → fortigate) pays immediately too.
- **why improvable:** grammar exists (repo's own vendor-reference documents it); nested-subtable machinery proven in-file (vrrp, dhcp ip-range, snmp hosts).
- **wiring (parse):** after `parse.py:341`, `for sub in edit.sub_blocks: if sub.config_path == "secondaryip": for se in sub.edits: tok = se.settings.get("ip"); ip, mask = tok[0].split()[0:2] if single-token else (tok[0], tok[1]); append CanonicalIPv4Address(ip=ip, prefix_length=_mask_to_prefix(mask,...), is_secondary=True)`. (Beware the FortiOS quoted `"1.2.3.4 255.255.255.0"` single-token form — mirror the trap-host split at `parse.py:571-574`.) Render: emit `set secondary-IP enable` + `config secondaryip` table for `is_secondary` addresses; flip matrix to `supported`, drop the twin `/ipv6/address/secondary-ip` via `ip6-extra-addr` in the same PR or leave declared.
- **verification:** V2 probe; then `parse(render(tree)) == tree` with 2 secondaries.

### P3. juniper_junos — static-LAG mode parse default
- **xpath:** `/lags/lag/mode` (lossy)
- **payoff: high / risk: medium.** Protocol-changing loss (bundle-down against static peers) on both same-vendor round-trip and junos→cisco (`mode on` vs `mode active`). Risk is mesh-side: junos-source LAG cells in `cross_vendor_expectations/*.yaml` and the bb47f21 T0-1 audit probe assert today's active-default; they flip to preserved and need re-dispositioning (that's the desired outcome, but it must land with the YAML updates to keep the CI guard green).
- **why improvable:** render half already correct; fix is two default literals + one guard.
- **wiring (parse.py):** line 1289 + 1302: `setdefault(ae_name, {"members": [], "mode": "static"})`; lines 1286-1290: only assign `entry["mode"] = tokens[3]` when `tokens[3] in ("active", "passive")` (never coerce `periodic`/other lacp sub-options to active). Matrix: keep `lossy` only for the genuinely non-representable direction (none known — candidate for full `supported` promotion on junos; aoss/mikrotik/opnsense keep their platform-limitation lossy entries).
- **verification:** V3 probe; re-run junos LAG unit tests + the T0-1 round-trip probe expecting `static` preserved.

### P4. arista_eos — per-VRF static routes (`ip route vrf <NAME> ...`)
- **xpath:** `/routing/static-route/vrf` (unsupported)
- **payoff: high / risk: medium.** Real-corpus-backed (2/5 fixtures, mgmt default route). Risk: render half must land together (emit `ip route vrf <v> <dest> <gw>` at `render.py:934-947`, keeping tree order), and the documented phantom-instance trap applies (populate `route.vrf`, early-return before any instance auto-creation — memory `feedback_per_vrf_harvest_no_phantom_instance`).
- **why improvable:** schema field exists; proven donor wire-ups (cisco_iosxe PR #24, nxos `vrf context`); EOS grammar is a strict infix extension of the already-parsed form.
- **wiring (parse.py:88-92):** `_IP_ROUTE_RE = ^ip route\s+(?:vrf\s+(\S+)\s+)?(\d+\.\d+\.\d+\.\d+)/(\d+)\s+(\S+)` and populate `vrf=m.group(1) or ""`; mirror for `_IPV6_ROUTE_RE` (`ipv6 route vrf ...`). Matrix: `unsupported → supported`; update `arista_eos` cells in expectations YAML where static_routes was excused by the vrf drop.
- **verification:** V4 probe (real fixture `batfish_eos_evpn_vlan_based_leaf.txt`); assert the MGMT route materialises with `vrf='MGMT'` and no 11th phantom instance appears.

### P5. opnsense — harvest `<staticroutes><route>` + `<gateways><gateway_item defaultgw>` (parse-half-only payoff)
- **xpath:** `/routing/static-route` (lossy — declared for the RENDER drop; the PARSE side is also absent)
- **payoff: medium / risk: medium.** All 3 HA fixtures carry a `gateway_item` with `<defaultgw>1</defaultgw>` whose IP (172.18.0.250) appears NOWHERE in the canonical tree — opnsense-as-source migrations lose the box's default route. Parse harvest alone pays (opnsense→junos/cisco/vyos targets all render static routes); the render half (synthesizing `gateway_item` + interface binding) is the hard piece and was explicitly deferred by 98b — this candidate deliberately claims only the source side.
- **why improvable:** `opnsense/parse.py` has zero handling for `gateways`/`staticroutes` (grep-clean); the XML shapes are flat and name-keyed (`<route><network><gateway-name>` cross-refs `<gateway_item><name>`).
- **wiring (parse):** build `{name: (ip, interface)}` from `<gateways><gateway_item>`; for each `<staticroutes><route>`, resolve the named gateway → `CanonicalStaticRoute(destination=<network>, gateway=<ip>)`; for any `gateway_item` with `<defaultgw>1</defaultgw>` not already covered, synthesise `0.0.0.0/0` (or `::/0` for `inet6`) via its IP. Keep the matrix `lossy` (render still drops) but the reason gains "parse harvests; render pending" honesty.
- **verification:** parse `opnsense_docs_carp_ha_master.xml` → expect `[('0.0.0.0/0', '172.18.0.250')]`; cross-render to junos and assert the route line.

### P6. vyos — fe80::/10 scope inference
- **xpath:** `/interfaces/interface/ipv6/address/scope` (lossy)
- **payoff: medium / risk: low.** Scope is DERIVABLE from the address bytes, so promotion cannot re-introduce silent loss; misclassification today makes cisco-family targets render an fe80 address without the mandatory `link-local` keyword (invalid CLI on the target).
- **why improvable:** the exact inference already shipped twice (cisco_iosxe_cli Wave 10 γ-3; aoscx); vyos `parse.py:884` just hardcodes.
- **wiring:** `parse.py:884` — `scope_v6 = "link-local" if _is_fe80(ip) else "global"` using a shared `_helpers` predicate (first hextet & 0xffc0 == 0xfe80). Same one-liner closes the twin fortigate declaration inside P1.
- **verification:** V5 probe; round-trip a vyos config carrying `address fe80::1/64` and assert scope survives to a cisco render with the `link-local` keyword.

### P7. arista_eos — syslog-server harvest (`logging host`) + legacy `ip domain-name`
- **xpath:** `/system/syslog-server` (unsupported) (+ undeclared `ip domain-name` form gap on `/system/domain`)
- **payoff: medium / risk: low.** Corpus-backed: `ksator_dcs_7150s64_eos4224.txt:19 logging host 10.83.28.52` parses to `syslog_servers == []` (verified live) while the same fixture's ntp DOES parse — an asymmetric gap, not a scope decision. 98b's cross-ref also flags the EOS parser knowing only `dns domain` and not the widespread legacy `ip domain-name` form (code-read confirmed: `_DNS_DOMAIN_RE parse.py:83`).
- **why improvable:** identical shape to the in-file `_NTP_SERVER_RE` donor (`parse.py:84-87`) including the `vrf <x>` infix tolerance.
- **wiring:** add `_SYSLOG_RE = ^logging host\s+(?:vrf\s+\S+\s+)?(\S+)` harvest; widen `_DNS_DOMAIN_RE` to `^(?:dns domain|ip domain-name)\s+(\S+)`. Render half (arista emits no `logging host` today) must land with it to flip the matrix — sibling handoff; parse-half alone still pays cross-vendor into junos/iosxe_cli/fortigate/opnsense targets which all render syslog.
- **verification:** live probe already run (syslog_servers==[] on the real fixture); post-fix assert `['10.83.28.52']` and junos target emits `set system syslog host`.

### P8. cisco_iosxe_cli — VXLAN NVE parse (`interface nve1`)
- **xpath:** `/vxlan-vnis/vni`, `/vxlan-vnis/source-interface`, `/vxlan-vnis/udp-port` (unsupported, "deferred until demand")
- **payoff: medium / risk: medium.** The demand evidence exists in-corpus: `tests/fixtures/real/cisco_iosxe/ciscolive_brkops1104_evpn_leaf_iosxe1715.txt` carries `interface nve1` — its entire fabric overlay drops today. Donor: cisco_nxos solved the same grammar family (`source-interface Loopback0`, `member vni N mcast-group/ingress-replication`), including the documented nve1-intercepted-as-container gotcha (memory: NX-OS track). Risk is the interface walker: nve1 must be intercepted BEFORE generic interface materialisation exactly as nxos does, or a phantom `nve1` CanonicalInterface pollutes the tree.
- **why improvable:** proven in-repo donor parse pattern; `CanonicalVxlan` schema complete; IOS-XE emits `member vni N ingress-replication|mcast-group` forms that map 1:1 onto existing fields.
- **wiring (parse):** intercept `interface nve1` stanza; harvest `source-interface <X>` → per-record `source_interface`, `member vni <N> ...` → `CanonicalVxlan` records (+ `vxlan udp-port`); map `associate vrf` VNIs onto `routing_instances[].l3_vni` mirroring nxos. Render half optional first pass (parse-only wire = iosxe-as-source pays into arista/nxos targets; matrix flips those three paths off `unsupported` only when both halves land — otherwise document parse-only in the reason).
- **verification:** parse the ciscolive fixture; assert non-empty `vxlan_vnis` and stable interface count (no phantom nve1).

### P9. arista_eos — interface-nexthop static routes (`ip route X Null0 / Ethernet1`)
- **xpath:** `/routing/static-route/interface` (unsupported)
- **payoff: low / risk: low.** Corpus-absent (0 hits across the 5 EOS fixtures) but ubiquitous in BGP shops (Null0 aggregate anchors). Parse currently `continue`s on non-IP next-hop (`parse.py:421-428`); `CanonicalStaticRoute.interface` exists and iosxe_cli is the donor. Render must emit `ip route <dest> <iface>` and junos targets map Null0 → `discard`.
- **wiring:** in the `_IP_ROUTE_RE` consumer, on `AddressValueError` set `interface=next_hop, gateway=""` instead of `continue`.
- **verification:** probe already run (`ip route 10.99.0.0/16 Null0` → dropped); post-fix round-trip.

### P10. aruba_aoscx — `/lags/lag/mode` reason text is STALE (yaml-over-pessimistic) + cross-vendor residual is render-half
- **xpath:** `/lags/lag/mode` (lossy)
- **payoff: low / risk: low.** The declared reason ("a `passive` LACP bundle re-parses as `static` — verified by round-trip probe, audit bb47f21 T0-1") is no longer true same-vendor: live probe shows `passive` round-trips clean (parse `_LACP_MODE_RE parse.py:158-161` handles it; absent → static at `parse.py:727` is correct AOS-CX semantics). The REAL residual loss is cross-vendor only: junos ae0 passive → aoscx render emits NO `interface lag N` stanza at all (junos parse suppresses phantom ae0 interface materialisation per Wave 7c-E, so `render.py:329 if kind == "lag"` never fires) → re-parses `('lag 0', 'static')`. Fix is render-side synthesis of `interface lag <N>` stanzas from `tree.lags` — **handoff to the render lens**; the parse-half deliverable is correcting the reason text so the matrix states the true (cross-vendor render) loss.
- **verification:** both probes run this session (same-vendor clean; junos→aoscx drop reproduced).

## Excluded as HARD BLOCKERS / settled scope (do not pursue)

- **VyOS VRF surface entirely** (per-VRF static routes `/routing/static-route/vrf`, `table` id model field): donor-blocked synthetic surface per standing memory — explicitly named in the brief.
- **VyOS VRRP** `/interfaces/interface/vrrp-groups/group`: corpus-absent — every fixture "vrrp" hit is the `vyos-config-version` trailer, zero actual `high-availability vrrp` stanzas.
- **Platform grammar limits (correct lossy/unsupported):** mikrotik 802.3ad no-passive; aoss trunk-lacp active/passive; opnsense lagg single proto; fortigate single `vrip`/`vrdst` per group; aoscx SNMPv3 SHA-1/AES-128-only downgrades; per-user engine-id renders (device-assigned) everywhere; VLAN `description` on name-only vendors (EOS/NX-OS/IOS have no vlan description grammar); fortigate 25-char alias truncation; EOS system-wide-only virtual-router MAC.
- **Deliberate architecture:** cisco_iosxe NETCONF Phase-0.5 stub (its ~60 unsupported entries are the stub, not gaps); Tier-3 ACL/BGP/OSPF/NAT/firewall (safety policy); EVPN Type-5 as VRF-property model (design decision documented in matrix reasons); NX-OS vdc/feature synthesis; aoscx VSX/L3VNI/VRRP deferral (settled in codec track memory).
- **Timezone (all 12):** vendor-specific format strings; cross-vendor translation is a format-mapping project, not a harvest gap (98b reached the same verdict from the render side).
- **NX-OS HSRP timers / virtual_ipv6s:** grammar exists but corpus-absent (hsrp fixtures carry no `timers` line) and the hold-timer has no canonical home — model change with thin payoff; parked.
- **aoscx `snmp/trap-host`:** corpus-absent; parked.
- **aoscx VTEP source-as-IP → interface-name resolution:** genuinely divergent vendor grammar; the verbatim-opaque-string model is the honest treatment; a parse-time IP→loopback-name resolver is possible but risks inventing identities (promoting wrongly = silent wrongness). Left unpromoted by choice.

## Cross-reference ledger vs 98b (render half) — no double-claims

| Surface | 98b claim | 98a treatment |
|---|---|---|
| static-route metric ×6 (incl. mikrotik `distance=`, junos `preference`, arista trailing int) | R2 (both halves specified) | not re-claimed; my parse-site details corroborate (mikrotik `_parse_kv` @ parse.py:1273-1290 already tokenises `distance`) |
| nxos ntp/dns/domain/syslog | R3 | not re-claimed; my live fixture probe (spine01: ntp+syslog+dns all `[]`) is confirming evidence |
| iosxe_cli syslog false-unsupported | R1 | not re-claimed |
| nxos tunnel-type | R6 | not re-claimed (my code-read confirms zero `tunnel mode` parse) |
| arista `ip domain-name` legacy form | flagged to me | claimed here (P7) |
| opnsense static routes | excluded by 98b as full-feature | claimed here as parse-half-only source-side harvest (P5) |
| junos LAG static | — | P3 (parse-side; render already correct) |

## Raw notes

- Matrix dump (full lossy/unsupported inventory, 560 lines): scratchpad `matrix_dump.txt` (session-local).
- All probes: `py -c` in-memory; zero pytest, zero mesh runs, zero writes to tracked paths.
