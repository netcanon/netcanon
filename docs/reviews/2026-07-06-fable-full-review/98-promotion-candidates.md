# Netcanon v0.5.3 — Codec-Fidelity Promotion Candidates (2026-07-06)

> **PROPOSALS ONLY — nothing here is a defect, and nothing may land without the user's explicit
> greenlight.** All 20 candidates from the two promotion scouts (98a parse/model half, 98b
> render/disposition half) survived independent adversarial verification; 4 carry material
> verifier adjustments, folded in below. Code promotions must follow the established
> **ship-before-wire** discipline: schema/matrix declarations first where a new field is involved,
> parse + render halves landed **together per codec** so `parse(render(t)) == t` never regresses,
> matrix flips in the same PR as the wire-up with round-trip tests. **Matrix pessimism is the safe
> bias** — declaring lossy/unsupported when unsure is intentional and correct; a promotion is
> justified only where the verifier confirmed the surface genuinely round-trips (or can, with
> bounded work) and the flip cannot reintroduce silent loss.
>
> Ranked by payoff-vs-risk, high-payoff/low-risk first. Tags: **[code]** = parse/render wire-up;
> **[yaml]** = expectation-YAML / matrix-reason truth maintenance (no behavior change).
> Full evidence and repro transcripts: `98a-promotion-parse.md`, `98b-promotion-render.md`.

---

## 1. [code] `/system/syslog-server` — cisco_iosxe_cli

- **Current disposition:** unsupported — with a matrix reason that is **factually false about the codec's own render**.
- **Verifier verdict:** CONFIRMED (reproduced end-to-end at v0.5.3).
- **Why improvable:** `render.py:188-191` already emits `logging host <srv>` for every canonical syslog server, while `codec.py:328-331` declares the path unsupported ("Render emits no logging/syslog config"). A junos→iosxe_cli job carrying syslog gets a **false validation BLOCK** (partial job + dropped-banner) even though the rendered config contains the correct lines; parse.py has no logging harvest, so the mesh scores it dropped on re-parse. Also the "bonus contradiction" under synthesis finding #1 (Tier-1).
- **Not a hard blocker:** render half already shipped; core IOS grammar; donor exists (juniper_junos parses syslog hosts); corpus has `batfish_cisco_logging.txt`.
- **Wiring sketch:** add `logging host <ip>` (+ legacy `logging <ip>`) harvest beside the existing ntp/name-server regexes (`parse.py:358-378` seam); flip the matrix entry; extend the codec round-trip test; correct the `juniper_junos__cisco_iosxe_cli.yaml` syslog cell.
- **De-risking verification:** 3-line probe — junos `set system syslog host 10.9.9.9 any notice` → iosxe render → expect classify=supported and re-parse `['10.9.9.9']`.

## 2. [code] `/interfaces/interface/ipv6/address` (nested `config ipv6`) — fortigate_cli

- **Current disposition:** fail-open-silent — path **declared supported**, FortiOS 7.x nested form silently drops.
- **Verifier verdict:** CONFIRMED, payoff rated HIGH (an undeclared-drop on a supported surface — the class the honesty machinery exists to prevent).
- **Why improvable:** `parse.py:361` reads `ip6-address` only from the legacy direct form; FortiOS 7.x exports nest all interface IPv6 under `config ipv6` (29 nested blocks in the real fg100e corpus fixture — every corpus value is the `::/0` placeholder, which is exactly why the mesh never caught it). Nested `set ip6-address 2001:db8::1/64` parses to `ipv6_addresses==[]` while `classify()` returns supported.
- **Not a hard blocker:** the `_EditBlock.sub_blocks` machinery already parses the nested block unread (proven consumers in the same file: vrrp, dhcp, snmp-hosts); grammar documented in-repo (`docs/vendor-references/cisco_iosxe_cli_to_fortigate_cli/ip_addressing.md:66-70`).
- **Wiring sketch:** nested-or-fallback read of `ip6-address`/`ip6-mode` (+ `config ip6-extra-addr` secondaries); infer link-local scope via a shared fe80 helper hoisted into `codecs/_helpers.py` (also serves #10); render half emits the nested `config ipv6` form. **Verifier note:** ip6-extra-addr secondaries land under the declared-unsupported v6 secondary-ip path — keep that piece declared or wire its render in the same change.
- **De-risking verification:** post-fix parse of a real non-`::/0` nested address survives with correct scope; `parse(render(tree))==tree`.

## 3. [code] `/interfaces/interface/ipv4/address/secondary-ip` — fortigate_cli

- **Current disposition:** unsupported (declared — banner fires; the drop is honest but whole-subnet).
- **Verifier verdict:** CONFIRMED, payoff HIGH.
- **Why improvable:** `config secondaryip` with 2 entries parses to a single primary address; both secondary subnets vanish from canonical and re-render. The matrix's own reason calls it "a whole-subnet reachability loss". `CanonicalIPv4Address.is_secondary` exists and cisco/arista/junos donors populate it — cisco-secondary → fortigate inbound pays immediately.
- **Not a hard blocker:** FortiOS grammar documented in-repo (`ip_addressing.md:48-64`); the nested-subtable parse pattern is proven in the same file; the quoted single-token `'IP MASK'` concern has an in-file precedent (trap-hosts split, `parse.py:571-574`).
- **Wiring sketch:** parse `sub.config_path=='secondaryip'` entries → `CanonicalIPv4Address(is_secondary=True)`; render `set secondary-IP enable` + the table; **flip only the interface-mount matrix entry** — the VLAN-SVI twin (`/vlans/vlan/ipv4/address/secondary-ip`) stays declared until separately wired (verifier note).
- **De-risking verification:** round-trip with 2 secondaries; cross-render from a cisco `ip address X Y secondary` source.

## 4. [code] `/system/ntp-server` + `/system/dns-server` + `/system/domain` + `/system/syslog-server` — cisco_nxos

- **Current disposition:** unsupported ×4.
- **Verifier verdict:** CONFIRMED.
- **Why improvable:** arista→nxos renders neither dns nor ntp; the grammar is trivial core NX-OS present **verbatim in the codec's own real fixtures** (`ntp server 10.1.1.1 use-vrf default`, `ip domain-name …`, `logging server 10.125.1.171 6 port 7008`) — those source lines are also dropped on parse today, so wiring both halves upgrades same-vendor fidelity too. 7 donor codecs.
- **Not a hard blocker:** no feature-gate needed (verifier confirmed `_derive_features` untouched — ntp/logging/dns are not feature-gated on NX-OS); certified codec status does not preclude additive promotion.
- **Wiring sketch:** render seam at `render.py:83-92` (after hostname/vdc, before the feature block); parse regexes tolerant of `use-vrf`/`prefer`/severity/port tails (harvest the address; optionally declare tail-drop lossy); flip 4 entries; round-trip fixture assertions.
- **De-risking verification:** parse the akarneliuk/nautobot fixtures → fields populated; same-vendor re-render re-emits; arista→nxos cell shows preserved. Expect same-vendor golden-fixture churn (render gains lines) — normal test maintenance, not a risk.

## 5. [code] `/lags/lag/mode` — juniper_junos

- **Current disposition:** lossy (declared).
- **Verifier verdict:** CONFIRMED, payoff HIGH — and **stronger than filed**: the verifier also reproduced that an explicit `lacp passive` followed by `lacp periodic fast` (real junos emit order) parses as **active** — the `periodic` token overwrites an explicit passive. The same token guard fixes both corruptions.
- **Why improvable:** a static bundle (members via `ether-options 802.3ad ae0`, no lacp line) parses `mode='active'`, and same-vendor re-render **invents** `set interfaces ae0 aggregated-ether-options lacp active`. Deploying that against a static-bonded peer takes the bundle down — protocol-changing loss. The render side is already correct; the fix is two parse-side default literals plus a guard.
- **Not a hard blocker:** junos semantics unambiguous — an ae without an lacp statement IS static; `periodic` alone does not enable LACP, so the post-fix static default is correct there as well.
- **Wiring sketch:** `parse.py:1289`/`:1302` setdefault `'active'`→`'static'`; only assign `entry['mode']=tokens[3]` when `tokens[3] in ('active','passive')`. Update expectation YAMLs recording static→active drift (e.g. `fortigate_cli__juniper_junos.yaml`); **verifier-corrected remediation scope:** the bb47f21 T0-1 probe is an implication guard (loses-mode ⇒ must-declare) and passes unchanged once the loss stops — only the YAMLs and the eventual LossyPath removal need edits. Consider lossy→supported.
- **De-risking verification:** static stays static, active stays active, **passive stays passive**; junos LAG unit tests + T0-1 probe. All real junos fixtures use explicit `lacp active` → minimal mesh-baseline churn. Risk: medium (YAML churn only).

## 6. [code] `/routing/static-route/vrf` — arista_eos

- **Current disposition:** unsupported — literal ship-before-wire debt (matrix reason: "wire-up scheduled for v0.2.0").
- **Verifier verdict:** CONFIRMED, payoff HIGH — **verifier bonus:** arista `render.py:934-947` has NO vrf filter, so vrf-carrying routes from donor sources currently render into the **global table** (wrong-VRF emission, arguably worse than a drop); the render half of this promotion closes that too.
- **Why improvable:** `ip route vrf MGMT 0.0.0.0/0 192.168.2.1` — present in **2 of 5 real EOS fixtures** — parses to `static_routes==[]` while the MGMT instance parses fine: the management default route is silently absent from the migrated tree. The donor (cisco_iosxe_cli) graduated its identical entry in PR #24.
- **Not a hard blocker:** `CanonicalStaticRoute.vrf` exists; the grammar is a strict infix extension of the already-parsed form; the phantom-instance trap is documented in standing memory (harvest onto `route.vrf`, never auto-create an instance) and the sketch honors it.
- **Wiring sketch:** extend `_IP_ROUTE_RE` with an optional `vrf <name>` infix (+ the v6 twin); render `ip route vrf <v> <dest> <gw>` preserving tree order; matrix flip + arista static_routes expectation-YAML updates.
- **De-risking verification:** parse `batfish_eos_evpn_vlan_based_leaf.txt` → route materializes with `vrf='MGMT'`, routing-instance count unchanged (no phantom).

## 7. [code] `/routing/static-route/metric` — arista_eos, juniper_junos, mikrotik_routeros, fortigate_cli, aruba_aoss, cisco_iosxr

- **Current disposition:** lossy on all six.
- **Verifier verdict:** **ADJUSTED** — core confirmed by live repro (a floating static, metric 250, renders on all six targets with no distance token and re-parses metric=0: the backup default becomes co-equal with the primary, silently destroying failover), donors populate the field, all six vendors have native admin-distance grammar. **But two of the six sketches were unsound as written:**
  - **juniper_junos:** a route-level `preference` line applies to BOTH records of a floating pair (one canonical record per next-hop) and cannot be attributed on parse — use per-next-hop **`qualified-next-hop <gw> preference <n>`** on both halves instead.
  - **aruba_aoss:** all `0.0.0.0/0` destinations currently route through `ip default-gateway`, which has **no distance grammar** (and already emits two conflicting lines for a floating pair) — the default-route branch needs rework to `ip route 0.0.0.0 0.0.0.0 <gw> distance <n>` (valid with ip routing), or defaults stay lossy.
  - **Range edge for the flip:** IOS-XR max 254, junos preference is 32-bit — keep a narrow out-of-range clamp note or the mesh drifts on extreme values.
- **Not a hard blocker:** documented grammar on all six platforms; four donor parsers (iosxe_cli/nxos/vyos/aoscx) already populate metric; mirrors the shipped IPv6-static-route sweep (#252–#260) in shape.
- **Wiring sketch:** per codec, render emit (only when metric>0, clamped) + symmetric parse harvest landed together; arista (trailing int), mikrotik (`distance=`), fortigate (`set distance`), iosxr (trailing int) are straightforward as originally sketched. **Suggested landing order:** the four easy codecs first, junos/aoss as a second PR after the redesigns.
- **De-risking verification:** per codec: 2-route config with metric 0/250 → distance token present, re-parsed metric==250; same-vendor round-trip test each.

## 8. [yaml] `per_field_expectation.dhcp_servers` — `fortigate_cli__arista_eos.yaml`

- **Current disposition:** cell says unsupported, reason claims "arista_eos does NOT advertise /dhcp/pool" — **stale-false** since Cluster E.1-A shipped the ip-dhcp-pool wire-up.
- **Verifier verdict:** CONFIRMED — live matrix classifies `/dhcp/pool` supported; the real 6-pool fixture round-trips byte-model-equal; the YAML's own deferred-items footer anticipated exactly this flip; flipping makes future drift **stricter** (scores CODEC_BUG instead of EXPECTED_UNSUPPORTED).
- **Wiring sketch:** edit the cell unsupported→good (or lossy with the advanced-option caveats the sibling files use); rewrite the reason to reference the shipped wire-up. No code change. Path correction from the verifier: the fixture lives at `tests/fixtures/real/fortigate/` (not `fortigate_cli/`).
- **De-risking verification:** re-run the parse→render→re-parse probe (6 pools, model_dump equality); phase-4 cell flips EXPECTED_UNSUPPORTED→ALIGNED.

## 9. [yaml] `per_field_expectation.static_routes` — `juniper_junos__cisco_iosxe_cli.yaml`

- **Current disposition:** lossy, reason cites "CanonicalStaticRoute lacks a vrf field" — the field has existed since v0.2.0 and both codecs wire it.
- **Verifier verdict:** CONFIRMED — verifier swept the **full** corpus: 8/8 junos fixtures with static routes byte-model-preserved through iosxe_cli (better than the claimed 5/5). The kept-as-notes residuals (junos `preference` unparsed — folds into #7; `qualified-next-hop` unparsed) are comparator-invisible, so the flip is detection-positive: any future genuine asymmetry surfaces as CODEC_BUG, the correct outcome.
- **Wiring sketch:** flip to good + notes; audit sibling static_routes cells citing the same stale vrf claim in the same pass. Pure YAML edit.

## 10. [code] `/interfaces/interface/ipv6/address/scope` — vyos

- **Current disposition:** lossy — the declared reason names this exact gap ("parse hardcodes scope=global"); promotion completes declared debt.
- **Verifier verdict:** CONFIRMED.
- **Why improvable:** `address fe80::1/64` parses scope='global'; cisco-family targets then render an fe80 address **without the mandatory `link-local` keyword** — invalid CLI on the target. Scope is a pure function of the address bytes, so the promotion cannot reintroduce silent loss.
- **Not a hard blocker:** the identical fe80::/10 inference already shipped twice in-repo (cisco_iosxe_cli Wave 10 gamma-3; aruba_aoscx) — an unfinished port, not new design.
- **Wiring sketch:** infer at `parse.py:884` via the shared fe80 helper hoisted to `codecs/_helpers.py` (the same helper closes the fortigate twin inside #2); vyos render needs no change (grammar has no scope keyword); lossy→supported.
- **De-risking verification:** vyos fe80 → cisco render carries the `link-local` keyword; same-vendor round-trip re-infers.

## 11. [code] `/system/syslog-server` (+ legacy `ip domain-name` rider) — arista_eos

- **Current disposition:** unsupported.
- **Verifier verdict:** CONFIRMED — real-fixture asymmetry: `ksator_dcs_7150s64_eos4224.txt` line 19 `logging host 10.83.28.52` parses to `[]` while the **same fixture's** `ntp server 10.83.28.52` parses fine. A harvest gap, not a scope decision.
- **Not a hard blocker:** identical regex shape to the in-file `_NTP_SERVER_RE` donor (including vrf-infix tolerance); Tier-1 list field exists; junos/iosxe_cli/fortigate/opnsense targets already render syslog.
- **Wiring sketch:** `_SYSLOG_RE = r'^logging host\s+(?:vrf\s+\S+\s+)?(\S+)'`; widen `_DNS_DOMAIN_RE` to accept legacy `ip domain-name` (corpus-thin rider, code-read-confirmed). The matrix flip needs the arista render half (`logging host X`) — the declared reason is render-framed, so **land both halves together**.
- **De-risking verification:** fixture parse → `['10.83.28.52']`; junos target emits `set system syslog host`.

## 12. [code] `/system/dns-server` + `/system/domain` — vyos

- **Current disposition:** unsupported ×2.
- **Verifier verdict:** CONFIRMED, with **two implementation guards**: (a) path-guard the harvest to the `system{}` level using the existing stack-depth pattern — dhcp-server subnet blocks legally carry `domain-name`/`name-server` leaves that must feed `CanonicalDHCPPool` fields, not the system scalars (one of the originally cited fixture lines is actually that dhcp leaf; the scottlaird fixture is the valid grounding); (b) tolerate/filter non-IP name-server values (`name-server "eth0"` = use-DHCP-resolvers is legal VyOS) so cross-vendor targets never render `ip name-server eth0`.
- **Not a hard blocker:** the `system{}` emission seam already exists (host-name/login/ntp); the repeated-leaf parse pattern exists for the identical ntp shape; set-form input comes free via `_setform_to_brace`; 7 donor codecs.
- **Wiring sketch:** render `domain-name` + `name-server` leaves inside the existing system block; parse the two nodes with the guards above; flip both entries; fixture round-trip assertions.
- **De-risking verification:** parse a vyos fixture carrying name-server/domain-name → populated + re-emitted; arista→vyos cell shows dns preserved.

## 13. [code] `/system/ntp-server` + `/system/dns-server` + `/system/syslog-server` — cisco_iosxr

- **Current disposition:** unsupported ×3 (`/system/domain` already wired).
- **Verifier verdict:** CONFIRMED — rank **below the NX-OS twin (#4)**: the dns/syslog halves are grammar-grounded rather than corpus-grounded (the one real XR fixture's `ntp` block does validate the tolerant-parse plan: harvest `server <ip>` leaves, skip maxpoll/prefer/source tails). **Do NOT attempt the aruba_aoscx sibling** — its parser deliberately discards the service footer including ntp lines; unwinding that is version-banner surgery.
- **Wiring sketch:** emit `domain name-server X` beside the existing domain-name line, an `ntp / server X` block, and `logging X` lines; three harvests beside `_extract_domain`; flip three entries. Same same-vendor golden-churn note as #4.
- **De-risking verification:** arista source with dns+ntp → iosxr render contains `domain name-server` + `ntp server` → re-parse equality; parse the real `iosxr_design_cst_pa3_xr752.cfg` ntp block.

## 14. [yaml] `per_field_expectation.ntp_servers` (+ dns subset) — multiple pair files

- **Current disposition:** lossy in 34/56 files, describing **pre-canonical option loss** (prefer/iburst/key not modelled) that the canonical-vs-canonical comparator can never observe — structural METHODOLOGY noise (the 933-cell under-bucket).
- **Verifier verdict:** **ADJUSTED** — full-corpus sweep confirmed all 7 ntp pairs preserved, but the flip set is corrected:
  - **Flip clean (~5 ntp cells):** junos→{iosxe_cli, fortigate, mikrotik}, arista→{iosxe_cli, fortigate}. The junos→mikrotik cell is safe because the ROS6 2-slot dialect gates on `source_vendor=='mikrotik_routeros'` — cross-vendor always renders the unbounded v7 form.
  - **Defer or caveat (2 aoss-target ntp cells):** aoss renders every server at `sntp … priority 1`, which on a real AOS-S **replaces** the previous server — the harness scores preservation, not on-device validity. Fixing the render to increment priority 1-3 first is the clean path.
  - **Do NOT flip (3 fortigate-target dns cells):** fortigate render caps at `set primary`/`set secondary` — a real, comparator-visible truncation at 3+ resolvers; flipping would mint a false CODEC_BUG on the first 3-resolver fixture. Only the opnsense-target dns cells qualify (unbounded per-entry emit).
- **Wiring sketch:** per surviving cell: disposition lossy→good; demote the per-server-options sentence to `note:`.
- **De-risking verification:** single parse→render→re-parse probe per flipped cell; post-fix phase-4 METHODOLOGY_under count drops.

## 15. [code] `/routing/static-route` (parse harvest) — opnsense

- **Current disposition:** lossy — but the declared reason is render-framed, and since parse harvests nothing the walker never yields the xpath, so opnsense-as-**source** loss of the box's default route is **fully silent today** (sharper than filed: no declaration fires at all).
- **Verifier verdict:** CONFIRMED, with guards: (a) skip `<route>` elements lacking network/gateway children — the corpus's only `<staticroutes>` payload is an empty `<route/>`; (b) skip non-IP gateway values (`dynamic`/empty on DHCP WANs) before synthesizing.
- **Why improvable:** all 3 real HA fixtures carry `<gateway_item>` with `defaultgw=1` whose IP (172.18.0.250) appears nowhere in the parsed tree. Parse-half-only pays without the hard render piece: XML shapes are flat name-keyed cross-refs, defaultgw→`0.0.0.0/0` is unambiguous.
- **Wiring sketch:** build name→(ip, iface, ipprotocol) map from `<gateways>`; resolve named `<staticroutes><route>` entries; synthesize `0.0.0.0/0` (`::/0` for inet6) for uncovered defaultgw items; **keep the matrix lossy** with an honest "parse harvests; render pending" reason — post-fix same-vendor drift lands as (drifted,lossy)=EXPECTED_LOSSY per the phase-4 cheat-sheet.
- **De-risking verification:** parse `opnsense_docs_carp_ha_master.xml` → `[('0.0.0.0/0','172.18.0.250')]`; junos cross-render emits the route.

## 16. [code] `/vxlan-vnis/vni` — cisco_iosxe_cli

- **Current disposition:** unsupported ("until demand arrives" — demand evidence is already in-corpus: the ciscolive EVPN leaf fixture carries a full `interface nve1` overlay).
- **Verifier verdict:** **ADJUSTED** — the gap is real (verifier live run: `vxlan_vnis==[]`, nve1 materialized as a generic interface, same-vendor re-render emits a **gutted** bare `interface nve1` with every overlay line dropped), but the sketch's "parse-only first pass" option is **unsound**: intercepting nve1 without the render half makes the stanza vanish from same-vendor re-render (a NEW silent loss on `/interfaces/interface`, which this codec classifies supported); harvesting without intercepting leaves a phantom nve1 CanonicalInterface that an nxos target renders alongside its own synthesized VTEP stanza (duplicate container). **Only sound landing = the full nxos pattern, parse-intercept + render-emit in ONE change.**
- **Not a hard blocker:** donor fully proven (cisco_nxos intercepts nve1 as a config container and re-emits from VXLAN data); schema complete; the interception trap is documented in the NX-OS track memory.
- **Wiring sketch:** intercept `interface nve1` pre-walker (mirror nxos); harvest source-interface / `member vni` (mcast-group, ingress-replication, `associate vrf` → l3_vni) / udp-port; emit the stanza in render. Budget expectation-YAML updates for iosxe-source cells: interception drops the interface count (14→13 on the fixture) — the original "unchanged interface count" verification text was wrong.
- **De-risking verification:** parse the ciscolive fixture → non-empty vxlan_vnis, nve1 absent from interfaces, same-vendor re-render reproduces the overlay lines.

## 17. [code] `/interfaces/interface/tunnel-type` — cisco_nxos

- **Current disposition:** lossy — the matrix reason itself concedes "NX-OS supports the tunnel mode grammar; this is a render-coverage gap".
- **Verifier verdict:** CONFIRMED, with two wiring notes: (1) add `feature tunnel` to `_derive_features` in the same change — today's bare `interface Tunnel<N>` render is **already** invalid on a real Nexus without it; (2) pin the exact NX-OS ipip token against the platform command reference (`tunnel mode ipip` vs `tunnel mode ipip ip` varies by train — round-trip unaffected, on-device validity depends).
- **Wiring sketch:** emit `tunnel mode gre ip` / `tunnel mode ipip` for tunnel_type in {gre, ipip}; parse the sub-command back; **narrow** the lossy declaration to the unmapped kinds (ipsec/vxlan) rather than removing it — over-warning on gre/ipip until then is the documented safe pessimism. Donors: iosxe_cli/arista/junos/mikrotik.
- **De-risking verification:** iosxe_cli `tunnel mode ipip` source → nxos render contains the mode line → re-parse `tunnel_type=='ipip'`; same-vendor nxos round-trip.

## 18. [code] `/routing/static-route/interface` (Null0 / interface next-hops) — arista_eos

- **Current disposition:** unsupported — the reason reads like a platform limit ("No interface-nexthop static-route form") but EOS grammar HAS the form; the parse regex's own comment cites it.
- **Verifier verdict:** CONFIRMED, with one precision: replace the render `if not route.gateway: continue` guard with gateway-OR-interface emission while **retaining the skip when both are empty** (never emit `ip route <dest> ` garbage from sources that populate neither).
- **Why improvable:** `ip route 10.99.0.0/16 Null0` is parse-ignored (explicit AddressValueError `continue`). Corpus-thin (0 hits in 5 EOS fixtures) but ubiquitous in BGP shops as aggregate anchors; junos targets map Null0 → discard.
- **Wiring sketch:** on AddressValueError set `interface=next_hop, gateway=''` instead of continue (donor: cisco_iosxe_cli's identical branch); render `ip route <dest> <iface>` when interface set.
- **De-risking verification:** same-vendor Null0 round-trip; junos cross-render emits discard.

## 19. [yaml+handoff] `/lags/lag/mode` — aruba_aoscx (stale lossy reason + render-half gap)

- **Current disposition:** lossy with a reason that is **false as written** ("a passive LACP bundle re-parses as static — verified by round-trip probe"): verifier reproduced that aoscx passive round-trips CLEAN same-vendor. The real residual is cross-vendor only.
- **Verifier verdict:** CONFIRMED, with a mechanism refinement: junos suppresses the phantom ae iface only for **bare** bundles (aoscx render then emits no `interface lag N` stanza at all → re-parses ('lag 0','static') with a dangling `lag 0` member reference); an **addressed** bundle materializes ae0 but renders as a non-lag-kind stanza — mode + lag stanza lost in **both** variants.
- **Wiring sketch:** (a) truth-maintain the LossyPath reason to state the cross-vendor render gap — plus the same stale text in the supported-list comment and the test comment (the test itself only pins classify=='lossy' and stays true); (b) render-lens handoff: synthesize `interface lag <N>` stanzas (with lacp mode from CanonicalLAG.mode) from `tree.lags` when no matching lag-kind interface exists — fixes the bare case; the addressed case additionally needs ae→lag-N name mapping for the L3 stanza. **Do NOT revert the junos phantom-lag guard** (pinned by test; it fixed CODEC_BUG drift).
- **De-risking verification:** both probes already ran (same-vendor passive clean; junos-passive → aoscx loss reproduced); post-fix junos-passive → aoscx re-parses ('lag N','passive').

## 20. [yaml] `per_field_expectation.snmp` → `snmp.v3_users` sub-key split — ~22 pair cells

- **Current disposition:** lossy on the whole snmp dict where only v3_users hash portability is lossy; v2c surface verified preserved (5/5 on the aoss corpus, incl. contact/location/trap_hosts).
- **Verifier verdict:** **ADJUSTED — demoted to documentation-only payoff.** The sketch mis-modeled the comparator in both directions: (1) **no parent shadowing** — reconcile_cell scores every YAML key independently, so a flipped `snmp: good` parent fires CODEC_BUG-high on any genuine future v3 drift (protocol-enum coercion, dropped empty-passphrase user) that the sub-key row does NOT protect; (2) **no net noise reduction** — the new `snmp.v3_users: lossy` row itself scores (preserved,lossy)=METHODOLOGY_under on preserved fixtures, merely relocating the noise. YAML cannot express "good EXCEPT a sub-attribute"; the codebase's own anycast precedent solves this in comparator **code** consulting the capability matrix.
- **Safe sequencing (pick one):** (a) keep parents lossy and ADD the v3_users sub-key rows as documentation; or (b) land a matrix-consulting v3 reclassifier (anycast pattern) first, THEN flip the 22 parents. Do not flip parents without one of these.

---

## Suggested batching (if greenlit)

- **Wave 1 — pure honesty corrections, zero behavior change:** #1 (matrix reason + tiny harvest), #8, #9, the clean subset of #14, and the reason-text half of #19.
- **Wave 2 — low-risk parse/render wire-ups with in-file donors:** #2, #3, #5, #6, #10, #11, #12.
- **Wave 3 — system-block sweeps with golden-fixture churn:** #4, #13; then #7 (four easy codecs → junos/aoss redesign PR).
- **Wave 4 — larger/design-tail:** #15 (guarded harvest), #16 (both halves in one change), #17, #18, render half of #19, and #20 only via its safe sequencing.
