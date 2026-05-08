# Adding a target profile — worked example

Use this as the template when shipping a new target-profile YAML — a
hardware-shape definition that drives the rename-modal port dropdowns
and the per-pane fit-check banners on the migrate page.  The worked
example below is hypothetical (Aruba 6300M-24G, the imaginary 24-port
sibling of the shipped 6300M-48G profile) so every step maps to a
file you can create and a test you can run.

---

## Why this doc exists

Adding a target profile is mechanically simple — write a YAML file
under `definitions/target_profiles/`, add a unit test, and the loader
picks it up on next start.  But the schema has two distinct shapes
(legacy flat-ports vs module-variant chassis), the test conventions
guard against copy-paste drift between sibling SKUs, and the
fit-check propagation isn't centrally documented.  This walkthrough
fills that gap.  Sibling cookbook for the canonical-schema side:
[`adding-a-canonical-field.md`](adding-a-canonical-field.md).

---

## What a target profile is

A target profile is a hardware-shape definition — vendor + model +
port enumeration + (optionally) `max_vlans` / `max_local_users`
ceilings — that tells the migration UI what the destination box can
accept.  It drives the per-port target-name dropdown in the rename
modal, port collision detection across operator overrides, the ports
fit-check banner ("source has 52 interfaces; target has 50; 2 won't
map"), and the VLAN / local-user fit-check banners.

Target profiles are NOT backup-side device definitions — those live
under `definitions/<vendor>/` and are consumed by the SSH / NETCONF /
REST collectors.  Target profiles are migration-side only and are
loaded from `definitions/target_profiles/` by
`netcanon/migration/target_profiles.py::load_profiles_dir`.

---

## Two YAML shapes

Profiles ship in two flavours.  Pick the one that matches the
hardware.

### Legacy flat-ports shape

For fixed-port switches, firewalls, and routers — every port the
device will ever have is listed directly under `ports:`.  Reference:
[`definitions/target_profiles/aruba_2930f_48g.yaml`](../definitions/target_profiles/aruba_2930f_48g.yaml).

```yaml
# Aruba 2930F-48G (JL260A)
vendor: aruba_aoss
model: 2930F-48G
display_name: "Aruba 2930F-48G (JL260A)"
device_class: switch
stacking: vsf-capable
ports:
  - {range: "1/1-1/48", kind: physical, speed: gig, poe: false}
  - {range: "1/A1-1/A4", kind: uplink, speed: 10gig, sfp: true}
lags: {max: 24, prefix: Trk}

max_vlans: 2048
max_local_users: 16
```

The `range:` shorthand expands at load time — `1/1-1/48` becomes 48
discrete `id: 1/N` entries that share the kind/speed/poe attributes.
See `_expand_range_entries` in `target_profiles.py` for the exact
rule (prefix-consistent ranges, integer end-points, `start <= end`).

### Module-variant shape

For chassis-style switches with swappable uplink modules — the
chassis-fixed access ports go under `ports:`, and each
swappable-module SKU goes under `modules:` keyed by SKU.  Reference:
[`definitions/target_profiles/cisco_c9300_24ux.yaml`](../definitions/target_profiles/cisco_c9300_24ux.yaml).

```yaml
vendor: cisco_iosxe
model: C9300-24UX
display_name: "Cisco Catalyst 9300-24UX (mGig 10G + UPOE)"
device_class: switch
stacking: stackwise
ports:
  - {range: "GigabitEthernet1/0/1-24", kind: physical, speed: 10gig, poe: true}
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
lags: {max: 48, prefix: Port-channel}

max_vlans: 4094
```

Module variants are ADDITIVE: `effective_ports(sku)` returns
`profile.ports + profile.modules[sku].ports`.  A profile with no
`modules:` key behaves identically to the legacy flat shape — the UI
hides the third-stage module dropdown and the rename modal works as
before.

Module variants get an extra discipline: the `{vendor}/{model}` key
must be added to
[`tests/fixtures/module_variants.py`](../tests/fixtures/module_variants.py).
That allowlist is the single source of truth for both the unit-tier
and integration-tier "modules-vs-no-modules" regression guards — a
CI invariant (`test_module_variant_allowlist_shared_with_integration_tier`)
asserts both tests import the same `frozenset` so the two layers
can't silently disagree.  See the CLAUDE.md doc-sync table for the
full rule.

---

## Step-by-step — adding the Aruba 6300M-24G

The shipped 6300M-48G profile covers the 48-port variant; the
hypothetical 24-port sibling — same SFP56 uplink shape, half the
access ports — is a clean walkthrough subject.

### 1. Pick the shape

The 6300M-24G has fixed access ports + fixed SFP56 uplinks (no
swappable network modules), so this is the legacy flat-ports shape.
If the hardware had a slot like Cisco's NM cage, we'd pick the
module-variant shape instead.

### 2. Create the YAML

Path: `definitions/target_profiles/aruba_6300m_24g.yaml`.  The
loader recursively globs `*.yaml` under `definitions/target_profiles/`,
so file naming is conventional only — `vendor + model` inside the
file is what uniquely identifies the profile.

```yaml
# Aruba 6300M 24-port 1GbE + 4x SFP56 (CX platform)
vendor: aruba_aoss
model: 6300M-24G-PoE4-SFP56
display_name: "Aruba 6300M 24G PoE+ 4xSFP56 (CX / port planning only)"
device_class: switch
stacking: vsx-stacking
ports:
  - {range: "1/1-1/24", kind: physical, speed: gig, poe: true}
  - {range: "1/A1-1/A4", kind: uplink, speed: 50gig, sfp: true, notes: "SFP56 10/25/50G uplink"}
lags: {max: 256, prefix: lag}

max_vlans: 4094
max_local_users: 64
```

### 3. Enumerate ports correctly

Each `id` (or each value the `range:` shorthand expands to) MUST
match the codec's `format_port_identity` output for the corresponding
vendor — operators see these strings in the rename UI's target
dropdowns.  A mismatch silently breaks rename-mesh suggestion
("source `1/1` cannot be mapped to anything in the target's port
list").

For Aruba AOS-S, `format_port_identity` in
[`netcanon/migration/codecs/aruba_aoss/port_names.py`](../netcanon/migration/codecs/aruba_aoss/port_names.py)
emits forms like `1/24` (two-part stack/port) and `1/A1` (uplink with
subslot letter).  That's why the profile uses `1/N` access ports and
`1/A1`-style uplink ids — exactly what AOS-S would render.  Cisco's
`format_port_identity` emits `GigabitEthernet1/0/1`, not `Gi1/0/1` —
target profiles use the long form for the same reason.

### 4. Set `max_vlans` and `max_local_users`

Pull these from the device's published spec.  6300M-CX supports the
full VLAN protocol range (4094) and AOS-CX 10.x documents
`max-users-local` around 64.  Fit-check banners use these to warn
when the source config has more VLANs / local users than the target
can accept.  Leave a field unset (None) only when the device has no
meaningful cap — the corresponding banner stays hidden.

For FortiGate profiles populate `max_vlans_source` too — caps drift
between FortiOS minors and the provenance string makes future
re-verification grep-able.  Other vendors do it opportunistically.

### 5. Add a unit test

Open
[`tests/unit/migration/test_target_profile_shipped.py`](../tests/unit/migration/test_target_profile_shipped.py)
and add a per-profile method that locks the port list and counts.
The shape mirrors the existing `test_aruba_2930f_48g_poep` method:

```python
def test_aruba_6300m_24g(self):
    profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
    p = profiles["aruba_aoss/6300M-24G-PoE4-SFP56"]
    assert p.port_count == 28  # 24 RJ45 + 4 SFP56 uplinks
    assert len(p.port_ids(kind="physical")) == 24
    assert len(p.port_ids(kind="uplink")) == 4
    assert p.lags.max == 256
    assert p.lags.prefix == "lag"
    assert p.max_vlans == 4094
    assert p.max_local_users == 64
    for port in p.ports:
        if port.kind == "physical":
            assert port.poe is True
```

The hard-coded counts are the regression guard: a copy-paste typo
that turned `1/1-1/24` into `1/1-1/48` would silently bring 24 extra
ghost ports into the rename UI; this test catches it at review.

### 6. If module-variant: register the allowlist

For our flat-ports 6300M-24G, skip this step.  For a module-variant
profile, add a row to
[`tests/fixtures/module_variants.py`](../tests/fixtures/module_variants.py):

```python
MODULE_VARIANT_PROFILES: frozenset[str] = frozenset({
    # ...existing entries...
    "cisco_iosxe/C9300-24UX",
    "aruba_aoss/3810M-48G-PoEP",
    "aruba_aoss/6300M-24G-MOD",   # ← new entry
})
```

The unit-tier `test_non_module_variant_profiles_stay_legacy` and the
integration-tier `TestModulesFieldSerialization` both import this
frozenset; the CI guard ensures they stay in lockstep.

### 7. Verify the UI surfaces it

Restart the server (`uvicorn netcanon.main:app --reload`), open the
migrate page, paste any Aruba source config, and confirm:

* the new model appears in the target-profile dropdown with its
  `display_name`,
* the rename modal's port dropdown lists the 28 ports and uses the
  correct AOS-S spelling (`1/1` ... `1/24`, `1/A1` ... `1/A4`),
* the VLAN-pane fit-check banner stays hidden when the source has
  ≤ 4094 VLANs (which is always — the cap is the protocol ceiling),
* a deliberately-overpopulated source config with 65 local users
  triggers the local-users-pane fit-check banner against the 64-user
  cap.

The fit-check JS lives in
[`netcanon/templates/migrate.html`](../netcanon/templates/migrate.html)
(search for `max_vlans` and `mig-rename-vlans-fitcheck`).  No code
changes are required — the data flows from `TargetProfile` →
`/api/v1/migration/target-profiles` → the rename-modal renderer.

### 8. No code changes needed

Target profiles are pure data.
`netcanon/migration/target_profiles.py::load_profiles_dir` walks the
directory at app start, the API serves whatever loaded successfully,
and the UI renders from that.  A new YAML file + a new unit test +
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
  `[0, 4096]`, `device_class` is a known enum value.

What it does NOT enforce (but the unit tests in
`test_target_profile_shipped.py` do):

* port ids parse as valid `PortIdentity` for the codec — wrong port
  spellings load happily, they just silently break the rename mesh,
* duplicate port ids inside the same profile,
* `max_vlans` within the VLAN-ID range,
* `vendor/model` uniqueness — duplicates log a warning, the second
  file wins.

If you're writing a new profile, the unit test is the safety net
for everything in that second list.

---

## What NOT to do

* **Don't put port names in vendor-display form when the codec uses
  internal form.**  Cisco target profiles use `GigabitEthernet1/0/1`,
  not the user-facing `Gi1/0/1` shorthand — the codec's
  `format_port_identity` is canonical and the rename mesh matches
  against its output.  Same for Junos `ge-0/0/0` versus any
  abbreviated form.
* **Don't enumerate ports across modules in the legacy flat shape
  when the model is genuinely modular.**  If the hardware has a
  swappable uplink card, every operator who picks a different SKU
  needs the right uplink set surfaced — flattening the largest SKU
  into `ports:` works for one customer and silently misleads every
  other.  Pick the module-variant shape and register the allowlist.
* **Don't set `max_vlans` to a value the underlying codec can't
  emit.**  The fit-check banner will go green on an over-permissive
  ceiling and the render step will then fail or silently truncate.
  Cross-check against the codec's `_CAPS` matrix before picking a
  number — see
  [`netcanon/migration/codecs/README.md`](../netcanon/migration/codecs/README.md).
* **Don't skip the unit test.**  A copy-paste typo between sibling
  SKUs (the 24G profile that inherits a 48G port range) is the
  exact failure mode the test class exists to catch.  It costs five
  minutes to write and saves a customer ticket.

---

## See also

* [`adding-a-canonical-field.md`](adding-a-canonical-field.md) —
  sibling cookbook for the canonical-schema side (MTU as the worked
  wire-through example)
* [`feature-parity-walkthrough.md`](feature-parity-walkthrough.md) —
  sibling cookbook for cross-platform feature work (web + desktop)
* [`../definitions/README.md`](../definitions/README.md) — schema
  reference for backup-side device definitions; target profiles
  share the same YAML-loader pattern
* [`../netcanon/migration/target_profiles.py`](../netcanon/migration/target_profiles.py)
  — `TargetProfile` / `TargetModule` model classes; the module
  docstring carries the canonical worked-YAML example
* [`../tests/fixtures/module_variants.py`](../tests/fixtures/module_variants.py)
  — module-variant allowlist (single source of truth, CI-guarded)
* [`../tests/unit/migration/test_target_profile_shipped.py`](../tests/unit/migration/test_target_profile_shipped.py)
  — port-list lock-in test pattern
* [`../CLAUDE.md`](../CLAUDE.md) — Documentation Sync Checklist row
  for new target profiles
