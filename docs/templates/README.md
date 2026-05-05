# `docs/templates/` — Starter Scaffolding for Matrix-Honesty Projects

This directory is **clone-and-adapt scaffolding** for a new project that
wants to inherit the matrix-honesty discipline — the practice of
declaring what you can and can't do, proving it via tests, and keeping
the prose, code, and assertions aligned commit-by-commit.

If you landed here cold, start with the **sister document**
[`../METHODOLOGY.md`](../METHODOLOGY.md) — that's the *why* behind the
shape of every file in this directory.  These templates are the *what*:
the concrete artefacts that operationalise the discipline.

---

## What this directory is

A set of generic, project-agnostic markdown / YAML templates extracted
from a real working project (NetConfig, a multi-vendor network config
translator) where the matrix-honesty discipline has been exercised over
hundreds of commits.  Each template encodes a pattern that worked there
and is portable elsewhere — you don't need to be writing a network
config translator to benefit.

**What it is NOT:**

* Not a framework.  No code to import, no CLI to run.  These are
  markdown and YAML files you copy into your own repo and edit.
* Not opinionated about your stack.  The templates work for a
  scientific data pipeline, a chat client, a calculator app, a
  compiler, a CRUD web service.  Where the source project's specifics
  bleed through (e.g. "vendor codec", "canonical intent tree"),
  they're called out as illustrative and given a generic placeholder.
* Not a substitute for thinking.  Templates encode patterns; you still
  decide which patterns apply to your project's actual surface area.

---

## What's in here

| Template | Purpose |
|---|---|
| `CLAUDE.md.template` | Operational rulebook for AI / human contributors — doc-sync checklist + hard rules |
| `ARCHITECTURE.md.template` | Conceptual map: layers, invariants, cross-cutting policies |
| `CHANGELOG.md.template` | Keep-a-Changelog-shaped log with rationale-first entries |
| `CAPABILITIES.md.template` | Operator-facing capabilities + known limitations matrix |
| `RELEASE_PLAN.md.template` | Forward-looking plan for taking a private project public |
| `SECURITY.md.template` | Substantive threat model (not just "email us") |
| `CONTRIBUTING.md.template` | Walkthroughs for the most common contribution shapes |
| `.github/ISSUE_TEMPLATE/bug_report.yml` | Pre-filled GitHub Issue Form for bug reports |
| `.github/ISSUE_TEMPLATE/feature_request.yml` | Pre-filled GitHub Issue Form for feature requests |
| `.github/ISSUE_TEMPLATE/fixture_submission.yml` | Pre-filled GitHub Issue Form for test-fixture donations (optional) |

Every template ends with a "See also" footer pointing at
`METHODOLOGY.md` and its closest siblings inside this directory.

---

## How to use these templates

### Step 1 — copy what you need

```sh
cp docs/templates/CLAUDE.md.template       /path/to/your-repo/CLAUDE.md
cp docs/templates/ARCHITECTURE.md.template /path/to/your-repo/ARCHITECTURE.md
cp docs/templates/CHANGELOG.md.template    /path/to/your-repo/CHANGELOG.md
# ... etc
```

You don't need to copy everything — pick the templates that fit your
project's current stage.  A library project may not need `CAPABILITIES.md`
yet; a private R&D project doesn't need `RELEASE_PLAN.md` until it's
nearing public release.

### Step 2 — replace placeholders

Templates use a small set of consistent placeholder forms:

| Placeholder | Meaning |
|---|---|
| `<PROJECT_NAME>` | Your project's name |
| `<COMPONENT>` / `<MODULE>` | Your project's primary unit of architecture (codec, plugin, layer, package) |
| `<CORE_ABSTRACTION>` | Your project's central data model (e.g. `CanonicalIntent` in NetConfig — replace with whatever yours is called) |
| `<VENDOR>` / `<INTEGRATION>` | External entities your project interfaces with |
| `<EXAMPLE: ...>` | An illustrative example to either edit or remove |
| `<!-- PROJECT: ... -->` | HTML-style comment with guidance the project-author should resolve and then delete |

A `git grep '<PROJECT' -- '*.md'` after copying surfaces every spot
that still needs your attention.

### Step 3 — adapt rows to your project's surface

The doc-sync checklist in `CLAUDE.md.template` lists *kinds* of changes
("a new public function", "a new test marker", "a new hard rule").  The
rows are illustrative — you'll have your own kinds.  When you add a
new test fixture concept, a new translation tier, a new pipeline stage,
add a row.  The rows come from the failure modes you've actually seen,
not from a template author's imagination.

### Step 4 — wire the cross-references

Each template's "See also" footer points at its peer documents.  After
you've placed all the files in your repo, do a final pass to make sure
the reciprocal links exist — a one-way reference rots faster than any
of the content it points at.

---

## What you get from following the discipline

The matrix-honesty discipline pays off in three ways:

1. **Trust** — operators / users / downstream consumers can verify
   your accuracy claims because every claim has a test or a doc that
   says *what you actually do* (not "what should be possible").
2. **Decision velocity** — when you can read your own
   `CAPABILITIES.md` and trust it, you don't waste cycles
   re-deriving "wait, do we support X?" every quarter.
3. **Survival across LLM contexts** — if AI agents help develop your
   project, the doc-sync checklist gives them a deterministic
   instrument for keeping prose aligned with code, even across
   compactions or session changes.

---

## Where to see this in practice

The source project is publicly viewable; clone it and walk the live
versions of these files to see them filled in:

* `CLAUDE.md` — the actual operational rulebook
* `ARCHITECTURE.md` — the actual layered design doc
* `CHANGELOG.md` — actual rationale-first entries
* `docs/CAPABILITIES.md` — actual matrix with per-component rows
* `docs/RELEASE_PLAN.md` — actual forward-looking plan
* `SECURITY.md` — actual threat model

Reading the live version alongside the template clarifies which parts
are shape-of-the-discipline (template-stable) vs. project-specific
(template-placeholder).

---

## Future plan: extract to a standalone repository

Once the templates have been adapted on a second project and proven
to generalise (i.e. "I cloned them into my completely-unrelated app
and they still made sense"), they will be extracted to a standalone
repository — provisional name `claude-matrix-honesty-template`.

That extraction is **not yet done**.  Until then, this directory is
the canonical home and any improvements should land here as commits
to the source project.  When the extraction happens, this directory
will become a pointer to the standalone repo.

If you adapt these templates to your project, reach out — your
real-world friction with the placeholders is exactly the signal that
helps decide what to keep generic vs. what to drop.

---

## See also

* [`../METHODOLOGY.md`](../METHODOLOGY.md) — the discipline behind the
  templates' shape (sister document; explains *why* each section is
  shaped the way it is)
* [`../CAPABILITIES.md`](../CAPABILITIES.md) — the live, filled-in
  capabilities document this directory's `CAPABILITIES.md.template`
  was extracted from
* [`../../CLAUDE.md`](../../CLAUDE.md) — the live operational rulebook
  that `CLAUDE.md.template` was extracted from
* [`../RELEASE_PLAN.md`](../RELEASE_PLAN.md) — the live release plan
  that `RELEASE_PLAN.md.template` was extracted from
