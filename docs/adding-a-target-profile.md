# Adding a target profile — worked example

Use this as the template when shipping a new target-profile YAML — a
hardware-shape definition that drives the rename-modal port dropdowns
and the per-pane fit-check banners on the migrate page.  The worked
example below is the Aruba 2930F-8G-PoE+-2SFP+ (JL258A): a model with a
committed real capture and no shipped profile, so every step maps to a
file you can create and a test you can run, and every port name in it
can be checked against real hardware output.

---

## Why this doc exists

Adding a target profile is mechanically simple — write a YAML file
under `netcanon/definitions/library/target_profiles/`, add a unit test, and the loader
picks it up on next start.  What is NOT simple is getting the port
names right, and that is where this guide spends its words: a port id
an operator picks from a profile is written **verbatim** into the
generated config, so a wrong id is a config that names a port the
device does not have.

A registry audit found exactly that in a third of the shipped
profiles — `1/A1` uplinks on a switch with no module slot, a
`GigabitEthernet` prefix on a `TenGigabitEthernet` box, a stacking
module and a power supply offered as 40G uplink modules.  Most traced
to one written rule: an earlier version of this guide told authors to
derive port ids from the codec's `format_port_identity`, so profiles
came to describe the formatter instead of the device.  The rest were
vendor documents misread, or a sibling model's scheme transplanted —
two rows swapped in a hardware guide's table, a part number paired
with the wrong line of an ordering table, one appliance's interface
layout copied onto another.  §3 below is the rule for port names,
and §4 is the provenance a profile carries.

Sibling cookbook for the canonical-schema side:
[`adding-a-canonical-field.md`](adding-a-canonical-field.md).

---

## What a target profile is

A target profile is a hardware-shape definition — vendor + model +
port enumeration + (optionally) `max_vlans` / `max_local_users`
ceilings — that tells the migration UI what the destination box can
accept.  It drives the per-port target-name dropdown in the rename
modal, port collision detection across operator overrides, the ports
fit-check banner ("source has 56 interfaces; target has 52; 4 won't
map"), and the VLAN / local-user fit-check banners.

Target profiles are NOT backup-side device definitions — those live
under `netcanon/definitions/library/<vendor>/` and are consumed by the SSH / NETCONF /
REST collectors.  Target profiles are migration-side only and are
loaded from `netcanon/definitions/library/target_profiles/` by
`netcanon/migration/target_profiles.py::load_profiles_dir`.

---

## Two YAML shapes

Profiles ship in two flavours.  Pick the one that matches the
hardware.

### Legacy flat-ports shape

For fixed-port switches, firewalls, and routers — every port the
device will ever have is listed directly under `ports:`.  Reference:
[`netcanon/definitions/library/target_profiles/aruba_2930f_48g.yaml`](../netcanon/definitions/library/target_profiles/aruba_2930f_48g.yaml).

```yaml
# Aruba 2930F-48G-4SFP (JL260A)
vendor: aruba_aoss
model: 2930F-48G
display_name: "Aruba 2930F-48G-4SFP (JL260A)"
device_class: switch
stacking: vsf-capable
deployment_state: "standalone (VSF disabled)"
evidence: capture
evidence_ref: "tests/fixtures/real/aruba_aoss/hpe_community_2930f_wc1607_intervlan.cfg"
caveat: "With VSF enabled every port, uplinks included, takes its member number as a prefix (49 becomes 1/49 on member 1)."
ports:
  - {range: "1-48", kind: physical, speed: gig, poe: false}
  - {range: "49-52", kind: uplink, speed: gig, sfp: true, notes: "1G SFP cage"}
lags: {max: 60, prefix: Trk}

max_vlans: 2048
max_vlans_source: "AOS-S 16.11 2930F/2930M Advanced Traffic Management Guide: max-vlans 16-2048, factory default 256"
```

The `range:` shorthand expands at load time — `1-48` becomes 48
discrete `id: N` entries that share the kind/speed/poe attributes.
See `_expand_range_entries` in `target_profiles.py` for the exact
rule (prefix-consistent ranges, integer end-points, `start <= end`).

### Module-variant shape

For chassis-style switches with swappable uplink modules — the
chassis-fixed access ports go under `ports:`, and each
swappable-module SKU goes under `modules:` keyed by SKU.  Reference:
[`netcanon/definitions/library/target_profiles/cisco_c9300_24ux.yaml`](../netcanon/definitions/library/target_profiles/cisco_c9300_24ux.yaml).

```yaml
vendor: cisco_iosxe
model: C9300-24UX
display_name: "Cisco Catalyst 9300-24UX (mGig 10G + UPOE)"
device_class: switch
stacking: stackwise
deployment_state: "stack member 1 (the factory default; a standalone C9300 keeps whatever member number it was last given)"
evidence: capture
evidence_ref: "tests/fixtures/real/cisco_iosxe/user_contrib_cat9300_iosxe1712.txt"
ports:
  - {range: "TenGigabitEthernet1/0/1-24", kind: physical, speed: 10gig, poe: true}
  - {id: "GigabitEthernet0/0", kind: mgmt, speed: gig}
modules:
  NM-8X:
    description: "8x 10G SFP+ uplinks (C9300-NM-8X)"
    ports:
      - {range: "TenGigabitEthernet1/1/1-8", kind: uplink, speed: 10gig, sfp: true}
  NM-2Q:
    description: "2x 40G QSFP+ uplinks (C9300-NM-2Q)"
    ports:
      - {range: "FortyGigabitEthernet1/1/1-2", kind: uplink, speed: 40gig, sfp: true}
lags: {max: 128, prefix: Port-channel}

max_vlans: 4094
```

Module variants are ADDITIVE: `effective_ports(sku)` returns
`profile.ports + profile.modules[sku].ports`.  A profile with no
`modules:` key behaves identically to the legacy flat shape — the UI
hides the third-stage module dropdown and the rename modal works as
before.

Only modules that contribute **data ports** belong under `modules:`.
On Aruba hardware a stacking module and a power supply share the
J-number namespace with the uplink modules.  Take a part's description
from a heading or sentence where the number and the description
appear together — never from its number, and never by pairing the
columns of an ordering table extracted as text: the rows drift, which
is the likely origin of a 3810M chassis shipping under the wrong
J-number here.

Module variants get an extra discipline: the `{vendor}/{model}` key
must be added to
[`tests/fixtures/module_variants.py`](../tests/fixtures/module_variants.py).
That allowlist is the single source of truth for both the unit-tier
and integration-tier "modules-vs-no-modules" regression guards — a
CI invariant (`test_module_variant_allowlist_shared_with_integration_tier`)
asserts both tests import the same `frozenset` so the two layers
can't silently disagree.  See the AGENTS.md doc-sync table for the
full rule.

---

## Step-by-step — adding the Aruba 2930F-8G-PoE+-2SFP+ (JL258A)

### 1. Find the evidence before you write anything

Start from the device, not from a sibling profile.  The repo already
holds a real `show running-config` from this exact model:
`tests/fixtures/real/aruba_aoss/hpe_community_2930f_wc1610_dhcp_server.cfg`.
Its header reads `; JL258A Configuration Editor`, its `module 1 type`
line names the same part, and its default VLAN lists `no untagged
1,3,7-8` and `untagged 2,4-6,9-10`.  That is ten ports, named `1`
through `10`, with nothing else: eight copper ports and two uplinks
that simply continue the numbering.

If no capture exists, the next-best source is the vendor's hardware
installation guide or configuration guide for that model — not a
reseller listing, and not another model's profile.

### 2. Pick the shape

The JL258A has fixed access ports and fixed uplink cages (no swappable
module), so this is the legacy flat-ports shape.  If the hardware had
a slot like Cisco's NM cage, we'd pick the module-variant shape
instead.

### 3. Enumerate ports correctly

Each `id` (or each value the `range:` shorthand expands to) MUST be
the name **the hardware itself uses** for that port — taken from a real
`show running-config` of that exact model, or failing that from the
vendor's hardware installation guide.  Cite which in a comment.

**Never derive a port id from `format_port_identity` output.**  A
profile that agrees with the codec proves nothing — both can be wrong
together, and a self-consistency check cannot see it.  The formatter
is a heuristic over the *shape* of a name; it does not know the model.

Things a port name depends on that the model number alone does not
settle — check each against the capture or guide:

* **Deployment state.**  An AOS-S 2930F is `24` standalone and `1/24`
  under VSF; a 2930M / 3810M / 2920 flips the same way with stacking.
  A profile describes ONE state; `deployment_state` says which.
* **Port speed class.**  The interface-type prefix follows the port's
  hardware class, not a speed table: C9300-24U is `GigabitEthernet`,
  C9300-24UX is `TenGigabitEthernet`.
* **Installed module.**  Uplink names come from the module fitted, and
  "no module" is a valid configuration.  A switch with no module slot
  has no letter slot: a 2930F's uplinks are `49`-`52` (`25`-`28` on a
  24-port, `9`-`10` on the 8-port), never `A1`.
* **Index base.**  Junos starts at 0, Catalyst switches at 1, IOS-XE
  routers at 0.  It is per platform, not per vendor.

Use the long form the device prints (`GigabitEthernet1/0/1`, not
`Gi1/0/1`).  If the codec cannot classify or reproduce a name the
hardware genuinely uses, that is a codec gap to report — not a reason
to change the profile.

### 4. State the provenance

Four optional fields say what is actually known about the port names.
A new profile should set all that apply.

| Field | Meaning |
|---|---|
| `deployment_state` | The single state the ids describe — `"standalone (VSF disabled)"`, `"stack member 1"`.  **Required** whenever `stacking` is non-empty. |
| `evidence` | `capture`, `vendor-doc` or `inferred` — see below. |
| `evidence_ref` | What backs the grade.  For `capture`, the repo-relative fixture path; otherwise the documents, named. |
| `caveat` | Operator-visible text: what would make these ids wrong on the operator's device.  **Required** when `evidence` is `inferred`. |

The grades, strongest first:

* **`capture`** — every port id appears as a hardware port in a
  committed real capture of this exact model.  This is a *checked*
  claim:
  [`tests/unit/migration/test_target_profile_evidence.py`](../tests/unit/migration/test_target_profile_evidence.py)
  parses the fixture named by `evidence_ref` on every run and fails if
  the fixture does not identify itself as this model, is another
  vendor's capture, or lacks any id.  It would have caught the
  2930F-48G and C9300-24UX errors before they shipped.  Two limits:
  it does not notice a port the profile *omits* (the exact-list test
  in step 7 does), and on a platform that lists absent hardware in
  its config — a C9300 prints every network module's interfaces — a
  capture proves a module port's *name* exists, not that the module
  is fitted.
* **`vendor-doc`** — the ids are established for this exact model from
  published sources: the vendor's own documentation (hardware guide,
  data sheet, configuration guide, published device configs) and/or
  real-device output of that model that is public but not committed
  here.  Name every vendor document in `evidence_ref`, and give
  enough in the file's header comment to re-find any device output
  (repo, path and commit; forum message id).  Nothing re-checks this
  grade, so it is only as good as the reading behind it — read the
  document; do not grade from a reseller listing or a sibling model.
* **`inferred`** — derived by analogy with a sibling model, or doubtful
  for the target it is filed under.  Say what is unverified in
  `caveat`; the rename modal turns the notice amber for this grade.

Leaving `evidence` unset means *not yet graded* — the rename modal and
the definitions page both say so.  It is not a clean bill of health,
so grade what you add.  A graded profile must also be added to the
pinned set for its grade in the evidence test (step 7); the sets are
compared for equality, so skipping this fails CI.

If you find a shipped profile is wrong but cannot establish the right
names for that exact model, **flag it, don't rename it**: set
`evidence: inferred`, write the `caveat`, and add its key to
`KNOWN_DOUBTFUL` in the evidence test.  Replacing one plausible name
with another is how the registry got into this state.

Flagging is for a profile whose target is real but whose names are in
doubt.  If the target OS does not run on the hardware at all, delete
the profile instead — there is no device for the names to be right
on.  Two Netgate ARM profiles filed under OPNsense went that way.

### 5. Create the YAML

Path: `netcanon/definitions/library/target_profiles/aruba_2930f_8g_poep.yaml`.  The
loader reads every `*.yaml` directly under `netcanon/definitions/library/target_profiles/`
(it does not descend into subdirectories), so file naming is
conventional only — `vendor + model` inside the file is what uniquely
identifies the profile.

```yaml
# Aruba 2930F-8G-PoE+-2SFP+ (JL258A)
# 8 × 10/100/1000 BASE-T RJ45 + PoE+, 2 × SFP+ uplink (ports 9-10)
#
# A 2930F has no module slot; the uplinks continue the access
# numbering.  Validation: tests/fixtures/real/aruba_aoss/
# hpe_community_2930f_wc1610_dhcp_server.cfg is a real JL258A whose
# default VLAN spans ports 1-10.
vendor: aruba_aoss
model: 2930F-8G-PoEP
display_name: "Aruba 2930F-8G-PoE+-2SFP+ (JL258A)"
device_class: switch
stacking: vsf-capable
deployment_state: "standalone (VSF disabled)"
evidence: capture
evidence_ref: "tests/fixtures/real/aruba_aoss/hpe_community_2930f_wc1610_dhcp_server.cfg"
caveat: "With VSF enabled every port, uplinks included, takes its member number as a prefix (9 becomes 1/9 on member 1)."
ports:
  - {range: "1-8", kind: physical, speed: gig, poe: true}
  - {range: "9-10", kind: uplink, speed: 10gig, sfp: true}
lags: {max: 60, prefix: Trk}

max_vlans: 2048
max_vlans_source: "AOS-S 16.11 2930F/2930M Advanced Traffic Management Guide: max-vlans 16-2048, factory default 256"
```

### 6. Set `max_vlans` and `max_local_users`

Pull these from the device's published spec, and say which document
in `max_vlans_source` — here the `max-vlans` ceiling from HPE's AOS-S
Advanced Traffic Management Guide.  Fit-check banners use these to
warn when the source config has more VLANs / local users than the
target can accept.

Leave a field unset (None) when the device has no meaningful cap, **or
when you cannot source one** — the corresponding banner stays hidden,
which is better than a confident wrong number.  The example above
omits `max_local_users` for that reason: the `16` the shipped AOS-S
profiles used to carry turned out not to be a vendor figure at all, and
was removed.  `lags.max` had the same problem: those profiles said 24
where every HPE document says 60.

For FortiGate profiles populate `max_vlans_source` too — caps drift
between FortiOS minors and the provenance string makes future
re-verification grep-able.  Other vendors do it opportunistically.

### 7. Add the unit tests

Open
[`tests/unit/migration/test_target_profile_shipped.py`](../tests/unit/migration/test_target_profile_shipped.py)
and add a per-profile method that locks the port list and counts.
The shape mirrors the existing `test_aruba_2930f_48g_poep` method:

```python
def test_aruba_2930f_8g_poep(self):
    profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
    p = profiles["aruba_aoss/2930F-8G-PoEP"]
    assert p.port_ids(kind="physical") == [str(n) for n in range(1, 9)]
    assert p.port_ids(kind="uplink") == ["9", "10"]
    assert p.lags.max == 60
    assert p.lags.prefix == "Trk"
    assert p.max_vlans == 2048
    assert p.max_local_users is None
    for port in p.ports:
        if port.kind == "physical":
            assert port.poe is True
```

Assert the exact id list, not just the count.  A count would not have
noticed `1/A1` standing where `49` belongs.

Then register the grade in
[`tests/unit/migration/test_target_profile_evidence.py`](../tests/unit/migration/test_target_profile_evidence.py).
This profile is graded `capture`, so add it to `CAPTURE_MODEL_MARKER`
with a line that only a capture of this model contains, lower-cased:

```python
CAPTURE_MODEL_MARKER = {
    # ...existing entries...
    "aruba_aoss/2930F-8G-PoEP": "module 1 type jl258a",
}
```

The marker is what stops a profile being graded against a *sibling's*
capture whose port names happen to cover it.  A `vendor-doc` profile
goes in `EXPECTED_VENDOR_DOC_GRADED` instead, an `inferred` one in
`KNOWN_DOUBTFUL`.  All three are compared for equality with what the
YAMLs declare, so a grade can neither appear nor vanish unreviewed.

### 8. If module-variant: register the allowlist

For our flat-ports JL258A, skip this step.  For a module-variant
profile, add a row to
[`tests/fixtures/module_variants.py`](../tests/fixtures/module_variants.py):

```python
MODULE_VARIANT_PROFILES: frozenset[str] = frozenset({
    # ...existing entries...
    "cisco_iosxe/C9300-24UX",
    "aruba_aoss/3810M-48G-PoEP",
    "aruba_aoss/2930M-24G-PoEP",   # ← new entry
})
```

The unit-tier `test_non_module_variant_profiles_stay_legacy` and the
integration-tier `TestModulesFieldSerialization` both import this
frozenset; the CI guard ensures they stay in lockstep.

### 9. Verify the UI surfaces it

Restart the server (`uvicorn netcanon.main:app --reload`), open the
migrate page, translate any config to Aruba AOS-S, open the rename
modal and confirm:

* the new model appears in the target-profile dropdown with its
  `display_name`,
* the notice under the fit-check banner reads "Port names describe:
  standalone (VSF disabled)" and reports the capture grade,
* the port dropdown lists exactly `1` … `8` for access rows and `9`,
  `10` for uplink rows,
* a row whose *Auto target* is not one of the profile's ports is
  marked "not on profile" (a Cisco source's `1/1` against these bare
  ids, for instance) and clears when you pick a port from the list,
* the VLAN-pane fit-check banner reads "VLAN fit: N / 2048" in green,
  and turns red only when the source has more than 2048 VLANs.

The ports fit-check and the provenance notice live in
[`netcanon/templates/_partials/fit-check.js`](../netcanon/templates/_partials/fit-check.js);
the VLAN- and local-user-pane banners are inline in `migrate.html`
(search for `mig-rename-vlans-fitcheck`).
No code changes are required — the data flows from `TargetProfile` →
`/api/v1/migration/target-profiles` → the rename-modal renderer.

### 10. No code changes needed

Target profiles are pure data.
`netcanon/migration/target_profiles.py::load_profiles_dir` walks the
directory at app start, the API serves whatever loaded successfully,
and the UI renders from that.  A new YAML file + its unit tests +
(optionally) one allowlist entry are the entire change set.

---

## Validation the loader actually runs

The loader is intentionally permissive — it logs and skips
malformed files rather than failing app startup.  In practice that
means contributors who break the rules below will get warnings in
the server log, not exceptions.  Run the unit-test suite to surface
problems at review time.

What `load_profile_file` enforces:

* the YAML file parses,
* the top-level value is a mapping,
* `range:` shorthand entries are well-formed (single-prefix or
  matching prefixes on both sides, integer end-points,
  `start <= end`),
* `modules:` is a mapping of SKU → mapping (not a list, not scalar),
* the resulting object validates against the `TargetProfile` Pydantic
  schema — required fields present, types correct, `lags.max` in
  `[0, 4096]`, `device_class` is a known enum value, `evidence` is one
  of the three grades.

What it does NOT enforce — the unit tests do:

* every file actually loads — the loader *skips* a file that fails
  validation, so a typo in `evidence:` would otherwise remove the
  profile from the product silently
  (`test_target_profile_shipped.py::test_all_profiles_load`),
* a `capture`-graded profile's ids all appear in its cited fixture,
  an `inferred` profile carries a caveat, a stack-capable profile
  states its deployment, and no grade appears or vanishes unreviewed
  (`test_target_profile_evidence.py`),
* the exact port list and counts, no repeated port id, `max_vlans`
  within the VLAN-id range, and no two files declaring the same
  `vendor/model` key (`test_target_profile_shipped.py`).

Nothing checks that a `vendor-doc` or ungraded profile's names are
*true*.  That is the author's job, which is why §1 comes first.

---

## What NOT to do

* **Don't take a port name from the codec, a sibling profile, or
  memory.**  Take it from a capture of that model or the vendor's
  guide, and cite it.  The codec's `format_port_identity` is a
  heuristic; agreeing with it is not evidence.
* **Don't abbreviate.**  Cisco profiles use `GigabitEthernet1/0/1`,
  not `Gi1/0/1`; Junos uses `ge-0/0/0`.  The id is written into the
  config as-is.
* **Don't enumerate ports across modules in the legacy flat shape
  when the model is genuinely modular.**  If the hardware has a
  swappable uplink card, every operator who picks a different SKU
  needs the right uplink set surfaced — flattening the largest SKU
  into `ports:` works for one customer and silently misleads every
  other.  Pick the module-variant shape and register the allowlist.
* **Don't list a part as a module because its number is in the
  family.**  Stacking modules and power supplies are not uplink
  choices.
* **Don't set `max_vlans` to a value the underlying codec can't
  emit.**  The fit-check banner will go green on an over-permissive
  ceiling and the render step will then fail or silently truncate.
  Cross-check against the codec's `_CAPS` matrix before picking a
  number — see
  [`netcanon/migration/codecs/README.md`](../netcanon/migration/codecs/README.md).
* **Don't skip the unit tests.**  A copy-paste typo between sibling
  SKUs (the 24G profile that inherits a 48G port range) is the
  exact failure mode the shipped-profile test class exists to catch.

---

## See also

* [`adding-a-canonical-field.md`](adding-a-canonical-field.md) —
  sibling cookbook for the canonical-schema side (MTU as the worked
  wire-through example)
* [`feature-parity-walkthrough.md`](feature-parity-walkthrough.md) —
  sibling cookbook for cross-platform feature work (web + desktop)
* [`../netcanon/definitions/library/README.md`](../netcanon/definitions/library/README.md) — schema
  reference for backup-side device definitions; target profiles
  share the same YAML-loader pattern
* [`../netcanon/migration/target_profiles.py`](../netcanon/migration/target_profiles.py)
  — `TargetProfile` / `TargetModule` model classes; the module
  docstring carries the canonical worked-YAML example
* [`../tests/fixtures/module_variants.py`](../tests/fixtures/module_variants.py)
  — module-variant allowlist (single source of truth, CI-guarded)
* [`../tests/unit/migration/test_target_profile_shipped.py`](../tests/unit/migration/test_target_profile_shipped.py)
  — port-list lock-in test pattern
* [`../tests/unit/migration/test_target_profile_evidence.py`](../tests/unit/migration/test_target_profile_evidence.py)
  — the provenance guards (capture conformance, caveat, deployment state)
* [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — "Target profiles" →
  "Provenance: a profile describes hardware, in one stated state"
* [`../AGENTS.md`](../AGENTS.md) — Documentation Sync Checklist row
  for new target profiles
