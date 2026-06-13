"""Guard: ``classify_port_name`` always populates ``PortIdentity.original``.

Project review 2026-06-06, finding R-17 / CC-03: ``PortIdentity.original``
is documented "Always populated by the source classifier" (used by the
cross-vendor port-name bridge to echo the source token back when a
target can't represent an identity), but arista_eos and juniper_junos
returned it empty on every path — a latent contract violation.  This
test pins the contract for the codecs that ship a classifier, including
cisco_iosxe_cli as a known-compliant control.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.arista_eos.port_names import (
    classify_port_name as arista_classify,
)
from netcanon.migration.codecs.cisco_iosxe_cli.port_names import (
    classify_port_name as cisco_classify,
)
from netcanon.migration.codecs.juniper_junos.port_names import (
    classify_port_name as junos_classify,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "classify, samples",
    [
        (
            arista_classify,
            ["Ethernet1", "Ethernet3/1", "Management1", "Port-Channel5",
             "Vlan10", "Loopback0", "this-is-not-a-port"],
        ),
        (
            junos_classify,
            ["ge-0/0/0", "xe-1/2/3", "em0", "lo0", "ae5", "irb",
             "vlan.100", "this-is-not-a-port"],
        ),
        (
            cisco_classify,  # known-compliant control
            ["GigabitEthernet0/0/1", "TenGigabitEthernet1/0/1",
             "Port-channel2", "Vlan20", "this-is-not-a-port"],
        ),
    ],
    ids=["arista_eos", "juniper_junos", "cisco_iosxe_cli"],
)
def test_classify_populates_original(classify, samples):
    for name in samples:
        identity = classify(name)
        assert identity.original == name, (
            f"{classify.__module__}.classify_port_name({name!r}) left "
            f"`original` = {identity.original!r}; the PortIdentity contract "
            "requires the source classifier to echo the verbatim input."
        )
