"""
Adapter contract: :class:`CodecBase` + :class:`CapabilityMatrix`.

Every vendor adapter subclasses :class:`CodecBase` and ships:

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


class CodecError(Exception):
    """Base class for adapter-layer errors.

    Subclasses separate *parsing* failures (malformed input) from
    *rendering* failures (tree states the adapter cannot emit).  The
    pipeline stage layer translates these into ``MigrationJob``
    terminal-failure states.
    """


class ParseError(CodecError):
    """Raised by ``CodecBase.parse`` when the input cannot be understood.

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


class RenderError(CodecError):
    """Raised by ``CodecBase.render`` when a tree cannot be emitted.

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


class CodecBase(ABC):
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

    #: Direction capability.  ``"bidirectional"`` (default) means the
    #: codec can both parse AND render.  ``"parse_only"`` means render()
    #: raises NotImplementedError — the UI should only offer the codec as
    #: a SOURCE, never as a TARGET.  ``"render_only"`` is the reverse.
    direction: ClassVar[str] = "bidirectional"

    #: Certainty tier (see translator-plans.txt "Certainty Model").
    #:   ``"certified"``     — round-trip tested against ≥3 real captures.
    #:   ``"best_effort"``   — tested against synthetic samples only.
    #:   ``"experimental"``  — parse-only or incomplete; human review needed.
    certainty: ClassVar[str] = "experimental"

    #: Which canonical intent model this codec's tree shape targets.
    #: Default ``"openconfig-lite"`` covers the L2/L3 subset we support;
    #: firewall codecs will declare ``"netconfig-firewall-ext"`` etc.
    canonical_model: ClassVar[str] = "openconfig-lite"

    #: Human-readable description of what :meth:`parse` expects.  Shown
    #: in the /migrate UI's format-hint banner.  One short paragraph,
    #: no line breaks — the UI wraps as needed.  Empty string means
    #: "fall back to generic help text".
    description: ClassVar[str] = ""

    #: Minimal working sample of this codec's input format.  Used by
    #: the /migrate UI's "Load sample" button to populate the textarea.
    #: Empty string means "no sample available" (button becomes inert).
    #: Keep samples small and sanitised — no real IPs, credentials,
    #: or identifiable device serials.
    sample_input: ClassVar[str] = ""

    #: File extension (without the dot) to offer when the UI downloads
    #: this codec's rendered output.  Empty string defaults to ``"cfg"``
    #: at the UI layer.  Examples: ``"xml"``, ``"rsc"``, ``"json"``.
    output_extension: ClassVar[str] = ""

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
        nested tree shapes (e.g. :class:`CiscoIOSXECodec`, which
        uses a nested dict mirroring the OpenConfig XML tree) MUST
        override.
        """
        if isinstance(tree, dict):
            for key in tree:
                if isinstance(key, str):
                    yield key

    @classmethod
    def probe(cls, raw_prefix: str) -> tuple[int, str] | None:
        """Inspect *raw_prefix* and return a confidence score if the
        codec's :meth:`parse` is likely to succeed on the full input.

        This is the auto-detection hook (R5).  Each codec overrides
        this to emit a confidence score in ``[0, 100]`` along with a
        short human-readable reason explaining the match.  Returning
        ``None`` means "I have no opinion" — the codec does not
        participate in detection ranking.

        Args:
            raw_prefix: First ~500 bytes of the input config.  The
                detection service truncates for speed; codecs should
                NOT assume the full input.

        Returns:
            ``(confidence, reason)`` where confidence is 0-100, or
            ``None`` if the prefix does not match this codec's
            expected format.

        Scoring convention:
            * 95-100 — unique unambiguous marker (e.g. ``<opnsense>``
              root, ``/system identity`` MikroTik section header)
            * 75-94  — format-specific features (e.g. NETCONF XML
              namespace, FortiGate ``#config-version=`` banner)
            * 40-74  — structural shape only (e.g. leading ``<``,
              ``{``, ``!``) when no stronger signal is available
            * 0-39   — reserved for negative-signal fallbacks

        The default implementation returns ``None`` — it is safe for
        codecs that haven't been wired into auto-detection yet.
        """
        return None
