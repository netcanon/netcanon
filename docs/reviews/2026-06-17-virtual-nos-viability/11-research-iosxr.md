# R2 — Cisco IOS-XR virtualization viability (CiscoIOSXR backup def)

**Author:** R2 (research) · **Date:** 2026-06-17 · **Process:** netcanon blackboard (read-only)
**Backup def under test:** `definitions/cisco/ios-xr/7.x.yaml` (`type_key: CiscoIOSXR`, netmiko driver `cisco_xr`)

## TL;DR verdict

**GO-WITH-FRICTION.** Cisco's own `IOS-XRd Control Plane` Docker container *is the real IOS-XR
software image* (same codebase as ASR 9000 / NCS), boots to the genuine `RP/0/RP0/CPU0:<host>#` CLI,
serves real `ssh server v2` on `MgmtEth0/RP0/CPU0/0`, and returns a real `show running-config` /
`show version`. It is light enough for the lab (control-plane flavor: **2 GiB RAM + 2 vCPU per
instance**, no hugepages, no PCI/IOMMU) and we *already lean on an "xrd corpus"* for the IOS-XR
fixtures, so XRd grammar is known-representative. **The single biggest blocker is acquisition:**
the image is gated behind a Cisco account with an *active service/support contract* on
`software.cisco.com` — there is **no anonymous free download**. Secondary friction: XRd requires
**cgroups v1** (modern hosts default to v2 → kernel-cmdline change + reboot), `apparmor=unconfined`,
and a couple of inotify sysctls. The free **DevNet XRd sandbox** sidesteps acquisition entirely and
is a legitimate validation path if SSH-reachable from netcanon. **PARITY-OK** on the exact backup
surface; the only divergence is cosmetic (`detected_model` token), not a collection break.

---

## 1. What virtual image(s) exist (2026-current)

Cisco ships **two distinct IOS-XR virtual products**, both running the *real* IOS-XR NOS (control-plane
software shared with hardware ASR 9000 / NCS-class platforms — **vendor software, not a third-party
reimplementation**):

| Product | Form | Dataplane | Use cases | Status for our purpose |
|---|---|---|---|---|
| **IOS-XRd Control Plane** | Docker **container** (`x86_64` tarball) | none (control-plane only) | vRR, SR-PCE, route-reflector, NETCONF/gNMI/YANG labs | **Best fit** — lightest, real CLI, real SSH |
| **IOS-XRd vRouter** | Docker **container** | full software dataplane (DPDK) | vPE, vCSR, cloud router needing forwarding | overkill + heavy (hugepages, vfio-pci) |
| **IOS-XRv 9000 (XRv9k)** | KVM/ESXi **VM** (qcow2/OVA) | software dataplane | legacy "virtual ASR9k" VM, runs in CML | heavier VM; fine but no advantage over XRd CP |

- **XRd is the modern, container-native successor.** containerlab, CML, and Cisco's own docs treat
  XRd as the current virtual IOS-XR; XRv9000 is the older VM lineage.
- **It is the real software.** The `show version` banner reads `Cisco IOS XR Software, Version 7.7.1`
  (or 24.x/25.x on newer trains) and `cisco XRd Control Plane cisco XRd-CP-C-01 processor with 32GB
  of memory` — i.e. identical IOS-XR codebase, only the chassis identity string differs from hardware.
- **Dataplane parity is irrelevant** to netcanon's backup (per the seed: we only do management-plane
  SSH collection), so the Control-Plane flavor's lack of forwarding is a non-issue.

Sources: [XRd images: Where can one get them? (xrdocs)](https://xrdocs.io/virtual-routing/tutorials/2022-08-22-xrd-images-where-can-one-get-them),
[XRd with docker: Control-Plane and vRouter (xrdocs)](https://xrdocs.io/virtual-routing/tutorials/2022-08-23-xrd-with-docker-control-plane-and-vrouter),
[Cisco IOS XRd series (cisco.com)](https://www.cisco.com/c/en/us/support/routers/ios-xrd/series.html),
[IOS XRv 9000 — CML node (DevNet)](https://developer.cisco.com/docs/modeling-labs/ios-xrv-9000/),
[Red Hat catalog: Cisco IOS XRd Control Plane](https://catalog.redhat.com/en/software/container-stacks/detail/647ef796c0702939ecc381ed).

---

## 2. Acquisition + licensing  — **the gating dimension**

- **Where:** `software.cisco.com` —
  Control Plane: `https://software.cisco.com/download/home/286331236/type/280805694`,
  vRouter: `https://software.cisco.com/download/home/286331238/type/280805694`. Distributed as a
  signed tarball (e.g. `xrd-control-plane-container-x64.7.7.1.tgz`) you `docker load`.
- **Licensing reality (the blocker):** XRd images are **"available for download only for users who
  have an active service account."** Multiple primary sources state a Cisco account *with software-
  download privileges / an active support contract* is required; if your account lacks privileges
  you are told to "contact your Cisco Sales Representative." **There is no free-to-any-registered-user
  download** the way Nexus 9000v / some CSR1000v evals were. → tag **ACQUISITION-BLOCKER**.
  - Note the contrast with the VyOS validation: VyOS was a free, real-OS rolling image. Cisco XRd is
    **not** freely downloadable without a commercial relationship. Do **not** cargo-cult the VyOS outcome.
- **Once obtained, running it privately is permitted** under the Cisco lab/eval terms — XRd is
  explicitly positioned for lab/dev/CI use. We are not committing or redistributing the image (the run
  rules forbid that anyway), so the only legal question is *can we download it*, which hinges on the
  account/contract above.
- **Two contract-free escape hatches:**
  1. **DevNet XRd Sandbox** (free, reservation-based) — Cisco hosts XRd for you; "perfect to get
     familiar with XRd … YANG/NETCONF/gNMI." If the sandbox node is reachable over SSH from a
     netcanon instance (DevNet sandboxes expose SSH/VPN), this validates the def with **zero image
     acquisition**. *Caveat:* sandbox networking may require Cisco's AnyConnect/VPN reservation rather
     than a clean SSH path to our Proxmox lab — needs a live check.
  2. **IOS-XRv 9000 in CML** runs "in *demo mode* … without any additional licensing" — but CML
     itself is a paid product, so this only helps if a CML instance already exists (it does not in
     our lab budget).

Sources: [XRd images: Where can one get them? (xrdocs)](https://xrdocs.io/virtual-routing/tutorials/2022-08-22-xrd-images-where-can-one-get-them),
[Software Download — XRd Control Plane (cisco.com)](https://software.cisco.com/download/home/286331236/type/280805694),
[containerlab — Cisco XRd](https://containerlab.dev/manual/kinds/xrd/) ("XRd image is available for
download only for users who have an active service account"),
[Explore network programmability with the DevNet XRd Sandbox (Cisco Blogs)](https://blogs.cisco.com/developer/explore-network-programmability-with-the-devnet-xrd-sandbox),
[CiscoDevNet/XRd-Sandbox](https://github.com/CiscoDevNet/XRd-Sandbox),
[IOS XRv 9000 — CML node (DevNet)](https://developer.cisco.com/docs/modeling-labs/ios-xrv-9000/).

---

## 3. Run on our lab (Proxmox/KVM, hard budget a modest two-VM lab)

XRd is a **container**, so it runs *inside* a Linux VM on Proxmox (no nested virt needed — it is not
itself a VM). Plan: one Ubuntu/Rocky VM (within the modest-lab budget) runs Docker + the XRd CP container;
netcanon (the `netcanon/netcanon:0.3.0` Docker app VM) SSHes into it. Authoritative resource figures
come from Cisco's `xrd-tools` **`host-check`** script — the canonical per-platform requirement source:

### Control Plane (what we'd use) — fits the budget comfortably
- **RAM:** **2 GiB per container** minimum (host-check `XRd Control Plane` check).
- **CPU:** **2 cores** minimum.
- **Hugepages:** **none required.**
- **PCI/IOMMU/vfio-pci:** **not required** (those are vRouter-only).
- **Disk:** container image tarball is a few GB; ~7 GB working footprint is ample.
- Net: one CP instance fits easily in a single modest-lab VM with room to spare.

### vRouter (not needed) — would strain the budget
- **RAM:** 5 GiB/container (host-check); Cisco deployment manifests reserve **16 GiB** + `hugepages-1Gi: 6Gi`.
- **Hugepages:** **3 GiB of 1 GiB-pages per instance** (kernel cmdline `hugepages=N` or sysctl).
- **CPU extensions** `ssse3, sse4_1, sse4_2`; **PCI driver** `vfio-pci`/`igb_uio`; IOMMU recommended.
- → would chew most of one 8GB VM and add hugepage/IOMMU plumbing. **Avoid** — no benefit for
  management-plane validation.

### Host prerequisites (the FRICTION) — apply to the Docker VM
| Requirement | Detail | Friction |
|---|---|---|
| **Kernel** | ≥ 4.6 (host-check); practical guides use 5.15+. RHEL/CentOS 8.3 kernel `4.18.0-240` explicitly rejected | low — modern distro fine |
| **cgroups** | **v1 required**; host-check fails with *"Cgroups version 2 is in use, but this is not supported by XRd"* on v2 hosts. Modern Ubuntu 22.04 / Rocky 9 default to **v2** → set `systemd.unified_cgroup_hierarchy=false` on the kernel cmdline + **reboot** | **MEDIUM — kernel-cmdline change + reboot** |
| **apparmor** | XRd "cannot run with the default docker profile"; run with `--security-opt apparmor=unconfined` (or install the `xrd-unconfined` profile host-check looks for) | low — one docker flag |
| **kernel modules** | `dummy`, `nf_tables` loaded | low |
| **inotify sysctls** | `fs.inotify.max_user_instances` ≥ 4000 (rec. 64000), `max_user_watches` ≥ 64000 | low — two sysctls |
| **Docker** | client+daemon ≥ 18.0; FS supports `d_type` | trivial |

**Verification tooling exists:** Cisco's `ios-xr/xrd-tools` repo ships `host-check` (run it to confirm
the VM is ready, PASS/FAIL per requirement) and `launch-xrd` (one-shot container launcher, e.g.
`sudo ./launch-xrd localhost/ios-xr:7.7.1`). containerlab also supports XRd (control-plane only — it
notes the **vrouter is incompatible because it needs PCI interfaces**) and would be the cleanest
orchestration path if we want repeatability.

> **Could XRd CP run on the netcanon VM-A host?** Yes — co-locating the XRd container on the same
> Docker host as netcanon is technically possible (2 GiB + 2 cores fits), **but** the cgroups-v1
> requirement is host-global: flipping the netcanon VM to cgroups v1 affects *all* its containers and
> needs a reboot. Cleaner to put XRd on the **second** lab VM (the modest-lab sibling) and keep netcanon's
> host on its default cgroups. Either way we stay inside the modest two-VM lab budget. **No RESOURCE-BLOCKER
> for the Control-Plane flavor.**

Sources: [xrd-tools `host-check` script](https://raw.githubusercontent.com/ios-xr/xrd-tools/main/scripts/host-check),
[ios-xr/xrd-tools (GitHub)](https://github.com/ios-xr/xrd-tools),
[Setting up the Host Environment to run XRd (xrdocs)](https://xrdocs.io/virtual-routing/tutorials/2022-08-22-setting-up-host-environment-to-run-xrd),
[Setup — Cisco XRd with XRD-Tools (mirror)](https://hmntsharma.github.io/cisco-xrd/base_setup/) (kernel 5.15,
cgroups v1 via `systemd.unified_cgroup_hierarchy=false`, `docker load`, `launch-xrd`),
[containerlab — Cisco XRd](https://containerlab.dev/manual/kinds/xrd/) (control-plane only, inotify tuning),
[XRd on OpenShift (xrdocs)](https://xrdocs.io/virtual-routing/tutorials/2023-05-02-xrd-on-openshift/).

---

## 4. Management-plane parity for the backup surface — **the crux** (PARITY-OK)

The CiscoIOSXR def drives, via netmiko `cisco_xr`, exactly: `show running-config` for config, a
`show version` probe, prompt regexes `^RP/\S+:\S+#\s*$` (+ generic `^\S+[#>]\s*$`), `needs_enable: false`,
`cisco_more_paging: false` (netmiko owns paging). Mapping each to XRd CP behavior:

| Backup-def expectation | XRd Control Plane behavior | Match? |
|---|---|---|
| **Prompt** `^RP/\S+:\S+#\s*$` | XRd CP boots to **`RP/0/RP0/CPU0:ios#`** (default hostname `ios`; becomes `RP/0/RP0/CPU0:<hostname>#`). Real IOS-XR RP prompt, byte-identical to hardware | **YES** — primary regex matches |
| **`needs_enable: false`** (SSH lands in exec; no enable) | IOS-XR has **no enable mode** — SSH lands in exec, privilege is task-group based. Exactly as the def's note says | **YES** |
| **Paging** — netmiko `cisco_xr` `session_preparation()` sends `terminal width 511` + `terminal length 0` | IOS-XR natively supports `terminal length 0` / `terminal width`; the driver disables paging itself. Def correctly keeps `cisco_more_paging: false` and does **not** put `terminal length 0` in `commands.pre` | **YES** |
| **`show running-config`** returns real, complete CLI-form config | XRd CP returns the genuine IOS-XR running-config (hierarchical `interface MgmtEth0/RP0/CPU0/0 … !`, `ssh server v2`, `router bgp`, etc.) — **the same grammar the `cisco_iosxr` codec parses**, and the same lineage as netcanon's existing "xrd corpus" fixtures | **YES — and self-consistent with our fixtures** |
| **`show version`** probe `detected_os_version` = `Cisco IOS XR Software, Version\s+(\d+\.\d+)` | Banner reads `Cisco IOS XR Software, Version 7.7.1` (and `24.x`/`25.x`/`26.x` on newer trains). Regex captures `7.7` / `24.1` etc. | **YES** |
| **`show version`** probe `detected_model` = `^cisco\s+(\S+)` | Banner reads `cisco XRd Control Plane cisco XRd-CP-C-01 processor with 32GB of memory` → first token after leading `cisco` is **`XRd`** (hardware would yield `ASR9K`/`NCS-5501`) | **PARTIAL — cosmetic only** (see below) |
| **SSH server** | XRd CP runs real `ssh server v2` on `MgmtEth0/RP0/CPU0/0`; containerlab auto-maps `eth0`→Mgmt and exposes SSH (user/pass e.g. `clab/clab@123`, or operator-configured `cisco`) | **YES** |

### The one divergence — and why it's not a blocker
`detected_model` will resolve to `XRd` on the VM vs `ASR9K`/`NCS-5501` on hardware. This is:
- **Cosmetic, not a collection break.** The probe is explicitly *non-fatal* (def comment:
  "Failure is non-fatal"); it only populates `DeviceProfile.detected_facts` and feeds overlay
  resolution. `show running-config` — the actual deliverable — is unaffected.
- **A real but minor caveat for the reviewer:** a PASS against XRd proves the *config command, prompt,
  paging, no-enable, and version-regex* all work on real IOS-XR software. It does **not** independently
  prove the `detected_model` regex captures a *hardware* platform string, because the VM emits `XRd`.
  That sub-claim stays "verified against sample `show version` output only" — but it is one regex
  against a documented, stable hardware banner, and the def comment already scopes the probe as
  advisory. Honest framing: validating against XRd lets us drop the `⚠ NOT YET VALIDATED` marker for
  the **collection wiring** (driver, prompt, paging, config command, version probe), with a one-line
  note that the model-string capture is confirmed only against documented hardware output.

**No THEATER here:** XRd CP is the vendor's *real IOS-XR software*, presenting the *real* management
plane the def touches. A PASS is honest evidence the def collects from real IOS-XR routers — exactly
the bar the seed sets. This is the strongest of the three NOS cases precisely because netcanon's
IOS-XR fixtures already derive from an xrd corpus, so the VM and our test expectations share a lineage.

Sources: [XRd with docker (xrdocs)](https://xrdocs.io/virtual-routing/tutorials/2022-08-23-xrd-with-docker-control-plane-and-vrouter)
(`RP/0/RP0/CPU0:ios#`, `cisco XRd Control Plane … processor with 30GB/32GB of memory`),
[Setup — Cisco XRd (mirror)](https://hmntsharma.github.io/cisco-xrd/base_setup/) (boots to console,
`RP/0/RP0/CPU0:ios#`, `show version` / `show platform`),
[netmiko `cisco_xr` API docs](https://ktbyers.github.io/netmiko/docs/netmiko/cisco/cisco_xr.html) +
[netmiko session_preparation discussion #3154](https://github.com/ktbyers/netmiko/discussions/3154)
(`terminal width 511` + `terminal length 0` in `session_preparation`),
[XRd Control Plane on OpenShift (xrdocs)](https://xrdocs.io/virtual-routing/tutorials/xrd-control-plane-on-openshift)
(`ssh server v2` on `MgmtEth0/RP0/CPU0/0`),
[containerlab — Cisco XRd](https://containerlab.dev/manual/kinds/xrd/) (SSH creds, mgmt iface mapping).

### Version-train note for the def
`version_match: "^7\\."` is **advisory** (the def comment says so) and the `detected_os_version`
regex captures any `\d+\.\d+`, so it still works on the newer **24.x / 25.x / 26.x** IOS-XR calendar
trains. If we validate against a 7.7.1 XRd CP image the version pin matches literally; against a 25.x
image the regex still extracts `25.1` cleanly and resolution falls back to base — no code change needed,
but worth a one-line awareness note when picking which XRd tarball to pull.

---

## 5. Verdict — **GO-WITH-FRICTION**

| Dimension | Finding | Tag |
|---|---|---|
| Image exists & is real NOS | XRd Control Plane container = real IOS-XR software | PARITY-OK |
| Acquisition / licensing | `software.cisco.com`, needs Cisco account **with service contract**; no anon free DL. DevNet sandbox = free escape hatch | **ACQUISITION-BLOCKER** / FRICTION |
| Lab runnability | CP = 2 GiB + 2 vCPU, no hugepages — fits a modest two-VM lab; but **cgroups v1** + apparmor-unconfined + inotify | FRICTION (no RESOURCE-BLOCKER) |
| Mgmt-plane parity | prompt, no-enable, paging, `show run`, version probe all match real IOS-XR; xrd-corpus lineage | PARITY-OK |
| Single divergence | `detected_model` → `XRd` not `ASR9K` (cosmetic, non-fatal probe) | minor caveat |

**Biggest blocker:** *acquisition* — obtaining the XRd Control Plane image requires a Cisco.com
account with an active service/support contract (no free anonymous download). If we have such an
account, this is the easiest of the three NOS to validate and is genuinely worth it. If we do not,
the **DevNet XRd sandbox** (free) is the recommended path, contingent on a live check that the
sandbox node is SSH-reachable from a netcanon instance.

**Friction if GO:** (1) get the image (account/contract or DevNet sandbox); (2) put XRd CP on the
second lab VM with **cgroups switched to v1** (kernel cmdline + reboot), `apparmor=unconfined`, and
the inotify sysctls; run Cisco's `host-check` to confirm green; (3) bring up `ssh server v2` on
`MgmtEth0/RP0/CPU0/0`; (4) point netcanon `0.3.0` at it and run the backup. Expect a clean PASS on
collection wiring; footnote the `detected_model` string as VM-cosmetic.

**Recommended priority among the three:** IOS-XR is the **strongest worth-it case** — real vendor
software, lightest control-plane footprint, and we already trust XRd-derived fixtures — *if and only
if* the acquisition gate (account/contract or working DevNet sandbox SSH path) is cleared. That gate,
not resources or parity, is the deciding variable.
