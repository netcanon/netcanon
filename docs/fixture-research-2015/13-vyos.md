# VyOS — fixture catalogue (2015+)

> **Tier**: Tier-D (no codec yet — design not started)
> **Existing corpus**: 0 fixtures
> **License caveat**: VyOS occupies a tricky license posture.  The
> distro itself ships under **GPL-2.0 / LGPL-2.1** (`vyos/vyos-build`
> is GPL-2.0; `vyos/vyos-1x` — the command-definition + smoketest
> package — is **LGPL-2.1**).  Config text-files in the smoketest
> corpus are arguably data, not derivative code, but the project's
> conservative posture (see
> [`tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md))
> is "Apache / MIT / BSD / CC0 only", so the LGPL-housed smoketest
> bundle should be cleared with maintainers before bulk-import.
> Documentation is more ambiguous still: `docs.vyos.io`'s own
> copyright page reads as a custom permissive verbatim-distribution
> notice (closer to GNU FDL than CC-BY-NC-SA), while the briefing
> for this catalogue assumed CC-BY-NC-SA.  No explicit license
> file is present in the `vyos/vyos-documentation` GitHub repo at
> the time of writing.  Per project rule we **classify the docs
> licensing as "unknown / restrictive — treat as out-of-scope
> until clarified"** and concentrate on the explicitly-permissive
> alternatives below.  Operator-contributed configs from `forum.vyos.io`
> are usable under the forum-share precedent that already underpins
> the Aruba AOS-S corpus.

VyOS uses a hierarchical **set-form configuration syntax inherited
directly from Vyatta** (`set interfaces ethernet eth0 address
10.0.0.1/24`), and stores it on disk in a curly-brace JunOS-style
tree at `/config/config.boot`.  A future `vyos` codec could very
plausibly **share the set-form tokeniser layer with the existing
`juniper_junos` codec** — see § "Codec planning note" at the end.

---

## Version timeline

| Version | Codename | Release date | LTS-ness | Priority |
|---|---|---|---|---|
| 1.0 | Hydrogen | 2013-12-22 | EoS — Vyatta-derived | Out of scope (pre-2015) |
| 1.1 | Helium | 2014-10-09 | EoS — last Vyatta-codebase release | Low retrospective |
| 1.2 | Crux | 2019-01-28 | EoS 2023 — first community-major after Vyatta departure | Medium retrospective |
| 1.3 | Equuleus | 2021-12-21 | EoS 2025 — recent LTS | Medium-high |
| 1.4 | Sagitta | 2024-06-04 | Current LTS | High |
| 1.5 | Circinus | 2026-03-31 | Current rolling → next LTS | High |

> 2015-window note: Helium (1.1) is the only release that was
> "current GA" during 2015 itself.  Crux (1.2) was the next major,
> but didn't ship until 2019 — there is a real 4-year gap in
> VyOS releases from 2015→2019.  Coverage priority follows
> current-deployment likelihood, not retrospective coverage:
> capturing 1.4 / 1.5 fixtures is the highest-leverage activity.

---

## Pull-target inventory

### 1.5 Circinus (current rolling / pre-LTS)

#### GitHub repositories

* [`vyos/vyos-1x`](https://github.com/vyos/vyos-1x) — `smoketest/configs/`
  directory at branch `current`.  **~50+ test-corpus configs** in
  config.boot curly-brace form, each named by feature
  (`basic-vyos`, `bgp-evpn-l2vpn-leaf`, `bgp-evpn-l3vpn-pe-router`,
  `bgp-dmvpn-hub`, `bgp-dmvpn-spoke`, `bgp-medium-confederation`,
  `bgp-rpki`, `bgp-small-internet-exchange`, `ospf-simple`,
  `ospf-small`, `vrf-ospf`, `dialup-router-complex`,
  `container-simple`, `cluster-basic`, `firewall*`, `nat-basic`,
  `pppoe-server`, `vpn-openvpn`, `wireless-basic`, `dns-dynamic`,
  `basic-haproxy`, `basic-ipv6`, `basic-syslog`, etc.).
  Repo license: **LGPL-2.1** (verified from
  `https://github.com/vyos/vyos-1x/blob/current/LICENSE`).
  Sanitisation: NONE — these are already synthetic test fixtures
  using RFC-1918 / RFC-5737 ranges and no operator-PII.
  License-compatibility classification: **needs maintainer clearance**.
  The LGPL applies cleanly to the surrounding Python codebase;
  the bare config text files arguably aren't derivative works of
  code, but the project's conservative
  Apache-/MIT-/BSD-/CC0-only stance means we should open a
  fixture-license-clarification thread on the VyOS forum or
  `vyos/vyos-1x` repo before bulk-importing.
  Inspect `bgp-evpn-l2vpn-leaf` (verified contents): 145-line
  EVPN VxLAN leaf config covering peer-group `evpn`, AF
  `ipv4-unicast` + `l2vpn-evpn`, `next-hop-self`, MGMT VRF,
  bridge `vxlan100` source-address 172.29.0.1.

* [`vyos/vyos-build`](https://github.com/vyos/vyos-build) — primary
  ISO/image build scaffold.  License: **GPL-2.0** (code) +
  unspecified artwork.  Holds `data/` resources for ISO creation
  but no end-user example configs — out of scope for fixture
  pull unless `data/` boot-config templates qualify
  (probably not — they're config-skeletons, not exercised
  configurations).

* [`bjw-s/vyos-config`](https://github.com/bjw-s/vyos-config) —
  homelab-IaC VyOS config repo.  License: **Apache-2.0** ✓.
  Structured as `config-parts/` with `apply-config.sh` driver —
  contains real set-form commands.  Excellent low-friction pull
  candidate.  VyOS version not explicitly tagged in README; recent
  commits suggest Sagitta/Circinus era.

* [`binaryn3xus/VyosConfig`](https://github.com/binaryn3xus/VyosConfig) —
  homelab.  License: **Apache-2.0** ✓.  Explicitly tagged for
  **VyOS 1.4**.  Set-command form, SOPS-encrypted secrets
  (the encrypted-secret blocks will need scrubbing for fixture use).

* [`budimanjojo/vyos-config`](https://github.com/budimanjojo/vyos-config) —
  homelab IaC.  License: **Apache-2.0** ✓.  Version unspecified;
  recent commits — likely Sagitta era.  Declarative-state
  presentation — convertible to either set-form or config.boot.

#### Forum / community posts

* [`forum.vyos.io`](https://forum.vyos.io) — small but high-signal.
  Critical observation: the VyOS docs explicitly teach
  `show configuration commands | strip-private` as the sanitisation
  command **for the express purpose of safely posting to the forum**
  (verified at
  `https://docs.vyos.io/en/1.4/cli.html`).  This is unique among
  vendor communities — VyOS has a first-class, documented
  forum-share workflow.  The forum-share precedent in
  `NOTICE.md` applies with extra confidence.
  Sanitisation already done by the poster via `strip-private`
  in well-formed threads; verify on a per-thread basis.

* [`forum.vyos.io/c/general-questions`](https://forum.vyos.io/c/general-questions) —
  configuration-questions category; multi-version mix.

* `r/vyos` on Reddit — very small.  Operator-share occasional; treat
  per Tier-2.2 (heavy sanitisation review).

#### Vendor docs / lab guides

* `docs.vyos.io/en/latest/configexamples/` — Configuration Blueprints.
  ~12 primary blueprints (Zone-Policy, BGP IPv6 unnumbered,
  OSPF unnumbered, Azure VPN single + redundant, High
  Availability / VRRP, WAN Load Balancer, Dual-Hub DMVPN) plus
  3 auto-tested examples (Tunnelbroker.net IPv6, DHCP Relay
  through GRE-Bridge, Wireguard).
  **License: NOT FROM HERE — see § "Out of scope" below.**

#### Lab platforms

* [`sever-sever/containerlab-vyos`](https://github.com/sever-sever/containerlab-vyos) —
  containerlab kind wrapper.  License: **GPL-3.0** — out of scope
  per project's Apache/MIT/BSD/CC0-only rule.
* `containerlab.dev/manual/kinds/vyosnetworks_vyos/` — vendor-supplied
  startup configs in `topology.clab.yaml` form.  containerlab
  itself is BSD-3 ([`srl-labs/containerlab`](https://github.com/srl-labs/containerlab));
  any sample VyOS startup-configs published in the official lab
  docs inherit the project license.  Low yield though — typical
  examples are tiny.
* [`inmanta/examples`](https://github.com/inmanta/examples) at
  `Networking/Vyos/` — has `*.cf` and `ospf.cf`.  License of
  inmanta/examples not visible in their README; verify before
  pull.

### 1.4 Sagitta (current LTS)

Sagitta has the widest deployment base of any LTS as of 2026.

#### GitHub repositories

* [`vyos/vyos-1x` at branch `sagitta`](https://github.com/vyos/vyos-1x/tree/sagitta) —
  same smoketest/configs/ corpus pinned to Sagitta-era grammar.
  License **LGPL-2.1** (same caveat as above).  `basic-vyos`
  config-version metadata at this branch declares "Release
  version: 1.2.6" historically (the Sagitta smoketest base reuses
  many Crux-era fixtures); per-file inspection needed to
  classify which Sagitta-specific surfaces (`container`,
  `qos`, `policy-route` updates) are exercised.

* [`binaryn3xus/VyosConfig`](https://github.com/binaryn3xus/VyosConfig) —
  Apache-2.0, explicit 1.4 target.  Primary recommended pull.

* GitHub topic search:
  `language:Text "set system host-name" "1.4" path:*.cfg OR path:*.txt`
  yields scattered homelab repos; license per-repo.

#### Forum / community posts

* `forum.vyos.io/tag/sagitta` — version-tagged subset.

#### Vendor docs

* `docs.vyos.io/en/1.4/` — Sagitta-tagged docs branch.  Same
  copyright caveat as latest (§ "Out of scope" below).

### 1.3 Equuleus (recent LTS, EoS 2025)

Equuleus is the migration-bridge LTS — many ops shops are still
running it in 2026 because Sagitta upgrades were paused for
specific feature regressions.  Grammar coverage value: high.

#### GitHub repositories

* [`vyos/vyos-1x` tag `1.3.1`](https://github.com/vyos/vyos-1x/tree/1.3.1) —
  Equuleus-pinned smoketest/configs/.  Same LGPL caveat.
  Useful for catching Equuleus-vs-Sagitta grammar drift
  (e.g. firewall-rule syntax changed between 1.3 and 1.4).

* [`onedr0p/vyos-config`](https://github.com/onedr0p/vyos-config) —
  **archived 2024-07-10**, License: **Apache-2.0** ✓.  Real
  homelab config from the Equuleus era — high-quality fossil.
  Probably the cleanest single-fixture pull candidate.

#### Forum / community posts

* `forum.vyos.io/tag/equuleus` — version-tagged subset; well-trafficked
  during 2022-2024.

#### Vendor docs / lab guides

* `docs.vyos.io/en/equuleus/configexamples/index.html` — same set
  of ~12 blueprints, Equuleus-pinned.  License-restricted.

### 1.2 Crux retrospective (EoS 2023)

Lower priority — most 1.2 deployments have migrated, but as the
first non-Vyatta major it carries grammar that was inherited
forward.  Worth one or two fixtures to anchor the version-bridge.

#### GitHub repositories

* [`vyos/vyos-build` branch `crux`](https://github.com/vyos/vyos-build/tree/crux) —
  build-system snapshot for Crux.  GPL-2.0.  No example configs.

* [`vyos/vyos-1x` Crux-era tags] — same smoketest pattern, version-pinned.

* Verified specimen: `vyos/vyos-1x/smoketest/configs/basic-vyos`
  ends with `/* Release version: 1.2.6 */` and declares
  `vyatta-config-version: ...` metadata covering modules
  `firewall@5 ipsec@5 quagga@6 nat@4 vrrp@2 zone-policy@1`
  — i.e. the **module-version manifest** itself is a useful
  grammar-version oracle for the future codec.

#### Forum / community posts

* `forum.vyos.io/tag/crux` — historic threads, often discussing
  the Vyatta→VyOS divergence.

### 1.1 Helium retrospective (Vyatta-codebase era)

Effectively only fixture-research-historical interest.  Helium
shipped 2014 and was patched through 2017.  Anyone running 1.1
in 2026 is in a frozen environment.  One fixture suffices for
grammar-archaeology.

#### GitHub repositories

* [`vyos-legacy/`](https://github.com/vyos-legacy) — archived legacy
  repos.  Mixed licenses per-repo: `libvyosconfig` LGPL-2.1,
  `vyos-vpp` GPL-2.0, etc.  Suitable for grammar reference but
  not direct config pull (these are code repos, not config repos).

* [`vyos/vyatta-cfg`](https://github.com/vyos/vyatta-cfg) — the
  Vyatta-derived configuration backend.  GPL-2.0.  Not a config
  source per se but the canonical reference for what Helium's
  parser accepted.

* GitHub Gist:
  [`shafiqsaaidin/Vyos Basic Setup.txt`](https://gist.github.com/shafiqsaaidin/4f25d94eb9d6a14771e17fcaf47a7572) —
  bare Helium-era set-form example.  Gist license inherits owner
  default (no explicit declaration); treat as Tier-3 discovery,
  not direct import.

#### Forum / community posts

* `forum.vyos.io/tag/helium` — small archive.

---

## Recommended pull priority order

1. **`binaryn3xus/VyosConfig`** (Apache-2.0, 1.4 explicit) — single
   real homelab fixture, lowest license friction.  Sanitise SOPS-encrypted
   secret blocks; otherwise drop-in.
2. **`onedr0p/vyos-config`** (Apache-2.0, 1.3 Equuleus) — bridge
   version, archived clean.
3. **`bjw-s/vyos-config`** + **`budimanjojo/vyos-config`** (both
   Apache-2.0, recent Sagitta/Circinus-era) — additional 1.4/1.5
   coverage.
4. **`vyos/vyos-1x/smoketest/configs/*`** — pending license
   clearance from VyOS maintainers.  This is the highest-leverage
   single source (50+ purpose-built test fixtures across
   Crux → Circinus, each exercising a specific feature surface).
   Open a forum thread (or `vyos/vyos-1x` issue) requesting an
   explicit fixture-redistribution clarification (e.g. dual-license
   the `smoketest/configs/` subtree under Apache-2.0).  If granted,
   this alone closes most VyOS coverage gaps in one pull.
5. **Forum-share captures** via `forum.vyos.io` `strip-private`
   threads — best signal-to-noise ratio for "real operator
   deployed it like this" patterns that synthetic test corpus
   doesn't cover (e.g. PPPoE + NAT + firewall+VRRP combinations).
   Per-thread sanitisation review still required; the
   `strip-private` discipline only covers WAN IPs / hashes / hostnames,
   not architectural-identification (datacenter names, VLAN
   labelling conventions).

---

## Out of scope (deliberately excluded)

* **`docs.vyos.io` directly** — license posture is unclear /
  appears restrictive (the `copyright.html` page describes a
  GNU-FDL-style verbatim-preservation notice, the project briefing
  asserted CC-BY-NC-SA, and the `vyos/vyos-documentation` GitHub
  repo has no `LICENSE` file).  Per project conservative-licensing
  rule: skip entirely until a maintainer-confirmed permissive
  license is established.  The official Configuration Blueprints
  are excellent reference material for *what* to capture, but the
  *capture itself* must come from an explicitly-permissive source.
* **`sever-sever/containerlab-vyos`** — GPL-3.0; out of scope.
* **`vyos/vyos-build`** code — GPL-2.0; code/build scripts are not
  fixture material anyway.
* **`vyos/vyatta-cfg`** — GPL-2.0; reference-only for grammar
  archaeology.
* **`vyos-legacy/*` LGPL/GPL repos** — out of scope as primary
  fixture sources; treat as historical-reference only.
* **Gists without explicit licenses** (`shafiqsaaidin/...`,
  `achiang/...`, `fatred/...`, `bufadu/...`, `mrbuk/...`) — Tier-3
  discovery only; redraft as synthetic if pattern is needed.
* **`bertvv/cheat-sheets` VyOS page** — no `LICENSE` file visible
  in the repo metadata at time of writing; treat as inspiration,
  not import.  Also only ~140 lines, only covers
  RIP/NAT/DNS/static — too thin to be high-value anyway.
* **Cert-prep / training material** — VyOS lacks a formal cert
  programme; no equivalent of Cisco Press / Junos Genius to
  worry about here.

---

## Codec planning note (architecture hint to whoever scopes the VyOS codec)

VyOS uses **set-form configuration syntax inherited directly from
Vyatta** — which is also the syntactic ancestor of JunOS set-form
syntax.  Both render as `set <hierarchical-path> <value>` and both
store on disk in a curly-brace hierarchical tree.  The existing
`juniper_junos` codec has a working set-form tokeniser (used for
`.set` fixtures like `ksator_labmgmt_qfx10k2_junos173.set`).

A future `vyos` codec could **share the set-form tokeniser
scaffolding** with `juniper_junos`, with codec-specific divergence
at the semantic / hierarchy-validation layer.  Things that differ:
* VyOS namespaces are different (`set interfaces ethernet ethN ...`
  vs Junos `set interfaces ge-0/0/N unit 0 family inet address ...`).
* VyOS has no concept of "candidate vs committed" config in the
  on-disk text (a stricter commit-discipline lives in the daemon).
* VyOS uses single-quotes around scalar values
  (`set system host-name 'vyos01'`), Junos doesn't.
* Config-file trailer for VyOS includes the
  `vyatta-config-version: "..."` metadata line — useful
  fingerprint for codec auto-detection.

This shared-scaffolding hypothesis matters for codec planning
priority: if `juniper_junos` set-form parsing can be lifted into
a shared base, the VyOS codec is much smaller than a standalone
estimate would suggest — possibly 50-60% of the work of a
codec-from-scratch.  Worth pinning down as a v0.3.0 design question
when the VyOS codec is scoped.

---

## See also

* [`00-source-analysis.md`](00-source-analysis.md) — source-type
  taxonomy + license-confidence tiers
* [`02-juniper_junos.md`](02-juniper_junos.md) — set-form
  tokeniser scaffolding the VyOS codec could re-use
* [`tests/fixtures/real/WANTED.md`](../../tests/fixtures/real/WANTED.md)
  Tier-D table — VyOS entry noting "LGPL caveat — careful licensing"
* [`tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — provenance ledger + forum-share precedent (Aruba AOS-S
  HPE Community threads), the model for VyOS
  `forum.vyos.io strip-private` captures
* [`BUG_REPORTING.md`](../../BUG_REPORTING.md) — sanitisation +
  fixture-submission workflow
