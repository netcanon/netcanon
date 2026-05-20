# 06 — Fixture targets

For each codec that currently has no VRRP-exercising fixture in
`tests/fixtures/real/`, this file lists concrete public URLs from
which a permissively-licensed fixture can be sourced or synthesised.
Each entry includes sanitization notes.

The `tests/fixtures/real/WANTED.md` already includes a VRRP section
(lines 144-166) — this document aligns with it and adds source-URL
detail.

---

## Status of corpus today (post — this design pass)

Confirmed via `grep -rln -i "vrrp\|virtual-address\|virtual-gateway\|carp" tests/fixtures/`:

| Codec | Existing fixture | Form | Lines |
|---|---|---|---|
| cisco_iosxe | `tests/fixtures/real/cisco_iosxe/batfish_iosxe_basic_vrrp.txt` | classic VRRP | 85-86 |
| junos | `tests/fixtures/real/junos/ksator_labmgmt_qfx10k2_junos173.set` | anycast (virtual-gateway-address) | 95-128 |
| junos | `tests/fixtures/real/junos/batfish_evpntype5_router1_junos2541.set` | virtual-address (less coverage) | grep found nothing strong |
| arista_eos | `tests/fixtures/real/arista_eos/batfish_labval_dc1_leaf2a_eos4230.txt` | VARP (`ip address virtual` + global `ip virtual-router mac-address`) | 202-290 |
| arista_eos | `tests/fixtures/real/arista_eos/batfish_eos_evpn_vlan_based_leaf.txt` | suspected VARP, needs verification | (in match list) |
| fortigate | `tests/fixtures/real/fortigate/user_contrib_fg100e_fos7213.conf` | only `set vrrp-virtual-mac disable` (toggle, no real VRRP block) | n/a (does NOT exercise `config vrrp / edit N`) |
| aruba_aoss | — | none | n/a |
| mikrotik | — | none | n/a |
| opnsense | `tests/fixtures/real/opnsense/user_contrib_supergate_opn25.xml` | empty `<vip/>` envelope (line 4527) — NO active VIPs | NO active CARP |

**Verdict:** 3 codecs (cisco_iosxe / arista_eos / junos) have real
VRRP-exercising fixtures already. 5 codecs (aruba_aoss, fortigate_cli,
mikrotik_routeros, opnsense, cisco_iosxe NETCONF) need new fixtures —
fortigate has a partial fixture without an active VRRP block; opnsense
has a CARP envelope without active VIPs.

---

## Specific check: batfish/lab-validation VRRP snapshots

Probed at design time via
`curl -s https://api.github.com/repos/batfish/lab-validation/contents/snapshots`:

| Snapshot directory | Vendor | Useful for |
|---|---|---|
| `snapshots/ios_basic_vrrp/configs/{BR1,BR2,LAN-RTR,WAN-RTR}` | Cisco IOS classic (15.7) | **Source of the existing `batfish_iosxe_basic_vrrp.txt`** — already in corpus |
| `snapshots/nxos_hsrp/configs/{nxos1,nxos2}` | Cisco NX-OS | Tier-D (NX-OS codec doesn't ship yet — would unlock the codec when it does) |
| `snapshots/fortios_first_basic/configs/{d1_inside,d2_fw,d3_outside}` | FortiGate (FortiOS unspecified) | Maybe — but the snapshot is firewall-policy-focused; manual inspection needed for VRRP content |

**Definitive answer to "do batfish snapshots have FortiGate / MikroTik /
Aruba / OPNsense VRRP fixtures?":** NO. Batfish lab-validation
holds zero FortiGate-with-VRRP, zero MikroTik (it's not a batfish-
supported parser), zero Aruba (not supported), and zero OPNsense
(not supported). The `fortios_first_basic` snapshot exists but
covers firewall policies only.

---

## Per-codec fixture targets

### A. aruba_aoss (NEW FIXTURE REQUIRED)

Aruba AOS-S VRRP requires a `router vrrp` enabler + a nested
`ip vrrp vrid N` block inside a `vlan N` stanza. AOS-S is a
commercial campus switch family; public lab captures are sparse.

**Source candidates:**

1. **HPE community forums** (`community.hpe.com`) — operators
   regularly paste sanitized snippets when troubleshooting.
   License is per-post; quoting fair-use is acceptable but the
   poster must explicitly permit reuse. **License caveat: not
   permissive by default.**

2. **NTC-templates** (`networktocode/ntc-templates`,
   Apache-2.0) — has parser fixtures under
   `tests/aruba_aoscx/` and `tests/hp_procurve/` (the
   procurve family is the AOS-S predecessor; grammar is
   compatible). Specifically:
   * <https://github.com/networktocode/ntc-templates/tree/master/tests/hp_procurve/show_running-config>
     — sample running-configs.
   Search those for `vrrp`. NTC-templates is Apache-2.0 — fully
   permissive.

3. **NAPALM aruba_os tests** —
   <https://github.com/napalm-automation-community/napalm-aruba-cx>
   has fixture configs under `tests/`. AOS-CX, not AOS-S, but
   grammar overlap is sufficient for VRRP. License: Apache-2.0.

4. **HPE / Aruba Validated Reference Design (VRD) PDFs.** PDFs
   contain CLI block examples in figure boxes. Examples can be
   typed up (NOT screenshotted) as synthetic fixtures with
   provenance citing the VRD title + revision. **License caveat:
   PDFs are copyrighted; CLI examples within are typically
   reusable as facts, but transcribe rather than copy verbatim.**

5. **Operator-contributed.** Open a Fixture Submission issue
   targeting the Aruba 2930F class (already in corpus per
   `WANTED.md`). High-value contributor donation.

**Recommended approach:** synthesize a minimal fixture from the
AOS-S 16.10 Advanced Traffic Management Guide's VRRP example
(public document on `arubanetworks.com/techdocs`). Document as
"synthesized from public vendor documentation; representative
two-VLAN HA pair".

**Sanitization notes:**
* Hostnames → `LAB-CORE-A` / `LAB-CORE-B`.
* VLAN IDs from documentation are usually 10/20/100 — keep.
* IPs → RFC 5737 documentation ranges
  (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24).
* Passwords → `REDACTED` placeholder.

Place at `tests/fixtures/real/aruba_aoss/aruba_atmg_vrrp_pair_aoscli.txt`.

### B. fortigate_cli (NEW FIXTURE REQUIRED — or extend existing)

FortiGate exists in corpus (`user_contrib_fg100e_fos7213.conf`)
but the file has only `set vrrp-virtual-mac disable` toggles, not
an actual `config vrrp / edit N` block. Two options:

**Option B1 — supplement the existing fixture.** Ask the original
contributor (line in `NOTICE.md`) to provide a sibling capture
with active VRRP, OR append a synthetic VRRP block to the
existing fixture.

**Option B2 — new fixture.** Source candidates:

1. **FortiOS CLI Reference 7.2 / 7.4** — public PDFs on
   `docs.fortinet.com`. VRRP examples are in the
   `config system interface` → `config vrrp` section. Synthesize
   per the published grammar.
2. **NTC-templates fortinet tests** —
   <https://github.com/networktocode/ntc-templates/tree/master/tests/fortinet_fortios>
   has running-config fixtures. Search for `vrrp` content.
   License: Apache-2.0.
3. **KevinGuenay/fortinet-resources** — referenced in the existing
   FortiGate parser comments
   ([parse.py:381-383](../../../netcanon/migration/codecs/fortigate_cli/parse.py)).
   Check the same repo for VRRP-bearing captures: the comment cites
   `FGT-70G-BRANCH.conf` — adjacent files may have HA configs.
   <https://github.com/KevinGuenay/fortinet-resources>.
4. **netbox-community/devicetype-library** has sample configs
   referenced in vendor-validated YAMLs; CC-BY-4.0.

**Recommended:** synthesize from FortiOS 7.2 CLI Reference's
`config router vrrp` example.

**Sanitization notes:**
* Drop `set password ENC <blob>` blocks entirely (or replace
  with deterministic placeholder).
* Reset `set uuid` values (FortiGate generates unique UUIDs per
  object).
* Strip license / serial / wireless-controller stanzas.
* RFC 5737 IPs.

Place at `tests/fixtures/real/fortigate/synth_fortios_7213_basic_vrrp.conf`.

### C. mikrotik_routeros (NEW FIXTURE REQUIRED)

RouterOS VRRP exists since RouterOS 3.x; modern grammar (v6.x and
v7.x) uses `/interface vrrp` + `/ip address`. Source candidates:

1. **MikroTik wiki "Manual:Interface/VRRP"** —
   <https://help.mikrotik.com/docs/spaces/ROS/pages/24805458/VRRP>.
   Public CC-BY-SA documentation; the grammar examples are
   directly transcribeable into a synthetic fixture.

2. **NTC-templates mikrotik_routeros tests** —
   <https://github.com/networktocode/ntc-templates/tree/master/tests/mikrotik_routeros>.
   License Apache-2.0; check for VRRP-bearing samples.

3. **NAPALM RouterOS community module** —
   <https://github.com/napalm-automation-community/napalm-ros>
   may have fixtures.

4. **RouterOS lab tutorials** on GitHub (search
   "site:github.com mikrotik vrrp .rsc"). Filter by Apache-2.0 /
   MIT / CC0 licenses.

5. **Operator-contributed.** RouterOS configs are short and
   often sanitization-free at the L3 redundancy layer.

**Recommended:** synthesize a 2-router pair from the MikroTik
wiki's `Manual:Interface/VRRP` reference example. Two `.rsc`
files (`lab_router_a.rsc`, `lab_router_b.rsc`) make a complete
HA pair.

**Sanitization notes:**
* Drop `/system identity set name=...` lines if hostnames have
  PII; replace with `LAB-RTR-A` / `LAB-RTR-B`.
* Replace `/system license` blocks.
* Strip `/system clock`, `/snmp set` secrets, `/user` password
  hashes.
* RFC 5737 IPs.

Place at `tests/fixtures/real/mikrotik/synth_routeros718_basic_vrrp.rsc`.

### D. opnsense (NEW FIXTURE REQUIRED — HA-deployment capture)

Existing `user_contrib_supergate_opn25.xml` has an EMPTY
`<vip/>` envelope (line 4527-4531). For CARP exercise, need a
config from an OPNsense device participating in a CARP HA pair.

**Source candidates:**

1. **OPNsense documentation HA tutorial** —
   <https://docs.opnsense.org/manual/hacarp.html> has a
   step-by-step CARP setup with full `<virtualip>` XML examples.
   License: CC-BY-NC-SA-4.0. Limits commercial use but allows
   transcription into a synthetic fixture (with provenance).

2. **OPNsense forum HA threads** —
   <https://forum.opnsense.org/index.php?board=18.0> (HA section).
   Operators frequently paste `<vip>` blocks. License per-post;
   permission required.

3. **GitHub `opnsense/` org** has community plugins
   exercising the API; their CI may include CARP-bearing
   fixtures.

4. **pfSense documentation** —
   <https://docs.netgate.com/pfsense/en/latest/highavailability/carp.html>.
   pfSense `config.xml` and OPNsense `config.xml` share heritage;
   pfSense CARP examples translate directly to OPNsense form.
   License: GFDL / CC-BY-SA. Permissive for transcription.

**Recommended:** synthesize from the OPNsense HA tutorial — two
config.xml files for a primary + secondary, both with a single
CARP VHID.

**Sanitization notes:**
* Replace all `<password>` bcrypt hashes (system + CARP) with
  `$2y$11$RedactedRedactedRedactedRedactedRedactedRedacted` or
  similar deterministic placeholder.
* Strip `<crypto-key>`, `<ipsec>` PSK blocks (Tier 3 anyway).
* Replace WAN public IP with RFC 5737 `203.0.113.X`.
* Clear `<menu>` plugin state.
* Replace `<system><dnsserver>` operator's actual DNS with
  TEST-NET DNS literals (`192.0.2.53`).

Place at `tests/fixtures/real/opnsense/synth_opnsense_25_ha_carp_primary.xml`
and `..._secondary.xml`.

### E. cisco_iosxe (NETCONF stub) — NO FIXTURE NEEDED

Codec stays `unsupported`. The cross-mesh audit picks it up from
the matrix declaration. If a real OpenConfig NETCONF dump
containing `openconfig-if-ip:vrrp` ever surfaces in the corpus,
the codec wiring can land alongside.

**Note:** OpenConfig public YANG models repo (`openconfig/public`)
has the `openconfig-if-ip.yang` augmentation
(<https://github.com/openconfig/public/blob/master/release/models/interfaces/openconfig-if-ip.yang>)
which defines the `vrrp` grouping. A sample NETCONF dump exercising
this could be sourced from openconfig-network-emulator or vendor
SDKs, but landing the NETCONF wire-up is out of v0.2.0 scope.

---

## Cross-codec extension fixtures (high-value-but-optional)

These would exercise edge cases beyond the basic-VRRP per-codec
fixtures, and are nice-to-have for `v0.2.0` certified status.

| Fixture | Source | Coverage |
|---|---|---|
| `cisco_iosxe/synth_iosxe1712_vrrp_v6_track.txt` | synthesize | VRRPv3 IPv6 + track-object decrement |
| `arista_eos/synth_eos4_30_classic_vrrp.txt` | synthesize from EOS User Manual | classic VRRP (the existing fixture is VARP-only) |
| `junos/synth_junos_classic_vrrp_md5_auth.set` | synthesize | classic `vrrp-group` with MD5 authentication-key (the existing fixture is anycast only) |
| `aruba_aoss/synth_aoss_2930_track_id.txt` | synthesize | `track-id` + top-level `track <id> interface` lookup |
| `fortigate/synth_fos74_vrrp_v6.conf` | FortiOS 7.4 CLI Reference | `set vrip6` and `set version 3` |
| `mikrotik/synth_routeros7_vrrp_v3_ipv6.rsc` | MikroTik wiki | `v3-protocol=ipv6` + `/ipv6 address` |
| `opnsense/synth_opnsense_25_carp_v6.xml` | OPNsense docs | IPv6 VIP |

---

## Sanitization automation

The repository has a `netcanon sanitize` CLI that handles standard
masking (real IPs → RFC 5737, password hashes → redacted markers,
serial numbers → placeholders). Run it on every new fixture before
landing.

```bash
# Sketch only — actual command run during fixture-landing PRs.
netcanon sanitize \
    --codec aruba_aoss \
    --output tests/fixtures/real/aruba_aoss/aruba_atmg_vrrp_pair_aoscli.txt \
    raw-input.txt
```

After sanitization, every fixture file gets a row in
`tests/fixtures/real/NOTICE.md` declaring:

* origin URL (or "synthesized from <doc>")
* OS version
* license
* what it exercises (the new "VRRP / CARP" tag)

Without the NOTICE row, the fixture cannot land per repo policy.

---

## License compatibility summary

| Source class | License | Acceptable for fixture? |
|---|---|---|
| batfish/lab-validation snapshots | Apache-2.0 | YES (already used) |
| NTC-templates tests | Apache-2.0 | YES |
| napalm-automation tests | Apache-2.0 | YES |
| MikroTik wiki examples | CC-BY-SA-4.0 | YES (cite, paraphrase) |
| OPNsense docs HA tutorial | CC-BY-NC-SA-4.0 | YES for synthesis (cite + non-commercial use; netcanon project is OSS) |
| Cisco IOS Configuration Guide | proprietary | LIMITED — re-creation as synthetic from public documentation only, not direct copy |
| Aruba VRD PDFs | proprietary | LIMITED — re-creation only, not direct copy |
| FortiGate CLI Reference | proprietary | LIMITED — re-creation only |
| Operator-contributed (issue submissions) | per-issue declared | YES if contributor declares Apache-2.0 / MIT / CC0 |
| HPE forum posts | per-post | NO unless poster explicitly waives |

---

## Order of fixture landing

Match the implementation order in
[`README.md` § "Implementation order recommendation"](README.md):

1. (already done) cisco_iosxe VRRP — `batfish_iosxe_basic_vrrp.txt`
2. (already done) junos anycast — `ksator_labmgmt_qfx10k2_junos173.set`
3. (already done) arista_eos VARP — `batfish_labval_dc1_leaf2a_eos4230.txt`
4. junos classic VRRP — `synth_junos_classic_vrrp_md5_auth.set` (new)
5. aruba_aoss — `aruba_atmg_vrrp_pair_aoscli.txt` (new)
6. fortigate — `synth_fortios_7213_basic_vrrp.conf` (new)
7. mikrotik — `synth_routeros718_basic_vrrp.rsc` (new)
8. opnsense — `synth_opnsense_25_ha_carp_primary.xml` + secondary (new)

Per-codec PRs ship the fixture in the SAME commit as the parse +
render wire-up. Real-fixture round-trip tests
([`04-test-plan.md` § D](04-test-plan.md)) reference these by
path; fixtures landing in a separate commit would cause CI breakage.
