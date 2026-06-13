"""
Canonical intent tree — the shared vendor-neutral model every codec
parses into and renders from.

The tree is a Pydantic model hierarchy rooted at
:class:`.intent.CanonicalIntent` (interfaces, VLANs, VRRP groups, SNMP,
users, static routes, …).  The originally-planned libyang-backed loader
was not adopted — ``loader.py`` remains an unused stub kept for a stable
import path — so validation is the model's own Pydantic constraints,
not external YANG-schema validation.
"""
