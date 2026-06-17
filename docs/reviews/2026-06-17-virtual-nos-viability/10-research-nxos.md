# R1 — Cisco NX-OS virtualization viability (Nexus 9000v / n9kv)

**Author:** R1 (research) · **Date:** 2026-06-17 · **Backup def under test:**
`definitions/cisco/nx-os/10.x.yaml` (`type_key: CiscoNXOS`, netmiko driver `cisco_nxos`).

**One-line verdict: GO** — Cisco's own Nexus 9000v is the *real* NX-OS software (a
control-plane "demo version"), free to download with any Cisco.com account (no contract),
runs on plain Proxmox/KVM as a single ~2 GB qcow2 at **8 GB RAM / 2 vCPU**, and over SSH it
presents a real CLI where `show running-config` is complete real config and `show version`
hits all three probe regexes. The only friction is RAM headroom and an OVMF/UEFI + SATA boot
recipe. **Biggest blocker:** 8 GB RAM per instance is right at the ceiling of our 8 GB-per-VM
budget — it must run *as* the device VM, not alongside the netcanon app VM.

---

## 0. How this maps to the backup surface (what actually needs to be true)

From the seed's table, the `CiscoNXOS` row exercises *only* the management plane:

| Surface | Def value | What the VM must do |
|---|---|---|
| netmiko driver | `cisco_nxos` | boot a real NX-OS SSH server that the `cisco_nxos` driver drives |
| config command | `show running-config` | return complete, real set/CLI-form config text |
| probe command | `show version` | emit a banner the 3 regexes below hit |
| os-version regex | `(?:NXOS\|system):\s+version\s+(\d+\.\d+)` | banner line `  NXOS: version 10.x(y)` |
| model regex | `cisco Nexus\S*\s+(\S+)\s+[Cc]hassis` | banner line `Hardware cisco Nexus9000 C9300v Chassis` |
| serial regex | `Processor Board ID\s+(\S+)` | banner line `Processor Board ID <id>` |
| prompt regex | `^\S+[#>]\s*$` | prompt like `switch#` |
| enable? | `false` | NX-OS admin lands at `#`, no enable mode |
| paging | `cisco_more_paging: false` | netmiko's driver sends `terminal length 0` itself |

Dataplane / ASIC / linecard parity is explicitly **out of scope** for the backup. So a
control-plane-only image that runs the genuine NX-OS binary is exactly as good as hardware
**for this def**. The whole question reduces to: is the obtainable image the real NX-OS
software, and does its management plane behave identically? Both are **yes** (evidence below).

---

## 1. Which image exists in 2026, and is it real NX-OS?

**The image is the Cisco Nexus 9000v ("n9kv"), Cisco's own real NX-OS software running as a
control-plane VM.** It is *not* a third-party reimplementation.

- **Current product / version train.** Cisco ships the Nexus 9000v across the full 9.x → 10.x
  trains. Release-specific deployment guides exist for **9.3(x), 10.1(x), 10.2(x), 10.3(x),
  10.4(x), 10.5(x), and 10.6(x)** — i.e. it is actively maintained in 2026 and tracks the same
  NX-OS releases as the physical Nexus 9000. Our def's `version_match: "^(9|10)\\."` covers
  exactly this. (Cisco Nexus 9000v guides, releases 9.3 through 10.6.)
- **Two modern flavors** under the same "Nexus 9000v" umbrella:
  - **Nexus 9300v / 9500v** — the standard image (single qcow2, e.g.
    `nexus9300v.9.3.9.qcow2`, or `nxos64-cs.10.2.2.185.F.bin` style images).
  - **Nexus 9300v / 9500v "Lite"** — a reduced-memory, smaller image introduced in
    **10.2(3)F** (`nxos64-cs-lite.10.2.2.75.F.bin`, current `nxos64-cs-lite.10.5.3.F.bin`).
    Lite needs less RAM (see §3) — relevant to our budget.
- **It runs the genuine NX-OS binary.** The `show version` banner literally reads
  *"Nexus 9000v is a demo version of the Nexus Operating System Software"* and reports
  `NXOS: version 10.2(3) [build 10.2(2.185)]` with image file
  `bootflash:///nxos64-cs.10.2.2.185.F.bin`. "Demo version" here means *control-plane
  simulation of the real software* — the same NX-OS CLI, parser, and `running-config` grammar
  as hardware, with the dataplane/ASIC stubbed. This is the vendor's own software, not an
  open-source clone.
- **Lineage note (older image).** The earlier **"NX-OSv 9000"** (a.k.a. "Titanium" heritage,
  `nxosv9k-7.0.3.I7.4.qcow2`, `nxosv-final.7.0.3.I7.x.qcow2`) is the same family's predecessor
  and is the image behind the older `system: version 7.0(3)I7(8)` style banner our def's regex
  also anticipates (`(?:NXOS|system):`). It is effectively superseded by Nexus 9000v 9.3+/10.x;
  no reason to use it when 10.x is freely available. Worth knowing only because it confirms the
  `system:`-form branch of our version regex is real, not invented.

**Verdict on dimension 1: PARITY-OK — vendor's own NX-OS software, not a reimplementation.**

---

## 2. Acquisition + licensing

- **Where:** Cisco Software Download portal (`software.cisco.com`, Nexus 9000v switch product
  page `cisco.com/c/en/us/support/switches/nexus-9000v-switch/model.html`). qcow2 / OVA / VMDK
  artifacts are published per release.
- **Cost / gating:** **Free to any registered Cisco.com (CCO) account; no service contract or
  paid license is attached to the n9kv image itself.** Community/primary guidance is explicit:
  *"Cisco Nexus 9000v is publicly free to download. You need to have a Cisco account, but you
  don't need to have any contract attached to it."* Cisco positions it for
  "validate configuration changes on a simulated network prior to applying them on a production
  network… feature testing, verification, and automation tooling" — i.e. exactly lab/dev use.
- **Legality of private-lab use:** The image is downloaded under Cisco's standard EULA for
  software downloads; running it in a private lab for config/automation validation is its
  stated purpose. We are NOT redistributing or committing the image (the mission forbids that),
  so the only obligation is "registered account + don't redistribute," which we satisfy by each
  operator downloading under their own CCO. **No commercial relationship or purchase is
  required** to obtain or run n9kv standalone on KVM.
- **The licensing trap to avoid — CML.** Do *not* try to get NX-OS via the **free** Cisco
  Modeling Labs tier. **CML-Free (5-node) does NOT include the NX-OS 9000 node** — its refplat
  ships only IOL/IOL-L2/ASAv + Linux hosts. NX-OS 9000 (and IOS-XR, Cat8000v) require
  **CML-Personal (paid, ~US$199/yr, 20-node)**. CML is *not* the acquisition path for us; the
  **standalone n9kv qcow2 downloaded directly from software.cisco.com is**, and it is free. CML
  is only relevant if the operator already happens to own a Personal license.

**Verdict on dimension 2: FRICTION-LIGHT — free with a Cisco account, legal for private lab,
no purchase. The only "gotcha" is not confusing it with CML-Free (which excludes the node).**

---

## 3. Run it on the Proxmox lab (format, boot recipe, resource cost)

Primary runbook: Karneliuk, *"How to Run Cisco Nexus 9000v in Proxmox to Lab Cisco Data
Centre"* (karneliuk.com, 2022) — directly our scenario (n9kv on Proxmox/KVM). Cross-checked
against containerlab `vr-n9kv` and the Cisco deployment guides.

**Format:** single **qcow2** disk image (~1.98 GB on disk for 9.3(9); 10.x images are similar
single-file qcow2/`.bin`). No multi-disk OVA wrangling needed for KVM.

**Proxmox boot recipe (the load-bearing quirks):**

| Setting | Required value | Why |
|---|---|---|
| BIOS / firmware | **OVMF (UEFI)** — *mandatory* | "Cisco Nexus 9000v requires this type of BIOS… VM will not launch" on SeaBIOS |
| Disk bus | **SATA (sata0)**, set as top boot priority | qcow2 must attach as SATA, not SCSI/virtio |
| mgmt NIC model | **E1000** | mgmt0 must be `E1000`; virtio not supported for mgmt |
| Serial console | **needed for first boot** (`qm terminal <vmid>`) | POAP prompt appears on serial at first boot |
| Import | `qm importdisk <vmid> <image>.qcow2 <storage>` | standard Proxmox import |
| First-boot prompt | "Abort Power On Auto Provisioning [yes/skip/no]" | choose **skip/yes** to get to setup, then configure mgmt + SSH |
| Boot time | ~5 minutes to full CLI | matches containerlab's "~5 min to fully boot" |

**Resource cost (honest, vs the modest two-VM lab budget):**

| Variant | RAM | vCPU | Disk | Source |
|---|---|---|---|---|
| n9kv standard (Karneliuk Proxmox) | **8 GB** | **2** | ~2 GB qcow2 (+ overlay) | Karneliuk Proxmox guide |
| n9kv standard (Cisco min, rel 10.1+) | **8 GB minimum to boot** | 4 (some docs) | ~2 GB | Cisco; learningnetwork |
| n9kv standard (containerlab default) | 10 GB | 4 | qcow2 in vrnetlab container | containerlab `vr-n9kv` |
| **n9kv "Lite"** (10.2(3)F+) | **6 GB min** | **2** | smaller `.bin` | containerlab; Cisco lite-image guide |

**Budget reality:** The lab budget is **two small VMs** on the lab host total, shared with the
netcanon app VM. The standard n9kv wants **8 GB / 2–4 vCPU**, which *consumes one entire 8 GB
VM by itself*. That is feasible **only if** n9kv runs as the dedicated device VM (VM-B in the
dogfood paradigm) and the netcanon app/Docker runs in the *other* 8 GB VM (VM-A) — exactly how
VyOS was validated. There is **no headroom to co-locate** n9kv with anything else on the same
VM. The **Lite image at 6 GB / 2 vCPU is the recommended choice** here: it leaves ~2 GB
headroom on the 8 GB VM and boots the identical CLI/`running-config` grammar. containerlab's
10 GB default is conservative; 8 GB (standard) and 6 GB (lite) are the real floors.

- No **nested-virt** requirement for the VM itself (it's a normal KVM guest; Proxmox on bare
  metal is fine — nested virt only matters if the lab host is itself a VM, which it is not).
- No CML/EVE-NG wrapper needed — runs as a plain Proxmox VM. (EVE-NG and containerlab support
  exist but add nothing for a single-node mgmt-plane validation.)

**Verdict on dimension 3: FRICTION — runs natively on Proxmox/KVM, but 8 GB (or 6 GB Lite)
eats a whole budget VM. Use the Lite image; dedicate the VM. Boot needs the OVMF+SATA+E1000
recipe (RESOURCE-BLOCKER-adjacent, not a hard blocker).**

---

## 4. Management-plane parity — the crux (judged against EXACTLY the def's surface)

This is where a virtual image can be theater. For n9kv it is **not** — every surface the def
touches behaves as on hardware:

**(a) SSH + prompt.** n9kv boots a real NX-OS SSH server. Default/lab creds `admin` /
`admin` (containerlab, dockerized_n9kv both confirm `admin:admin`). After login the admin role
lands directly at `switch#` — **no enable mode**, matching `needs_enable: false`. The prompt
`switch#` / `switch(config)#` matches the def's `^\S+[#>]\s*$` (no spaces → `\S+` holds).
**PARITY-OK.**

**(b) Paging.** netmiko's `CiscoNxosSSH.session_preparation` sets `terminal width 511` and
calls `disable_paging()` which sends **`terminal length 0`** — both natively supported by
NX-OS (and by n9kv, same binary). This matches the def's design note exactly: paging is owned
by the driver, `cisco_more_paging: false`, and we must NOT add `terminal length 0` to
`commands.pre`. n9kv honors `terminal length 0` like hardware. **PARITY-OK.**

**(c) `show running-config`.** n9kv runs the genuine NX-OS config parser and emits **complete,
real set/CLI-form running-config** — the same grammar `netcanon/migration/codecs/cisco_nxos`
round-trips (the MEMORY notes this codec is COMPLETE+CERTIFIED against a 6-config batfish
corpus). The control-plane is fully present: interfaces (`Ethernet1/X`, `mgmt0`), VLANs, SVIs,
BGP/OSPF, VRF contexts, `feature` toggles, route-maps, etc. all render exactly as on hardware.
The *only* things absent are pure-dataplane artifacts (real linecard inventory, ASIC counters)
— which are not in `running-config` and not in scope. **PARITY-OK for the config command.**

**(d) `show version` vs the three probe regexes.** This is the highest-risk spot (the seed
flags "any virtual-chassis banner that could break the model regex"). Verified against the
documented n9kv banner:

```
Nexus 9000v is a demo version of the Nexus Operating System Software
...
  NXOS: version 10.2(3) [build 10.2(2.185)] [Feature Release]
...
Hardware
  cisco Nexus9000 C9300v Chassis
  Intel(R) Xeon(R) CPU E5-2658 v4 @ 2.30GHz with 20499656 kB of memory.
  Processor Board ID 9GFDLI2JD0R
...
```

Regex-by-regex:

| Probe field | Regex | Banner line | Match | Captured value |
|---|---|---|---|---|
| os-version | `(?:NXOS\|system):\s+version\s+(\d+\.\d+)` | `  NXOS: version 10.2(3)` | ✅ | `10.2` |
| model | `cisco Nexus\S*\s+(\S+)\s+[Cc]hassis` | `cisco Nexus9000 C9300v Chassis` | ✅ | **`C9300v`** |
| serial | `Processor Board ID\s+(\S+)` | `Processor Board ID 9GFDLI2JD0R` | ✅ | `9GFDLI2JD0R` |

- **os-version: clean match → `10.2`.** Exactly the `major.minor` an overlay (`os_version:
  "10.x"`) would pin. The leading `Nexus 9000v is a demo version…` line does NOT interfere —
  it lacks the `NXOS:`/`system:` token, so the regex skips it and hits the real version line.
  *No regression from the "demo version" banner.*
- **model: matches, captures `C9300v`** (or `C9500v` for the 9500v image). `Nexus\S*` eats
  `Nexus9000`, `(\S+)` grabs `C9300v`, `[Cc]hassis` anchors. **The regex is NOT broken by the
  virtual SKU** — it captures successfully. The honest caveat: the captured *model string is a
  virtual SKU* (`C9300v` / `C9500v`), not a hardware SKU (`C93180YC-EX`, `C9336C-FX2`, …). For
  **validating that the def's collection pipeline works** this is a full pass — the regex fires
  and populates `detected_model`. It does NOT prove the regex handles *every* hardware SKU
  string, but the def's comment cites `cisco Nexus9000 C93180YC-EX Chassis` as the target, and
  the n9kv line is structurally identical (`Nexus9000 <SKU> Chassis`), so the same regex path
  is exercised. This is honest evidence, not theater.
- **serial: clean match.** n9kv generates a synthetic but well-formed Processor Board ID; the
  regex captures it. (On hardware it's a real FDO-style serial; structurally identical for the
  regex.)

**(e) Prompt for netmiko base_pattern.** netmiko's NX-OS driver tests the channel against
`[>#]` and sets the base prompt from `switch#`. n9kv's prompt satisfies this. No virtual banner
or MOTD breaks prompt detection (the "demo version" text appears only in `show version`, never
in the prompt). **PARITY-OK.**

**Net parity assessment:** Every one of the def's nine management-plane surfaces behaves on
n9kv exactly as documented for hardware. The single nuance — model regex captures a *virtual*
SKU `C9300v` — does not break the regex and is inherent to validating against any vendor
control-plane sim; it does not make the result theater because the regex *structure path*
(`Nexus9000 <token> Chassis`) is identical to hardware.

**Verdict on dimension 4: PARITY-OK.**

---

## 5. Verdict

### GO

Standing up Nexus 9000v in the Proxmox lab and pulling its `show running-config` over the
`CiscoNXOS` def is **worth something** — a PASS is honest evidence the def works on real
hardware, because n9kv *is* the real NX-OS software with an identical management plane (SSH,
no-enable `#` prompt, native `terminal length 0`, complete real `running-config`, and a
`show version` banner that hits all three probe regexes). This is the strongest of the three
provisional defs to validate (Cisco even ships it free).

**Biggest blocker (and it's only friction):** **RAM.** The standard image wants 8 GB, which
consumes an entire budget VM. Mitigation: use the **Nexus 9300v Lite** image (6 GB / 2 vCPU)
and dedicate one of the two 8 GB lab VMs to it (VM-B = device), exactly mirroring how VyOS
was validated, with the netcanon Docker app on VM-A. Plus the one-time boot recipe friction:
**OVMF/UEFI firmware (mandatory) + SATA disk bus + E1000 mgmt NIC + serial console to clear the
POAP prompt on first boot.**

**Severity tags:** `PARITY-OK` (real NX-OS software, mgmt-plane identical) ·
`FRICTION` (free CCO download + OVMF/SATA/E1000 boot recipe) ·
`RESOURCE-BLOCKER (soft)` (8 GB standard / 6 GB Lite — dedicate the VM; Lite recommended).
**Not `ACQUISITION-BLOCKER`** (free, no contract). **Not `THEATER`** (genuine NX-OS binary).

**Validation-readiness checklist for the lab:**
1. Download `nexus9300v.<rel>.qcow2` *or* the Lite `nxos64-cs-lite.<rel>.F.bin`/qcow2 from
   software.cisco.com under a CCO account (free).
2. Proxmox VM: OVMF BIOS, `qm importdisk` the qcow2 → attach as **sata0** (top boot priority),
   mgmt NIC = **E1000**, RAM **6 GB (Lite) or 8 GB (standard)**, 2 vCPU.
3. `qm terminal <vmid>`; at first boot answer the POAP prompt (skip), set `admin` password,
   `feature ssh` is on by default, configure `mgmt0` IP.
4. SSH `admin@<mgmt-ip>`; confirm prompt `switch#`, run `show version` (expect the regex hits
   above) and `show running-config`.
5. Point netcanon (Docker `netcanon/netcanon:0.3.0`) at it with the `CiscoNXOS` def; confirm
   backup pulls a complete config and probe populates os-version `10.x` / model `C9300v` /
   serial. On PASS, drop the `⚠ NOT YET VALIDATED` marker in `definitions/cisco/nx-os/10.x.yaml`
   `notes` (same move as VyOS PR #113).

---

## Sources

- Cisco Nexus 9000v (9300v/9500v) Guide, Release 10.5(x) — Overview & Lite NX-OS Image:
  https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/105x/configuration/n9000v-9300v-9500v/cisco-nexus-9000v-9300v-9500v-guide-release-105x/m-overview.html
- Cisco Nexus 9000v (9300v/9500v) Guide, Release 10.3(x) — Overview (show version banner / demo
  version / C9300v chassis):
  https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/103x/n9000v-n9300v-9500v/cisco-nexus-9000v-9300v-9500v-guide-release-103x/m-overview.html
- Cisco Nexus 9000v Switch product page (downloads / purpose):
  https://www.cisco.com/c/en/us/support/switches/nexus-9000v-switch/model.html
- Cisco Software Download portal (Nexus 9000v): https://software.cisco.com/download/home/285954710
- Cisco NX-OS Release Notes 10.2(3)F (Lite image `nxos64-cs-lite` introduction):
  https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/102x/release-notes/cisco-nexus-9000-nxos-release-notes-1023.html
- Karneliuk — "How to Run Cisco Nexus 9000v in Proxmox to Lab Cisco Data Centre" (Proxmox boot
  recipe: qcow2, OVMF, SATA, E1000, 8G/2vCPU, POAP, SSH):
  https://karneliuk.com/2022/05/infrastructure-4-how-to-run-cisco-nexus-9000v-in-proxmox-to-lab-cisco-data-centre/
- containerlab `vr-n9kv` kind (10 GB/4vCPU default, 6 GB/2 CPU Lite, admin:admin, ~5 min boot,
  qcow2-in-vrnetlab): https://containerlab.dev/manual/kinds/vr-n9kv/
- jpmondet/dockerized_n9kv (NX-OS 7.0.3.I7(9)/9.3(3)/9.3(7)/10.1(1) tested; ssh admin/admin
  confirmed): https://github.com/jpmondet/dockerized_n9kv
- Cisco DevNet — NX-OS 9000 node in Cisco Modeling Labs v2.10 (bundled NX-OS, min 4 vCPU
  reference): https://developer.cisco.com/docs/modeling-labs/nx-os-9000/
- Cisco DevNet — CML-Free (5-node, NX-OS NOT included; needs CML-Personal):
  https://developer.cisco.com/docs/modeling-labs/cml-free/
- Cisco Community — "Nexus 9000v licensing" (free to download, no contract):
  https://community.cisco.com/t5/network-security/nexus-9000v-licensing/m-p/3918036
- Cisco Learning Network — n9kv 10.1+ requires min 8 GB RAM to boot:
  https://learningnetwork.cisco.com/s/question/0D56e0000EBsV59CQF/hardware-requirements-for-using-nxos-and-iosxr-on-cisco-cml-272
- netmiko CiscoNxosSSH driver (session_preparation: `terminal width 511` + `disable_paging` →
  `terminal length 0`; base prompt `[>#]`):
  https://ktbyers.github.io/netmiko/docs/netmiko/cisco/cisco_nxos_ssh.html
- GNS3 marketplace — Cisco NX-OSv 9000 (older `nxosv9k-7.0.3.I7.x.qcow2` lineage):
  https://www.gns3.com/marketplace/appliances/cisco-nx-osv-9000
- EVE-NG — Cisco Nexus 9000v add guide (qcow2, format confirmation):
  https://www.eve-ng.net/index.php/documentation/howtos/howto-add-cisco-nexus-9000v-switch/
