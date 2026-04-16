"""
Canonical YANG intent tree — loader, schema, and validation helpers.

Phase 0 ships only this stub.  The real libyang context loader arrives
in Phase 0.5; Phase 0 code treats the "tree" as an opaque
adapter-internal type and the mock adapter round-trips via plain
``dict[str, str]``.
"""
