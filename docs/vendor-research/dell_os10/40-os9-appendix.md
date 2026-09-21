# Dell OS9 / FTOS — appendix (PARKED)

**Not being pursued.**  Scope was narrowed to OS10 by the user on
2026-09-21 ("Let's focus on os10 first. That's my real world use case").
This file preserves what was gathered incidentally so a future OS9 effort
does not start from zero.

---

## Why OS9 is a separate codec, not an OS10 dialect

OS9 (Force10 FTOS, later DNOS 9.x) shares a vendor with OS10 and almost
nothing else.  The VLAN membership model is **inverted**:

| | OS10 | OS9 |
|---|---|---|
| VLAN membership | **port-centric** — `switchport access vlan 700` on the interface | **VLAN-centric** — `interface Vlan 700` then `untagged Te 0/5` |
| Port naming | `ethernet 1/1/1` | `TenGigabitEthernet 0/1`, `Te 0/1` |
| Management port | `interface mgmt1/1/1` | `interface ManagementEthernet 0/0` |
| LAG | `interface port-channel10` + `channel-group` | `interface Port-channel 1` + `channel-member` |
| VRF bind | `ip vrf forwarding <n>` | `ip vrf forwarding <n>` (same) |
| Spanning tree | `spanning-tree mode rstp` | `protocol spanning-tree rstp` |
| Version banner | `! Version 10.5.1.0` | `! Version 9.9(0.0)` |

OS9's VLAN model is the **same shape as Aruba AOS-S** (tagged/untagged
member lists under the VLAN), which netcanon already models — so an OS9
codec would borrow from `aruba_aoss`, not from any future `dell_os10`.

`portmode hybrid` is the OS9 keyword enabling mixed tagged/untagged on one
port; there is no OS10 equivalent because OS10 is port-centric already.

## OS9 SNMPv3 — a DIFFERENT provenance marker from OS10

```
snmp-server user <name> <group> [1|2c|3] [encrypted]
    [auth {md5|sha} <auth-password>]
    [priv {des56|aes128} <priv-password>]
```

OS9's marker is **`encrypted`**; OS10's is **`localized`** (see
[`10-grammar.md`](10-grammar.md) §8).  Two Dell NOSes, two different
per-line keywords, two different semantics:

- OS10 `localized` → key salted to the switch's **engine ID** → maps to
  canonical kind `localised`.
- OS9 `encrypted` → key stored under a **device key** → maps to canonical
  kind `ciphertext` / `encrypted`.

> They therefore **cannot share a `_SOURCE_DEFAULT_KIND` entry**, and an
> OS9 codec must not reuse an OS10 parser's marker regex.  Getting this
> wrong reintroduces the #471 class of bug.

OS9 also has `snmp-server user (for AES128-CFB Encryption)` as a
*separate* command page — a second grammar for the same concept.

## OS9 corpus already gathered (all MIT, ingestible)

`microsoft/SDN` — `SwitchConfigExamples/Dell Force10 S4810 - Redundant TOR
with Aggregate/`: `S4810-TOR1.cfg`, `S4810-TOR2.cfg`, `S4810-AGG1.cfg`,
`S4810-AGG2.cfg` (+ a 19 KB README).  Real FTOS **9.9(0.0)** configs,
passwords already redacted to `<password>` at source.

⚠️ GitHub's licence API reports `NOASSERTION` / "Other" for this repo
because `License.txt` has a product-name preamble before the MIT text.
Reading the file resolves it: **it is MIT.**  Do not take the API summary
as the answer.

Other OS9 sources found, **no licence** (knowledge-only):
`grantcurell/projects` (FN410), `dav1x/how-to-switch`, `litnet/SORA`,
`novacain1/rhosp-templates`, `sdn-sense/sense-dellos9-collection`.

## OS9 manuals held locally

- Dell Configuration Guide for the S4048-ON System **9.14.2.0** (63,736
  lines extracted)
- Dell Command Line Reference Guide S4048-ON **9.14.2.5** (101,622 lines)
- Dell Command Line Reference Guide S4048-ON **9.14.2.2** (101,441 lines)

## The migration corridor is the actual point

Dell publishes an official **OS9-to-OS10 Command Mapping** guide
(`dell.com/support/manuals/…/os9-to-os10-cli-mapping-pub/`), covering
interfaces, VLAN, VRF, static routing, VRRP, STP, LACP, SNMP, NTP, DNS,
syslog and hostname.

Its content could not be extracted — the HTML pages return navigation only
to a fetcher, and no PDF URL was found (all pattern guesses 404'd).  It
would need either a browser session or the PDF located via Dell's manuals
index.

**OS9 → OS10 is a live, vendor-acknowledged migration corridor**, and a
same-vendor cross-NOS translation is exactly netcanon's shape.  If both
codecs ever ship, that pair is the highest-value one in the matrix — and
Dell's own mapping guide is the ready-made expectation-YAML source.
