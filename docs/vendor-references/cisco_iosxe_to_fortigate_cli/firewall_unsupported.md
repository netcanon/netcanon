# FortiGate firewall / NAT / UTM — no canonical analogue (forward direction)

Source: [Fortinet FortiGate Cookbook — Firewall policies](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/)
Retrieved: 2026-05-01

Source: [Cisco IOS-XE Programmability Configuration Guide](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/prog/configuration/1715/b_1715_programmability_cg/m_1715_prog_yang_netconf.html)
Retrieved: 2026-05-01

## Forward-direction framing

This direction is `cisco_iosxe` (NETCONF/OpenConfig) -> `fortigate_cli`
(FortiOS).  FortiGate's primary product surface is firewall policy +
NAT + VIP + UTM.  None of these have a canonical representation in
the v1 NetConfig model:

* No `CanonicalFirewallPolicy` / `CanonicalSecurityPolicy` record.
* No `CanonicalNATRule` record.
* No `CanonicalAddressObject` / `CanonicalServiceObject` record.

This means the canonical surface carries no firewall intent that
the FortiGate render could emit.  But on this **forward** direction
(NETCONF source), the question is moot for a different reason:
the cisco_iosxe parser does not read OpenConfig `<acl>` /
`<acl-set>` / NAT subtrees (and Cisco IOS-XE's ZBF / NAT do not
have universally-deployed OpenConfig representations anyway —
OpenConfig's `acl` model is shipped but Cisco's coverage is partial).

So the forward direction has no firewall intent to migrate
regardless of canonical schema gaps.

## What this means in practice

Operators standing up a FortiGate from a Cisco IOS-XE NETCONF
snapshot get:

* The interface canonical-core (name / description / enabled /
  IPv4 / IPv6) — the only fields the cisco_iosxe parser populates.

They do NOT get:

* Cisco ACLs, ZBF zone-pairs, NAT rules — not in the parsed surface.
* FortiGate-side firewall policy / VIP / UTM — must be configured
  from scratch on the FortiGate target, regardless of what the
  Cisco source had.

The pair is inappropriate for full edge-router migration; it is
appropriate ONLY for the narrow case where the upstream
orchestrator has already built the security policy externally and
is using cisco_iosxe -> fortigate_cli for the interface-only
bring-up sub-step.

## Disposition

The canonical schema does not enumerate firewall / NAT fields, so
there is nothing to mark in the per-field expectation YAML.  The
absence is itself the documentation.  This file exists for the
operator orientation: if you came here looking for "where does the
firewall / NAT / VIP migration get tracked", the answer is "the
canonical schema doesn't model it; this is intentional v1 scope".

Reverse direction: see `../fortigate_cli_to_cisco_iosxe/firewall_unsupported.md`
for the FortiGate-source-to-Cisco-target framing where FortiGate
firewall policy IS the source's primary content but has no
canonical landing pad.
