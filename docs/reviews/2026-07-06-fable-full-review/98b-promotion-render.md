# 98b — Codec-fidelity promotion lens: RENDER side + expectation-YAML dispositions

Agent: codec-fidelity-improvement / render-disposition half (Fable max).
Target: main @ 8598d74 (v0.5.3). READ-ONLY review; all probes were in-memory `py -c` round-trips.

## Method

1. Dumped all 12 codecs' CapabilityMatrix lossy/unsupported entries (502 declarations) and cross-read each against the codec's `render.py`/`parse.py` and the vendor's actual CLI grammar.
2. Checked donor availability for every candidate (a render promotion is pointless if no parser populates the field) — `timezone` is donor-blocked (no parser populates it) and is **excluded** per brief.
3. For the expectation YAMLs (56 pair files, 8 codecs): ran an in-memory sweep — parse up to 6 real fixtures per source, render to every YAML-covered target, re-parse, strict-equality compare each top-level canonical field. Flagged cells where the YAML says `lossy`/`unsupported` but the field was **byte-identical preserved** on ≥1 real fixture. Result: **101 over-pessimistic pair-cells** (sweep script: scratchpad `yaml_sweep.py`; conservative — strict equality only).
   - Corroborates the retained phase4 aggregate: `METHODOLOGY_ISSUE_under = 933` vs `over = 25` (tests/fixtures/real/_phase4_runs/latest.json) — the pessimism skew is systemic and one-sided.
4. Verified the top candidates with real reproductions (transcripts below).

## Verified reproductions (top 2)

### V1 — cisco_iosxe_cli `/system/syslog-server`: declared `unsupported` with a FALSE reason; render already emits the config

```
junos.parse("set system syslog host 10.9.9.9 any notice")  -> syslog_servers=['10.9.9.9']
cisco_iosxe_cli.render(tree)                               -> contains "logging host 10.9.9.9"
cisco_iosxe_cli.capabilities.classify('/system/syslog-server') -> 'unsupported'
cisco_iosxe_cli.parse(rendered)                            -> syslog_servers=[]
```

- `netcanon/migration/codecs/cisco_iosxe_cli/render.py:188-191` emits `logging host <srv>` for every entry.
- `netcanon/migration/codecs/cisco_iosxe_cli/codec.py:329-330` declares the path unsupported with reason "Render emits no logging/syslog config" — **factually wrong about its own render**.
- `cisco_iosxe_cli/parse.py` has no `logging` harvest (only the stdlib import), so the emitted line is dropped on re-parse.
- Consequence today: a junos→iosxe_cli migration carrying syslog gets a validation **block** (partial job + "will be dropped" banner) even though the rendered config already contains the correct `logging host` lines; the mesh scores it as a drop because re-parse loses it.

### V2 — `/routing/static-route/metric`: floating-static admin distance silently destroyed on six targets that ALL have native distance grammar

```
cisco_iosxe_cli.parse("ip route 0.0.0.0 0.0.0.0 10.0.0.1\nip route 0.0.0.0 0.0.0.0 10.99.0.1 250")
  -> routes [(0.0.0.0/0 gw 10.0.0.1 metric 0), (0.0.0.0/0 gw 10.99.0.1 metric 250)]
render to arista_eos      -> "ip route 0.0.0.0/0 10.99.0.1"                       (250 gone) reparse metric=0
render to juniper_junos   -> "set routing-options static route 0.0.0.0/0 next-hop 10.99.0.1" (no preference)
render to mikrotik_routeros / fortigate_cli / aruba_aoss / cisco_iosxr             (no distance token)
classify('/routing/static-route/metric') on all six -> 'lossy'
```

Operational hazard: the backup default (250) becomes co-equal with the primary — the classic floating-static failover pattern is silently converted into two active equal routes. Donors that populate `metric` today: cisco_iosxe_cli, cisco_nxos, vyos, aruba_aoscx (all parse it). Native target grammar exists on every one of the six lossy-declared codecs (see candidate R2).

## Candidates — render-side matrix promotions

### R1. cisco_iosxe_cli `/system/syslog-server` — unsupported → supported (CONFIRMED, V1)
- **Payoff: high** for the pair-cells that carry syslog (junos is the donor); removes a false validation block; reason string is corrected.
- **Risk: low.** Render already ships; only a parse harvest is new.
- **Wiring:** add `logging host <ip>` (+ legacy bare `logging <ip>`) harvest in `cisco_iosxe_cli/parse.py` (module already regex-harvests `ntp server`/`ip name-server` — mirror that); move the path from `unsupported` to `supported` in `codec.py:329`; extend the codec round-trip unit test; correct `juniper_junos__cisco_iosxe_cli.yaml: syslog_servers` if marked lossy/unsupported.
- **Not a hard blocker:** grammar is core IOS; render half already exists; junos donor + fixture (`batfish_cisco_logging.txt` in the corpus even carries logging lines).

### R2. `/routing/static-route/metric` — lossy → supported on arista_eos, juniper_junos, mikrotik_routeros, fortigate_cli, aruba_aoss, cisco_iosxr (CONFIRMED, V2)
- **Payoff: high.** Floating-static routes are ubiquitous; the drop changes failover semantics, not cosmetics.
- **Risk: medium** (six codecs; each change small; render+parse must land together per codec to keep `parse(render(t)) == t`; clamp to each vendor's range and emit only when `metric > 0`).
- **Wiring per codec** (render emit + symmetric parse harvest):
  - arista_eos: `render.py:945` → `ip route <dest> <gw>[ <1-255>]`; extend parse regex at `parse.py:89-90` with optional trailing int.
  - juniper_junos: `render.py:1016-1021` → additional `set routing-options static route <dest> preference <n>` line (and the routing-instance twin at 1009-1016); parse: harvest `preference <n>` tail (verified today it parses to 0).
  - mikrotik_routeros: `render.py:608` block → append `distance=<n>`; parse `parse.py:1274-1279` `kv.get("distance")`.
  - fortigate_cli: `render.py:967-974` → `set distance <n>` inside the edit; parse the same key (static + static6).
  - aruba_aoss: `render.py:869` → `ip route <dest> <gw> distance <n>`; parse tail.
  - cisco_iosxr: `router static` block → trailing `<1-254>` after the next-hop; parse tail.
- **Not a hard blocker:** every vendor has a documented admin-distance/preference token (EOS trailing int, Junos `preference`, RouterOS `distance=`, FortiOS `set distance`, AOS-S `distance`, XR trailing int); four donor parsers already populate the field; this mirrors the #252–#260 IPv6-static-route sweep shape.
- Same-family smaller siblings (optional tail): `/routing/static-route/description` on arista (`name <single-token>` — match the iosxe_cli partial-lossy pattern) and mikrotik already does comment.

### R3. cisco_nxos `/system/ntp-server`, `/system/dns-server`, `/system/domain`, `/system/syslog-server` — unsupported → supported (verified: nothing emitted today)
- Probe: arista source with `ip name-server 10.0.0.53` + `ntp server 10.0.0.123` → nxos render emits neither.
- **Payoff: high.** NX-OS is a certified, heavily-used target; these are on effectively every real switch. Donors: 7 codecs parse ntp, 7 parse dns. The codec's own real fixtures carry the exact grammar (`ntp server 10.1.1.1 use-vrf default`, `ip domain-name lab.karneliuk.com`, `logging server 10.125.1.171 6 port 7008` in tests/fixtures/real/cisco_nxos/) — today those source lines are ALSO dropped on parse, so wiring both halves upgrades same-vendor fidelity too.
- **Risk: low.** Emission point: `cisco_nxos/render.py:83-90` (after `hostname`/`vdc`, before the feature block): `ip domain-name X`, `ip name-server X`, `ntp server X`, `logging server X`. Parse: line regexes tolerant of `use-vrf`/`prefer` tails (harvest address, keep tail-drop declared lossy if desired).
- **Not a hard blocker:** trivially documented NX-OS grammar; fixtures already in corpus; no vendor image needed for grammar-level verification.

### R4. vyos `/system/dns-server` + `/system/domain` — unsupported → supported
- Probe: same arista source → vyos emits `server 10.0.0.123` (NTP wired) but no name-server/domain-name.
- **Payoff: medium-high.** `set system name-server <ip>` / `set system domain-name <fqdn>` are core VyOS grammar; the vyos real fixtures literally contain `name-server "10.1.5.70"` and `domain-name "vyos.net"` (dropped today).
- **Risk: low.** The `system { }` block already exists in the renderer (`vyos/render.py:105-108` emits host-name + login + ntp) — add `domain-name` and `name-server` leaves; harvest the two nodes in the brace parser (and the set-form input path gets them free via `_setform_to_brace`).
- **Not a hard blocker:** grammar is first-page VyOS basics; donors abound; corpus grounded.

### R5. cisco_iosxr `/system/ntp-server`, `/system/dns-server`, `/system/syslog-server` — unsupported → supported
- XR grammar: `ntp` block with `server <ip>`, `domain name-server <ip>`, `logging <ip>`. `domain name` is ALREADY wired (`cisco_iosxr/render.py:84-85`) so the emission seam exists.
- **Payoff: medium** (SP corpus; fewer donor fixtures carry these than the DC corpus). **Risk: low.**
- **Not a hard blocker:** documented ASR9k/NCS grammar; donors exist; same shape as R3.
- Same-family: aruba_aoscx `/system/ntp-server` + `/system/dns-server` (`ntp server X`, `ip dns server-address X`) — **flag with caution**: the AOS-CX parser currently discards the service footer (incl. `ntp` lines) per its `/system/raw-sections/version-banner` lossy entry, so the parse half means unwinding part of that discard (risk medium, listed as extension not a top candidate).

### R6. cisco_nxos `/interfaces/interface/tunnel-type` — lossy → supported (matrix reason self-identifies the gap)
- The declaration itself says: "NX-OS supports the `tunnel mode` grammar; **this is a render-coverage gap**".
- **Wiring:** emit `tunnel mode gre ip` / `tunnel mode ipip` under `interface Tunnel<N>` when `tunnel_type` ∈ {gre, ipip} (leave ipsec/vxlan out: NX-OS models those elsewhere — keep a narrowed lossy entry for them); parse the sub-command back.
- **Payoff: low-medium** (tunnels rarer in the DC corpus). **Risk: low.**

## Candidates — expectation-YAML over-pessimism (corrections, no code)

### Y1. `fortigate_cli__arista_eos.yaml: dhcp_servers = unsupported` — STALE; actually fully preserved (verified)
- Reason text claims "The arista_eos codec does NOT advertise `/dhcp/pool` in its supported set" — false since Cluster E.1-A shipped `ip dhcp pool` render+parse (grammar cited to the Arista EOS User Manual in `arista_eos/render.py:337-355`).
- Verified: fortigate fixture `user_contrib_fg100e_fos7213.conf` → 6 CanonicalDHCPPool records → arista render emits six `ip dhcp pool <name>` stanzas → re-parse **model-equal (True)**.
- It is the only `*__arista_eos.yaml` still saying `unsupported` (siblings say lossy/not_applicable). Fix: disposition → `good` (or `lossy` with the FortiGate-side multi-community-style caveat if preferred), rewrite reason.
- **Payoff: medium** — kills a standing false `EXPECTED_UNSUPPORTED` classification for a surface that round-trips perfectly. **Risk: low** (single-cell YAML edit).

### Y2. `ntp_servers = lossy` — systemic over-pessimism; 7 pair-cells verified preserved N/N on real fixtures
- Marked lossy in **34 of 56** files. The reasons describe PARSE-side modelling ("per-server `prefer`/`iburst`/`key` options are not modelled … Address list itself is preserved") — i.e. loss BEFORE the canonical tree, which the phase-4 comparator (canonical-vs-canonical) can never observe. Result: every fixture with NTP scores `actual=preserved, expected=lossy` → METHODOLOGY_ISSUE_under noise on every run (visible in the one retained latest.json cell: arista→iosxe_cli ntp_servers, severity low).
- Verified preserved N/N: arista→{aruba_aoss, cisco_iosxe_cli, fortigate_cli} (3/3 each), junos→{aruba_aoss, cisco_iosxe_cli, fortigate_cli, mikrotik_routeros} (2/2 each).
- Fix: for pairs where both codecs round-trip the address list, disposition → `good` and demote the per-server-options text to `note:`. Exception to KEEP lossy: junos→aruba_aoss-style protocol-shift cells if the NTP→SNTP distinction is judged semantic (the current reason already flags it; that one is defensible either way).
- **Payoff: medium** (shrinks the 933-cell under-bucket; makes phase4 CODEC_BUG hunting cleaner). **Risk: low.**
- Same shape applies to several `dns_servers = lossy` cells verified preserved (arista→fortigate/opnsense, junos→fortigate/opnsense, aoss→opnsense, opnsense→fortigate).

### Y3. `juniper_junos__cisco_iosxe_cli.yaml: static_routes = lossy` — reason factually stale; verified 5/5 preserved
- Reason cites "per-VRF static routes … parse-and-ignore in v1 (**CanonicalStaticRoute lacks a `vrf` field**)" — the field exists since v0.2.0 and BOTH codecs wire per-VRF routes (junos `parse.py:2048` harvests per-VRF; iosxe_cli renders/parses `ip route vrf`).
- Verified: all 5 junos fixtures' static_routes byte-preserved into cisco_iosxe_cli.
- Fix: disposition → `good`, note the two real residuals (junos `preference` not yet parsed — see R2; multi-word description → single-token `name`, already declared codec-side lossy).
- **Payoff: medium. Risk: low.** Sweep shows the same staleness pattern in other `static_routes` cells (e.g. arista→{aoss,iosxe_cli,fortigate,mikrotik} 2/2, aoss→mikrotik 4/4) — audit the family while in there.

### Y4. `snmp = lossy` cells whose own reason says "v1/v2c surface round-trips cleanly" — use the sub-field key the schema already provides
- 22 flagged pair-cells; verified full preservation including contact/location/trap_hosts: aoss→{arista, iosxe_cli, fortigate, mikrotik, opnsense} 4/4, iosxe_cli→{arista, aoss, fortigate, mikrotik, opnsense} 1/1, fortigate→X 1/1, arista→X 1/1.
- The lossiness the reasons describe is confined to `v3_users` (hash portability — correctly lossy, don't touch). The README schema supports exactly this split: `snmp: good` + `snmp.v3_users: lossy`.
- **Payoff: medium. Risk: low-medium** (judgement call per pair; only flip cells whose fixtures/matrices show a clean v2c surface — the verified list above).
- Weaker siblings in the same bucket (flag for the follow-up YAML pass, not individually promoted here): `dhcp_servers=lossy` cells preserved N/N (opnsense→{arista,fortigate,junos} 3/3, mikrotik→{fortigate,junos} 2/2), `lags=lossy` cells preserved N/N where the reason is only the passive-mode caveat, `vlans` cells (aoss→iosxe_cli 5/5).

## Explicitly excluded (and why)

- `/system/timezone` (all 12 codecs): **donor-blocked** — no parser populates `intent.timezone`; a render emit would be dead code. (Parse-side wire-up is the sibling lens's territory.)
- `radius_servers = lossy` YAML cells (fortigate→aoss etc., byte-preserved in sweep): preservation is of an opaque vendor-encrypted key blob (`fortios:ENC …`) — semantically requires re-key on target; `lossy` is CORRECT. Textbook (preserved,lossy)=METHODOLOGY-tolerated.
- `hostname` mikrotik→X (1/2 preserved): the failing fixture is the documented hostname-normalization behaviour — verified non-bug list.
- `cisco_iosxe_cli→cisco_iosxe vlans unsupported-but-preserved`: preservation happens via target-side VLAN materialization from SVIs (verified non-bug); the stub genuinely renders no `<vlans>` subtree.
- opnsense whole-static-route surface: parse populates nothing (`opnsense/parse.py` never appends to `static_routes`) AND render emits no `<staticroutes>` — both halves absent; the config.xml schema supports it (`<staticroutes><route>` + `<gateways><gateway_item>` cross-ref) so it's promotable in principle, but it's a full feature (gateway_item synthesis), not a promotion — left to the backlog.
- VyOS VRF synthetic surface: donor-blocked per standing memory — not re-hunted.
- aoscx VSX/L3VNI/VRRP, junos apply-groups leftovers, EVPN per-prefix Type-5: platform/design-scoped per matrix docstrings.

## Cross-reference for the parse-lens sibling

- arista_eos parse does not harvest `ip domain-name <fqdn>` (probe: domain='' from an EOS config carrying it) while nxos/iosxr do — likely the EOS parser only knows the newer `dns domain` form. Donor-side gap that would amplify R3/R4.
- junos `preference` parse gap is folded into R2 (must land with the junos render half anyway).

## Raw sweep summary

101 over-pessimistic (YAML lossy/unsup, strictly preserved ≥1 real fixture) pair-cells by field:
snmp 22, static_routes 17, lags 14, vlans 13, dhcp_servers 9, ntp_servers 7, interfaces 6, dns_servers 6, radius_servers 3, routing_instances 2, hostname 2.
(Strict equality ⇒ conservative undercount; `interfaces`/`hostname`/`radius` rows individually triaged above as earned-lossy or excluded.)
