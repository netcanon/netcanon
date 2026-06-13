# Result: RA-2021 — R-20 + R-21

Agent: RA-2021 (Sonnet)  
Findings: R-20 (`file_store` hostname decode), R-21 (NETCONF codec port-name banner)  
Branch: `review/2026-06-06-sweep`

---

## Section A — R-20: `file_store._parse_filename` hostname decode

### Finding + current state

`netcanon/storage/file_store.py` lines 344–347:

```python
safe_host = m.group("safe_host")
    # Best-effort host reconstruction: dots were encoded as single
# hyphens and colons (IPv6) as double hyphens.
host = safe_host.replace("--", ":").replace("-", ".")
```

The encode step (line 157):
```python
safe_host = host.replace(":", "--").replace(".", "-")
```

**The decode is NOT a bijection.**  A literal hyphen in the hostname (e.g. `router-1.example.com`) encodes to `router-1-example-com`, which decodes back to `router.1.example.com` — a different host.  Double-hyphens that originated from colons decode correctly, but single hyphens that originated from real hyphens are wrongly turned into dots.

**Impact assessment:**  Display-only.  File lookup, deletion, and collision safety all key on the verbatim filename string — `resolve_path`, `delete`, and `list_configs` all consume the filename directly or via the regex groups (`device_type`/`safe_host`) without ever reconstructing the host.  The `ConfigRecord.host` field is the only consumer of the decoded value; it surfaces in the UI's file listing.  No file is ever mislocated or mis-deleted due to this bug.

**Why bijective encode is impractical without on-disk filename changes:**

A truly bijective scheme (e.g. `%2E` for dot, `%3A` for colon, `%2D` for hyphen) would change the on-disk filename format, breaking every stored file that exists today — `resolve_path` and `_migrate_flat_files` both parse existing filenames via `_FILENAME_RE`.  Re-writing the filename format is a migration-level change far outside P3 scope.

**An alternate percent-escape applied only to hyphens** (encode real hyphens as `%2D`, dots as single `-`, colons as `--`) would be bijective and backward-compatible only for files written after the change.  Old files with real hyphens would still misdecode.  This is no better for the existing corpus.

### Recommendation: document the lossy display; do not change the on-disk format

The safest option is a minimal code fix that:

1. Corrects the indentation bug on line 345 (the comment line is accidentally indented as if it were inside the `safe_host =` assignment — harmless but confusing).
2. Upgrades the inline comment to clearly state "best-effort / lossy for hostnames containing literal hyphens" so no future reader treats this as lossless.
3. Adds a module-level note in the docstring's "Dots and colons" paragraph.

No behavioral change; no on-disk filename change; no migration risk.

### Proposed change

**File:** `netcanon/storage/file_store.py`

**Change 1 — fix indentation + upgrade comment on decode (lines 344–347):**

Old:
```python
        safe_host = m.group("safe_host")
            # Best-effort host reconstruction: dots were encoded as single
        # hyphens and colons (IPv6) as double hyphens.
        host = safe_host.replace("--", ":").replace("-", ".")
```

New:
```python
        safe_host = m.group("safe_host")
        # Best-effort host reconstruction.  Encode: dots → "-", colons → "--".
        # Decode is LOSSY for hostnames that contain literal hyphens
        # (e.g. "router-1.example.com" encodes to "router-1-example-com" which
        # decodes to "router.1.example.com").  This affects display only —
        # file lookup, deletion, and collision safety all key on the verbatim
        # filename, so no file is ever mislocated due to this ambiguity.
        # Changing the on-disk filename format would break existing stored
        # files; the display inaccuracy is the accepted trade-off.
        host = safe_host.replace("--", ":").replace("-", ".")
```

**Change 2 — update module docstring paragraph (lines 27–29):**

Old:
```
Dots and colons in host addresses are replaced with hyphens so filenames are
safe on all platforms.  The metadata fields (device type, host, timestamp) are
recovered by parsing the filename, making the directory self-describing without
a sidecar database.
```

New:
```
Dots and colons in host addresses are replaced with hyphens so filenames are
safe on all platforms.  The metadata fields (device type, host, timestamp) are
recovered by parsing the filename, making the directory self-describing without
a sidecar database.  **Host reconstruction is best-effort**: hostnames
containing literal hyphens (e.g. ``router-1.example.com``) decode with those
hyphens turned into dots — a display-only inaccuracy, since lookups key on
the verbatim filename rather than the reconstructed host.
```

### Test plan

No new test file needed (the fix is documentation-only / comment-fix with no behavioural change).  The existing test suite should continue to pass without modification.

To validate the finding manually:
```python
# Demonstrates the lossy decode:
host = "router-1.example.com"
safe = host.replace(":", "--").replace(".", "-")
# safe == "router-1-example-com"
decoded = safe.replace("--", ":").replace("-", ".")
# decoded == "router.1.example.com"  ← WRONG, dots not hyphens
assert decoded != host  # True — confirms the bug
```

If the orchestrator wants a regression guard:

```python
# tests/unit/storage/test_file_store_hostname_decode.py
"""
R-20 regression guard: _parse_filename decodes host best-effort; confirm the
comment is truthful (lossy for hyphenated hostnames) and file operations are
unaffected.
"""
from pathlib import Path
import tempfile
from datetime import datetime, timezone

import pytest
from netcanon.storage.file_store import FileConfigStore


def test_hyphenated_hostname_display_is_lossy(tmp_path):
    """Host display is lossy for names containing hyphens — expected behaviour.

    Encodes "router-1.example.com" to a safe filename, then verifies that
    list_configs() returns the same file with the decoded (approximate) host.
    The key invariant: the file IS found (filename-keyed ops work); only the
    decoded host display differs.
    """
    store = FileConfigStore(tmp_path)
    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    record = store.save(
        device_type="Cisco",
        host="router-1.example.com",
        timestamp=ts,
        extension="cfg",
        content="hostname router-1\n",
    )

    # File is saved and retrievable by filename — no mislocate.
    content = store.get_content(record.filename)
    assert "hostname router-1" in content

    # list_configs() returns the record — display host is approximate.
    records = store.list_configs()
    assert len(records) == 1
    found = records[0]

    # Verify the filename round-trips exactly (no mislocate).
    assert found.filename == record.filename

    # The decoded host IS lossy (hyphens → dots) — this is documented behaviour.
    # "router-1.example.com" encodes to "router-1-example-com" then decodes to
    # "router.1.example.com".
    assert found.host == "router.1.example.com"  # lossy but predictable
    assert found.host != "router-1.example.com"  # NOT lossless


def test_ipv4_hostname_decodes_correctly(tmp_path):
    """IPv4 addresses (dots only, no hyphens) decode cleanly."""
    store = FileConfigStore(tmp_path)
    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    record = store.save(
        device_type="Cisco",
        host="192.168.1.254",
        timestamp=ts,
        extension="cfg",
        content="hostname R1\n",
    )
    records = store.list_configs()
    assert records[0].host == "192.168.1.254"


def test_ipv6_hostname_decodes_correctly(tmp_path):
    """IPv6 addresses (colons → double-hyphens) decode cleanly."""
    store = FileConfigStore(tmp_path)
    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    record = store.save(
        device_type="Cisco",
        host="2001:db8::1",
        timestamp=ts,
        extension="cfg",
        content="hostname R1\n",
    )
    records = store.list_configs()
    assert records[0].host == "2001:db8::1"
```

### Risk + blast radius

- **No on-disk filename changes.** All existing stored files continue to be found, listed, and deleted correctly.
- **No API/behavioral change.** The `ConfigRecord.host` field already showed the (incorrect) decoded value; after this change it still shows the same decoded value (we are not fixing the decode, just documenting it).
- **Risk: near-zero.** The only change to executable code is the removal of an accidental indentation inconsistency on the comment lines (the `    # Best-effort` line was indented 12 spaces instead of 8 — visually broken but not a Python syntax error).

### Self-assessment

**Confidence: high.**  The encode/decode mismatch is mechanical and unambiguous.  The recommendation to document rather than fix is grounded in the back-compat constraint (changing on-disk filenames would be a breaking migration) and the display-only impact assessment.  The only open question for the orchestrator: if a future release ever wants to fix this fully, the right approach is a sidecar `.meta.json` field for the original host (the sidecar already exists for `device_profile_id`) rather than changing filenames.

---

## Section B — R-21: NETCONF codec port-name no-op banner

### Finding + current state

`netcanon/migration/codecs/cisco_iosxe/codec.py` (`CiscoIOSXECodec`) inherits `CodecBase.classify_port_name` and `CodecBase.format_port_identity` without override.  The base-class defaults return `PortIdentity(kind="unknown")` and `None` respectively.

When `cisco_iosxe` is the **migration target**, the cross-vendor orchestrator in `netcanon/migration/canonical/port_names.py` calls `target_codec.format_port_identity(ident)` for each interface name, gets `None` back, and appends a per-port warning string to `PortRenameResult.warnings`.  For a source config with N interfaces this produces N identical-category warnings like:

```
cisco_iosxe: no native representation for physical GigabitEthernet1/0/1 (source cisco_iosxe_cli); left verbatim.
cisco_iosxe: no native representation for physical GigabitEthernet1/0/2 (source cisco_iosxe_cli); left verbatim.
...
```

These cascade onto `MigrationJob.warnings` (via `run_plan_with_overrides` lines 590–594) and fill the UI's warning panel with per-port noise instead of one actionable banner.

**Root cause:** The codec has no `unsupported_rename_categories` declaration for `"ports"`.  The existing mechanism (`CodecBase.unsupported_rename_categories` → `migrate.html` amber banner) would suppress this per-port chatter entirely — the UI shows ONE amber banner on the ports pane instead of N per-port warnings.

**Mechanism already established:**  `CiscoIOSXECodec` already uses this mechanism for `"snmpv3"` (line 181–183):
```python
unsupported_rename_categories: ClassVar[frozenset[str]] = frozenset({
    "snmpv3",
})
```
The `migrate.html` amber banner path at line 679 and the `_migration_helpers.py` serialiser at line 156–158 already propagate this to the UI.  Adding `"ports"` to the same frozenset is the minimal, correct fix.

**Why this is correct for the NETCONF codec:** The NETCONF codec is a Phase 0.5 stub.  Its `_render_canonical()` only emits the `openconfig-interfaces` subtree; it has no port-name translation logic.  It does NOT override `classify_port_name` or `format_port_identity`.  Declaring `"ports"` in `unsupported_rename_categories` is honest: the codec does not support port-rename and never will until those two methods are implemented.

### Proposed change

**File:** `netcanon/migration/codecs/cisco_iosxe/codec.py`

**Change — add `"ports"` to `unsupported_rename_categories` (lines 181–183):**

Old:
```python
    unsupported_rename_categories: ClassVar[frozenset[str]] = frozenset({
        "snmpv3",
    })
```

New:
```python
    unsupported_rename_categories: ClassVar[frozenset[str]] = frozenset({
        "snmpv3",
        # The NETCONF codec is a Phase 0.5 stub — classify_port_name and
        # format_port_identity are inherited no-ops (CodecBase defaults).
        # Declaring "ports" here surfaces a single amber banner on the
        # port-rename pane of the migrate UI instead of N per-port
        # "no native representation" warnings when this codec is the
        # migration target.  Remove once the stub grows real port-name
        # translation (i.e. classify_port_name + format_port_identity
        # are overridden in this codec).
        "ports",
    })
```

**Update the comment block above the `unsupported_rename_categories` declaration (lines 175–183) to reflect the new member:**

Old:
```python
    # The NETCONF/OpenConfig codec is a Phase-0.5 stub — no SNMPv3
    # wire-up (would require Cisco-IOS-XE-snmp native YANG bridging
    # that hasn't landed).  Declaring ``"snmpv3"`` here surfaces the
    # amber pane-compat banner when operators select this codec as
    # target, matching the capability-matrix ``/snmp/v3-user``
    # ``Unsupported`` declaration below.
    unsupported_rename_categories: ClassVar[frozenset[str]] = frozenset({
        "snmpv3",
    })
```

New:
```python
    # The NETCONF/OpenConfig codec is a Phase-0.5 stub — two categories
    # are unsupported as rename targets:
    #
    # ``"snmpv3"`` — no SNMPv3 wire-up (would require Cisco-IOS-XE-snmp
    #   native YANG bridging that hasn't landed).  Matches the
    #   capability-matrix ``/snmp/v3-user`` ``Unsupported`` declaration.
    #
    # ``"ports"`` — classify_port_name + format_port_identity are
    #   inherited no-ops (CodecBase defaults).  Without this declaration,
    #   using this codec as a migration TARGET generates N per-port
    #   "no native representation" warnings instead of one up-front
    #   amber banner.  Remove when the stub grows real port-name
    #   translation.
    unsupported_rename_categories: ClassVar[frozenset[str]] = frozenset({
        "snmpv3",
        "ports",
    })
```

### How this suppresses per-port warnings

Tracing the execution path when `port_rename_map is not None` and target is `cisco_iosxe`:

1. `run_plan_with_overrides` calls `build_port_rename_transform(source, target, ...)`.
2. The transform calls `translate_port_names(intent, source_codec, target_codec, ...)`.
3. For each interface, `resolve(name)` calls `target_codec.format_port_identity(ident)` → `None`.
4. The `else` branch at `port_names.py:432` appends a per-port warning to `warnings`.
5. These warnings propagate to `job.warnings` via `run_plan_with_overrides:590–594`.

After the fix:
- The UI's JS `updateCompatBanners()` function reads `target.unsupported_rename_categories` from the `/adapters` endpoint.
- When `"ports"` is present, the ports pane shows the amber "this codec doesn't support port rename" banner BEFORE the operator even engages the pane.
- The pipeline still runs (the declaration is a UI hint, not a pipeline gate per `CodecBase` docstring line 200: "This is a DECLARATIVE hint, not a gate").
- The per-port warnings still fire in the pipeline, but the amber banner means the operator already knows to expect them — the noise is contextualised.

**If we also want to suppress the pipeline-level per-port warnings** (not just the UI banner), that requires a small additional change in `port_names.translate_port_names`: before the per-interface loop, check whether the target codec declares `"ports"` in `unsupported_rename_categories` and emit a single up-front warning instead of per-port ones.  This is the more complete fix.  See "Option 2" below.

### Option 1 (minimal — UI banner only, recommended)

Apply only the `unsupported_rename_categories` change above.  One-line code change, zero pipeline behaviour change, consistent with the existing `"snmpv3"` pattern.

### Option 2 (complete — suppress per-port warnings too)

Also change `netcanon/migration/canonical/port_names.py` to emit a single banner-level warning when the target codec's port translation is a no-op.

**Additional change in `port_names.py` — add an early-exit up-front notice:**

In `translate_port_names`, after line 310 (`if not isinstance(intent, CanonicalIntent): return ...`), add:

```python
    # If the target codec declares it doesn't support port rename,
    # emit ONE up-front notice rather than N per-port "no native
    # representation" warnings.  The pipeline still runs (the
    # declaration is a UI hint, not a gate) — interfaces are left
    # verbatim as if format_port_identity returned None for each one.
    if "ports" in getattr(target_codec, "unsupported_rename_categories", frozenset()):
        return PortRenameResult(
            applied={},
            warnings=[
                f"{target_codec.name}: port-name translation is not supported "
                f"for this codec (Phase 0.5 stub — classify_port_name / "
                f"format_port_identity not implemented).  Interface names "
                f"from {source_codec.name} are left verbatim.  No per-port "
                f"rewrites applied."
            ],
            dropped=[],
        )
```

This must be inserted AFTER the `CanonicalIntent` guard and AFTER the `logger.debug("translate_port_names: entry ...")` call, so the entry log still fires.

**Exact insertion point** — after line 309 in `port_names.py`:

Old:
```python
    if not isinstance(intent, CanonicalIntent):
        return PortRenameResult(applied={}, warnings=[], dropped=[])

    user_map = dict(rename_map or {})
```

New:
```python
    if not isinstance(intent, CanonicalIntent):
        return PortRenameResult(applied={}, warnings=[], dropped=[])

    # Early-exit: target codec declares port-name translation unsupported.
    # Emit ONE banner-level warning instead of N per-port "no native
    # representation" warnings.  Behaviour-preserving for codecs that DO
    # implement port-name translation (they won't have "ports" in the set).
    if "ports" in getattr(target_codec, "unsupported_rename_categories", frozenset()):
        logger.debug(
            "translate_port_names: target %s declares ports unsupported — "
            "skipping per-port rename loop, emitting single banner warning",
            target_codec.name,
        )
        return PortRenameResult(
            applied={},
            warnings=[
                f"{target_codec.name}: port-name translation is not supported "
                f"(inherited no-op classify_port_name / format_port_identity). "
                f"Interface names from {source_codec.name} are carried verbatim. "
                f"No per-port rewrites applied."
            ],
            dropped=[],
        )

    user_map = dict(rename_map or {})
```

**Orchestrator recommendation:** Option 2 is slightly larger but strictly better — it eliminates the warning spam at the pipeline level rather than merely contextualising it in the UI.  Option 1 alone leaves N warnings in `job.warnings` even though the operator already saw the amber banner.  The extra 15-line change in `port_names.py` is low risk (it only activates for codecs that explicitly declare `"ports"` in `unsupported_rename_categories`, which is currently no codec — the fix is additive until `cisco_iosxe` gains the declaration).

### Test plan

**New test file (full content):**

```python
# tests/unit/migration/codecs/cisco_iosxe/test_port_name_noop_banner.py
"""
R-21 regression guard: CiscoIOSXECodec (NETCONF) declares "ports" in
unsupported_rename_categories, producing an up-front banner warning rather
than N per-port warnings when used as a migration target.
"""
from __future__ import annotations

import pytest

from netcanon.migration.codecs.cisco_iosxe.codec import CiscoIOSXECodec
from netcanon.migration.codecs.cisco_iosxe_cli.codec import CiscoIOSXECLICodec
from netcanon.migration.canonical.port_names import (
    PortIdentity,
    PortRenameResult,
    translate_port_names,
)
from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
)


class TestCiscoIOSXEUnsupportedRenameCategories:
    def test_ports_declared_unsupported(self):
        """cisco_iosxe (NETCONF) must declare 'ports' in unsupported_rename_categories."""
        codec = CiscoIOSXECodec()
        assert "ports" in codec.unsupported_rename_categories

    def test_snmpv3_still_declared_unsupported(self):
        """Regression: 'snmpv3' must remain in unsupported_rename_categories."""
        codec = CiscoIOSXECodec()
        assert "snmpv3" in codec.unsupported_rename_categories

    def test_classify_port_name_returns_unknown(self):
        """Inherited no-op: classify_port_name returns kind='unknown'."""
        codec = CiscoIOSXECodec()
        ident = codec.classify_port_name("GigabitEthernet1/0/1")
        assert ident.kind == "unknown"
        assert ident.original == "GigabitEthernet1/0/1"

    def test_format_port_identity_returns_none(self):
        """Inherited no-op: format_port_identity returns None."""
        codec = CiscoIOSXECodec()
        ident = PortIdentity(kind="physical", port=1, original="Gi1/0/1")
        result = codec.format_port_identity(ident)
        assert result is None


class TestTranslatePortNamesBannerBehaviour:
    """Verify that the up-front banner path fires for cisco_iosxe target.

    These tests apply to Option 2 (the port_names.py early-exit change).
    If only Option 1 (unsupported_rename_categories) is applied, skip the
    single-warning assertion tests and keep only the codec-level tests above.
    """

    def _make_intent_with_interfaces(self, names: list[str]) -> CanonicalIntent:
        intent = CanonicalIntent(
            source_vendor="cisco_iosxe_cli",
            source_format="cli-ios",
        )
        for name in names:
            intent.interfaces.append(CanonicalInterface(name=name))
        return intent

    def test_single_warning_not_per_port(self):
        """With N interfaces, translate_port_names emits exactly 1 warning
        when target declares 'ports' unsupported (Option 2 behaviour)."""
        source = CiscoIOSXECLICodec()
        target = CiscoIOSXECodec()
        intent = self._make_intent_with_interfaces([
            "GigabitEthernet1/0/1",
            "GigabitEthernet1/0/2",
            "GigabitEthernet1/0/3",
            "Loopback0",
        ])
        result = translate_port_names(intent, source, target, rename_map={})
        # Single up-front banner, not 4 per-port warnings.
        assert len(result.warnings) == 1
        assert "not supported" in result.warnings[0].lower() or \
               "no port" in result.warnings[0].lower() or \
               "unsupported" in result.warnings[0].lower()

    def test_no_renames_applied(self):
        """No renames when target's port rename is a no-op."""
        source = CiscoIOSXECLICodec()
        target = CiscoIOSXECodec()
        intent = self._make_intent_with_interfaces(["GigabitEthernet1/0/1"])
        result = translate_port_names(intent, source, target, rename_map={})
        assert result.applied == {}

    def test_no_drops(self):
        """No drops when target's port rename is a no-op (interfaces survive verbatim)."""
        source = CiscoIOSXECLICodec()
        target = CiscoIOSXECodec()
        intent = self._make_intent_with_interfaces(["GigabitEthernet1/0/1"])
        result = translate_port_names(intent, source, target, rename_map={})
        assert result.dropped == []
        # Interface name is preserved verbatim.
        assert intent.interfaces[0].name == "GigabitEthernet1/0/1"

    def test_codecs_with_port_translation_unaffected(self):
        """Codecs that DO implement port translation are unaffected by the
        early-exit guard (they don't have 'ports' in unsupported_rename_categories)."""
        from netcanon.migration.codecs.opnsense.codec import OPNsenseCodec
        target = OPNsenseCodec()
        assert "ports" not in target.unsupported_rename_categories
```

**Existing tests to run:**
```
py -m pytest tests/unit/migration/codecs/cisco_iosxe/ -v
py -m pytest tests/unit/migration/ -v -k "port"
```

### Risk + blast radius

**Option 1 only (unsupported_rename_categories addition):**
- Additive change — no existing test should fail.
- The amber banner appears in the UI for `cisco_iosxe` as a target, consistent with `"snmpv3"`.
- Per-port warnings still fire in `job.warnings`; they are not suppressed.
- Risk: near-zero.

**Option 2 (port_names.py early-exit):**
- The early-exit fires ONLY when `"ports"` is in the target codec's `unsupported_rename_categories`.  No current codec (except `cisco_iosxe` after the Option 1 change) declares this, so existing tests are unaffected.
- Interfaces are left verbatim (same as the current per-port fallback behaviour — no data loss).
- `strip_unmappable` flag is bypassed in the early-exit path; interfaces are NOT dropped.  This is correct behaviour: the codec can't rename ports but it CAN render them (the `_render_canonical` path uses interface names verbatim from the canonical tree).
- Risk: low.  The new code path is gated on the `unsupported_rename_categories` check and has a clear comment explaining why.

**Interaction with `strip_unmappable`:**  The early-exit in Option 2 bypasses `strip_unmappable`.  This is correct for `cisco_iosxe`: the target CAN render the interface names from the source verbatim (they appear in OpenConfig `<name>` elements); it just can't TRANSLATE them.  Dropping them would be wrong.  If future codecs declare `"ports"` but DO want strip-unmappable behaviour, the early-exit can be made conditional on `strip_unmappable`.  Leave as-is for now (simpler, correct for the only current case).

### Self-assessment

**Confidence: high.**  The `unsupported_rename_categories` mechanism is already established and tested for `"snmpv3"`.  Adding `"ports"` follows an identical pattern.  The Option 2 early-exit in `port_names.py` is small, gated, and directly observable in the unit tests above.

**Open question for orchestrator:** Should Option 2 also be applied, or is Option 1 (UI banner only) sufficient for P3?  The finding says "propose surfacing a single up-front notice"; Option 2 achieves this at the pipeline level; Option 1 achieves it only at the UI level.  I recommend Option 2 as the complete fix since it eliminates the `job.warnings` spam for API callers too.
