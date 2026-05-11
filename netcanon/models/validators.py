"""
Shared validation helpers for device-related models.

Centralised here so that ``device.py`` and ``device_profile.py`` share
the same hostname/IP validation logic without duplication.
"""

import ipaddress
import re

# RFC-1123 hostname: labels of 1-63 alphanumeric/hyphen chars, not starting
# or ending with a hyphen, separated by dots.
HOSTNAME_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$"
)


def validate_host(v: str) -> str:
    """Accept a valid IPv4, IPv6, or RFC-1123 hostname; reject everything else."""
    v = v.strip()
    try:
        ipaddress.ip_address(v)
        return v
    except ValueError:
        pass
    if HOSTNAME_RE.match(v):
        return v
    raise ValueError(
        f"Invalid host {v!r}: must be a valid IPv4 address, IPv6 address, "
        f"or RFC-1123 hostname.  Example: '192.168.1.1', '2001:db8::1', "
        f"or 'core-sw-01.example.com'."
    )
