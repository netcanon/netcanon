# Lens 11 — Codec correctness deep-dive (v0.5.3 @ 8598d74)

Focus: recently-changed codecs (mikrotik NTP #293/#299, junos pre-ELS port-mode #294, arista/iosxe_cli VRF harvest #295/#296, same-vendor version echo #297) + parse/render symmetry spot-checks. All findings below were **reproduced** with inline `py` round-trips (no reasoning-only claims except where tagged). What came back CLEAN: #296 (`ip vrf` incl. `route-target both`, full sub-line harvest, round-trip stable), #297 (all four echo codecs idempotent across double-render, real hardware tokens like `FL.10.06.0110` echo correctly, cross-vendor untouched), #294's own change (pre-ELS `port-mode access|trunk` correct in set-form AND block-form), #299's gate conditions (never fires cross-vendor / unknown-version / hostname / 3+ servers). The findings are in the code *surrounding* those fixes.

---

### F1. MAJOR — junos block-form bracket value lists never expanded: silent loss + literal `[` ingested as data

- **File:** `netcanon/migration/codecs/juniper_junos/parse.py:986` (`emit_leaf` inside `_blockform_to_setform`, lines 968–1060)
- **Confidence:** confirmed (reproduced)
- **Failure scenario:** Block-form (`show configuration`) input — one of the two supported junos input shapes — writes every multi-valued leaf as a bracket list. The converter emits the brackets verbatim as one set-line and downstream token-position handlers corrupt or drop:
  - `system { name-server [ 8.8.8.8 1.1.1.1 ]; }` → `intent.dns_servers == ['[']` — a literal `[` becomes the DNS server and both real servers are lost. Cross-vendor render then emits e.g. cisco `ip name-server [` / mikrotik `set servers=[` — invalid config containing garbage.
  - `family ethernet-switching { port-mode trunk; vlan { members [ v10 v20 ]; } }` → `trunk_allowed_vlans == []` (both memberships silently dropped; token[7] == `[`). On an IOS-style target the port renders as bare `switchport mode trunk` = **all VLANs allowed** instead of two.
  - Any other multi-value leaf (`import [ p1 p2 ]`, etc.) same class. `apply-groups [ G1 G2 ]` is special-cased at file-line level and works (verified).
  - The corpus is blind to this: all committed junos fixtures are `.set` files (display-set never emits brackets), so the mesh/CI guard can't see it.
- **Fix:** in `_blockform_to_setform`'s statement reader, when `words` contains a `[ ... ]` group, emit one `set <path> <prefix-words> <value>` line per value (Junos grammar puts the value list only in trailing position). Handles empty `[ ]` as no-op. Add a block-form fixture with bracket lists.

### F2. MAJOR — junos `vlan members <vid>` / `<vid-range>` silently dropped (numeric member tokens never resolve)

- **File:** `netcanon/migration/codecs/juniper_junos/parse.py:543–562` (the `vid_by_vlan_name` resolve post-pass; feeds from `l2_vlan_member_names` collected at :1549–1560)
- **Confidence:** confirmed (reproduced)
- **Failure scenario:** Junos accepts VLAN-ID literals and ranges in `vlan members` (`set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members 100`, `... members 100-110`). The post-pass resolves member tokens ONLY through the name→id map (`vid_by_vlan_name.get(vname)`); numeric and range tokens miss and are "silently dropped (parse tolerance)" — even when the VLAN **is** defined (`set vlans v100 vlan-id 100` + `members 100` still yields `access_vlan=None`).
  End-to-end (reproduced): junos `port-mode access` + `vlan members 100` → cisco_iosxe_cli renders `switchport mode access` with **no** `switchport access vlan` line → port lands in VLAN 1. Trunk + `members 100-110` → bare `switchport mode trunk` → allows all 4094 VLANs instead of 11. Semantic inversion of exactly the kind #294 was fixing — and it bites hardest on the new pre-ELS path (numeric members are common on quick-configured EX access switches).
- **Fix:** in the resolve pass: `if vname.isdigit() and 1 <= int(vname) <= 4094: vid = int(vname)`; for trunks additionally expand `^(\d+)-(\d+)$` ranges. Optionally materialise a `CanonicalVlan` for numerics with no record (mirrors target-side VLAN materialisation).

### F3. MAJOR — mikrotik `gateway=<ip>%<iface>` combined form not split on parse → invalid next-hop tokens on every target

- **File:** `netcanon/migration/codecs/mikrotik_routeros/parse.py:1273–1290` (`_parse_ip_route`); render-side emitter of the same form at `render.py:609–612`
- **Confidence:** confirmed (reproduced)
- **Failure scenario:** RouterOS documents `gateway=192.168.88.1%ether1` (IP pinned to egress interface) and netcanon's own renderer emits it (cross-vendor gateway+interface case, fortigate→mikrotik). But `_parse_ip_route` stores the whole token in `route.gateway` (`interface` stays empty). Reproduced:
  - mikrotik source `add dst-address=0.0.0.0/0 gateway=192.168.88.1%ether1` → cisco render `ip route 0.0.0.0 0.0.0.0 192.168.88.1%ether1` (rejected by IOS), junos render `set routing-options static route 0.0.0.0/0 next-hop 192.168.88.1%ether1` (rejected at commit).
  - The codec's own emission is parse/render asymmetric: fortigate-sourced `gateway=192.168.1.1%port1` reparses to `gateway='192.168.1.1%port1', interface=''`.
  - Committed mikrotik fixtures carry no `%` gateways, so the mesh never exercises this; the `fortigate_cli__mikrotik_routeros.yaml` static_routes prose is also stale (says the codec "does not currently emit" `%`, but render.py:609–612 now does — disposition still correct).
- **Fix:** in `_parse_ip_route`: `gw, sep, egress = gateway.partition('%')`; when `sep`, set `route.gateway = gw`, `route.interface = egress`. (Comma-separated ECMP gateway lists remain a separate, pre-existing limitation.)

### F4. MEDIUM — arista legacy `vrf definition` harvest (#295) reads only the header; inline `rd` / `description` silently dropped

- **File:** `netcanon/migration/codecs/arista_eos/parse.py:574–577` (finditer creates `CanonicalRoutingInstance(name=...)` only)
- **Confidence:** confirmed (reproduced for code behaviour; legacy-grammar prevalence is from EOS ≤4.22 docs where `vrf definition` mode carried `rd`/`description` IOS-style)
- **Failure scenario:** the exact legacy dialect #295 targets keeps the RD *inside* the stanza (pre-4.23 EOS followed the IOS model; RD moved under `router bgp … vrf` only in the modern dialect). Reproduced: `vrf definition RED / description customer red / rd 65000:100` → routing instance `RED` with `route_distinguisher=''`, `description=''`. The router-bgp merge pass only rescues configs that *also* declare `router bgp … vrf RED`. EOS→EOS re-render emits `vrf instance RED` with no rd (silent same-vendor loss); cross-vendor L3VPN targets (junos routing-instances, nxos vrf context) lose the RD. Comparator-invisible on the mesh (committed 4.21/4.22 fixtures carry no VRFs — noted in #295's own commit message).
- **Fix:** harvest the stanza body like cisco_iosxe_cli does (`scan_stanzas` with `rd`/`description`/`route-target` handlers), then let the existing router-bgp pass merge on top (it already merges by name).

### F5. MEDIUM — mikrotik VRRP VIP prefix rewritten to the parent interface's prefix on same-vendor round-trip

- **Files:** `netcanon/migration/codecs/mikrotik_routeros/parse.py:938–941` (prefix stashed in scratch), `parse.py:851–887` (`_materialise_vrrp_groups` drops it), `netcanon/migration/codecs/mikrotik_routeros/render.py:1048–1055` (falls back to parent's first IPv4 prefix unconditionally)
- **Confidence:** confirmed (reproduced)
- **Failure scenario:** `add address=10.0.0.100/28 interface=vrrp10` with parent `ether1` at `10.0.0.1/24` → parse stashes `virtual_ip_prefix=28`, materialise discards it, render emits `add address=10.0.0.100/24 interface=vrrp10`. A same-vendor sanitize changes the VIP's on-wire netmask (/28→/24 alters the connected route on the VRRP interface). Invisible to every comparator because `CanonicalVRRPGroup.virtual_ips` stores bare IPs; the matrix declares the VRRP group surface fully supported, so nothing warns. Same story for `virtual_ip6_prefix`/`/128` fallback (parse.py:998–1002).
- **Fix:** carry the stashed prefix onto the group (add an optional `virtual_ip_prefix`/`virtual_ip6_prefix` int to `CanonicalVRRPGroup` — ship-before-wire pattern applies) and prefer it over the parent-prefix fallback in `_render_vrrp`; or, minimally, declare the prefix loss as a `LossyPath` so the banner fires.

### F6. MINOR — junos render byte-order not a fixpoint: double-pass output drift (settles on pass 2)

- **Files:** `netcanon/migration/codecs/juniper_junos/parse.py` (`lag_state` first-mention insertion order; late stub materialisation for VRF-bound interfaces), `render.py:767–779` (stub emission)
- **Confidence:** confirmed (reproduced on two committed fixtures)
- **Failure scenario:** `render(parse(render(parse(raw)))) != render(parse(raw))` on real captures:
  - `jnprautomate_mnha_vsrx_a_junos.set`: the VRF-bound `lo0.20` stub is materialised late on first parse (appended after `st0.*`) but lands in sorted position on reparse → the stub block moves.
  - `ksator_labmgmt_qfx5100_junos173.set`: canonical `lags` order flips `[ae0, ae1]` → `[ae1, ae0]` on reparse because first-mention order in the rendered text is driven by member-port alphabetical order (`et-*` members of ae1 render before `xe-*` members of ae0).
  Semantic content is identical (verified: name/lag sets equal; o2==o3, so it converges), and the mesh comparator normalises these orders — the cost is pure diff noise for anyone re-sanitizing or version-controlling rendered output, and it violates the "render must preserve tree order" round-trip doctrine.
- **Fix:** normalise at parse end — sort `intent.lags` by name and insert late-materialised stub interfaces through the same ordering used for file-order interfaces (junos parse has no `_sort_interfaces` equivalent; mikrotik's pattern applies).

### F7. MINOR — mikrotik v6 NTP dialect gate self-destructs on second pass (documented in-code; cheap alignment with #297 available)

- **File:** `netcanon/migration/codecs/mikrotik_routeros/render.py:150–154` (documented), gate at :160–165
- **Confidence:** confirmed (reproduced on the committed `routeros_diff_verbose_export.rsc` fixture: render1 `primary-ntp=10.200.0.15` → render2 `servers=10.200.0.15`)
- **Failure scenario:** the renderer emits no `# ... by RouterOS <ver>` header, so a second sanitize sees `source_version==""` and emits the v7 `servers=` form — the very output #299 exists to avoid on a 6.x device. Single-pass (the stated use case) is correct, and the limitation is documented in-code, so this is a design-tail note, not a new bug. But mikrotik is now the only codec whose render *consumes* `source_version` while being the one left out of #297's same-vendor version echo.
- **Fix:** emit `# exported by netcanon -- by RouterOS {tree.source_version}` as the first comment line when `source_vendor=="mikrotik_routeros" and source_version` (parse already reads the header comment via `_VERSION_RE`); makes the dialect gate idempotent and version-preserving like the other four codecs.

### F8. MINOR — five stale `_extract_version` parse docstrings contradict #297/#299 behaviour

- **Files/lines:** `cisco_nxos/parse.py:484–486`, `cisco_iosxr/parse.py:313–314`, `aruba_aoscx/parse.py:418–420`, `vyos/parse.py:145–147`, `mikrotik_routeros/parse.py:238–243`
- **Confidence:** confirmed (read; render code contradicts)
- **Failure scenario:** each still claims "the render path synthesises a fresh banner rather than echoing this / does not echo it, so it is informational only" — false since #297 (four codecs echo it same-vendor) and doubly misleading for mikrotik, where `source_version` now *gates the NTP render dialect* (#299). A maintainer trusting the docstring could conclude version extraction is safe to loosen/remove. Same truth-maintenance class as #300.
- **Fix:** update the five docstrings to "echoed on same-vendor render (#297)" / "gates the v6 NTP dialect (#299)".

---

**Not re-reported (verified per instructions / documented design):** hostname-vlan-name items on the verified-non-bug list; junos render always emitting the modern ELS `interface-mode`/arista `vrf instance`/iosxe `vrf definition` forms for legacy sources (one-way modernisation is the deliberate version-vector scope decision); v6 `server-dns-names=` never emitted (documented in `_all_ip_literals`); NX-OS synthesized `boot nxos bootflash:/nxos.<ver>.bin` footer naming (pre-existing synthesized default). Sanitizer preserving the real OS version post-#297 is the intended behaviour change of that PR.
