# 99 — Synthesis: is virtualizing NX-OS / IOS-XR / AOS-CX worth it to validate the 3 provisional backup defs? (2026-06-17)

**Author:** main thread. **Inputs:** R1 NX-OS (`10-`), R2 IOS-XR (`11-`), R3 AOS-CX (`12-`),
V1 parity-skeptic (`30-`). This was a **read-only research run** — no code changed.

## Verdict: all three are virtualizable with REAL vendor software → not theater, **with two caveats**. Recommended order: **NX-OS → AOS-CX (after a 1-line regex fix) → IOS-XR (only if a contract-backed Cisco account exists).**

The headline question — "do the available virtual images have enough parity that the work is worth
something?" — resolves **YES for all three on the collection surface** (prompt, paging, `show
running-config`), because every candidate is the vendor's **own NOS binary** (control-plane sim), not a
third-party reimplementation. The dataplane is stubbed, but netcanon's backup never touches it. Two real
catches sit on the `show version` **probe**, and one is a genuine theater finding.

## Per-NOS

| NOS | Image (real SW) | Acquire | Lab fit | Mgmt-plane parity | Verdict |
|---|---|---|---|---|---|
| **NX-OS** | Nexus 9000v / **9300v "Lite"** (real NX-OS) | **Free** CCO download, **no contract** | 6–8 GB RAM (Lite=6) → dedicated VM-B; OVMF/UEFI+SATA+E1000+serial/POAP boot | **Full 9/9** — prompt, no-enable, `terminal length 0`, real running-config, **all 3 probe regexes fire** (model captures virtual SKU `C9300v` via the *same* hardware regex path) | **GO — do first** |
| **AOS-CX** | CX **Switch Simulator** (real AOS-CX) | Free, **HPE/Aruba account + EULA** | 4 GB/2 vCPU, OVA→qcow2 one-liner, plain KVM | Collection 3/4 OK; **`show version` probe BREAKS**: sim prints `Version : Virtual.10.13.1110`, def regex `[A-Z]{2}\.` needs two caps+dot → no match (hardware `FL.`/`GL.` matches) | **GO-WITH-FIX** (widen regex first) |
| **IOS-XR** | **IOS-XRd Control-Plane** container (real XR; lineage of our xrd corpus) | **Cisco account + ACTIVE SERVICE CONTRACT** (no anonymous DL); DevNet sandbox needs AnyConnect VPN | Light: 2 GB/2 vCPU, no hugepages (CP flavor); needs host **cgroups v1** (`systemd.unified_cgroup_hierarchy=false`) | Full — real `RP/0/RP0/CPU0:ios#` prompt, no-enable, native paging, real running-config; probe fires (model captures `XRd`) | **GO-WITH-FRICTION** — gated on acquisition |

## The two catches that make this "worth something" vs theater

1. **AOS-CX probe regex is theater on the sim (blocker, MF-1).** `definitions/aruba/aos-cx/10.x.yaml:51`
   `Version\s*:\s*[A-Z]{2}\.(\d+\.\d+)` matches hardware (`FL.10.x` / `GL.10.x`, both confirmed) but
   provably **cannot** fire on the simulator's `Virtual.10.13.1110`. A sim backup would go green while
   `detected_os_version` stays silently empty — validating the probe against the one device class on which
   it can't fire. **Fix before any AOS-CX run:** widen to `(?:[A-Z]{2}|Virtual)\.(\d+\.\d+)` (keeps the
   hardware contract tight). This is a genuine, cheap def improvement the research surfaced — worth doing
   regardless, since anyone running the free sim hits it.
2. **Marker-drop honesty for the Cisco model token (minor, MF-3).** NX-OS `detected_model` captures the
   virtual SKU `C9300v` (not a hardware SKU); IOS-XR captures `XRd` (not `ASR9K`/`NCS-5501`). Both regexes
   *do* fire — so it's evidence, not theater — but a marker-drop should be scoped: "collection wiring +
   version probe verified on real NOS software; the hardware *model* token is confirmed against documented
   `show version` banners only." (Same honesty discipline as the VyOS graduation.)

Plus MF-4 (minor): for each run, push a representative config (VLAN/SVI/VRF/BGP; AOS-CX also `no routing`
L2 opt-in + active-gateway) before backup so the codec grammar is actually exercised, and confirm the
capture is byte-clean (no residual ANSI / `--More--`). Don't validate against a bare default box.

## Recommended order (each = a VyOS-shaped run: device on VM-B, netcanon Docker on VM-A, ≤2 VMs)

1. **NX-OS first.** Only one with a free, no-contract image AND all probe regexes firing. A PASS is honest
   hardware evidence → drop the marker (scoped per MF-3). Cost: the OVMF/SATA/E1000/serial-POAP boot recipe
   + 6 GB Lite image on the dedicated VM.
2. **AOS-CX second — but land the MF-1 regex widening first** (tiny PR, also a real correctness fix), then
   the sim validates collection + prompt + paging + (post-fix) the version probe. Free account-gated DL.
3. **IOS-XR only if you have a contract-backed Cisco.com account** (or are willing to drive the DevNet XRd
   sandbox over AnyConnect — not a clean SSH path). Parity itself is excellent and the image is light;
   acquisition is the sole gate.

**Bottom line:** the work is worth doing — these are real NOS binaries, so a PASS means what we want it to
mean. NX-OS is the clear next target. AOS-CX needs a one-line probe-regex fix first (and that fix is worth
making either way). IOS-XR is parity-ready but acquisition-gated on a Cisco support contract.

This dossier is the frozen evidence trail (EXPECTED-STALE; a future audit must not flag it as drift).
