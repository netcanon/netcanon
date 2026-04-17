"""
Cisco IOS-XE CLI codec — parses ``show running-config`` text.

This is R4 of the long-term architecture: the first ``parse_only``
codec, and the first multi-codec-per-vendor instance (both
``cisco_iosxe`` and ``cisco_iosxe_cli`` share ``vendor_id=cisco_iosxe``).

Direction: ``parse_only`` — render() raises NotImplementedError.
Certainty: ``experimental`` — tested against synthetic samples;
    needs real-world captures to graduate to ``best_effort``.

The parsed tree matches the same shape as ``CiscoIOSXECodec`` so the
two codecs are interchangeable as SOURCE inputs.  This means a stored
``show running-config`` backup (captured by the existing Netmiko
collector) can be fed directly into the translator pipeline via the
``source_filename`` shorthand on ``POST /api/v1/migration/plan``.
"""

from .codec import CiscoIOSXECLICodec

__all__ = ["CiscoIOSXECLICodec"]
