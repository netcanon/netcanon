# 05 — Fixture targets

> Concrete fixture sources for the `tests/fixtures/real/cisco_iosxr/`
> corpus.  Each entry: source URL, license, line count, grammar
> coverage profile, sanitization status.

## Required minimum corpus to clear `certified` tier

Per `netcanon/migration/codecs/base.py:142-144`:
```
certainty: certified — round-trip tested against ≥3 real captures.
```

T4 targets **≥7 real captures** (the full batfish/lab-validation
trio) for Phase 1 ship, with the explicit goal of declaring
`certified` at Phase 4 end.  Recommendation: source 1-2 additional
fixtures from non-batfish channels in Phase 4 for genuine
grammar-diversity coverage.

---

## Primary source — batfish/lab-validation (Apache-2.0)

All seven configs below come from a single repo under a single
license (Apache-2.0) — trivial to attribute in `NOTICE.md`.

### Snapshot 1: `cisco_xr_ios_vpnv4` (XR-XE VPNv4 interop)

URL base: `https://github.com/batfish/lab-validation/tree/main/snapshots/cisco_xr_ios_vpnv4/configs/`

| Node | Role | URL | Bytes | Lines | Grammar coverage |
|---|---|---|---|---|---|
| PE1 | IOS-XR PE | `<base>/PE1/show_running-config.txt` | 2,671 | 155 | vrf top-level (3 VRFs), MPLS LDP, BGP RR client + vpnv4, route-policy PASS_ALL, MgmtEth, 4-segment ports |
| PE2 | IOS-XR PE | `<base>/PE2/show_running-config.txt` | 2,251 | ~130 | Same shape as PE1, single VRF (smaller variant) |
| PE3 | IOS-XR PE | `<base>/PE3/show_running-config.txt` | 2,253 | ~130 | Mirror peer to PE1/PE2 |

(CE1-CE4 in this snapshot are **IOS classic** (15.7) — not XR.
They go into `tests/fixtures/real/cisco_iosxe/` instead.  This is
actually useful: the snapshot itself becomes a cross-vendor
migration test case — XR PE alongside IOS-XE CE configs.)

**Raw URLs (copy-paste ready):**
```
https://raw.githubusercontent.com/batfish/lab-validation/main/snapshots/cisco_xr_ios_vpnv4/configs/PE1/show_running-config.txt
https://raw.githubusercontent.com/batfish/lab-validation/main/snapshots/cisco_xr_ios_vpnv4/configs/PE2/show_running-config.txt
https://raw.githubusercontent.com/batfish/lab-validation/main/snapshots/cisco_xr_ios_vpnv4/configs/PE3/show_running-config.txt
```

### Snapshot 2: `iosxr_ebgp_basic`

URL base: `https://github.com/batfish/lab-validation/tree/main/snapshots/iosxr_ebgp_basic/configs/`

| Node | Role | URL | Bytes | Lines | Grammar coverage |
|---|---|---|---|---|---|
| border01 | IOS-XR border router | `<base>/border01/show_running-config.txt` | 2,608 | 153 | eBGP with route-policy + prefix-set, **encapsulation dot1q subinterface** (.35), route-policy with elseif, ASN local-as replace-as, remove-private-AS |
| border02 | IOS-XR border router | `<base>/border02/show_running-config.txt` | 1,901 | ~110 | Smaller peer config; useful for minimal-XR coverage |

(`azure` config is a placeholder cloud router stub — skip.)

**Raw URLs:**
```
https://raw.githubusercontent.com/batfish/lab-validation/main/snapshots/iosxr_ebgp_basic/configs/border01/show_running-config.txt
https://raw.githubusercontent.com/batfish/lab-validation/main/snapshots/iosxr_ebgp_basic/configs/border02/show_running-config.txt
```

### Snapshot 3: `iosxr_ibgp_rr_over_ospf`

URL base: `https://github.com/batfish/lab-validation/tree/main/snapshots/iosxr_ibgp_rr_over_ospf/configs/`

| Node | Role | URL | Bytes | Lines | Grammar coverage |
|---|---|---|---|---|---|
| RR | Route reflector | `<base>/RR/show_running-config.txt` | 2,630 | 137 | **Bundle-Ether** (2 bundles), member channel-group + bundle id N mode active, OSPF underlay, BGP RR with neighbor-group, MTU 9216, additional-paths |
| border01 | iBGP client | `<base>/border01/show_running-config.txt` | 2,899 | 155 | Bundle-Ether members, network statements, aggregate-address with summary-only, additional-paths selection route-policy ADD-PATH |

(border02 in this snapshot is grammatically nearly identical to border01;
optional inclusion for diversity.)

**Raw URLs:**
```
https://raw.githubusercontent.com/batfish/lab-validation/main/snapshots/iosxr_ibgp_rr_over_ospf/configs/RR/show_running-config.txt
https://raw.githubusercontent.com/batfish/lab-validation/main/snapshots/iosxr_ibgp_rr_over_ospf/configs/border01/show_running-config.txt
```

### Total primary corpus

7 fixtures × ~2.5KB each = ~17KB total wire content.  All Apache-2.0
licensed; no sanitization required (the configs use private/reserved
IPv4 blocks and lab device names that contain no identifying
information).

---

## Per-fixture grammar coverage matrix

Used by `tests/fixtures/real/RESULTS.md` for visualisation; mirrors
the per-vendor RESULTS.md format other codecs use.

| Fixture | hostname | iface (4-seg) | Bundle-Ether | MgmtEth | Loopback | vrf | route-policy | static | BGP | OSPF | MPLS-LDP | LAG mode |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `vpnv4_PE1.txt` | ✓ | ✓✓✓✓ | — | ✓ | ✓ | ✓✓✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| `vpnv4_PE2.txt` | ✓ | ✓✓✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| `vpnv4_PE3.txt` | ✓ | ✓✓✓ | — | ✓ | ✓ | ✓ | ✓ | — | ✓ | ✓ | ✓ | — |
| `ebgp_border01.txt` | ✓ | ✓✓✓✓✓ + .35 subif | — | ✓ | ✓✓ | ✓ | ✓✓✓ | — | ✓ | — | — | — |
| `ebgp_border02.txt` | ✓ | ✓✓ | — | ✓ | ✓ | ✓ | ✓✓ | — | ✓ | — | — | — |
| `ibgp_RR.txt` | ✓ | ✓✓✓✓✓ + 2x.subif | ✓✓ | ✓ | ✓✓ | — | ✓✓ | — | ✓ | ✓ | — | active |
| `ibgp_border01.txt` | ✓ | ✓✓✓✓✓ | ✓✓ | ✓ | ✓✓✓ | — | ✓✓ | ✓ | ✓ | ✓ | — | active |

Cells: ✓ = single instance, ✓✓ = multiple instances. `—` = not exercised.

---

## Sanitization needs

The batfish corpus configs use:

- **IPv4 addresses:** RFC 5737 documentation prefixes (192.0.2.0/24,
  198.51.100.0/24, 203.0.113.0/24) and RFC 1918 private prefixes
  (10.0.0.0/8, 192.168.0.0/16).  No public IP addresses.
  **No sanitization needed.**
- **AS numbers:** 65001-65300 (RFC 6996 private ASN range).  **No
  sanitization needed.**
- **Device names:** `PE1`, `PE2`, `border01`, `RR` — generic lab
  identifiers.  **No sanitization needed.**
- **Passwords:** All hashed (Cisco type-5 or type-7).  Example:
  `password 7 030752180500` (a published Cisco type-7 weak-cipher
  hash that decrypts to "cisco").  These are publicly known lab
  credentials.  **Acceptable to include verbatim** with a comment
  in the fixture file noting the source is a public Apache-2.0
  lab snapshot.
- **Domain names:** `test.lab`, `test.com`, `lab.com` — generic.
  **No sanitization needed.**
- **VRF names:** `red`, `blue`, `management`, `AZURE`.  Generic
  except `AZURE` which references a cloud-platform name — kept
  as-is (Microsoft's trademark is fine to reference in lab
  configs; the batfish maintainers have done so under Apache-2.0).
  **No sanitization needed.**

The fixtures can be committed as-is from the batfish source.  Each
file should get a 3-line attribution header:

```
! Source: https://github.com/batfish/lab-validation
! License: Apache-2.0
! Snapshot: cisco_xr_ios_vpnv4/configs/PE1
```

(Prepended to the file content; the parser must tolerate `!`-prefixed
comment lines, which it already does as part of XR's comment syntax.
The probe must still match — banner is on line 1 inside the file, so
prepended comments push it down a line, which doesn't affect the
multiline regex.)

---

## Follow-on fixture sources (Phase 4)

To clear the `certified` bar, T4 should source 1-2 additional
fixtures **beyond batfish** for grammar diversity.  Candidate
sources:

### Cisco DevNet Sandbox (license: free reservation; check ToS for re-distribution)

- `https://devnetsandbox.cisco.com` — IOS-XR ASR 9000 sandbox.
  Live config can be captured via SSH session; sanitization rules
  apply (replace real IPs, MAC addresses, hostnames).
- License concern: Cisco's sandbox usage agreement may restrict
  redistribution.  Recommendation: capture for testing; do not
  commit to the corpus.

### Cisco public documentation example configs

- `https://www.cisco.com/c/en/us/td/docs/iosxr/...` — Cisco's
  public configuration guide examples are often "click-to-copy"
  snippets that fall under Cisco's documentation license (allows
  reuse with attribution).
- License concern: read each document's notice carefully.
  Conservative interpretation: paraphrase rather than verbatim
  re-host.

### NTC-Templates `tests/cisco_xr/` (Apache-2.0)

- `https://github.com/networktocode/ntc-templates/tree/main/tests/cisco_xr`
- License: Apache-2.0 (per `LICENSE` file at repo root)
- Format: Small command-output snippets (NOT full `show running-config`).
  These are designed for testing TextFSM template parsing — they
  exercise `show interfaces`, `show ip bgp summary`, etc. **NOT
  useful as netcanon fixtures** (no full config), but useful as a
  grammar-coverage reference for the implementor.

### NAPALM `tests/unit/...` IOS-XR fixtures (Apache-2.0)

- `https://github.com/napalm-automation/napalm/tree/main/napalm/iosxr`
- License: Apache-2.0
- Format: Some unit-test fixtures include `show running-config`
  snippets (smaller than batfish's; ~500-1000 lines mixed). Worth
  scanning for one or two diverse examples.

### YANG-suite reference configs

- `https://github.com/CiscoDevNet/yang-suite` — Cisco-maintained
  YANG tool examples.  Some include XR config samples.
- License: BSD-3-Clause per `LICENSE`.

### Operator donations (community-driven)

`tests/fixtures/real/WANTED.md` currently lists IOS-XR under
"Tier-D" (line 126).  Once T4 ships Phase 1, the WANTED.md row
should be revised to:

> Cisco IOS-XR | Done — bidirectional codec landed in v0.X.Y. Additional grammar coverage welcomed for: ACL extended, QoS class-maps, IS-IS, L2VPN bridge groups, snmp-server stanza.

This invites operator-contributed fixtures via the existing
`fixtures/real/NOTICE.md` workflow — anonymised real-network XR
captures donated under MIT-equivalent terms.

---

## Recommended initial corpus = 7 fixtures (batfish only)

For Phase 1-3 — ship with **only** the batfish corpus.  The 7
configs collectively exercise:

- 4-segment physical ports ✓
- Bundle-Ether (2 bundles, in iBGP-RR snapshot) ✓
- MgmtEth (every fixture has one) ✓
- Loopback (every fixture has 1-3) ✓
- VRF stanza with RT imports/exports (vpnv4 snapshot, 3 VRFs) ✓
- BGP vpnv4 + RR + neighbor-group templates (vpnv4 + ibgp snapshots) ✓
- route-policy DSL (ebgp + ibgp + vpnv4 snapshots) ✓
- prefix-set (ebgp + ibgp snapshots) ✓
- Static routes via `router static` stanza (vpnv4_PE1 + ibgp_border01) ✓
- MPLS LDP (vpnv4 PE1) ✓
- OSPF (ibgp_RR + ibgp_border01) ✓
- Subinterface + encapsulation dot1q (ebgp_border01 .35) ✓
- LAG mode active (ibgp_RR + ibgp_border01) ✓
- `bundle minimum-active links` (ibgp_RR Bundle-Ether23 + 45) ✓
- `call-home` Tier-3 stanza (every fixture) ✓
- ssh server v2 + vrf (vpnv4 + ebgp_border01) ✓

That's enough Tier-1 + Tier-2 grammar diversity to support
declaring `certainty="best_effort"` at Phase 3.  For
`certainty="certified"` at Phase 4, add 2 more fixtures from any
of the follow-on sources above so the corpus exceeds the
"≥3 real captures" minimum bar by 2× redundancy.

---

## Test-harness mechanical wiring

1. Create directory `tests/fixtures/real/cisco_iosxr/`.
2. Download each fixture URL above; save to that directory with a
   stable filename matching the snapshot+node — e.g.
   `vpnv4_PE1.cfg`, `ibgp_RR.cfg`, `ebgp_border01.cfg`.
3. Add the attribution header (3 `!`-prefixed comment lines) to
   each file.
4. Add row to `_DIR_TO_CODEC_NAME` in
   `tests/unit/migration/test_real_captures.py:80`:
   ```python
   "cisco_iosxr":  "cisco_iosxr",
   ```
5. Run `pytest tests/unit/migration/test_real_captures.py -v -k
   cisco_iosxr` — confirms the parametric tests pick up each fixture.
6. Update `tests/fixtures/real/RESULTS.md` with a coverage table
   for the new codec (matches the existing per-codec sections —
   one row per fixture with the populated-field counts).
