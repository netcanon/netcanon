# Cisco IOS-XR — fixture catalogue (2015+)

> **Tier**: Tier-D (codec design complete; implementation queued for
> v0.3.0+, deferred until after Cisco NX-OS lands).
> **Codec**: not yet implemented; design at
> [`docs/v0.2.0-planning/04-iosxr-codec/`](../v0.2.0-planning/04-iosxr-codec/).
> **Existing corpus**: 0 fixtures (no `tests/fixtures/real/cisco_iosxr/`
> directory yet).
> **Audience note**: IOS-XR is a service-provider / hyperscaler PoP /
> large-ISP NOS — the operator population is narrower than NX-OS by
> 1-2 orders of magnitude.  Most Fortune-500 networks never touch
> IOS-XR; SP-routing teams at AT&T, Verizon, Comcast/Xfinity,
> Lumen, Telia, Telefónica, DT, NTT, Tata are the bullseye audience.
> A corpus of 7-12 fixtures gets us further per fixture than NX-OS
> because the operator base is denser per device.

---

## Version timeline

IOS-XR ships from `git.cisco.com/ios-xr` (internal) and tags
itself in the wire-form header as `!! IOS XR Configuration <version>`
followed by major.minor.maintenance — e.g. `!! IOS XR Configuration
6.6.2`.  **In 2024 Cisco rebranded the 7.10+ train to a YY.x scheme**
(7.10 → 24.1, 7.11 → 24.2, etc.) — the wire-form header on a 24.1
device reads `!! IOS XR Configuration 24.1.1`.  The codec probe must
accept both forms.

| Version family | Release window | EoS status | In corpus | Platforms | Pull priority |
|---|---|---|---|---|---|
| **5.x classic** | 2014-2018 (5.0 → 5.3) | End-of-Sale 2020 | 0 | CRS-1/3, ASR 9000 G1/G2, c12000 | Low (legacy; grammar diverges from modular train at e.g. `interface Bundle-Ether` introduction) |
| **6.0-6.2** | 2016-2018 | End-of-Sale | 0 | ASR 9000 G3, NCS 5500 introduction | Medium (still in production at conservative SPs; batfish snapshots target 6.2.2) |
| **6.3-6.6** | 2018-2020 | End-of-Sale | 0 | ASR 9000, NCS 540 / 560 / 5500 / 5700 | **High (batfish covers 6.6.2 PEs — primary seed)** |
| **7.0-7.4** | 2019-2022 | EoSWMaintenance (varies) | 0 | ASR 9000, NCS 540 / 560 / 5500 / 5700 / 8000 | **High (most operator-deployed band today)** |
| **7.5-7.9** | 2022-2023 | Active | 0 | NCS 540 / 560 / 5500 / 8000 (CRS sunset) | High (current production train) |
| **7.10+ / 24.x** (rebrand) | 2024+ — 7.10 became 24.1.1 | Active (current GA) | 0 | NCS 540 / 560 / 5500 / 5700 / 8000 (modern only) | High (forward-looking — operator pulls happen here) |

> **The 7.10 → 24.x rebrand.**  In 2024 Cisco realigned the IOS-XR
> version-scheme to track calendar year + release-within-year, the
> way Junos already does (`24.4R1`).  The wire-form header
> still emits `!! IOS XR Configuration X.Y.Z` — the codec doesn't
> need to parse the version string itself, just the banner.  But
> when sourcing fixtures, fixture-name conventions like `xr24_PE1.cfg`
> may surface in donations — keep both `xr7_*` and `xr24_*` variants
> acceptable to the test-harness loader.

---

## Pull-target inventory

This section enumerates source-classes per the
[`00-source-analysis.md`](00-source-analysis.md) taxonomy.

### 24.x / 7.10+ (current train)

#### GitHub repositories

* **`ios-xr/xrd-tools`**
  ([`github.com/ios-xr/xrd-tools`](https://github.com/ios-xr/xrd-tools))
  — **Apache-2.0, Cisco-maintained.**  `samples/xr_compose_topos/`
  contains 5 multi-node topologies with full XR startup configs as
  separate `.cfg` files:
  * `simple-bgp/` — 2 nodes (`xrd-1_xrconf.cfg`, `xrd-2_xrconf.cfg`)
    ~50 lines each — minimal BGP coverage, useful as smoke fixture.
  * `ospf-bgp-rr/` — RR + clients topology, OSPF underlay.
  * `isis-ipfrr/` — IS-IS underlay with IP fast-reroute.  **High
    value — fills batfish's IS-IS gap.**
  * `segment-routing/` — 8-node topology (`xrd-1-startup.cfg` …
    `xrd-8-startup.cfg`) with SR-MPLS, VRFs, route-policy 100,
    extcommunity-set, segment-routing global-block, traffic-eng,
    PCE candidate-paths, on-demand-color, ISIS flex-algo.  **Highest
    grammar-coverage single donor available — fills batfish's
    segment-routing + flex-algo + PCE gap entirely.**
  * `srv6-l3vpn/` — SRv6 L3VPN — covers the v7+ SRv6 grammar surface
    (`segment-routing srv6` stanza) not in batfish at all.
  Grammar coverage: ISIS L1-L2 with flex-algo (128, 129), SR-MPLS
  global-block / traffic-eng / candidate-paths / on-demand color
  policies, BGP with neighbor-groups + vpnv4 + link-state AF,
  route-policy with `set extcommunity color`, VRF top-level with
  RT import/export, MgmtEth + 4-segment ports.
  Sanitisation: none needed — labs use private IPv4 + RFC private ASNs.
  **Recommended next pull-target after batfish.**

* **`YangModels/yang/vendor/cisco/xr/<version>/`**
  ([`github.com/YangModels/yang/tree/main/vendor/cisco/xr`](https://github.com/YangModels/yang/tree/main/vendor/cisco/xr))
  — **No license file at the per-vendor level; YANG models published
  by Cisco for OpenConfig interoperability.**  Per-version directories:
  `601/`, `611/`, `612/`, `621/`, `622/`, `631/`, `632/`, `641/`,
  `642/`, `643/`, `651/`, `652/`, `653/`, `661/`, `662/`, `701/`,
  `702/`, `711/`, `721/`, `722/`, `731/`, `741/`, `751/`, `761/`,
  `771/`, `781/`, `791/`.  **Not running-configs** — these are
  YANG schema files.  Use as a Tier-3 reference for "what config
  surfaces exist per version" but **not** as direct fixture pulls.

* **`CiscoDevNet/openconfig-getting-started`**
  ([`github.com/CiscoDevNet/openconfig-getting-started`](https://github.com/CiscoDevNet/openconfig-getting-started))
  — Cisco-maintained, license per LICENSE file (likely Apache-2.0
  or BSD-3; verify before pull).  `models/policy/` and `models/bgp/`
  directories contain XR CLI + OpenConfig JSON/XML pairs as
  worked examples.  CLI snippets are **partial-stanza** (route-policy
  + BGP neighbor block, not full router configs) — use as
  grammar-coverage reference, not as standalone fixtures.

* **`ansible-collections/cisco.iosxr`**
  ([`github.com/ansible-collections/cisco.iosxr`](https://github.com/ansible-collections/cisco.iosxr))
  — **GPL-3.0** (Ansible collection-standard).  Per
  [`BUG_REPORTING.md`](../../BUG_REPORTING.md)'s
  permissive-license-only stance, **GPL-3.0 is incompatible** with
  the netcanon fixture corpus' permissive-license policy.  **Do
  not pull.**  Mention only for awareness — operators familiar with
  the Ansible collection's test fixtures should know they're
  GPL-3 and need an Apache/BSD/MIT alternative.

* **`napalm-automation/napalm/napalm/iosxr/`**
  ([`github.com/napalm-automation/napalm/tree/develop/napalm/iosxr`](https://github.com/napalm-automation/napalm/tree/develop/napalm/iosxr))
  — **Apache-2.0.**  `templates/` directory has ~12 Jinja2 templates
  for `set_users`, `set_hostname`, `set_ntp_servers`, `snmp_config`,
  etc.  These are **not full configs** (single-feature templates)
  but they faithfully render XR's wire form for the surfaces they
  cover.  Use as grammar-corner-case reference (e.g. confirming
  `username X / group root-lr / password 7 <hash>` shape).

* **`ters-golemi/IOS-XR-Segment-Routing`**
  ([`github.com/ters-golemi/IOS-XR-Segment-Routing`](https://github.com/ters-golemi/IOS-XR-Segment-Routing))
  — **No license declared** ("provided as-is for educational and
  deployment purposes").  Contains 3 template configs
  (`core-router-template.txt`, `aggregation-router-template.txt`,
  `edge-router-template.txt`) targeting 7.3+.  **Do not pull
  directly** — no explicit license.  Useful as inspiration / grammar
  reference only.

#### Cisco DevNet sandboxes

* **IOS XR Programmability Always-On Sandbox**
  ([`developer.cisco.com/site/ios-xr/`](https://developer.cisco.com/site/ios-xr/))
  — 24x7 free, no reservation.  Live XR-running router accessible via
  SSH + NETCONF.  `show running-config` captures possible.  **License
  concern:** Cisco sandbox ToS may restrict redistribution of captured
  configs.  Conservative interpretation: **capture for testing,
  do not commit verbatim**.  Paraphrased / re-synthesised configs are
  fine.

* **XRd Sandbox** (reservable) — containerised XR; same ToS concerns
  apply.  Worth using to verify a candidate fixture loads on a real
  XR before committing.

#### Vendor docs / lab guides

* **xrdocs.io** ([`xrdocs.io`](https://xrdocs.io/)) — Cisco TME-run
  IOS-XR knowledge base.  Heavy on **Converged SDN Transport**,
  **Peering Fabric**, **Metro Design**, **Core Fabric** implementation
  guides — each containing 50-500 line config snippets.  **License**:
  not explicitly stated; treat as fair-use excerpts.  Use as
  grammar-coverage reference for SRv6, MPLS-LDP, MPLS-TE, and
  segment-routing-PCE flows.  **Do not pull verbatim**; rewrite as
  synthetic fixtures.  Especially valuable URLs:
  * `xrdocs.io/design/blogs/latest-converged-sdn-transport-ig` —
    full reference deployment configs.
  * `xrdocs.io/design/blogs/latest-peering-fabric-hld` — large-scale
    peering edge configs (route-policy + prefix-set + community-set
    Tier-3 grammar in heavy use).
  * `xrdocs.io/ncs5500/tutorials/bgp-evpn-configuration-ncs-5500-part-1`
    — BGP EVPN configs (cross-vendor: EVPN is the IOS-XR ↔ Arista
    EOS migration pattern).
  * `xrdocs.io/multicast/tutorials/tree-sid-demo` — Tree-SID
    multicast on XR.

* **Cisco.com configuration guides** —
  `www.cisco.com/c/en/us/td/docs/routers/asr9000/software/asr9k-r<X.Y>/`
  and `www.cisco.com/c/en/us/td/docs/routers/asr9000/software/24xx/`.
  Click-to-copy code samples within each guide.  License:
  vendor-defined; example reuse with attribution generally
  acceptable.  Use as grammar-corner-case reference (e.g. the
  Implementing Routing Policy guide is the canonical RPL reference).
  **Conservative pull-policy: paraphrase, don't verbatim re-host.**

#### Forum / community (Tier-2 — operator-share precedent)

* **Cisco Community — Service Provider Knowledge Base**
  ([`community.cisco.com/.../service-providers-knowledge-base`](https://community.cisco.com/))
  — Cisco-maintained articles such as "ASR9000/XR: Understanding
  and using RPL (Route Policy Language)" (TA-p/3117050) and "BGP
  Basic Configuration On IOS XR - IBGP And EBGP" (TA-p/3145638).
  These are vendor-author articles, not user-paste threads —
  treat as vendor doc, not as forum-share.  Heavy sanitisation
  not required.  Use as grammar reference.

* **Cisco Community IOS-XR user threads** —
  `community.cisco.com/t5/forums/searchpage/tab/message?q=ios-xr+running-config`
  — user-paste threads (operator's actual router output).
  Forum-share precedent applies (per
  [`NOTICE.md`](../../tests/fixtures/real/NOTICE.md) the
  forum-share pattern is established by HPE Community fixtures).
  **Heavy sanitisation needed** — hostnames + IPs + AS numbers
  in real-world threads may be live.

#### Reddit + Stack Exchange

* `r/networking` and `r/cisco` — occasional XR threads, especially
  around SR-MPLS rollout, EVPN config, ASR 9000 + NCS 5500 hardware.
  Mostly **discovery-only** (use for fixture inspiration, draft
  synthetic).

* **Network Engineering Stack Exchange** — CC-BY-SA-licensed.
  Search `[cisco-ios-xr]` tag.  ~100 tagged questions, many
  with answer-embedded config snippets.  **Acceptable for direct
  citation with attribution**; high-leverage for filling 5-10 line
  grammar gaps the batfish corpus misses.

#### Operator blogs (Tier-2.4)

License assessment per
[`00-source-analysis.md`](00-source-analysis.md): blogs are
inspiration, not direct import.  Notable XR-heavy blogs:

* **`packetlife.net`** — Jeremy Stretch, IOS-XR coverage in older
  posts (2014-2017 era).
* **`null.53bits.co.uk`** — UK-based SP-routing operator, IOS-XR
  AS-options + route-policy posts.
* **`ericroc.how`** ([`ericroc.how/ios-xr-route-policies.html`](https://ericroc.how/ios-xr-route-policies.html))
  — operator-run blog with detailed RPL walk-throughs.
* **`bspendlove.github.io`** — L3VPN + RTC IOS-XR posts.
* **`brezular.com`** — IOS-XRv lab walkthroughs (BGP, prefix-sets,
  route-policies).
* **`ispcolohost.com`** — NCS5501 IOS-XR 6.2 + BGP in VRF, operator
  perspective.
* **`fryguy.net`** — Jeffrey Fry's PDF "Cisco IOS XR" reference
  (older — 2012/2013).

### 7.0-7.9 (most recent operator-deployed band)

#### GitHub repositories

* **`batfish/lab-validation`**
  ([`github.com/batfish/lab-validation`](https://github.com/batfish/lab-validation))
  — **Apache-2.0.**  3 snapshots × 7 XR device configs already
  catalogued by
  [`docs/v0.2.0-planning/04-iosxr-codec/05-fixture-targets.md`](../v0.2.0-planning/04-iosxr-codec/05-fixture-targets.md):
  * `cisco_xr_ios_vpnv4/configs/{PE1,PE2,PE3}` (XR 6.6.2) — VRFs,
    MPLS LDP, BGP RR + vpnv4, route-policy PASS_ALL.
  * `iosxr_ebgp_basic/configs/{border01,border02}` (XR 6.2.2) —
    eBGP with route-policy + prefix-set, encapsulation dot1q
    subinterface.
  * `iosxr_ibgp_rr_over_ospf/configs/{RR,border01}` (XR 6.2.2) —
    Bundle-Ether LAGs, OSPF underlay, BGP RR + neighbor-group.
  All XR versions in this snapshot trio are **6.x**, not 7.x — the
  grammar is still substantially representative of 7.x, but the
  capability matrix should call out "validated against 6.6.2 + 6.2.2;
  7.x untested" until a fixture from the 7.x band is added.

* **`xrdocs/<topic-repos>`** — various Cisco TME repos
  (`segment-routing`, `cloud-scale-networking`, `telemetry`) on
  `github.com/xrdocs` — most are documentation source, not
  running-configs.  Worth a sweep for any `examples/` or
  `configs/` directory.

* **`CiscoDevNet/yang-suite`** — **BSD-3** per
  [`05-fixture-targets.md`](../v0.2.0-planning/04-iosxr-codec/05-fixture-targets.md);
  YANG tooling examples may include XR config samples.  Lower-yield
  than xrd-tools.

#### Lab platforms

* **containerlab — XRd kind**
  ([`containerlab.dev/manual/kinds/xrd/`](https://containerlab.dev/manual/kinds/xrd/))
  — XRd nodes mount a startup-config from a host path.  Public
  community labs using this kind are sparse but growing.

* **netlab** ([`netlab.tools/labs/clab/`](https://netlab.tools/labs/clab/))
  — generates IOS-XR startup configs from topology specs.  License:
  Apache-2.0.  Generated configs are valid XR but **may have a
  template stamp** ("Generated by netlab") — keep that in the
  fixture provenance.

#### NANOG / IETF / RIPE archives

NANOG archives (`archive.nanog.org`) host presentations with XR
config examples, especially:

* "BGP Multihoming Techniques" — Philip Smith (NANOG 32) — Cisco
  IOS CLI examples; pre-IOS-XR-modular form but useful as ancestry
  reference.
* "BGP Communities: A Guide for SP Networks" — Richard Steenbergen
  (NANOG 40).
* Cisco TME presentations (BRKSPG sessions from Cisco Live archives)
  — heavily IOS-XR-focused; PDFs at `ciscolive.com/c/dam/r/ciscolive/`.

**License**: NANOG presentation slides are presenter-copyright;
grammar samples are fair-use excerpts.  Use as inspiration.

### 6.x (still in production at SPs)

#### GitHub repositories

* **batfish/lab-validation** — already covered (6.2.2 + 6.6.2 are
  the snapshot versions; this is the **primary 6.x corpus**).

* **YangModels/yang/vendor/cisco/xr/{621,622,631,632,641,642,643,
  651,652,653,661,662}/** — schema-only.  Useful as a "what does
  XR 6.5 support" cross-reference.

#### Vendor docs

* **ASR 9000 6.x configuration guides**
  ([`cisco.com/c/en/us/support/ios-nx-os-software/ios-xr-software-end-of-sale/`](https://www.cisco.com/c/en/us/support/ios-nx-os-software/ios-xr-software-end-of-sale/products-installation-and-configuration-guides-list.html))
  — End-of-Sale software but configuration guides still hosted.
  Click-to-copy snippets target the 6.x grammar.

#### Forum (operator-paste precedent)

* Cisco Community 6.x troubleshooting threads — same pattern as
  7.x; lots of "we upgraded from 5.x to 6.x and X broke" threads
  with running-config fragments.

### 5.x retrospective (legacy)

#### Internet Archive

* **`web.archive.org`** captures of `cisco.com/c/en/us/td/docs/
  routers/asr9000/software/asr9k-r5-*` and CRS-1 docs from
  2014-2018.  Useful only if codec needs explicit 5.x backward-compat
  testing.  Lower priority; the 5.x → 6.x → 7.x grammar evolution is
  gradual and 6.2/6.6 already covers most of what 5.x produced.

#### Cisco Press examples

* **End-of-Life Cisco Press books** (e.g. "Cisco IOS XR Fundamentals"
  by Mobeen Tahir et al., 2009; "MPLS in the SDN Era" 2017) — 5.x
  config examples.  **Heavy copyright** — do not pull verbatim;
  paraphrase only.

#### Discontinued operator blogs

* Wayback Machine captures of `fryguy.net` (Jeffrey Fry) "Cisco IOS
  XR" introductions from 2012-2013 — illustrative of pre-modular
  XR grammar (the era before `Bundle-Ether<N>` replaced
  `Port-channel` semantically equivalent constructs).

---

## Sample IOS-XR grammar callouts (per task brief)

These grammar shapes are distinctive to IOS-XR and **divergent from
IOS-XE**; fixture-pull verification should confirm presence of at
least one of each surface.  Codec design at
[`docs/v0.2.0-planning/04-iosxr-codec/01-grammar-survey.md`](../v0.2.0-planning/04-iosxr-codec/01-grammar-survey.md)
lays these out in detail; reproduced here for fixture-validators.

### `router bgp` per-VRF address-family

```
router bgp 65001
 address-family vpnv4 unicast
 !
 neighbor 10.0.0.1
  remote-as 65001
  update-source Loopback0
  address-family vpnv4 unicast
   route-reflector-client
  !
 !
 vrf red
  rd 65001:1
  address-family ipv4 unicast
   redistribute connected
  !
 !
!
```

Key distinctions: VRF nested **under** `router bgp`; RD declared
**there**, not in the top-level `vrf` stanza; `!`-terminated
sub-blocks; the address-family namespace is per-protocol not
per-router.

### `route-policy` DSL (replaces `route-map`)

```
route-policy AZURE-EAST-IN
  if destination in AZURE-EAST-IN then
    pass
  elseif destination in AZURE-WEST-IN then
    prepend as-path 65300 1
    pass
  else
    drop
  endif
end-policy
```

Key distinctions: structured `if / elseif / then / endif` flow
control; `end-policy` terminates (not `!`); references `destination
in <prefix-set-name>` rather than `match ip address prefix-list <N>`.

### `prefix-set` / `community-set` (replace `ip prefix-list` /
`ip community-list`)

```
prefix-set AZURE-EAST-IN
  10.77.128.0/17 le 32,
  192.168.122.0/24
end-set
!
community-set BLUE-IMPORT
  65102:2,
  65102:4
end-set
```

Key distinctions: set-form (comma-separated, terminated by
`end-set`) — not sequence-form (`seq 10 permit X`); no per-line
permit/deny verb.

### Top-level `vrf` stanza with RT import/export sub-blocks

```
vrf red
 address-family ipv4 unicast
  import route-target
   65102:2
   65102:4
  !
  export route-target
   65102:2
   65102:4
  !
 !
!
```

Key distinctions: `vrf <name>` (not `vrf definition <name>`); RT
imports/exports are **sub-blocks of address-family**, not inline; RD
**not declared here** (lives under `router bgp / vrf <name>`).

### 4-segment port names + Bundle-Ether + MgmtEth

```
interface GigabitEthernet0/0/0/0
 ipv4 address 10.254.1.1 255.255.255.255
!
interface GigabitEthernet0/0/0/1.35
 encapsulation dot1q 35
 ipv4 address 192.0.2.1 255.255.255.0
!
interface Bundle-Ether23
 ipv4 address 10.254.23.1 255.255.255.252
 bundle minimum-active links 2
!
interface MgmtEth0/RP0/CPU0/0
 vrf management
 ipv4 address 10.10.10.10 255.255.255.0
!
```

Key distinctions: 4-segment (`rack/slot/instance/port`) physical
ports; **`Bundle-Ether<N>`** LAG (not `Port-channel<N>`); **`MgmtEth`**
dedicated management kind; `ipv4 address` (not `ip address`); `vrf
<name>` per-interface binding (not `vrf forwarding <name>`).

---

## Recommended pull priority order

For an implementor working through T4 phases (per
[`docs/v0.2.0-planning/04-iosxr-codec/README.md`](../v0.2.0-planning/04-iosxr-codec/README.md)):

| Priority | Source | License | Phase wired in | Fixtures count | Coverage gap closed |
|---|---|---|---|---|---|
| **1 (Seed corpus)** | `batfish/lab-validation` (3 snapshots × 7 configs) | Apache-2.0 | Phase 1 | 7 | VRF + BGP-vpnv4 + RR + neighbor-group + route-policy + prefix-set + MPLS LDP + OSPF + Bundle-Ether + 4-seg ports + .subif dot1q + LAG mode active |
| **2 (Phase 4 expansion)** | `ios-xr/xrd-tools` `samples/xr_compose_topos/segment-routing/` (8 configs) | Apache-2.0 | Phase 4 | 8 | SR-MPLS global-block + traffic-eng + PCE candidate-paths + on-demand-color + ISIS flex-algo + extcommunity-set + segment-routing srv6 (in `srv6-l3vpn/`) |
| **3 (Phase 4 expansion)** | `ios-xr/xrd-tools` `samples/xr_compose_topos/isis-ipfrr/` | Apache-2.0 | Phase 4 | 2-4 | IS-IS with IP fast-reroute — fills batfish IS-IS gap |
| **4 (Diversity)** | `CiscoDevNet/openconfig-getting-started/models/` | Apache-2.0 (TBV) | Phase 4 | 1-2 (partial-stanza only — paraphrase as standalone) | OpenConfig CLI mappings + neighbor-group + route-policy + extcommunity-set worked examples |
| **5 (Diversity)** | NetworkEngineering Stack Exchange `[cisco-ios-xr]` answers | CC-BY-SA | Phase 4 (review-each) | 1-2 (with attribution) | Specific grammar corners batfish misses (e.g. `aaa authentication ...`, `tacacs-server host ...`, `banner login`, `snmp-server group / view / community`, `ipv4 access-list` with sequence numbers) |
| **6 (Synthesis-only)** | `xrdocs.io` Converged-SDN-Transport implementation guide | Fair-use (not direct import) | Phase 4 (synthetic) | 0 (rewrite) | Reference for large-scale SR + EVPN + L3VPN deployment patterns |
| **7 (Synthesis-only)** | Cisco Community vendor articles (RPL guide, BGP basic config) | Fair-use (not direct import) | Phase 4 (synthetic) | 0 (rewrite) | Pedagogically clean RPL + BGP examples to fill any final grammar gaps |
| **8 (Operator donation)** | `tests/fixtures/real/WANTED.md` invite for XR donations | MIT-equivalent (per WANTED.md flow) | Post-v0.X.Y | N (community-driven) | 24.x current-train coverage; SP-specific patterns (e.g. RPKI, RTBH, BGP flowspec, GRE tunnels) |

The seed corpus + xrd-tools segment-routing topology together deliver
~15 fixtures with the full Tier-1 + Tier-2 + most of Tier-3 surface
exercised.  That's plenty for `certified` certainty at Phase 4.

---

## Out-of-scope (deliberately excluded)

* **GPL-3.0 `cisco.iosxr` Ansible collection test fixtures.**  Per
  [`BUG_REPORTING.md`](../../BUG_REPORTING.md) permissive-license
  policy.  Same goes for any Ansible collection (cisco.ios,
  cisco.nxos, juniper.junos) — Ansible-collection-standard licensing
  is GPL-3.
* **Cisco IOS-XR Sandbox captures (verbatim).**  ToS unclear on
  redistribution; conservative interpretation is fair-use-only.
  Captures from sandboxes are fine for **testing** a candidate
  fixture but not for **committing** the capture itself.
* **Cisco Press book example configs.**  Copyright-real; do not
  pull verbatim.  Same for INE / IPexpert workbooks.
* **Operator blog post configs (verbatim).**  Per
  [`00-source-analysis.md`](00-source-analysis.md) Tier-2.4 — blogs
  are inspiration, not direct import.  Operator-authored fictitious
  examples are fine to mimic in synthetic fixtures with attribution.
* **`ters-golemi/IOS-XR-Segment-Routing` templates.**  Repo has no
  declared license ("as-is for educational purposes" is not a
  recognised OSI license).  Useful as reference; do not pull.
* **Configs containing public-route IP addresses + real ASN.**
  Any fixture surfacing through forum / Reddit / blog channels must
  pass the same sanitisation bar as the existing AOS-S forum-share
  fixtures — replace public IPs with RFC 5737 documentation prefixes;
  replace real ASNs with RFC 6996 private (65000-65535 / 4200000000-
  4294967294).

---

## Audience-narrowness analysis

IOS-XR's operator population is narrower than NX-OS by approximately
1.5 orders of magnitude — most North-American + European Tier-1 SPs
plus hyperscaler PoP / DCI tier 1 + the largest MSPs.  Worldwide
deployment count: ~25-50K production routers
(vs ~500K+ Nexus switches).  However:

* **Density per device is higher.**  An IOS-XR ASR 9922 carrying
  multi-VRF transit traffic touches more grammar surfaces per device
  than a Nexus 9300 leaf.  Coverage value per fixture is correspondingly
  higher.
* **Operator donation likelihood is lower.**  SP operators are more
  reluctant to share configs (real prefixes + real ASN + real
  next-hops would betray network topology to competitors / state
  actors).  Synthetic + lab + sandbox sources are correspondingly
  more important.
* **Cross-vendor migration appetite is concentrated.**  The XR →
  Junos MX, XR → Arista 7800, XR → SONiC migrations are real but
  rare.  Each migration win is worth more, but they happen less often.

Net assessment: **codec ships, but expansion velocity will be lower
than NX-OS**.  Plan for 5-10 fixtures at GA and 15-25 within 12 months,
not the 40+ that NX-OS could realistically accrete.

---

## Overlap with planning doc

The [`05-fixture-targets.md`](../v0.2.0-planning/04-iosxr-codec/05-fixture-targets.md)
planning artifact covers Phase 1 seed (7 batfish configs) with full
URL + line-count + grammar-coverage detail.  This catalogue
**extends** that planning doc in three directions:

1. **Beyond batfish:** `ios-xr/xrd-tools` (the same upstream Cisco
   `ios-xr` GitHub org as `xrdocs`) is a high-yield Apache-2.0
   donor missed by the planning doc.  The `segment-routing/` and
   `srv6-l3vpn/` topologies fill batfish's SR + SRv6 + flex-algo
   coverage gaps entirely.
2. **Version-band stratification:** planning doc fixes on 6.2/6.6
   (batfish) — this catalogue surveys 5.x through 24.x with
   per-band pull-target lists, especially calling out the **7.10 →
   24.x rebrand**.
3. **Source-class diversification:** planning doc treats batfish as
   the trunk; this catalogue adds Tier-2 forum sources (Cisco
   Community articles, NetEng SE answers), Tier-2.4 operator blogs
   (xrdocs.io, packetlife, null.53bits), Tier-3 lab platforms
   (containerlab XRd, netlab), and the Internet Archive fallback
   for 5.x retrospective work.

---

## See also

* [`docs/v0.2.0-planning/04-iosxr-codec/05-fixture-targets.md`](../v0.2.0-planning/04-iosxr-codec/05-fixture-targets.md)
  — concrete batfish IOS-XR pull list (7 configs, URLs ready to
  copy-paste); this catalogue is the **superset** with additional
  source-class diversity.
* [`docs/v0.2.0-planning/04-iosxr-codec/01-grammar-survey.md`](../v0.2.0-planning/04-iosxr-codec/01-grammar-survey.md)
  — full XR grammar inventory with Tier-1 / Tier-2 / Tier-3
  classification and IOS-XE divergence callouts.
* [`docs/v0.2.0-planning/04-iosxr-codec/README.md`](../v0.2.0-planning/04-iosxr-codec/README.md)
  — codec scope + 4-phase implementation plan.
* [`00-source-analysis.md`](00-source-analysis.md) — source-type
  taxonomy + license-class guidance.
* [`README.md`](README.md) — folder index + per-OS catalogue listing.
* [`tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — fixture provenance ledger (currently no `cisco_iosxr/` rows;
  this catalogue's pull-targets will populate it).
* [`tests/fixtures/real/WANTED.md`](../../tests/fixtures/real/WANTED.md)
  — operator-facing fixture gap list (IOS-XR currently Tier-D row).
* [`BUG_REPORTING.md`](../../BUG_REPORTING.md) — sanitisation +
  fixture-submission workflow.
