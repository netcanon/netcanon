"""
Reference "mock" adapter — exercises the CodecBase contract.

Side-effect import: defining ``MockCodec`` (decorated with
``@register``) populates the adapter registry under the name
``"mock"``.  Tests that need it just do::

    import netcanon.migration  # triggers registration

No vendor semantics here — the mock stores a flat ``dict[str, str]``
(xpath -> value) and round-trips it via JSON.  Its purpose is
exercising the full parse → validate → render loop end-to-end without
requiring libyang or any real device.
"""

from .codec import MockCodec

__all__ = ["MockCodec"]
