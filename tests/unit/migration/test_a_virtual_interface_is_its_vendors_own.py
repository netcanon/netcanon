"""A virtual interface is its own vendor's, and no other vendor has a form for it.

``virtual`` is the kind a classifier gives an interface that only its
own vendor has: an IOS-XE ``VirtualPortGroup`` (an app-hosting
interface) and a RouterOS bridge.  Three formatters wrote one of
another vendor as a loopback, "the closest analogue" (AOS-CX, NX-OS,
OS10), and IOS-XE wrote a RouterOS bridge as a ``VirtualPortGroup``.
The bridge of a RouterOS router's own default configuration holds the
LAN's gateway (``192.168.88.1/24``): onto those four it came out on
an interface with no port, the LAN's hosts reaching nothing, in jobs
that said ``completed``.

Each such identity says whose it is (``meta``), and only that
vendor's formatter gives it a name.  Onto every other platform it is
dropped and listed in ``unresolved_ports``, as a name the target has
no form for is.

Nothing here asks the code it guards what is right: the names, whose
each is and what its own platform writes for it are typed here, and
the output of a job is read as text.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.canonical.port_names import PortIdentity, collect_port_names
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

_TARGETS = sorted(list_public_codecs())

#: The codecs of one platform: a virtual interface of one of them is
#: the other's own.
_PLATFORM = {
    "mikrotik_routeros": {"mikrotik_routeros"},
    "cisco_iosxe_cli": {"cisco_iosxe_cli", "cisco_iosxe"},
    "cisco_iosxe": {"cisco_iosxe_cli", "cisco_iosxe"},
}

#: Names each source codec's classifier reads as a virtual interface of
#: its own, written back as they stand by its platform.
_NAMES = {
    "mikrotik_routeros": ("bridge", "br-lan"),
    "cisco_iosxe_cli": ("VirtualPortGroup0", "VirtualPortGroup7"),
    "cisco_iosxe": ("VirtualPortGroup0", "VirtualPortGroup7"),
}

#: A RouterOS router's own default configuration, cut to the bridge
#: that holds the LAN's gateway and the port that faces the WAN.
_ROUTEROS_LAN = "\n".join([
    "/interface bridge",
    "add name=bridge",
    "/interface bridge port",
    "add bridge=bridge interface=ether2",
    "add bridge=bridge interface=ether3",
    "/ip address",
    "add address=192.168.88.1/24 interface=bridge network=192.168.88.0",
    "add address=10.0.0.2/30 interface=ether1 network=10.0.0.0",
    "",
])

#: An IOS-XE app-hosting interface with an address.
_IOS_VPG = "\n".join([
    "hostname r1",
    "!",
    "interface GigabitEthernet0/0/1",
    " ip address 10.0.0.2 255.255.255.252",
    "!",
    "interface VirtualPortGroup0",
    " ip address 192.168.1.1 255.255.255.0",
    "!",
    "end",
    "",
])

#: (source codec, config, the virtual name, its address).
_SOURCES = (
    pytest.param("mikrotik_routeros", _ROUTEROS_LAN, "bridge", "192.168.88.1", id="bridge"),
    pytest.param("cisco_iosxe_cli", _IOS_VPG, "VirtualPortGroup0", "192.168.1.1", id="vpg"),
)


def _captures() -> dict[str, list[Path]]:
    """Every committed capture, by its source codec."""
    real = Path(__file__).resolve().parents[2] / "fixtures" / "real"
    found: dict[str, list[Path]] = {}
    for directory in sorted(real.iterdir()):
        codec = DIR_TO_CODEC_NAME.get(directory.name)
        if codec is None or not directory.is_dir():
            continue
        found.setdefault(codec, []).extend(
            path for path in sorted(directory.iterdir())
            if path.is_file()
            and path.suffix.lower() in {".txt", ".cfg", ".xml", ".conf", ".rsc", ".set"}
        )
    return found


def _problems(source: str, target: str, raw: str, name: str, address: str) -> list[str]:
    """What is wrong with the job of *raw* from *source* onto *target*,
    through the path every plan endpoint takes (an empty port map)."""
    job = run_plan_with_checked_names(
        get_codec(source), get_codec(target), raw, port_rename_map={},
    )
    text = job.rendered or ""
    lines_with_it = [line for line in text.splitlines() if address in line]
    if target in _PLATFORM[source]:
        found = [] if name in text and lines_with_it else [
            f"{name} or {address} is not in the output of its own platform",
        ]
        return found
    found = []
    if lines_with_it:
        found.append(f"{address} is written onto {target}: {lines_with_it[0].strip()!r}")
    if job.status == MigrationJobStatus.completed:
        found.append("the job says completed")
    if name not in job.unresolved_ports:
        found.append(f"{name} is not in unresolved_ports ({job.unresolved_ports})")
    return found


class TestTheTable:
    def test_every_virtual_name_of_the_captures_is_here(self) -> None:
        """Completeness by experiment: every name of every committed
        capture that its codec's classifier reads as a virtual
        interface is a name of a codec typed above."""
        read: dict[str, set[str]] = {}
        for codec_name, paths in _captures().items():
            if codec_name not in list_public_codecs():
                continue
            codec = get_codec(codec_name)
            for path in paths:
                raw = path.read_text(encoding="utf-8", errors="replace")
                try:
                    tree = codec.parse(raw)
                except Exception:  # a refused capture names nothing
                    continue
                for name in collect_port_names(tree):
                    ident = codec.classify_port_name(name)
                    if ident is not None and ident.kind == "virtual":
                        read.setdefault(codec_name, set()).add(name)
        assert read, "no capture has a virtual interface: the experiment reads nothing"
        assert set(read) <= set(_NAMES), read

    @pytest.mark.parametrize("codec_name", _TARGETS)
    def test_no_other_codec_reads_these_as_virtual(self, codec_name: str) -> None:
        """A codec that reads one of these names as a virtual interface
        of its own has to be in the table."""
        names = {name for each in _NAMES.values() for name in each} | {"bridge1", "br0"}
        codec = get_codec(codec_name)
        own = {
            name for name in names
            if (ident := codec.classify_port_name(name)) is not None
            and ident.kind == "virtual"
        }
        assert not own or codec_name in _NAMES, own


@pytest.mark.parametrize("target", _TARGETS)
@pytest.mark.parametrize(
    ("source", "name"),
    [(source, name) for source, names in _NAMES.items() for name in names],
)
def test_only_its_own_platform_has_a_form_for_it(source: str, name: str, target: str) -> None:
    ident = get_codec(source).classify_port_name(name)
    assert ident is not None and ident.kind == "virtual"
    written = get_codec(target).format_port_identity(ident)
    if target in _PLATFORM[source]:
        assert written == name
    else:
        assert written is None, f"{source} {name!r} written {written!r} onto {target}"


@pytest.mark.parametrize("target", _TARGETS)
def test_a_virtual_interface_that_says_nobodys_has_no_form(target: str) -> None:
    assert get_codec(target).format_port_identity(PortIdentity(kind="virtual", index=0)) is None


@pytest.mark.parametrize("target", _TARGETS)
@pytest.mark.parametrize(("source", "raw", "name", "address"), _SOURCES)
def test_its_address_is_not_written_on_another_interface(
    source: str, raw: str, name: str, address: str, target: str,
) -> None:
    """Onto another platform the interface and its address are left
    out, and the job lists the name; onto its own it stands."""
    if target == source:
        pytest.skip("a config to its own codec is no translation")
    assert _problems(source, target, raw, name, address) == []


@pytest.mark.parametrize("target", ["aruba_aoscx", "cisco_nxos", "dell_os10", "cisco_iosxe_cli"])
def test_the_check_sees_the_defect(target: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Handed the formatters as they were, the check fails."""
    codec_class = type(get_codec(target))
    real = codec_class.format_port_identity
    old = {
        "aruba_aoscx": "loopback 0",
        "cisco_nxos": "loopback0",
        "dell_os10": "loopback0",
        "cisco_iosxe_cli": "VirtualPortGroup0",
    }[target]

    def as_it_was(self, identity):
        if identity.kind == "virtual":
            return old
        return real(self, identity)

    monkeypatch.setattr(codec_class, "format_port_identity", as_it_was)
    found = _problems("mikrotik_routeros", target, _ROUTEROS_LAN, "bridge", "192.168.88.1")
    assert any("192.168.88.1 is written onto" in each for each in found), found
    assert "the job says completed" in found
