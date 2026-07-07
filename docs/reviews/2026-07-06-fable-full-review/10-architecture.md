# Lens 10 — Architecture & maintainability (netcanon @ v0.5.3 / 8598d74)

**Summary:** The "minimal utilities / no base class" codec architecture is holding up well — registry-wide honesty guards, the vendor-agnostic port-name bridge, `_helpers` consolidation, and universal `detect_input_shape` adoption are all in good shape. Five real seams found: (1) SVI-mounted IPv6 is structurally homeless in the canonical model, producing a **silent, undeclared cross-vendor drop** into aruba_aoss (reproduced); (2) DHCP pools are the one Tier-2 surface with zero sub-field walker vocabulary, so sub-field drops are *undeclarable* — MikroTik silently resets `lease_time` (reproduced); (3) the round-trip semantic-compare normalizer exists in three hand-synced copies that have **already drifted** (reproduced landmine); (4) the same-vendor version-echo gate is copy-pasted 5× with hardcoded vendor literals and an unenforced pairing convention; (5) 11 identical `iter_xpaths` overrides import the shared walker through a sibling vendor codec, and the README teaches the legacy path.

---

### Finding 1 — SVI-mounted IPv6 has no home in the VLAN-centric model → silent undeclared drop (aruba_aoss)

* **Severity:** MAJOR
* **Confidence:** confirmed (two reproductions)
* **Files:**
  * `netcanon/migration/canonical/intent.py:313` — `CanonicalVlan` carries `ipv4_addresses` only; no `ipv6_addresses` twin.
  * `netcanon/migration/codecs/aruba_aoss/parse.py:626-634` — `ipv6 address` lines inside `vlan <N>` stanzas are **silently skipped** ("CanonicalVlan does not carry an ipv6_addresses list today").
  * `netcanon/migration/codecs/aruba_aoss/codec.py:121` — matrix declares `/interfaces/interface/ipv6/address/ip` **supported** (true for physical ports, false for SVIs).
  * `netcanon/migration/canonical/transforms.py:308` (`project_svi_to_vlan`) and `:390` (`synthesize_svis_from_vlan_l3`) — both projections are IPv4-only by construction.
  * `netcanon/migration/canonical/xpath_walker.py:215-238` — the VLAN-SVI mount walks `/vlans/vlan/ipv4/...` only; no v6 twin exists in the vocabulary.

**Failure scenarios (both reproduced):**

1. Cross-vendor: `cisco_iosxe_cli` source with `interface Vlan10` + `ipv6 address 2001:DB8:10::1/64` → migrate to `aruba_aoss`. The SVI is absorbed into the `vlan 10` stanza; the absorption render emits IPv4 only, the IPv6 management address **vanishes from the output**, and `validate_against` flags **zero** ipv6 paths (the interface-mount v6 xpaths classify "supported" because physical-port v6 genuinely round-trips — exact-match xpaths cannot condition on interface kind). Silent loss with a clean report — exactly the class blind-audits 3ec11f3-T0-2 / f92e97a-T0-2 closed **for IPv4**; the v6 twin was never built.
2. Native/same-vendor: AOS-S config with `vlan 10 / ipv6 address 2001:db8:10::1/64` → parse drops the line on the floor (not on any interface, not in `dropped_tier3_sections`), so even an aoss→aoss sanitize re-render loses the address with no trace.

**Why this is architectural:** the model asymmetry (`CanonicalVlan` v4-only) means every VLAN-centric / SVI-absorbing codec must hand-roll or drop v6; the honesty machinery is structurally unable to see it (parse-side drop = never enters the tree; render-side drop = mounted on an xpath declared supported for the physical case). Any future absorption codec inherits the same trap.

**Fix:**
* Near-term (codec-local, honest): in aoss, parse `ipv6 address` in vlan context onto the synthesized `Vlan<N>` `CanonicalInterface` (the mechanism already exists — VRRP groups attach there, parse.py:638-641), and emit `ipv6 address` inside the vlan stanza in the SVI-absorption render (the vendor grammar supports it — that's where parse finds it). Interim honesty until that lands: declare `/interfaces/interface/ipv6/address/ip` **lossy** ("SVI-mounted IPv6 dropped; physical-port IPv6 round-trips") — lossy declarations pass `test_roundtrip_emitted_xpath_not_unsupported` (which checks `unsupported` only).
* Long-term (model symmetry): add `CanonicalVlan.ipv6_addresses`, extend `project_svi_to_vlan` / `synthesize_svis_from_vlan_l3`, and add the `/vlans/vlan/ipv6/...` walker mount mirroring the v4 twins added in f92e97a-T0-2.

---

### Finding 2 — DHCP pools are the one Tier-2 surface with zero sub-field walker vocabulary; MikroTik silently resets lease_time

* **Severity:** MEDIUM
* **Confidence:** confirmed (reproduced)
* **Files:**
  * `netcanon/migration/canonical/xpath_walker.py:295-296` — `for _ in intent.dhcp_servers: yield "/dhcp-servers/pool"` — one opaque xpath for the whole pool.
  * `netcanon/migration/codecs/mikrotik_routeros/render.py:712-728` — `/ip pool` + `/ip dhcp-server network` emission carries gateway/dns/domain but **no `lease-time=`** (RouterOS supports it on `/ip dhcp-server`); parse has no lease grammar either.

**Failure scenario (reproduced):** a `CanonicalDHCPPool` with `lease_time=7200` (2h) rendered to `mikrotik_routeros` and re-parsed comes back with `lease_time=86400` (the schema default, i.e. the operator's lease policy silently changes 2h → 1 day on the target device). `/dhcp-servers/pool` is not declared lossy by mikrotik, so live validation reports the surface fully supported. Crucially, the codec author **cannot** declare the sub-field honestly: `/dhcp-servers/pool/lease-time` is not in the walker's vocabulary, so the declaration would be flagged by `test_lossy_unsupported_nonwalkable_is_documented_synthetic` as a suspicious dead path. The audit sweeps that added sub-field walks to static routes (xpath_walker.py:250-262), SNMPv3, VRRP, routing-instances and VXLAN left DHCP behind — it is now the lone Tier-2 list surface where the "declare what you drop" contract is structurally unsatisfiable.

Sweep result across the fleet (kitchen-sink pool round-trip): arista / iosxe_cli / fortigate / junos / opnsense preserve all four sub-values; aoscx / aoss / iosxr / nxos / vyos drop the whole pool **and honestly declare the base path**; mikrotik is the only silent sub-value drop.

**Fix:** extend `_walk_canonical` with conditional sub-field yields mirroring the static-route pattern — `gateway`, `dns-servers`, `domain-name` when populated, `lease-time` when `!= 86400` — then have mikrotik declare `/dhcp-servers/pool/lease-time` lossy (or wire `lease-time=` into its `/ip dhcp-server` render, which it currently doesn't emit at all). The existing registry honesty guards will then police the rest of the fleet automatically.

---

### Finding 3 — Round-trip semantic-compare normalizer triplicated; the synthetic copy has already drifted from the twin it claims to mirror

* **Severity:** MEDIUM
* **Confidence:** confirmed (code diff + live reproduction of the landmine)
* **Files:**
  * `tests/unit/migration/test_synthetic_kitchen_sink_round_trips.py:280-314` — `_compare` copy #1; docstring says "Mirrors `test_real_captures::_compare` — same invariants apply to both corpora". **False on two counts.**
  * `tests/unit/migration/test_real_captures.py:336-390` — `_compare` copy #2: additionally pops `dropped_tier3_sections` (line 347, with documented rationale) and sorts `routing_instances` by name (line 364, CHANGELOG.md:1903).
  * `tools/run_full_mesh.py:200-259` — copy #3 (`_normalise_records` / `_LIST_ID_KEYS` / `_COSMETIC_LIST_SUBFIELDS`), which "mirrors" #2 but additionally sorts `vxlan_vnis` / `evpn_type5_routes` and strips `is_secondary`.

**Failure scenario (reproduced):** append a Tier-3 stanza the render will not re-emit — e.g. `router ospf 100` — to `tests/fixtures/synthetic/cisco_iosxr/kitchen_sink.cfg`. First parse yields `dropped_tier3_sections=['router bgp 65001', 'router ospf 100']`; re-parse of the rendered output yields `['router bgp 65001']`; the synthetic `_compare` (which does not pop the field) reports "canonical representation changed after parse→render→parse" — a false failure on correct-by-design behaviour (Tier-3 is parse-for-display, never rendered), while the identical content under the real-capture harness passes. The synthetic corpus is green **today only by accident**: the IOS-XR renderer happens to re-emit a `router bgp 65001` header (for VRF RDs) that re-trips the tier3 detector identically on both parses. Symmetrically, a codec whose render legitimately reorders `routing_instances` (the EVPN MAC-VRF case that forced the real-captures sort) false-fails only on the synthetic corpus. Every future divergence has to be discovered as a confusing test failure and fixed in the right one of three places.

**Precedent inside the same file:** `tools/run_full_mesh.py:120-124` consolidated `DIR_TO_CODEC_NAME` into `netcanon/migration/fixture_dirs.py` explicitly because "the two used to keep hand-replicated copies that drifted". The compare vocabulary is the same pattern, one step from the same outcome — and it's the *definition of round-trip stability* for the whole test pyramid.

**Fix:** extract one `canonical_compare_dump(intent, *, cross_vendor: bool = False)` helper (natural home: a `tests/unit/migration/_semantic_compare.py` util or next to `fixture_dirs.py`) encoding the union of the invariants (metadata pops incl. `dropped_tier3_sections`; identity-key sorts incl. `routing_instances`/`vxlan_vnis`/`evpn_type5_routes`; inner-list sorts; `is_secondary` stripping behind the `cross_vendor` flag), and import it from all three sites.

---

### Finding 4 — Same-vendor version-echo gate copy-pasted 5× with hardcoded vendor literals; the pairing convention is unenforced

* **Severity:** MINOR
* **Confidence:** confirmed
* **Files:** `netcanon/migration/codecs/cisco_nxos/render.py:47-52`, `cisco_iosxr/render.py:55-60`, `aruba_aoscx/render.py:61-66`, `vyos/render.py:70-74` (all `_version_token`/`_release_token` — identical logic, different literal + default), plus the fifth instance `mikrotik_routeros/render.py:160-165` (`_render_ntp_client`'s RouterOS-6 dialect gate, v0.5.3).

**Failure scenario:** each copy gates on `tree.source_vendor == "<literal>"`, where the literal must equal what *this codec's parse* stamps — which is `capabilities.vendor_id`, **not** the registry name (`cisco_iosxe_cli` stamps `"cisco_iosxe"`, `fortigate_cli` stamps `"fortigate"`). Nothing enforces the pair: no shared helper, no registry-wide test asserting `parse(sample).source_vendor == capabilities.vendor_id`. The next copy — iosxe_cli/fortigate are the natural candidates for the same-vendor-echo treatment, and this pattern has grown by one codec per release since v0.5.2 — that uses the registry name never fires; because `source_version` is metadata-excluded from every comparator, no round-trip test catches it, only a hand-written per-codec echo test (which must also be copied). The stated purpose (don't relabel a device's config with a synthetic constant on sanitize) silently fails.

**Fix:** one shared helper in `netcanon/migration/codecs/_helpers.py` — `def same_vendor_version(tree, *, vendor_id: str, default: str) -> str` — replacing the four `_version_token` bodies and the mikrotik gate's first two conjuncts; optionally add a registry-wide test pinning `parse(codec.sample_input).source_vendor == codec.capabilities.vendor_id` so the stamp convention itself is guarded.

---

### Finding 5 — 11 identical `iter_xpaths` overrides import the shared walker through a sibling vendor codec; the README teaches the legacy path

* **Severity:** MINOR
* **Confidence:** confirmed
* **Files:**
  * `netcanon/migration/canonical/xpath_walker.py:10-13` — walker was relocated here from `cisco_iosxe_cli/codec.py` precisely so it "no longer lives inside a single vendor codec".
  * Yet 10 codecs still lazy-import it via the vendor path — e.g. `aruba_aoss/codec.py:466`, `vyos/codec.py:630`, `cisco_nxos/codec.py:618`, `cisco_iosxe/codec.py:978`, `juniper_junos/codec.py:417`, etc. (`from ..cisco_iosxe_cli.codec import _walk_canonical`), each wrapped in the same 4-line `isinstance(tree, CanonicalIntent)` boilerplate.
  * `netcanon/migration/codecs/README.md:405` — the authorship cookbook still instructs: "Use the shared `_walk_canonical` from `cisco_iosxe_cli/codec.py`".

**Failure scenario:** the deprecated cross-vendor import edge is self-perpetuating — `vyos`, the newest codec, copied it; codec #13 will too, because the README says to. Every codec's capability classification thereby imports a full sibling vendor codec package (`cisco_iosxe_cli` codec + its 1,778-line parse + 862-line render) as a hidden dependency; any future refactor of the iosxe_cli package (e.g. completing the parse/render split by moving module-level symbols) must preserve a re-export whose consumers are 10 other vendors' capability paths, or every codec's `iter_xpaths` breaks at once.

**Fix:** add the canonical branch to `CodecBase.iter_xpaths` itself (`if isinstance(tree, CanonicalIntent): yield from _walk_canonical(tree)` via a runtime import from `...canonical.xpath_walker` — no import cycle; the flat-dict fallback for `mock` stays), delete the 11 identical overrides, keep the `cisco_iosxe_cli.codec._walk_canonical` re-export for third-party compat, and update README.md:405 to point at `canonical/xpath_walker.py`.

---

## Non-findings verified in passing (do not re-hunt)

* `_helpers.py` consolidation is clean — the one remaining private `_prefix_to_mask` in `fortigate_cli/parse.py:81` is a documented thin shim over the shared helper, not drift; `arista_eos._expand_vlan_list` is a documented deliberate near-twin injected into `merge_trunk_allowed`.
* `detect_input_shape` is adopted by all 10 CLI codecs (parse + probe) — full coverage despite the module docstring naming only the original six.
* Registration is anchored: pkgutil auto-discovery swallows broken codec imports (log-only), but the roster is transitively pinned by `test_every_synthetic_dir_maps_to_a_registered_codec`, `test_real_captures::test_every_mapped_codec_is_registered` (static `_DIR_TO_CODEC_NAME`), and explicit import lists in three test files that hard-fail at collection.
* The port-name orchestrator (`canonical/port_names.py`) is genuinely zero-edit for new codecs — the cleanest seam in the codebase.
* Registry-wide honesty guards (`test_registry_capability_honesty.py`) enforce both reverse-parity directions plus drop-declaration for naming-independent fields; the guard-the-guard tests cover new `CanonicalIntent` fields.
