# V1 — Parity-skeptic review: would a backup PASS against the virtual image PROVE hardware behaviour, or is it THEATER?

**Author:** V1 (review, adversarial) · **Date:** 2026-06-17 · **Process:** netcanon blackboard (read-only)
**Reads:** `00-blackboard.md`, `10-research-nxos.md` (R1), `11-research-iosxr.md` (R2), `12-research-aoscx.md` (R3)
**Def files independently re-read:** `definitions/cisco/nx-os/10.x.yaml`, `definitions/cisco/ios-xr/7.x.yaml`,
`definitions/aruba/aos-cx/10.x.yaml`. Primary `show version` strings + netmiko driver behaviour
re-verified against vendor docs / netmiko API / the cited repos (citations inline).

---

## 0. The skeptic's bar

A backup PASS is "worth something" only if **every one of the def's management-plane surfaces that the
PASS *claims* to exercise actually behaves on the VM the way it does on hardware.** Where a surface
diverges, the honest move is to scope the claim down, not to silently drop the `⚠ NOT YET VALIDATED`
marker. The four surfaces per the seed are: (1) prompt regex, (2) netmiko paging-disable, (3) `show
running-config` completeness + real grammar, (4) `show version` probe regex. I treat the `show version`
probe as the highest-risk surface exactly because a control-plane sim is most likely to lie about its
*own platform identity* while telling the truth about everything else.

**Methodology guardrail I applied:** I re-read all three def files myself rather than trusting the peer
quotes, and re-fetched the two load-bearing `show version` strings (AOS-CX `Virtual.`, XRd `cisco XRd`)
and the three netmiko `session_preparation` bodies from primary sources. Two peer claims changed nuance
under scrutiny (see AOS-CX §3 and the shared `ansi_escape_codes` finding §4); the rest held.

**Bottom-line per-NOS verdict (detail below):**

| NOS | Worth-it? | Dominant tag | One-line reason |
|---|---|---|---|
| **NX-OS (Nexus 9000v)** | **YES** | `PARITY-OK` | All 3 probe regexes fire on the real banner; only the *captured model token* is a virtual SKU, and the regex *path* is byte-identical to hardware. |
| **IOS-XR (XRd CP)** | **YES, scoped** | `PARITY-OK` + `ACQUISITION-BLOCKER` | Collection surface is genuine IOS-XR; `detected_model` captures `XRd` (cosmetic). Real blocker is *getting the image* (contract-gated; sandbox needs VPN). |
| **AOS-CX (CX Simulator)** | **PARTIAL — collection yes, probe NO** | `THEATER` (scoped to the probe) | The def's *only* probe regex `[A-Z]{2}\.` **cannot fire** on the sim's `Virtual.10.13.1110` banner. A sim PASS proves the collector, not the probe. |

`buildable_now_confirmed` → **NX-OS first** (no acquisition gate, parity clean), **AOS-CX second**
(free-ish, but the probe must be fixed or the marker-drop scoped). IOS-XR only when the image/account is
already in hand.

---

## 1. NX-OS — steelman the case against it, then where it survives

### 1.1 The strongest attack: "the model regex captures a fake SKU → detected_model is a lie"
The def's `detected_model: 'cisco Nexus\S*\s+(\S+)\s+[Cc]hassis'` will, on Nexus 9000v, capture
**`C9300v`** (or `C9500v`), not a hardware SKU like `C93180YC-EX`. I confirmed the banner verbatim from
Cisco's own 9000v overview docs (search-verified across the 9.3 → 10.6 guide family): the hardware line
is literally `cisco Nexus9000 C9300v Chassis` and `Processor Board ID 9TG6I6JMWV4`, under the header
*"Nexus 9000v is a demo version of the Nexus Operating System Software."*

**Why this attack FAILS (PARITY-OK, not THEATER):** the parity that matters for a regex test is whether
the **regex path** is exercised, not whether the captured *value* equals a hardware string. The 9000v
emits the identical token structure `cisco Nexus9000 <SKU> Chassis`; the def's own comment cites
`cisco Nexus9000 C93180YC-EX Chassis` as the target — structurally the same line. `Nexus\S*` eats
`Nexus9000`, `(\S+)` grabs the SKU token (`C9300v` *or* `C93180YC-EX` — both single non-space tokens),
`[Cc]hassis` anchors. The capture group fires on both. A PASS therefore honestly proves the regex
*matches and captures* on real NX-OS `show version` output. The only thing it does **not** prove is that
the regex handles *every exotic hardware SKU spelling*; but that is a regex-coverage question, not a
VM-vs-hardware question, and the structural class is identical. **Not theater.**

### 1.2 Second attack: "the 'demo version' banner line could be mis-captured by the version regex"
`detected_os_version: '(?:NXOS|system):\s+version\s+(\d+\.\d+)'`. The leading `Nexus 9000v is a demo
version of the Nexus Operating System Software` line contains the word *version* but **lacks the
`NXOS:`/`system:` anchor token**, so the regex skips it and hits the real `  NXOS: version 10.2(3)` line,
capturing `10.2`. I verified the real banner shows `NXOS: version 10.2(3)` / `9.3(3)` / `10.1(1)` forms.
**Attack fails — PARITY-OK.** R1's claim holds exactly.

### 1.3 Third attack: "paging / prompt / no-enable might differ on the sim"
- **Paging:** I re-read netmiko `CiscoNxosSSH.session_preparation`: it sets `ansi_escape_codes = True`,
  `set_terminal_width("terminal width 511")`, then `disable_paging()` (NX-OS default → `terminal length
  0`), then `set_base_prompt()`. All four are real NX-OS commands the genuine binary on 9000v honours.
  The def correctly keeps `cisco_more_paging: false` and adds nothing to `commands.pre`. **PARITY-OK.**
- **Prompt / no-enable:** admin role lands at `switch#` (no enable), matching `needs_enable: false` and
  `^\S+[#>]\s*$`. containerlab/dockerized_n9kv confirm `admin:admin` and the `#` landing. **PARITY-OK.**

### 1.4 `show running-config` completeness — the subtle one
A 9000v running-config omits **pure-dataplane** artifacts (real linecard inventory, transceiver/optics,
ASIC counters) — but none of those live in `show running-config` anyway, and the `cisco_nxos` codec is
already COMPLETE+CERTIFIED against a 6-config batfish corpus (per MEMORY). The control-plane grammar
(`feature` toggles, `interface Ethernet1/X`, SVIs, `vrf context`, BGP/OSPF, route-maps) is generated by
the same parser as hardware. **One honest caveat:** a *single default-config* 9000v will emit a *narrow*
running-config; to make the PASS meaningful, the operator should push a representative config first (a
few VLANs, an SVI, a `vrf context`, a BGP stanza) so the collector pulls real grammar, not an empty box.
That is a test-design note, not a parity gap. **PARITY-OK with a "configure it first" must-do.**

### 1.5 NX-OS verdict — **WORTH IT (YES). Tag: PARITY-OK + RESOURCE-FRICTION.**
The only real friction is RAM (8 GB standard / 6 GB Lite eats a whole budget VM) and the OVMF+SATA+E1000
boot recipe — neither is a parity problem. This is the cleanest of the three: free CCO download, no
contract (do **not** route through CML-Free, which excludes the node). A PASS is honest hardware
evidence.

---

## 2. IOS-XR — steelman, then scope

### 2.1 Attack: "`detected_model` will say `XRd`, which is not a hardware platform → the probe is a lie"
Confirmed verbatim from XRd docs: `show version` reads `Cisco IOS XR Software, Version 7.7.1 LNT` and
`cisco XRd Control Plane cisco XRd-CP-C-01 processor with 32GB of memory`. The def's
`detected_model: '^cisco\s+(\S+)'` (multiline-anchored) captures **`XRd`** — hardware would yield
`ASR9K` / `NCS-5501`.

**Severity — this is a *real* but *bounded* divergence, NOT wholesale theater.** Unlike AOS-CX (below),
the IOS-XR model regex **still fires and captures a value** — it just captures the VM's honest platform
identity (`XRd`) rather than a hardware one. So a PASS proves the `^cisco\s+(\S+)` regex *matches real
IOS-XR `show version` output and extracts the first post-`cisco` token*. What it does **not** prove is
that token equals a hardware platform string. Because `detected_model` is a documented *non-fatal,
advisory* probe (feeds overlay resolution only; the def comment scopes it so), this is a cosmetic caveat
to footnote, not a blocker. **Tag: minor caveat, scope the marker-drop to "collection wiring + version
probe verified; model-token confirmed against documented hardware banner only."**

### 2.2 Attack: "the version regex breaks on the `LNT` suffix or on 24.x/25.x trains"
`detected_os_version: 'Cisco IOS XR Software, Version\s+(\d+\.\d+)'` on `...Version 7.7.1 LNT` →
`(\d+\.\d+)` greedily-but-correctly captures `7.7` and stops; the trailing `.1 LNT` is ignored. On a
25.x image it captures `25.1`. I verified XRd ships current 7.11.x / 24.x / 25.1.1 trains (Cisco XRd
release-notes family). The def's `version_match: "^7\\."` is advisory; the probe regex is train-agnostic.
**Attack fails — PARITY-OK.**

### 2.3 Attack: "prompt / paging / no-enable differ"
Prompt `RP/0/RP0/CPU0:ios#` matches the primary regex `^RP/\S+:\S+#\s*$` (verified default hostname
`ios`). IOS-XR has no enable mode (task-group privilege) → `needs_enable: false` correct. netmiko
`cisco_xr` `session_preparation` sends `terminal width 511` + `terminal length 0` itself; def keeps
`cisco_more_paging: false`, `pre: []`. All **PARITY-OK** and self-consistent with netcanon's existing
xrd-derived fixture corpus (so VM and test expectations share a lineage — a point *in favour* of
worth-it).

### 2.4 The actual deciding variable: ACQUISITION (this is where IOS-XR is weakest)
- The XRd Control-Plane tarball on `software.cisco.com` is **"available for download only for users who
  have an active service account"** (containerlab + xrdocs both state this). There is **no
  free-to-any-registered-user** path like Nexus 9000v. → `ACQUISITION-BLOCKER` unless the operator
  already has a contract-backed CCO. **Do not cargo-cult the VyOS outcome** (VyOS was anonymous + free).
- **R2's escape hatch (DevNet XRd sandbox) is NOT turnkey.** I verified the DevNet reservation flow: the
  sandbox is reservation-based and reached via **Cisco AnyConnect VPN into private IP space** — VPN
  credentials are emailed per reservation; SSH only works *through that tunnel*. For our lab this means
  netcanon (Docker on VM-A) would have to source-route to the sandbox's private IP *over an AnyConnect
  tunnel established on the VM-A host* — doable but materially more plumbing than "SSH to a Proxmox VM,"
  and the reservation is time-boxed. This is `FRICTION`, edging `ACQUISITION-BLOCKER`, not the clean path
  R2's prose implies. Flag it as a live-check item, not an assumed fallback.

### 2.5 IOS-XR verdict — **WORTH IT *IF* the image is already obtainable; else gated. Tag: PARITY-OK (collection) + ACQUISITION-BLOCKER.**
The management-plane parity is genuine (this *is* real IOS-XR software, lightest footprint at 2 GiB/2
vCPU). The PASS would be honest evidence for prompt/paging/no-enable/config-command/version-probe, with
a one-line model-token footnote. But the deciding variable is acquisition, not parity — and the
contract-free fallback (DevNet sandbox) carries VPN friction that must be live-checked before counting on
it. **Lower priority than NX-OS purely because of the gate, not the parity.**

---

## 3. AOS-CX — the one place a PASS would be THEATER (scoped to the probe)

### 3.1 The crux, re-verified independently
The AOS-CX def has **exactly one** probe pattern — `detected_os_version: 'Version\s*:\s*[A-Z]{2}\.(\d+\.\d+)'`
— and **no model probe at all** (I re-read the file: the comment explicitly says model lives in
`show system`, not `show version`, so it is deliberately omitted). So for AOS-CX the *entire* `show
version` probe surface rides on that single `[A-Z]{2}\.` regex.

I re-confirmed from **two independent first-party-derived repos** (Shajeervu/arubavsx and
cheddarking/arubavsx) that the AOS-CX **Switch Simulator** emits:
```
Version      : Virtual.10.13.1110
Build ID     : ArubaOS-CX:Virtual.10.13.1110:40649b64b204:202506162315
```
The platform prefix is the **literal word `Virtual`**, not a two-letter hardware code. I also noted the
HPE **AOS-CX Switch Simulator OVA Release Notes** are themselves published as `10.13.1000` / `10.15.1000`
builds — i.e. `Virtual.` is *structural to the simulator build train*, not a per-VM accident a different
download would avoid.

**Trace the regex against the sim banner:** `[A-Z]{2}\.` needs two uppercase letters *immediately
followed by a dot*. The sim line is `Version      : Virtual.10.13.1110`. The first two letters are `Vi`
— but `Vi` is followed by `rtual`, **not** a `.`. The regex finds no `[A-Z]{2}\.` anywhere on the line
(`Vi`, `rt`-lowercase, etc. all fail). → **NO MATCH. `detected_os_version` is never captured on the
simulator.** On *hardware* the line is `Version : FL.10.10.0001` / `GL.10.07.xxxx` and the regex fires
(`FL.`, `GL.` are `[A-Z]{2}\.`). I confirmed the hardware FL./GL. format from the AOS-CX show-version
techdoc.

### 3.2 Why this is THEATER (scoped), and the steelman that *doesn't* rescue it
The probe is documented **non-fatal**, so the *backup job still succeeds* on the sim — prompt, paging,
and `show running-config` all work. The tempting steelman is: "the high-value surface (config
collection) passes, so dropping the marker is fine." **I reject that as applied to the probe regex
specifically.** The `⚠ NOT YET VALIDATED` marker covers *the probe regexes* by name (the def's `notes`
literally lists "probe regex" as one of the things verified "in code and against sample `show version`
output only"). If we drop the marker after a sim run, we would be asserting the probe regex is validated
against a live device — when in fact **the live device we ran against is the one device class on which
the regex provably cannot fire.** That is the definition of theater for *that line*: the green result
tells us nothing about whether the regex works, and worse, a naive reading of "it passed" hides that the
version fact silently came back empty.

So the verdict is **bifurcated**, and the bifurcation must be preserved in any marker-drop:
- `show running-config` collection + prompt + paging + no-enable → **PARITY-OK** on the sim (genuine
  AOS-CX OS, same grammar the `aruba_aoscx` codec round-trips; ~37 supported surfaces per MEMORY).
- `detected_os_version` probe regex → **THEATER on the sim** (cannot fire; remains hardware-confirmed
  only via the independent FL./GL. evidence).

### 3.3 The fix that converts theater → parity (must-fix, for the main thread — I do not edit)
Widen the probe regex so it fires on *both* hardware and the sim, e.g.
`Version\s*:\s*[A-Za-z]+\.(\d+\.\d+)` or the more conservative `(?:[A-Z]{2}|Virtual)\.(\d+\.\d+)`. With
that change, a sim run would capture `10.13` and the probe becomes genuinely validatable on the
simulator — making the sim a full 4-of-4 twin. **Caveat on the broad form:** `[A-Za-z]+\.` would also
match any unexpected prefix; the targeted `(?:[A-Z]{2}|Virtual)\.` is the safer widening because it
keeps the hardware contract tight while admitting the one known sim token. Either is a one-line YAML
edit. Until that lands, dropping the marker on the strength of a sim run is **defensible only for the
collection path and overstated for the probe** — the synthesis must say so explicitly.

### 3.4 Second AOS-CX attack I checked: does `ansi_escape_codes=True` corrupt the captured config?
netmiko's `ArubaCxSSH.session_preparation` sets `ansi_escape_codes = True` (verified) — because real
AOS-CX emits ANSI control sequences. The sim runs the same OS, so it emits the same sequences and the
driver strips them the same way. This is a *reason the parity holds*, not a gap — but it is worth a
one-line confirmation during the actual run that `show running-config` comes back clean (no stray escape
bytes), because a sim with a slightly different terminal type could in principle differ. Low risk;
verify-on-run. **FRICTION-low, not a blocker.**

### 3.5 Third AOS-CX attack: provisioning friction (login user creation)
The netlab build guide notes "it seems impossible to create a user called `vagrant` on AOS-CX" and uses a
`netlab/netlab` account instead; containerlab uses `admin/admin`. This is a real lab-bring-up wrinkle:
the netmiko collector needs a working SSH credential, and AOS-CX has constraints on username creation.
Not a parity issue, but a `FRICTION` item for the runbook (use `admin/admin` on the sim or a
manager-role account; confirm SSH login before pointing netcanon at it).

### 3.6 `show running-config` completeness on the sim
Same caveat as NX-OS but sharper: the sim omits hardware-only stanzas (transceiver/PoE/some
hardware-QoS) that have no meaning without an ASIC. The collector just grabs whatever the device emits,
so this is not a parse failure — but a sim running-config is a **subset** of a fully-featured hardware
config. To make the PASS meaningful, push a representative L2/L3 config first (VLANs, `no routing` L2
opt-in, an SVI, active-gateway, a BGP/OSPF stanza) so the codec-relevant grammar is actually exercised.
**FRICTION (test-design), not theater** for the config surface.

### 3.7 AOS-CX verdict — **WORTH IT for collection; NOT worth it for the probe until the regex is widened. Tag: PARITY-OK (collection) + THEATER (probe) + FRICTION (account/qcow2/login).**
Free HPE/Aruba account (not anonymous, not paid), 4 GB/2 vCPU (comfortably in budget), OVA→qcow2
one-liner. The blocker is **not** resources or acquisition — it is the `Virtual.` probe mismatch. A sim
PASS is honest for ~37 supported config surfaces but **cannot** validate the lone `show version` probe.

---

## 4. Cross-cutting finding none of the three peers fully closed

**All three netmiko drivers set `ansi_escape_codes = True` and all three rely on the driver (not the
def) to disable paging.** I verified the three `session_preparation` bodies:
- `cisco_nxos`: `ansi_escape_codes=True`; `terminal width 511`; `disable_paging()` (→ `terminal length 0`).
- `aruba_aoscx`: `ansi_escape_codes=True`; `disable_paging(command="no page")`.
- `cisco_xr`: `terminal width 511` + `terminal length 0` in `session_preparation`.

Implication for all three validations: the def is *correct* to keep `cisco_more_paging: false` and
`commands.pre: []` — adding `terminal length 0` ourselves would double-issue and (per MEMORY's standing
rule + AGENTS.md) is forbidden. The single thing to **confirm on each live run** is that the captured
`show running-config` is byte-clean (no residual ANSI/`--More--` fragments), since all three OSes are
ANSI-emitters and the sims run the same code. This is a *verify-on-run* checklist item, not a parity
verdict — but it is the one place a green job could still hide a dirty capture, so it belongs in every
runbook.

---

## 5. Per-NOS verdicts + must-fixes (what to confirm/work around to make each validation honest)

### NX-OS — **GO (worth it).** `PARITY-OK`
**Must-do before claiming the PASS validates hardware behaviour:**
1. Push a representative config (VLANs + SVI + `vrf context` + BGP) before backup, so `show
   running-config` exercises real grammar, not an empty default box.
2. When dropping the marker, note `detected_model` captured the **virtual SKU** `C9300v` (regex path
   identical to hardware `Nexus9000 <SKU> Chassis`; capture confirmed, hardware-SKU spellings not
   exhaustively exercised).
3. Confirm captured config is ANSI-clean (cross-cutting §4).
4. Resource: dedicate one 8 GB VM (use 6 GB Lite image); OVMF+SATA+E1000+serial-POAP boot recipe.

### IOS-XR — **GO-WITH-FRICTION (worth it only once the image is in hand).** `PARITY-OK` + `ACQUISITION-BLOCKER`
**Must-do:**
1. Resolve acquisition FIRST: either a contract-backed CCO download, or live-check that the **DevNet XRd
   sandbox is SSH-reachable from netcanon over AnyConnect VPN** (it is NOT a plain SSH path — VPN tunnel
   on the VM host + time-boxed reservation). Do not assume the sandbox is turnkey.
2. Scope the marker-drop: "collection wiring + version probe verified on real IOS-XR software;
   `detected_model` captured `XRd` (VM platform identity), hardware platform-token confirmed against
   documented banner only."
3. Host prep: cgroups v1 (kernel cmdline + reboot), `apparmor=unconfined`, inotify sysctls; run Cisco
   `host-check` green. CP flavour only (2 GiB/2 vCPU) — never vRouter.
4. Confirm ANSI-clean capture (§4).

### AOS-CX — **GO-WITH-FRICTION for collection; NO-GO for the probe until the regex is widened.** `PARITY-OK` (collection) + `THEATER` (probe)
**Must-fix (the load-bearing one):**
1. **Widen the probe regex** `Version\s*:\s*[A-Z]{2}\.(\d+\.\d+)` → `(?:[A-Z]{2}|Virtual)\.(\d+\.\d+)`
   (preferred) or `[A-Za-z]+\.(\d+\.\d+)` so it fires on the sim's `Virtual.10.13.1110`. **Without this,
   a sim PASS does NOT validate the probe regex** — the marker-drop must explicitly exclude the probe
   line, or the regex must be widened first. This is the difference between honest evidence and theater.
**Must-do:**
2. Push a representative config first (VLANs, `no routing` L2 opt-in, SVI, active-gateway, BGP/OSPF) so
   the codec grammar is exercised (sim config is otherwise a subset).
3. Confirm SSH login works (AOS-CX username-creation constraints; use `admin/admin` on the sim).
4. Confirm ANSI-clean capture (§4).
5. Resource: 4 GB/2 vCPU, OVA→qcow2 one-liner — comfortably in budget.

---

## 6. `buildable_now_confirmed` — what is genuinely worth standing up next

1. **NX-OS (Nexus 9000v / 9300v Lite)** — *first*. No acquisition gate (free CCO), parity clean across
   all three probe regexes, only RAM friction. Highest signal-per-effort.
2. **AOS-CX (CX Switch Simulator)** — *second, but only after widening the probe regex* (must-fix #1
   above) so the validation isn't theater on the one probe it has. Free-ish account, light resources.
3. **IOS-XR (XRd CP)** — *only if the image is already obtainable* (contract CCO or a confirmed
   VPN-reachable DevNet sandbox). Parity is genuine; the gate is acquisition, not behaviour.

**Net:** none of the three is wholesale theater, but **AOS-CX's sole `show version` probe is theater on
the simulator as the regex stands** — that is the single most important must-fix in this run. NX-OS is
the safe first move.

---

## Sources (re-verified by V1)
- NX-OS 9000v `show version` banner (`cisco Nexus9000 C9300v Chassis`, `Processor Board ID`, `NXOS:
  version 10.2(3)`, "demo version") — Cisco Nexus 9000v overview guides, releases 9.3(x)–10.6(x):
  https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/103x/n9000v-n9300v-9500v/cisco-nexus-9000v-9300v-9500v-guide-release-103x/m-overview.html
- XRd CP `show version` (`Cisco IOS XR Software, Version 7.7.1 LNT`, `cisco XRd Control Plane cisco
  XRd-CP-C-01 processor with 32GB`) — XRdocs "XRd with docker":
  https://xrdocs.io/virtual-routing/tutorials/2022-08-23-xrd-with-docker-control-plane-and-vrouter
- AOS-CX simulator `Version : Virtual.10.13.1110` / `Build ID : ArubaOS-CX:Virtual...` — two independent
  repos: https://github.com/Shajeervu/arubavsx and https://github.com/cheddarking/arubavsx
- AOS-CX hardware `Version : FL.10.x` / `GL.10.x` two-letter format — AOS-CX show-version techdoc:
  https://arubanetworking.hpe.com/techdocs/AOS-CX/10.11/HTML/fundamentals_6300-6400/Content/SysHW_cmds/sho-ver-10.htm
- AOS-CX Switch Simulator OVA Release Notes (10.13.1000 build train — `Virtual.` is structural):
  https://arubanetworking.hpe.com/techdocs/AOS-CX/10.13/OVA/RN/rn_ova_10.13.1000.pdf
- netmiko `aruba_aoscx` (`disable_paging("no page")`, `ansi_escape_codes=True`, prompt `[>#]`):
  https://ktbyers.github.io/netmiko/docs/netmiko/aruba/aruba_aoscx.html
- netmiko `cisco_nxos` (`ansi_escape_codes=True`, `terminal width 511`, `disable_paging()`,
  `_test_channel_read(pattern=r"[>#]")`):
  https://ktbyers.github.io/netmiko/docs/netmiko/cisco/cisco_nxos_ssh.html
- DevNet XRd sandbox = reservation + AnyConnect VPN into private IP space (NOT a plain SSH path):
  https://developer.cisco.com/docs/sandbox/first-reservation-guide/
- netlab AOS-CX box guide (tested 10.15; `netlab/netlab` user — `vagrant` user can't be created):
  https://netlab.tools/labs/arubacx/
- Def files re-read: `definitions/cisco/nx-os/10.x.yaml:54-58`, `definitions/cisco/ios-xr/7.x.yaml:51-54`,
  `definitions/aruba/aos-cx/10.x.yaml:51` (single probe, `[A-Z]{2}\.`, no model probe).
