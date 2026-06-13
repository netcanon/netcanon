# RA-19 — Result: `models/migration.py` codec-contract placement

**Verdict:** KEEP + document  
**Risk:** None (no code change)  
**Confidence:** High

---

## 1. Evidence gathered

### 1.1 What `codecs/base.py` imports from `models/migration.py`

`netcanon/migration/codecs/base.py:31`:

```python
from ...models.migration import CapabilityMatrix
```

Only `CapabilityMatrix` is imported at the base-class level. `LossyPath` and
`UnsupportedPath` are not imported into `base.py` — they appear only in the
`CapabilityMatrix` fields (`lossy: list[LossyPath]`, `unsupported:
list[UnsupportedPath]`) and are imported directly by each codec's `codec.py`
for constructing the concrete `_CAPS` object.

### 1.2 Full import graph for the three types (repo-wide)

**Sites that import `CapabilityMatrix` / `LossyPath` / `UnsupportedPath`
from `models/migration.py`:**

| Caller | Module | Role |
|--------|--------|------|
| `migration/codecs/base.py:31` | `from ...models.migration import CapabilityMatrix` | Abstract base — `capabilities` return type |
| `migration/codecs/_mock/codec.py:27-30` | `CapabilityMatrix, LossyPath, UnsupportedPath` | Mock codec `_CAPS` construction |
| `migration/codecs/aruba_aoss/codec.py` | `from ....models.migration import …` | Codec `_CAPS` construction |
| `migration/codecs/arista_eos/codec.py:42` | `from ....models.migration import …` | Codec `_CAPS` construction |
| `migration/codecs/cisco_iosxe/codec.py:103` | `from ....models.migration import …` | Codec `_CAPS` construction |
| `migration/codecs/cisco_iosxe_cli/codec.py:52` | `from ....models.migration import …` | Codec `_CAPS` construction |
| `migration/codecs/fortigate_cli/codec.py:32` | `from ....models.migration import …` | Codec `_CAPS` construction |
| `migration/codecs/juniper_junos/codec.py:60` | `from ....models.migration import …` | Codec `_CAPS` construction |
| `migration/codecs/mikrotik_routeros/codec.py:69` | `from ....models.migration import …` | Codec `_CAPS` construction |
| `migration/codecs/opnsense/codec.py:46` | `from ....models.migration import …` | Codec `_CAPS` construction |
| `services/migration_validate.py:20-23` | `CapabilityMatrix, LossyPath, UnsupportedPath` | Validate service uses all three |
| `api/routes/migration.py:104,160,164` | `CapabilityMatrix` | `GET /adapters/{name}/capabilities` response model |
| `tests/unit/migration/test_input_format.py:27` | `CapabilityMatrix` | Test construction |
| `tests/unit/migration/test_models.py:13` | (multiple) | Model tests |
| `tests/unit/migration/test_validate.py:13` | (multiple) | Validate tests |
| Various capability-matrix codec tests | `CapabilityMatrix` | Test construction |

**`models/__init__.py:6-19`** re-exports all three types as part of the
flat `netcanon.models` public surface alongside `BackupJob`, `DiffReport`,
etc. — i.e. they are already treated as platform-level DTOs, not internal
codec vocabulary.

### 1.3 Dependency direction

The import edge is `codecs → models.migration`. `models/` is a dependency leaf
— nothing in `models/` imports from `migration/codecs/` or `services/`. The
graph is **acyclic and clean**, as CD confirmed. This is a downward edge in
the stack (`codecs` → shared models), not a reach-across.

### 1.4 The "cross-layer smell" argument examined

The CA-03 finding notes that the codec-contract vocabulary lives outside the
`migration/codecs/` sub-package. This is a valid observation but evaporates
on closer inspection for two reasons:

1. **`CapabilityMatrix` is a serialised API response.** `GET
   /api/v1/migration/adapters/{name}/capabilities` returns the full
   `CapabilityMatrix` object directly (`api/routes/migration.py:160,164`).
   The type is therefore legitimately a platform-model DTO — it belongs in
   `models/` alongside `ValidationReport`, `MigrationJob`, and `CodecInfo`
   for exactly the same reason those types live there: they cross the
   HTTP boundary.

2. **`models/migration.py` is already cohesive as a schema file.** CE
   judged it KEEP-AS-IS: "large because the canonical surface is large —
   which is a documentation win, not a god-file." The module is 12 Pydantic
   classes + 1 method, zero service logic. `CapabilityMatrix` / `LossyPath`
   / `UnsupportedPath` fit in this cohesion family — they are data-only
   Pydantic models describing the codec-contract surface.

### 1.5 Move cost vs benefit

A move to `codecs/base.py` or a new `codecs/_matrix.py` would require
updating **every import site** — the base class, all 8 production codecs +
mock, the validate service, the API routes, and ~15 test files, for a total
of roughly 30+ files. In addition:

- `models/__init__.py` would need to either re-export from the new location
  (adding an indirect coupling) or drop the public export (breaking any
  caller using `from netcanon.models import CapabilityMatrix`).
- `GET /adapters/{name}/capabilities` returns `CapabilityMatrix` as its
  response model — keeping it in `models/` is the natural home for an HTTP
  response type.
- The 4-level relative imports in each codec (`from ....models.migration
  import …`) would become 2-level (`from ..contract import …`), which is
  genuinely cleaner, but this is a readability nicety not a correctness fix.
- CE's verdict ("KEEP-AS-IS") and CD's analysis ("deep but not reach-ins in
  the pejorative sense; every one targets a stable, intentional surface") are
  both on record.

**Net assessment:** broad churn (30+ files) for zero correctness gain and
a cosmetic import-depth reduction. The CE KEEP verdict is well-grounded.

---

## 2. Recommendation: KEEP + document

No code change. The placement is correct: `CapabilityMatrix` / `LossyPath` /
`UnsupportedPath` are Pydantic DTOs that cross the HTTP boundary and belong
in the platform models layer alongside `ValidationReport` and `MigrationJob`.

The only action is a short `ARCHITECTURE.md` note recording this as an
explicit decision rather than an accidental smell, so a future contributor
does not re-open the question without context.

---

## 3. Proposed `ARCHITECTURE.md` addition (literal old → new)

**Location:** `ARCHITECTURE.md`, Layer 2 — Format Codec section, after the
paragraph ending `"...no manual wiring."` (currently ending around line 166
with the sentence `"...pkgutil auto-discovery at app startup picks it up —
no manual wiring."`).

**Old** (the paragraph immediately before the `For authoring instructions`
line):

```
**Auto-registration.** Drop a subpackage under
`netcanon/migration/codecs/`, decorate the class with `@register`,
and `pkgutil` auto-discovery at app startup picks it up — no manual
wiring.
```

**New** (add the following block immediately after that paragraph, before
the `For authoring instructions` line):

```
**Codec-contract types live in `models/migration.py`, not in
`codecs/`.** `CapabilityMatrix`, `LossyPath`, and `UnsupportedPath`
are defined in `netcanon/models/migration.py` alongside the other
platform DTOs (`ValidationReport`, `MigrationJob`, `CodecInfo`).
This is intentional: `CapabilityMatrix` is returned verbatim over
HTTP (`GET /api/v1/migration/adapters/{name}/capabilities`) and
therefore belongs in the shared models layer that the API routes,
the validate service, and the codecs all import from a common leaf.
The dependency direction is strictly downward — `codecs/` imports
`models/`; `models/` imports nothing from `codecs/`.  A codec
author reaching for `CapabilityMatrix` uses
`from ....models.migration import CapabilityMatrix` (four dots
because the codec lives at `migration/codecs/<vendor>/`); this
depth is a function of the directory nesting, not of an incorrect
layering.
```

---

## 4. Risk assessment

| Dimension | Assessment |
|-----------|------------|
| Code risk | None — no code change |
| Doc change scope | One paragraph added to ARCHITECTURE.md Layer 2 section |
| Correctness impact | None |
| Import graph impact | None |
| Test impact | None |

---

## 5. Self-assessment

- **Confidence:** High. The API-DTO argument is deterministic: any type
  returned directly as a FastAPI `response_model` has a legitimate home in
  `models/`. The acyclic graph is confirmed by CD. CE's KEEP verdict and
  the 30+ file move cost both point unambiguously to KEEP.
- **Uncertainty:** None of substance. The one open micro-question (whether
  a future `codecs/_contract.py` re-export shim would be worthwhile) is
  answered "no" by the fact that `models/__init__.py` already provides a
  flat re-export.
- **What was NOT checked:** whether any external (third-party) consumer
  imports from `netcanon.models` — out of scope for a single-repo review.
