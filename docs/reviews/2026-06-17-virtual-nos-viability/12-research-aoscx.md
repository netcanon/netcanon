# R3 — Aruba AOS-CX virtualization viability (validate the `ArubaCX` backup def)

**Author:** R3 (research) · **Date:** 2026-06-17 · **NOS:** Aruba AOS-CX (CX 6000/8000/10000) · **type_key:** `ArubaCX`
**Def under test:** `definitions/aruba/aos-cx/10.x.yaml` · **Codec:** `netcanon/migration/codecs/aruba_aoscx`

## TL;DR verdict

**GO-WITH-FRICTION.** Aruba/HPE ships its own first-party control-plane image — the **AOS-CX Switch
Simulator** (a real AOS-CX OS image driving an ASIC *simulator*, not a third-party reimplementation). It
runs cleanly on Proxmox/KVM at **4 GB RAM / 2 vCPU** (well inside the modest two-VM lab budget), converts
OVA/VMDK → qcow2 with a one-line `qemu-img`, and presents a **real SSH server with the real AOS-CX CLI**:
the prompt, `no page` paging, `configure term`, `show running-config`, and `show version` all behave
exactly as the `aruba_aoscx` netmiko driver (and our def) assume. For the four things the backup def
actually exercises — prompt regex, paging, `show running-config` grammar, SSH — the simulator is a
**faithful management-plane twin of hardware.**

The friction is two-fold and both are real but surmountable:

1. **ACQUISITION** — the image is **free but gated behind an HPE/Aruba account** on the HPE Networking
   Support Portal (registration + EULA). Not anonymous like VyOS, but not paid either.
2. **One probe divergence (`THEATER`-adjacent but minor)** — the simulator's `show version` reports
   **`Version : Virtual.10.13.1110`**, i.e. the platform prefix is the literal word **`Virtual`**, NOT
   the **two-letter hardware code** (`FL`/`GL`/`TL`/…) that the def's probe regex
   `Version\s*:\s*[A-Z]{2}\.(\d+\.\d+)` requires. So the **probe's version-capture would NOT fire on the
   simulator** even though it fires on hardware. The probe is documented `non-fatal`, so backup itself
   still succeeds — but a "PASS" on the simulator would NOT prove the regex matches real hardware. This is
   the single most important nuance for the parity-skeptic. Verdict stays GO-WITH-FRICTION because the
   *hardware* regex is independently confirmed correct (see §4) and the def's high-value surface
   (`show running-config` collection) is fully validated by the simulator.

**Biggest blocker:** HPE/Aruba account-gated download (FRICTION, not a wall) + the `Virtual.` vs
`[A-Z]{2}.` probe-regex mismatch that makes the version-probe specifically un-validatable on the sim.

---

## 1. What virtual image exists — and is it the real AOS-CX software?

| Attribute | Finding | Source |
|---|---|---|
| Product name | **Aruba / HPE Networking AOS-CX Switch Simulator** (a.k.a. "CX Simulator", `Aruba_AOS-CX_Switch_Simulator`) | GNS3 marketplace; Airheads |
| What it is | "The virtual machine version of the Aruba CX switch series. At its core an **ASIC simulator** performs switching and routing functions with **the AOS-CX operating system managing and controlling** the device's operation." → **first-party real NOS, control-plane-identical**; only the dataplane is simulated. | GNS3 / Airheads |
| Vendor-real vs reimplementation | **Vendor-real.** It is the same AOS-CX build family shipped on hardware — disk images are named `arubaoscx-disk-image-genericx86-p4-<timestamp>.vmdk` (a `genericx86-p4` *platform build* of the real OS). **Not** a third-party reimplementation. | GNS3 appliance file (`aruba-arubaoscx.gns3a`) |
| Latest version (2026-current) | **10.15.0005** (`...-20241115202521.vmdk`) is the newest in the GNS3 registry; netlab reports testing against **10.15**. Older trains down to 10.01 are also published. The def targets the **10.x** train, so any of these is in-scope. | GNS3 registry; netlab |
| Ports | 10 interfaces total (1 management `1/1/1` + 9 data), virtio-net-pci. Enough for the management-plane test (we only need mgmt). | GNS3 appliance; containerlab |

**Image/version matrix (GNS3 registry, real OS builds):**

| AOS-CX version | VMDK filename |
|---|---|
| 10.15.0005 | `arubaoscx-disk-image-genericx86-p4-20241115202521.vmdk` |
| 10.14.1000 | `arubaoscx-disk-image-genericx86-p4-20240731173624.vmdk` |
| 10.13.1000 | `arubaoscx-disk-image-genericx86-p4-20240129204649.vmdk` |
| 10.12.1000 | `arubaoscx-disk-image-genericx86-p4-20230810165021.vmdk` |
| 10.11.0001 | `arubaoscx-disk-image-genericx86-p4-20221130174651.vmdk` |
| 10.10.1000 | `arubaoscx-disk-image-genericx86-p4-20220815162137.vmdk` |
| … (down to 10.01.0001) | … |

**Conclusion:** This is exactly the "control-plane sim running the vendor's real NOS" the seed says is
"as good as hardware for THIS purpose." `PARITY-OK` on the software-realness axis. The `genericx86-p4`
build is the real OS; the simulated piece (ASIC/forwarding) is the part the backup def never touches.

---

## 2. Acquisition + licensing

| Question | Answer |
|---|---|
| Where do you get it | **HPE Networking / Aruba Support Portal** ("Software & Documents" → search `Aruba_AOS-CX_Switch_Simulator`). Distributed as a `.zip` containing an OVA. | Airheads "Downloading the Aruba AOS-CX Switch Simulator"; GNS3 init page |
| Account required | **Yes — a free HPE/Aruba account (registration + accept EULA).** Not a paid product; "free to registered users." This is the VyOS-vs-Cisco difference the seed warns about: VyOS was anonymous; AOS-CX needs a (no-cost) login. | Airheads; GNS3 |
| Paid / eval / licence file | **No paid licence and no licence-server / feature licence file** required to run the simulator. It boots and runs the full CLI for free. (Contrast: Cisco n9kv/XRv often need Smart Licensing tokens.) | GNS3 marketplace; Airheads |
| Redistribution | **Restricted** — the image is downloaded under HPE's EULA; we must **not** commit it to git or redistribute (consistent with our "never commit images" rule). Each lab operator downloads under their own account. | HPE EULA (download-gated) |
| Blocked without commercial relationship? | **No.** A free HPE account is sufficient; no reseller/partner/support-contract relationship is needed to obtain the simulator. | Airheads |

**Severity:** `FRICTION` (account + EULA), **not** `ACQUISITION-BLOCKER`. We can legally download and run
it in a private lab with a free login.

---

## 3. Run it on our Proxmox/KVM lab

| Dimension | Finding | Source |
|---|---|---|
| Format | OVA (zip) → contains a **VMDK** (`arubaoscx-disk-image-genericx86-p4-*.vmdk`). | GNS3 registry |
| OVA/VMDK → qcow2 | One line: `qemu-img convert -f vmdk -O qcow2 arubaoscx-disk-image-genericx86-p4-20221130174651.vmdk arubacx-10.11.qcow2`. Well-trodden — this is exactly how vrnetlab/containerlab and netlab package it. | containerlab `vr-aoscx`; vrnetlab |
| Boot on KVM/libvirt | Three documented paths, all on plain KVM/QEMU: (a) **import the qcow2 directly into a Proxmox VM** (q35/virtio, no nested virt needed — it is an x86 OS, not nested hypervisor); (b) **netlab** `netlab libvirt package arubacx <ova>` builds a Vagrant/libvirt box; (c) **containerlab `vr-aoscx`** wraps the qcow2 in vrnetlab (QEMU-in-docker). For our lab the simplest is the direct Proxmox-qcow2 import. | netlab; containerlab; vrnetlab |
| RAM | **4096 MB** (GNS3 appliance `ram: 4096`; vrnetlab launches QEMU with `-m 4096`). | GNS3 appliance; vrnetlab |
| vCPU | **2** (GNS3 `cpus: 2`). | GNS3 appliance |
| Disk | Single VMDK/qcow2, a few GB. | GNS3 registry |
| NIC model | `virtio-net-pci`, 8 data adapters (+ mgmt) in GNS3; mgmt is `1/1/1`. | GNS3 appliance; containerlab |
| Console | Telnet/serial console exposed by QEMU; SSH on the mgmt interface once configured. Boot to login ~2 min (containerlab); first-boot/key-gen a bit longer. | GNS3; containerlab |
| KVM accel | KVM required (`kvm: required` in GNS3 appliance) — the lab host provides this natively; **no nested-virt** needed for the guest itself. | GNS3 appliance |
| vNICs / serial for our test | We only need the **management vNIC + SSH**. Trivial. | — |

**Resource verdict vs the modest two-VM lab budget:** **4 GB / 2 vCPU is comfortably inside one of the two
8 GB VMs**, leaving headroom for the OS and the netcanon app VM. No 16 GB problem. (The "16 GB / 4 vCPU"
figure seen in the *Codespaces* arubavsx labs is a recommendation for **multi-node topologies in a
codespace**, not the per-instance requirement — a single sim node is 4 GB.)

**Severity:** `FRICTION` only (OVA→qcow2 conversion + portal download); **no** `RESOURCE-BLOCKER`.

---

## 4. Management-plane parity — the crux

The def exercises exactly: (1) prompt regex, (2) paging via the `aruba_aoscx` driver, (3) `show
running-config` grammar, (4) `show version` probe regex. Point-by-point against the simulator:

### 4.1 Prompt regex — **PARITY-OK**
- Def trailing prompt: `^\S+[#>]\s*$` (e.g. `switch#` / `switch>`).
- netmiko `aruba_aoscx` (`ArubaCxSSH`, inherits `CiscoSSHConnection`) tests the channel with pattern
  `r"[>#]"` and the simulator lands at the manager `#` prompt (`agg-1#` in the arubavsx example).
- The simulator's prompt is produced by the **real AOS-CX CLI** → identical to hardware. ✔
- Source: netmiko `aruba.aruba_aoscx` API docs; arubavsx README (`agg-1#`).

### 4.2 Paging (`no page`) — **PARITY-OK**
- Def: `cisco_more_paging: false`, relies on the driver. netmiko's `ArubaCxSSH.session_preparation()`
  calls `disable_paging(command="no page")` and sets `ansi_escape_codes = True`.
- `no page` is a **real AOS-CX command** present in the simulator's CLI (same OS). The driver's paging
  disable works identically on sim and hardware. ✔
- Source: netmiko `aruba.aruba_aoscx` API docs (`disable_paging(command="no page")`).

### 4.3 `show running-config` grammar — **PARITY-OK (high-value surface)**
- Def `config: "show running-config"`.
- The simulator runs the **same AOS-CX OS** that generates running-config on hardware; the
  CLI grammar the `aruba_aoscx` migration codec parses (VLAN/interface/`no routing` L2 opt-in,
  active-gateway, BGP/OSPF, VRF) is produced **byte-for-byte by the same code path** as hardware. The
  netlab build even copy-pastes AOS-CX config during box creation — confirming the sim takes/returns
  real config. This is **exactly the parity that matters** for the backup, and it's solid. ✔
- Caveat for the skeptic: the simulator omits **hardware-only stanzas** that have no meaning without an
  ASIC/linecard (e.g. transceiver/PoE/some QoS-hardware knobs). The backup just *collects whatever the
  device emits*, so this is not a parse failure — but a sim running-config will be **narrower** than a
  fully-featured hardware config. A PASS proves the collector + codec handle real AOS-CX grammar; it does
  **not** exercise hardware-only stanzas the sim can't produce. (Tag this `FRICTION`, not `THEATER` — the
  grammar is identical, only the surface coverage is a subset.)
- Source: GNS3/Airheads ("ASIC simulator … OS managing the device"); netlab build guide.

### 4.4 `show version` probe regex — **THE DIVERGENCE (FRICTION / partial-THEATER)**
This is the load-bearing finding and the one place the simulator is **not** a faithful twin.

- Def probe regex: `detected_os_version: 'Version\s*:\s*[A-Z]{2}\.(\d+\.\d+)'` — requires **exactly two
  uppercase letters then a dot** (the hardware platform code).
- **Hardware** `show version` Version line (confirmed): `Version : FL.10.10.0001` (6300/6400),
  `Version : GL.10.07.xxxx` (8320). The `[A-Z]{2}\.` regex **matches** these (`FL.`, `GL.`, `TL.`, `XL.`,
  `RL.`, `PL.`, …). ✔ on hardware.
- **Simulator** `show version` Version line (confirmed from TWO independent first-party-derived sources —
  the Shajeervu/arubavsx and cheddarking/arubavsx containerlab labs):
  ```
  Version      : Virtual.10.13.1110
  Build Date   : ...
  Build ID     : ArubaOS-CX:Virtual.10.13.1110:40649b64b204:202506162315
  ```
  The platform prefix is the **literal word `Virtual`**, not a two-letter code.
- **Regex behaviour on the sim:** `[A-Z]{2}\.` would try to match `Vi` followed by `.` — but `Vi` is
  followed by `rtual`, not a dot → **NO MATCH**. The probe would fail to extract `detected_os_version` on
  the simulator (it would on hardware). Because the probe is documented **non-fatal**, the *backup itself
  still succeeds* (prompt + paging + `show running-config` all work), so the def is still validated on its
  high-value path. But the **version-probe specifically cannot be validated against the sim** — a sim PASS
  proves nothing about the regex, and the regex is only confirmed correct on *hardware* via the
  independent FL./GL. evidence above.

**Net parity:** 3 of the 4 surfaces (prompt, paging, running-config) are **PARITY-OK** on the simulator.
The 4th (version probe) **diverges** because the sim's platform code is `Virtual`, not `[A-Z]{2}`. The
divergence is *known, bounded, and explained by independent hardware evidence* — so it's `FRICTION` with
a thin slice of `THEATER` (the probe line specifically), not a wholesale theater verdict.

> **Actionable note for the main thread (NOT an edit by me):** if the team wants the version-probe to be
> validatable on the simulator too, the regex could be widened from `[A-Z]{2}\.` to something like
> `(?:[A-Z]{2}|Virtual)\.(\d+\.\d+)` or `[A-Za-z]+\.(\d+\.\d+)`. That would make the sim a full twin for
> all 4 surfaces. As-is, dropping the `⚠ NOT YET VALIDATED` marker on the strength of a sim run is
> *defensible for the collection path but overstated for the probe* — call that out in synthesis.

---

## 5. Verdict

**GO-WITH-FRICTION.**

| Axis | Result |
|---|---|
| Real vendor NOS? | **Yes** — first-party AOS-CX OS (`genericx86-p4` build), ASIC-only simulated. `PARITY-OK`. |
| Acquirable in a private lab? | **Yes**, free, but **HPE/Aruba account + EULA** gate. `FRICTION`. |
| Runs on our Proxmox/KVM budget? | **Yes** — 4 GB / 2 vCPU, OVA→qcow2 one-liner, no nested virt. `FRICTION` (conversion) only. |
| Mgmt-plane parity for the backup surface | prompt ✔, `no page` paging ✔, `show running-config` ✔ (subset of hardware stanzas); **`show version` probe ✗** (sim prefix `Virtual.` ≠ `[A-Z]{2}.`). |
| Worth something / not theater? | **Mostly yes.** A sim PASS genuinely proves the collector + codec + prompt + paging work on real AOS-CX grammar. The **version-probe alone is un-validatable on the sim** and stays hardware-confirmed only. |

**Single biggest blocker:** the HPE/Aruba account-gated download (free, but not anonymous) — and the
secondary, more interesting gotcha that the simulator's `show version` carries a **`Virtual.` platform
prefix** instead of the two-letter hardware code, so the def's probe regex (as written) **will not fire on
the simulator** and that specific line cannot be validated this way.

**Severity tags:** `PARITY-OK` (software realness, prompt, paging, running-config) · `FRICTION` (account +
OVA→qcow2 conversion + sim config is a subset of hardware stanzas) · partial `THEATER` scoped to the
`show version` probe line (`Virtual.` vs `[A-Z]{2}.`).

---

## Sources
- GNS3 marketplace — ArubaOS-CX Simulation Software: https://www.gns3.com/marketplace/appliances/arubaos-cx-simulation-software
- GNS3 server appliance def (RAM/vCPU/NIC/image matrix): https://github.com/GNS3/gns3-server/blob/master/gns3server/appliances/aruba-arubaoscx.gns3a
- netlab — Building an ArubaOS-CX Libvirt Box (OVA filename, netlab package, tested 10.15, admin creds): https://netlab.tools/labs/arubacx/
- containerlab — Aruba AOS-CX kind (`admin:admin`, mgmt `1/1/1`, ~2 min boot, vrnetlab): https://containerlab.dev/manual/kinds/vr-aoscx/
- containerlab — vrnetlab integration (qemu-img vmdk→qcow2 one-liner, `-m 4096`): https://containerlab.dev/manual/vrnetlab/
- Shajeervu/arubavsx (sim `show version` → `Version : Virtual.10.13.1110`, `admin:admin`): https://github.com/Shajeervu/arubavsx
- cheddarking/arubavsx (independent confirmation of `Virtual.10.13.1110` Build ID `ArubaOS-CX:Virtual...`): https://github.com/cheddarking/arubavsx
- netmiko `aruba.aruba_aoscx` API (ArubaCxSSH: `disable_paging("no page")`, prompt `[>#]`, `ansi_escape_codes=True`, `configure term`): https://ktbyers.github.io/netmiko/docs/netmiko/aruba/aruba_aoscx.html
- aruba/aoscx-ansible-collection (min firmware 10.04, SSH + REST): https://github.com/aruba/aoscx-ansible-collection
- Airheads — Downloading the Aruba AOS-CX Switch Simulator (portal, registration, free): https://airheads.hpe.com/discussion/downloading-the-aruba-aos-cx-switch-simulator
- HPE blog — Explore CX Switches with the AOS-CX Switch Simulator: https://blogs.arubanetworks.com/solutions/explore-aruba-cx-switches-with-the-aos-cx-switch-simulator/
- Hardware Version-line format (FL.10.x on 6300/6400, GL.10.x on 8320) via AOS-CX release-notes / show-version docs: https://arubanetworking.hpe.com/techdocs/AOS-CX/10.11/HTML/fundamentals_6300-6400/Content/SysHW_cmds/sho-ver-10.htm
- Repo def under test: `definitions/aruba/aos-cx/10.x.yaml` (probe regex `Version\s*:\s*[A-Z]{2}\.(\d+\.\d+)`, `aruba_aoscx`, `no page`, no enable)
