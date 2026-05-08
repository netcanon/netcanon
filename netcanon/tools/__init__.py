"""Operator-facing utility tooling — sanitize, etc.

Sub-modules:

* :mod:`netcanon.tools.sanitize` — produce a redacted copy of a network
  config for safe sharing in bug reports, fixture submissions, or
  public discussion.

The canonical-intermediate-model walk drives all of these tools so
sanitization rules track codec evolution automatically: a new field
on :class:`netcanon.migration.canonical.intent.CanonicalIntent` becomes
visible to the sanitizer in the same wave it ships.
"""
