"""Netcanon demo — run a cross-vendor translation in one command, no setup.

Shipped inside the ``netcanon`` package (wheel + Docker image), so it
works from a bare install with no source checkout::

    pip install netcanon
    netcanon demo                         # default: Cisco IOS-XE -> Junos
    netcanon demo --pair fortigate__mikrotik
    netcanon demo --list                  # show every available scenario

In the Docker image the entrypoint is the FastAPI server, so override
it to reach the CLI::

    docker run --rm --entrypoint netcanon \\
        ghcr.io/netcanon/netcanon:latest demo --pair cisco__junos

From a source checkout the repo-root shim also works::

    python tools/demo.py --pair cisco__junos

Each scenario uses a small embedded synthetic config (~10-25 lines) so the
demo is fully self-contained: no devices, no fixtures on disk, no FastAPI
server.

Internally this runs the rename-aware migration pipeline
(``run_plan_with_rename``) — the same path the HTTP API's
``POST /api/v1/migration/plan`` takes when a target profile is selected.
So the cross-vendor interface-name translation you see here
(``GigabitEthernet1/0/1`` -> ``ge-1/0/1``) is exactly what the API and
browser UI produce, through the same codec registry.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from ..migration.codecs.registry import get_codec
from ..services.migration_pipeline import run_plan_with_rename

# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    name: str
    source_codec: str
    target_codec: str
    description: str
    source_text: str


_CISCO_IOSXE = """\
hostname access-sw-01
!
vlan 10
 name DATA
!
vlan 20
 name VOICE
!
interface GigabitEthernet1/0/1
 description Server-A
 switchport mode access
 switchport access vlan 10
 no shutdown
!
interface GigabitEthernet1/0/2
 description Desk-Phone
 switchport mode access
 switchport access vlan 20
 no shutdown
!
interface GigabitEthernet1/0/24
 description Uplink-to-core
 switchport mode trunk
 switchport trunk allowed vlan 10,20
!
snmp-server community public RO
ip name-server 192.168.1.10
ip name-server 192.168.1.11
ntp server 192.168.1.20
!
ip route 0.0.0.0 0.0.0.0 192.168.1.1
"""


_FORTIGATE = """\
config system global
    set hostname "branch-fw-01"
end
config system dns
    set primary 192.168.1.10
    set secondary 192.168.1.11
end
config system interface
    edit "internal1"
        set ip 192.168.10.1 255.255.255.0
        set allowaccess ping
    next
    edit "internal2"
        set ip 192.168.20.1 255.255.255.0
        set allowaccess ping
    next
end
config system dhcp server
    edit 1
        set interface "internal1"
        set default-gateway 192.168.10.1
        set netmask 255.255.255.0
        config ip-range
            edit 1
                set start-ip 192.168.10.100
                set end-ip 192.168.10.200
            next
        end
    next
end
"""


_ARUBA_AOSS = """\
hostname "access-sw-01"
!
vlan 1
   name "DEFAULT_VLAN"
   no untagged 1-24
   no ip address
   exit
vlan 10
   name "USERS"
   untagged 1-20
   ip address 192.168.10.1 255.255.255.0
   exit
vlan 20
   name "MGMT"
   tagged 21-24
   ip address 192.168.20.1 255.255.255.0
   exit
ip default-gateway 192.168.1.1
ip dns server-address priority 1 192.168.1.10
snmp-server community "monitoring" operator
"""


_OPNSENSE = """\
<?xml version="1.0"?>
<opnsense>
    <system>
        <hostname>edge-fw-01</hostname>
        <domain>example.test</domain>
        <dnsserver>192.168.1.10</dnsserver>
        <dnsserver>192.168.1.11</dnsserver>
    </system>
    <interfaces>
        <wan>
            <if>igc0</if>
            <enable>1</enable>
            <descr>WAN</descr>
            <ipaddr>dhcp</ipaddr>
        </wan>
        <lan>
            <if>igc1</if>
            <enable>1</enable>
            <descr>LAN</descr>
            <ipaddr>192.168.10.1</ipaddr>
            <subnet>24</subnet>
        </lan>
    </interfaces>
</opnsense>
"""


SCENARIOS: dict[str, Scenario] = {
    "cisco__junos": Scenario(
        name="Cisco IOS-XE -> Juniper Junos",
        source_codec="cisco_iosxe_cli",
        target_codec="juniper_junos",
        description=(
            "Translate a Catalyst access switch into Junos set-form: "
            "hostname, VLAN definitions, switchport access + trunk ports "
            "with their VLAN membership, an SNMP community, DNS / NTP "
            "servers, and a default static route - including cross-vendor "
            "interface-name translation (GigabitEthernet1/0/1 -> ge-1/0/1)."
        ),
        source_text=_CISCO_IOSXE,
    ),
    "fortigate__mikrotik": Scenario(
        name="Fortinet FortiGate -> MikroTik RouterOS",
        source_codec="fortigate_cli",
        target_codec="mikrotik_routeros",
        description=(
            "Translate FortiGate's nested config / edit / set / next / end "
            "model (system global, system dns, system interface, system "
            "dhcp server) into RouterOS's `/path` slash-prefixed form."
        ),
        source_text=_FORTIGATE,
    ),
    "aruba__arista": Scenario(
        name="Aruba AOS-S -> Arista EOS",
        source_codec="aruba_aoss",
        target_codec="arista_eos",
        description=(
            "Switch refresh: translate AOS-S's banner-style positional "
            "port-list grammar (untagged 1-20, tagged 21-24) into Arista "
            "EOS's per-interface switchport configuration."
        ),
        source_text=_ARUBA_AOSS,
    ),
    "opnsense__junos": Scenario(
        name="OPNsense -> Juniper Junos",
        source_codec="opnsense",
        target_codec="juniper_junos",
        description=(
            "Translate OPNsense's XML config (system / interfaces / DNS) "
            "into Junos set-form.  Demonstrates the Tier-3 boundary: "
            "OPNsense's firewall, NAT, and IPsec stanzas are deliberately "
            "deferred (see docs/CAPABILITIES.md)."
        ),
        source_text=_OPNSENSE,
    ),
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


_HEADER = "=" * 72


def _print_section(title: str, body: str = "") -> None:
    print(_HEADER)
    print(title)
    print(_HEADER)
    if body:
        print(body)


def _list_scenarios() -> None:
    print(_HEADER)
    print("Available demo scenarios")
    print(_HEADER)
    for key, scenario in SCENARIOS.items():
        print(f"  --pair {key}")
        print(f"      {scenario.name}")
        # Wrap description lightly (don't pull in textwrap for one line)
        for line in scenario.description.split(". "):
            line = line.strip().rstrip(".")
            if line:
                print(f"      {line}.")
        print()


def _run_scenario(scenario: Scenario) -> int:
    _print_section(f"SCENARIO: {scenario.name}")
    print(scenario.description)
    print()

    _print_section(
        f"INPUT ({scenario.source_codec})",
        scenario.source_text.rstrip(),
    )
    print()

    source = get_codec(scenario.source_codec)
    target = get_codec(scenario.target_codec)
    job = run_plan_with_rename(source, target, scenario.source_text, port_rename_map={})

    if str(job.status).endswith("failed"):
        _print_section("FAILED")
        print(f"Error: {job.error}")
        return 1

    _print_section(
        f"OUTPUT ({scenario.target_codec})",
        (job.rendered or "").rstrip(),
    )
    print()

    # Show the cross-vendor interface-name translation explicitly — it
    # is the load-bearing step that turns source-vendor port names into
    # valid target-vendor syntax (GigabitEthernet1/0/1 -> ge-1/0/1).
    renames = dict(job.port_renames or {})
    if renames:
        _print_section("Interface-name translations applied")
        for src_name, tgt_name in renames.items():
            print(f"  {src_name} -> {tgt_name}")
        print()

    # Advisories: port names the target codec has no clean equivalent
    # for (left verbatim), plus any other per-pane warnings — honest
    # about what the auto-heuristic could not resolve.
    if job.warnings:
        _print_section("Advisories")
        for entry in job.warnings:
            print(f"  - {entry}")
        print()

    # Honest reporting of what didn't translate
    dropped = list(job.dropped_tier3_sections or [])
    if dropped:
        _print_section("Tier-3 sections detected but NOT translated")
        for entry in dropped:
            print(f"  - {entry}")
        print()
    else:
        _print_section("Tier-3 sections detected")
        print("  (none -- input was Tier-1/2 only)")
        print()

    _print_section("Done")
    print(
        f"Translated {scenario.source_codec} -> {scenario.target_codec} via "
        f"the canonical-intermediate model."
    )
    print(
        "Same pipeline used by the HTTP API at /api/v1/migration; same codec "
        "registry; same matrix-honesty discipline.  See "
        "docs/walkthroughs/ for narrative walkthroughs of real-world "
        "migration scenarios."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="netcanon demo",
        description=(
            "Run a cross-vendor translation demo in one command.  "
            "No setup, no devices, no FastAPI server."
        ),
    )
    parser.add_argument(
        "--pair",
        default="cisco__junos",
        choices=list(SCENARIOS.keys()),
        help="Source__target codec pair (default: cisco__junos)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available demo scenarios and exit",
    )
    args = parser.parse_args(argv)

    if args.list:
        _list_scenarios()
        return 0

    return _run_scenario(SCENARIOS[args.pair])


if __name__ == "__main__":
    sys.exit(main())
