# Blackboard — Is virtualizing NX-OS / IOS-XR / AOS-CX worth it to validate the 3 provisional backup defs? (2026-06-17)

**Process:** netcanon file-per-agent blackboard (docs/agent-workflow.md). Read-only agents each write
EXACTLY ONE report here; the main thread seeds this file + writes `99-synthesis.md` + is the sole actor
that verifies/commits. Agents must never read or write under `docs/codebase-review/` (uncommitted PII).

## Mission

We just stood up a Proxmox dogfood lab and **live-validated the `VyOS` backup definition** by SSHing a
real netcanon (`netcanon/netcanon:0.3.0` Docker) into a real VyOS rolling VM and pulling its running
config — that let us drop VyOS's `⚠ NOT YET VALIDATED` marker (PR #113). Three backup defs from #110
remain provisional because they have no free emulator we've tried yet:

- **`CiscoNXOS`** (Cisco NX-OS, Nexus 9000/3000)
- **`CiscoIOSXR`** (Cisco IOS-XR, ASR9k / NCS)
- **`ArubaCX`** (Aruba AOS-CX, CX 6000/8000/10000)

**Decide, per NOS: is there a practical virtual image we can run on our Proxmox lab, and does it have
enough CONFIG / CLI / MANAGEMENT-PLANE parity with a real device that validating the backup def against
it is actually WORTH SOMETHING — i.e. a PASS against the VM genuinely proves the def works on real
hardware, not theater?** Return a GO / GO-WITH-FRICTION / NO-GO per NOS with evidence.

## The ONLY thing the backup def exercises (judge parity against EXACTLY this — not full device features)

netcanon's backup is a **management-plane SSH collection**, nothing else. For each NOS the def
(`definitions/cisco/nx-os/10.x.yaml`, `definitions/cisco/ios-xr/7.x.yaml`, `definitions/aruba/aos-cx/10.x.yaml`)
drives, via the named **netmiko driver**, exactly:

| NOS | netmiko driver | config command | probe | prompt regex | enable? |
|---|---|---|---|---|---|
| NX-OS | `cisco_nxos` | `show running-config` | `show version` → `(?:NXOS\|system):\s+version\s+(\d+\.\d+)`, model `cisco Nexus\S*\s+(\S+)\s+[Cc]hassis`, serial `Processor Board ID\s+(\S+)` | `^\S+[#>]\s*$` | no |
| IOS-XR | `cisco_xr` | `show running-config` | `show version` → `Cisco IOS XR Software, Version\s+(\d+\.\d+)`, model `^cisco\s+(\S+)` | `^RP/\S+:\S+#\s*$` (+ `^\S+[#>]\s*$`) | no |
| AOS-CX | `aruba_aoscx` | `show running-config` | `show version` → `Version\s*:\s*[A-Z]{2}\.(\d+\.\d+)` | `^\S+[#>]\s*$` | no |

So the parity that matters is **purely management-plane**: does the virtual image, over SSH,
(1) present a prompt the regex matches, (2) let netmiko's driver disable paging the way it expects
(`terminal length 0` for the Cisco drivers / `no page` for aruba_aoscx), (3) return a `show running-config`
that is real, complete, set/CLI-form config text (the same grammar the migration codec parses), and
(4) return a `show version` whose banner the probe regex hits. **Dataplane / ASIC / linecard / forwarding
parity is IRRELEVANT here** — we never touch the dataplane. A control-plane-only VM that runs the *real
NOS software image* is therefore exactly as good as hardware for THIS purpose. A third-party
*reimplementation* (not the vendor's own software) would NOT be — call that out if found.

## What each research agent must establish (per NOS), with citations

1. **What virtual image(s) exist** (2026-current): exact product name + version (e.g. Nexus 9000v / n9kv,
   IOS-XRd / XRv9000, AOS-CX OVA simulator / Vagrant box / CML node). Is it the **vendor's real NOS
   software** (control-plane sim) or a third-party reimplementation?
2. **Acquisition + licensing**: where do you get it, does it need a vendor account / EULA / paid licence /
   eval, is redistribution restricted (we will NOT commit images or pull them into git — but can we even
   legally download + run one in a private lab?). Note any "free to registered users" vs "paid only".
   Flag if acquisition is blocked without a commercial relationship.
3. **Run on our lab**: format (qcow2 / vmdk / OVA / container), boot method on **Proxmox/KVM** (some need
   nested virt, multi-vNIC, serial console, specific NIC models, or a CML/EVE-NG wrapper), and
   **resource cost** (RAM/CPU/disk). Our hard budget is **two small VMs on the lab host** total (shared with the
   netcanon app VM) — so an image needing 16GB+ RAM is a real problem; say so. Lighter is better
   (XRd container vs XRv9000 VM, etc.).
4. **Management-plane parity for the table above** — the crux. Does it boot to a real SSH server with the
   real CLI? Will `show running-config` + `show version` + the prompt + paging behave as on hardware?
   Any KNOWN divergence (e.g. a virtual banner that says "9000v" and would break the model regex, a
   different prompt, a stripped feature set that changes `show running-config` output)? Be concrete.
5. **Verdict**: GO / GO-WITH-FRICTION / NO-GO for "stand it up in the lab and validate the def", with the
   single biggest blocker named. If GO-WITH-FRICTION, what's the friction (account, RAM, conversion).

Prefer primary sources (vendor docs, CML/DevNet, the netmiko driver's own assumptions) over forum
hearsay; cite URLs. Use WebSearch / WebFetch (load via ToolSearch). Where relevant, read the def file +
`netcanon/migration/codecs/<codec>` to confirm what grammar the config command must yield.

## Hard constraints / context (treat as fixed)

- The validation vehicle is the existing dogfood lab (see the gitignored `local/` ledger paradigm — agents
  don't need it; just know the budget is a modest two-VM lab on **the lab host**, never the secondary node). VyOS was validated this way.
- "Worth something" = a PASS against the VM is honest evidence the def works on real hardware. If the only
  obtainable image diverges on the management-plane surface above, validating against it is THEATER → say so.
- We are NOT deciding to buy anything or commit images. Output is research + a per-NOS verdict only.
- Don't cargo-cult the VyOS outcome: VyOS was free + runs the real OS. Cisco/Aruba licensing is different.

## File roster

| File | Phase | Author | Covers |
|---|---|---|---|
| 00-blackboard.md | seed | main thread | this protocol + mission + the exact backup surface + worthiness lens |
| 10-research-nxos.md | research | R1 | Cisco NX-OS: Nexus 9000v/n9kv + CML — availability, licensing, lab-runnability, mgmt-plane parity, verdict |
| 11-research-iosxr.md | research | R2 | Cisco IOS-XR: IOS-XRd (container) / XRv9000 — same dimensions + verdict (note we already used an "xrd corpus" for fixtures) |
| 12-research-aoscx.md | research | R3 | Aruba AOS-CX: OVA simulator / Vagrant box `arubanetworks/aoscx` / CML — same dimensions + verdict |
| 30-review-parity-skeptic.md | review | V1 | reads R1–R3; adversarially hunts where a VM PASS would NOT prove real-hardware behaviour for the backup surface; per-NOS worth-it vs theater verdict |
| 99-synthesis.md | synthesis | main thread | reconciled per-NOS GO/FRICTION/NO-GO + a recommended order (or "not worth it") |

## Severity tags for the reviewer

`THEATER` (a VM pass wouldn't prove hardware behaviour) · `ACQUISITION-BLOCKER` (can't get the image
without a commercial/paid relationship) · `RESOURCE-BLOCKER` (>8GB RAM / needs nested-virt/CML wrapper) ·
`PARITY-OK` (real NOS software, mgmt-plane identical) · `FRICTION` (works but account/convert/heavy).
