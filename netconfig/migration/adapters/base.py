"""
Adapter contract: :class:`AdapterBase` + :class:`CapabilityMatrix`.

Every vendor adapter subclasses :class:`AdapterBase` and ships:

    * ``name`` — unique, used as the adapter key in requests and URLs.
    * ``capabilities`` — a :class:`CapabilityMatrix` describing what
      paths the adapter can round-trip.
    * ``parse(raw)`` — convert a raw config string into an
      adapter-internal (Phase 0) or canonical-YANG-tree (Phase 0.5+)
      representation.
    * ``render(tree)`` — emit a raw config string from the tree.

The contract's key invariant is the round-trip::

    adapter.parse(adapter.render(tree)) == tree

for every tree in the adapter's supported subset.  Adapters must test
this explicitly; see ``tests/unit/migration/test_mock_adapter.py`` for
the reference pattern.

Thread-safety: adapters are instantiated fresh per call by the
registry; instances are stateless unless documented otherwise.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Iterable

from ...models.migration import CapabilityMatrix


class AdapterError(Exception):
    """Base class for adapter-layer errors.

    Subclasses separate *parsing* failures (malformed input) from
    *rendering* failures (tree states the adapter cannot emit).  The
    pipeline stage layer translates these into ``MigrationJob``
    terminal-failure states.
    """


class ParseError(AdapterError):
    """Raised by ``AdapterBase.parse`` when the input cannot be understood.

    Attributes:
        path: Adapter-scoped location of the failure (e.g. line number,
            YAML xpath).  ``None`` when the adapter cannot pinpoint.
        snippet: Up to ~120 characters of the offending input, for
            display in the UI.
    """

    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        snippet: str | None = None,
    ) -> None:
        super().__init__(message)
        self.path = path
        self.snippet = snippet


class RenderError(AdapterError):
    """Raised by ``AdapterBase.render`` when a tree cannot be emitted.

    Attributes:
        yang_path: xpath of the offending tree node; ``None`` when the
            adapter cannot pinpoint.
    """

    def __init__(
        self, message: str, *, yang_path: str | None = None
    ) -> None:
        super().__init__(message)
        self.yang_path = yang_path


#: Canonical catalogue of adapter input formats.  Short strings so they
#: can be used as HTML ``data-*`` attribute values; the UI maps them to
#: human-readable descriptions.  Add new values sparingly.
INPUT_FORMATS = frozenset({
    "xml-netconf",      # OpenConfig NETCONF <get-config> payload (Cisco IOS-XE)
    "xml-opnsense",     # OPNsense config.xml
    "xml-panos",        # Palo Alto PAN-OS XML (reserved — no adapter yet)
    "cli-ios",          # `show running-config` text (reserved — no adapter yet)
    "cli-fortigate",    # FortiGate CLI `config` blocks (reserved)
    "cli-mikrotik",     # MikroTik `/export` text (reserved)
    "json-flat",        # flat {"xpath": "value"} JSON — the mock adapter
    "unknown",          # experimental adapter with no declared format
})


class AdapterBase(ABC):
    """Abstract base class all vendor adapters subclass.

    Minimal contract — subclasses may add helper methods freely.  The
    registry invokes the zero-arg constructor so adapters that need
    configuration should read it from their module-level globals or
    accept ``**kwargs`` with defaults.

    Attributes:
        name: Class-level registration key.  Must be unique across the
            registry and stable across releases.
        version_hint: Optional vendor OS version this adapter targets
            (e.g. ``"17.x"`` for Cisco IOS-XE 17.x).  Informational;
            version gating lives in the :class:`CapabilityMatrix`.
        input_format: Short catalogue tag describing what ``parse()``
            expects.  Used by the UI to (a) show a human-readable hint
            on the /migrate page, (b) provide a matching placeholder,
            and (c) filter the stored-config dropdown to files the
            source adapter can actually parse.  Must be one of
            :data:`INPUT_FORMATS`; default is ``"unknown"`` so adapters
            under development don't break the UI.
    """

    #: Unique registry key.  Subclasses MUST override.
    name: ClassVar[str]

    #: Optional human-readable OS version hint for UI display.
    version_hint: ClassVar[str | None] = None

    #: Catalogue tag for the input format ``parse()`` accepts.
    input_format: ClassVar[str] = "unknown"

    @property
    @abstractmethod
    def capabilities(self) -> CapabilityMatrix:
        """Return the adapter's :class:`CapabilityMatrix`.

        May be constructed fresh on each call (for adapters whose
        capabilities depend on discovered device state) or cached at
        class level.
        """

    @abstractmethod
    def parse(self, raw: str) -> Any:
        """Parse *raw* config text into a tree.

        Phase 0 treats the tree as adapter-internal.  Phase 0.5+
        migrates to a canonical libyang-validated tree.

        Raises:
            ParseError: When *raw* cannot be parsed.
        """

    @abstractmethod
    def render(self, tree: Any) -> str:
        """Render *tree* back into raw config text.

        The inverse of :meth:`parse`.  The round-trip invariant
        ``parse(render(tree)) == tree`` MUST hold for every tree in
        the adapter's supported subset.

        Raises:
            RenderError: When *tree* contains paths the adapter
                cannot emit.  Callers should have run the
                ``strip_unsupported`` transform first if the target
                :class:`ValidationReport` flagged any paths.
        """

    def iter_xpaths(self, tree: Any) -> Iterable[str]:
        """Yield canonical xpaths for every leaf in *tree*.

        Used by the validate service to classify a tree against the
        target's :class:`CapabilityMatrix`.  Yielded xpaths are the
        *schema paths* — no list-key predicates — so they match the
        strings declared in ``CapabilityMatrix.supported /
        .lossy / .unsupported``.

        The default implementation handles the flat ``dict[str, str]``
        shape used by the reference mock adapter.  Adapters with
        nested tree shapes (e.g. :class:`CiscoIOSXEAdapter`, which
        uses a nested dict mirroring the OpenConfig XML tree) MUST
        override.
        """
        if isinstance(tree, dict):
            for key in tree:
                if isinstance(key, str):
                    yield key
