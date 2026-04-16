"""
``MockAdapter`` — reference adapter proving the AdapterBase contract.

Internal tree representation: ``dict[str, str]`` — a flat xpath-to-value
map.  Serialisation format: a single JSON object.  Neither choice is
vendor-meaningful; both are picked for test-only simplicity.

Capability matrix: declares ``/interfaces/**`` + ``/vlans/**`` as
supported, a single ``/legacy/deprecated`` as lossy, and any path under
``/unsafe/**`` as unsupported.  The pipeline's validate stage test
suite uses these to exercise every classification branch.

Round-trip invariant (enforced by ``tests/unit/migration/test_mock_
adapter.py``)::

    for tree in example_trees:
        adapter = MockAdapter()
        assert adapter.parse(adapter.render(tree)) == tree
"""

from __future__ import annotations

import json
from typing import ClassVar

from ....models.migration import (
    CapabilityMatrix,
    DeviceClass,
    LossyPath,
    UnsupportedPath,
)
from ..base import AdapterBase, ParseError
from ..registry import register


@register
class MockAdapter(AdapterBase):
    """In-memory reference adapter.  Not wired to any real device."""

    name: ClassVar[str] = "mock"
    version_hint: ClassVar[str | None] = "1.0"

    #: Class-level capability matrix — constant across instances.
    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="mock",
        version_range="1.x",
        # Multi-class so unit tests can exercise the "non-empty
        # intersection" path AND the "disjoint sets" path against
        # tiny adapter stubs that declare narrower classes.
        device_classes=[DeviceClass.switch, DeviceClass.router],
        supported=[
            "/interfaces/eth0/ip",
            "/interfaces/eth0/description",
            "/vlans/10/name",
            "/vlans/10/description",
        ],
        lossy=[
            LossyPath(
                path="/legacy/deprecated",
                reason="Mock adapter preserves but does not validate this path.",
                severity="warn",
            ),
        ],
        unsupported=[
            UnsupportedPath(
                path="/unsafe/kernel_module",
                reason="No sane adapter would let you set this via migration.",
            ),
        ],
    )

    @property
    def capabilities(self) -> CapabilityMatrix:
        return self._CAPS

    def parse(self, raw: str) -> dict[str, str]:
        """Parse a JSON-encoded flat xpath map.

        Raises:
            ParseError: If *raw* is not valid JSON or not an object of
                string->string mappings.
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ParseError(
                f"mock adapter expects a JSON object; parser said {exc.msg}",
                snippet=raw[:120],
            ) from exc
        if not isinstance(data, dict):
            raise ParseError(
                "mock adapter requires a JSON object at top level",
                snippet=raw[:120],
            )
        for k, v in data.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ParseError(
                    "mock adapter requires string keys and string values",
                    path=str(k),
                    snippet=str(v)[:120],
                )
        return data

    def render(self, tree: dict[str, str]) -> str:
        """Render *tree* back into pretty JSON.

        The sort key ensures deterministic output — required by the
        round-trip invariant and by the textual diff stage downstream.
        """
        return json.dumps(tree, indent=2, sort_keys=True) + "\n"
