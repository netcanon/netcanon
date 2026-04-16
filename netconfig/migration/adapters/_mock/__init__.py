"""
Reference "mock" adapter — exercises the AdapterBase contract.

Side-effect import: defining ``MockAdapter`` (decorated with
``@register``) populates the adapter registry under the name
``"mock"``.  Tests that need it just do::

    import netconfig.migration  # triggers registration

No vendor semantics here — the mock stores a flat ``dict[str, str]``
(xpath -> value) and round-trips it via JSON.  Its purpose is
exercising the full parse → validate → render loop end-to-end without
requiring libyang or any real device.
"""

from .adapter import MockAdapter

__all__ = ["MockAdapter"]
