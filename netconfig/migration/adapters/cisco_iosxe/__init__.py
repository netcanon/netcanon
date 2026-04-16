"""
Cisco IOS-XE adapter — Phase 0.5 first real adapter.

Operates against captured OpenConfig NETCONF ``<get-config>`` responses
(and produces ``<edit-config>``-ready output).  Live ncclient transport
is Phase 1's responsibility — the same split as the backup collectors
vs. collectors-consumers in the existing app.

Scope (Phase 0.5):
    * openconfig-interfaces: name, description, enabled, type.
    * openconfig-if-ip: IPv4 address + prefix-length on subinterfaces.

Everything else is either declared lossy (acknowledged gap) or
unsupported (explicit refusal) in the capability matrix.  Phase 1
expands coverage to BGP, ACLs, and VLANs.
"""

from .adapter import CiscoIOSXEAdapter

__all__ = ["CiscoIOSXEAdapter"]
