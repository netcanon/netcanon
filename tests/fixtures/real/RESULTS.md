# Real-capture validation results

Human-readable snapshot of `tests/unit/migration/test_real_captures.py`
as of the latest known-good run.  Provenance for every fixture is in
`NOTICE.md` alongside this file.

---

## cisco_iosxe_cli

**Codec:** `netconfig.migration.codecs.cisco_iosxe_cli.CiscoIOSXECLICodec`
**Direction:** `parse_only`
**Certainty (current):** `experimental`
**Certainty (proposed):** `best_effort`  *(see Certification Decision below)*

### Coverage matrix

| Fixture | Lines | hostname | interfaces | vlans | static_routes | lags | Notes |
|---|---:|---:|---:|---:|---:|---:|---|
| `batfish_cisco_interface.txt` | 337 | 1 | 24 | 9 | 0 | 1 | Grammar kitchen-sink — every interface sub-command Batfish supports. |
| `batfish_cisco_ip_route.txt` | 26 | 1 | 0 | 0 | 10 | 0 | Static-route variants (interface next-hops, IP next-hops). |
| `ntc_carrier_interfaces.txt` | 82 | 0 | 6 | 0 | 0 | 0 | Carrier IOS: VRFs, dot1Q Q-in-Q subinterfaces, QoS, ACL groups, uRPF. |

### Findings from first-pass dogfood

**Bug surfaced (FIXED):** `cisco_interface.txt` stacks seven
`channel-group 1 mode <variant>` lines on a single physical interface
(grammar-test of every LACP mode keyword).  `_parse_lags` naively
appended `Ethernet0` seven times to the member list.  Fix: dedupe
members inside the parse loop.  Regression test added as
`TestCiscoLAGParse.test_duplicate_channel_group_lines_dedupe_members`.

**Known silent drops (by design, not bugs):**

Real carrier IOS surfaces a long tail of features we deliberately
don't model in Tier 1 / 2 canonical.  None of these caused a parse
failure — they were just silently unused by our extractors:

| Feature | Example | Canonical tier |
|---|---|---|
| VRF definitions + memberships | `vrf forwarding CLIENT_VOIP:1234` | Fidelity polish (see roadmap) |
| Q-in-Q encapsulation | `encapsulation dot1Q 2234 second-dot1q 15` | Fidelity polish |
| QoS service-policies | `service-policy input VIPSIP_POLICY_2048_V1` | Tier 3 (informational) |
| ACL groups on interfaces | `ip access-group iACL in` | Tier 3 |
| IPv6 addressing | `ipv6 address FE80::/126` | Not yet canonical |
| Proxy-ARP flags | `no ip proxy-arp` | Fidelity polish |
| uRPF | `ip verify unicast source reachable-via rx` | Tier 3 |
| Bandwidth hint | `bandwidth 2048` | Fidelity polish |
| MTU override | `mtu 9096` | Fidelity polish (already queued) |

These match the "Fidelity Polish" bucket already on the roadmap.  No
new tracking needed.

**Observed fidelity wins:**

* Sub-interfaces with dot-notation names (`GigabitEthernet2/0/4.223415`)
  parse cleanly and keep their IP + description.
* VLAN 4094 / 1005 / 1006 (reserved/limbo ranges) parse without
  complaint — we don't validate the ID space, which is correct
  (we're not the source of authority on valid VLANs).
* `ip route X Y <ip-or-interface>` correctly distinguishes IP vs.
  interface next-hops — all 10 routes in the Batfish fixture resolved
  to the right shape.

### Certification decision

**Proposed: promote from `experimental` → `best_effort`.**

Rationale:
* Parser didn't crash on any of the three public fixtures, including
  the grammar kitchen-sink and the carrier-grade interface config.
* Bug surfaced (LAG dedup) was structural — a fix plus regression test
  landed in the same pass.
* Coverage is deliberately partial; the unsupported features are all
  listed above and already mapped to roadmap buckets.
* `certified` would require at least one full-device capture
  round-tripped through two real codecs, plus coverage metrics across
  more vendors.  Staying one tier below that is honest.

---

## Other vendors

Queued for follow-up sessions:

| Vendor | Codec | Fixture status |
|---|---|---|
| aruba_aoss | `ArubaAOSSCodec` | none yet |
| fortigate | `FortiGateCLICodec` | none yet |
| opnsense | `OPNsenseCodec` | none yet |
| mikrotik | `MikroTikRouterOSCodec` | none yet |

Each one follows the same shape as the Cisco pass: 2–4 public fixtures,
parametrized test picks them up automatically, diagnostic print,
decide on certainty.  Per-vendor fetch friction varies — Aruba AOS-S
and FortiGate captures are scarcer in public repos than Cisco IOS.

---

## How to add a new fixture

1. Find a permissively-licensed real-world config (Apache / MIT / BSD /
   CC0 sources only — see `NOTICE.md` for examples).
2. Drop into `tests/fixtures/real/<vendor>/<descriptive-name>.txt`.
3. Add a row to `NOTICE.md` with origin URL, license, and what the
   file stresses.
4. Run `pytest tests/unit/migration/test_real_captures.py -v -s` —
   the new fixture is picked up automatically.
5. Review the printed coverage; if new silent drops are visible and
   they *should* be caught, file a bug in `translator-plans.txt`.
6. Update the coverage matrix in this file with the new row.
