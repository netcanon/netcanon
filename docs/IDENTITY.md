# Netcanon — Brand & Identity

Source-of-truth for project identity surfaces (taglines, descriptions,
GitHub Topics, logo direction).  When something below changes, update
both this doc and the place it gets surfaced (PyPI metadata, README
header, GitHub repo settings).

This is the deliverable from Phase 2 of
[`docs/RELEASE_PLAN.md`](RELEASE_PLAN.md).

---

## Tagline

> **Multi-vendor network config translator with a verifiable cross-vendor audit.**

Used in:

- [`pyproject.toml`](../pyproject.toml) `description` field (PyPI listing)
- [`README.md`](../README.md) header (above-the-fold)
- GitHub repo About section (extended form below)

The tagline captures action (translate) + scope (multi-vendor) +
differentiator (verifiable audit).  Honesty about the differentiator
is what carries the matrix-honesty discipline into the marketing
surface.

---

## GitHub repo description (extended)

```
Multi-vendor network config translator — Cisco / Juniper / Fortinet / Aruba / Arista / MikroTik / OPNsense. Cross-mesh audit catches silent translation errors before they ship.
```

(Fits comfortably under GitHub's 350-char limit.  Names the vendor
families explicitly so the repo lands in vendor-specific search
results.)

**To set:** GitHub → Repo Settings → "About" → Description.

---

## GitHub Topics

To set on the repo (the list below; GitHub allows up to 20):

```
network-automation
network-configuration
cisco
juniper
fortinet
aruba
arista
mikrotik
opnsense
vendor-translation
config-migration
python
fastapi
```

These mirror the `keywords` field in [`pyproject.toml`](../pyproject.toml).
When a new vendor codec ships, add its topic here AND in
`pyproject.toml`.

**To set:** GitHub → Repo page → "About" gear icon → "Topics" field.

---

## Logo design brief

### Brand essence

Netcanon is a multi-vendor network config translator built on a
canonical-intermediate-language architecture and a matrix-honesty
discipline.  The differentiator is verifiable accuracy: every field's
translation is declared as supported, lossy, or unsupported with a
cited reason, and a cross-mesh audit catches silent errors.

### Audience

Network engineers — skeptical of automation, value clarity over
flash, familiar with vendor logos like Cisco / Juniper / Aruba.  The
visual register should match other operator tools (Wireshark, NAPALM,
Batfish) — clean, geometric, no ornamentation.

### Concept directions

**A. Mosaic cell (recommended).**  3×3 or 4×4 grid of squares with
one square highlighted in an accent color.  Reads as "every cell
tested" + visualises the cross-mesh audit.  Geometric,
brand-defensible, scales to favicon size.

**B. N letterform.**  Capital "N" with the diagonal stroke styled as
a translation arrow (chevron, dashed line, or "→" motif).  Compact
and favicon-friendly.

**C. Network constellation.**  Multiple nodes (one per vendor family)
connected by lines.  Storytelling-heavy; doesn't scale well below
~64×64.

### Visual constraints

- **Color.**  Operator-tool aesthetic: deep slate (`#1e2a35`) or dark
  teal (`#0f3a3a`) primary.  Single warm accent (`#f59e0b` amber or
  `#d97706` rust).  No gradients.
- **Typography.**  Geometric sans for the wordmark — Inter, JetBrains
  Mono, or Fira Code.  Uppercase "NETCANON" gives the right weight.
- **Simplicity.**  Must work as a 16×16 favicon.  Single-color
  (monochrome) variant must be legible.
- **No clichés.**  No globes, no padlocks, no swooshes, no lightning
  bolts, no ".io"-style abstract shapes.

### Deliverables (when commissioned)

- SVG primary logo (wordmark + icon)
- SVG icon-only mark (favicon / repo avatar / social cards)
- PNG raster exports at 16 / 32 / 64 / 128 / 256 / 512 px
- Color + monochrome variants
- Hex color codes documented here once finalised

### Status

**Not yet commissioned.**  This brief is the design spec for whoever
commissions the work — operator self-design, designer-for-hire, or
AI-generated.

A starter Midjourney prompt for Direction A:

> *"minimalist 4×4 grid mosaic logo, one cell highlighted in amber,
> dark slate background, geometric, vector, network engineering
> aesthetic, no gradients, flat"*

---

## See also

- [`docs/COMPARISON.md`](COMPARISON.md) — positioning vs adjacent
  tools (Batfish, Capirca, NAPALM, etc.)
- [`docs/CAPABILITIES.md`](CAPABILITIES.md) — operator-facing
  capabilities and Tier-3 boundary
- [`docs/RELEASE_PLAN.md`](RELEASE_PLAN.md) — Phase 2 of which this
  doc is the deliverable
- [`README.md`](../README.md) — where the tagline lands
