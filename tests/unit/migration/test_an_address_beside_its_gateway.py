"""An interface's address is written whether or not a virtual gateway is
beside it.

Junos ``address X/M virtual-gateway-address Y``, AOS-CX ``active-gateway
ip Y`` and an NX-OS anycast SVI hold ONE address record with the
interface's own address (``ip``) and the gateway beside it
(``virtual_gateway_address``).  FortiOS has no form for the gateway, and
its renderer, asked to leave out a row of EOS VARP (which has a gateway
and no address of its own), left out every row that had a gateway: each
such interface came out with no address at all, in a job that was
``partial`` for the gateway and said nothing of the address.

Every committed capture whose parse holds such a row is sent onto every
public codec, and the address is looked for in the output read back with
the target's parser and in its text.  The targets that write no
interface for a VLAN interface say so ("no native representation for
svi") and are pinned here with the count, their jobs ``partial``.  The
check is handed an output with the address taken out and has to fail.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
PUBLIC = list_public_codecs()

#: The targets that write no interface for a VLAN interface, and how many
#: of the rows below each leaves out so (every row is on one).
_WRITES_NO_SVI = {"cisco_iosxr": 54, "vyos": 54}

_NOT_A_CAPTURE = {".md", ".json", ".yaml", ".yml", ".py"}


def _captures() -> list[tuple[str, str, Path]]:
    """(codec, path under tests/fixtures, path) for every committed
    capture of a public codec."""
    found: list[tuple[str, str, Path]] = []
    for root in ("real", "synthetic", "iosxe", "opnsense"):
        for path in sorted(p for p in (FIXTURES / root).rglob("*") if p.is_file()):
            if path.suffix.lower() in _NOT_A_CAPTURE:
                continue
            parts = path.relative_to(FIXTURES).parts
            label = parts[1] if root in ("real", "synthetic") else {"iosxe": "cisco_iosxe"}.get(root, root)
            codec = DIR_TO_CODEC_NAME.get(label, label)
            if label == "cisco_iosxe" and path.suffix.lower() == ".xml":
                codec = "cisco_iosxe"
            if codec in PUBLIC:
                found.append((codec, "/".join(parts), path))
    return found


def _rows(codec: str, raw: str) -> list[tuple[str, str, str]]:
    """(where, address, gateway) for each IPv4 record of the parse that
    has an address of its own and a virtual gateway beside it."""
    tree = get_codec(codec).parse(raw)
    rows = [
        (i.name, a.ip, a.virtual_gateway_address)
        for i in tree.interfaces for a in i.ipv4_addresses
        if a.ip and a.virtual_gateway_address
    ]
    rows += [
        (f"vlan {v.id}", a.ip, a.virtual_gateway_address)
        for v in tree.vlans for a in v.ipv4_addresses
        if a.ip and a.virtual_gateway_address
    ]
    return rows


def _with_rows() -> list[tuple[str, str, str, list[tuple[str, str, str]]]]:
    out = []
    for codec, label, path in _captures():
        raw = path.read_text(encoding="utf-8")
        try:
            rows = _rows(codec, raw)
        except Exception:  # a capture its parser refuses has no rows
            continue
        if rows:
            out.append((codec, label, raw, rows))
    return out


WITH_ROWS = _with_rows()


def lost_addresses(target: str, rows: list[tuple[str, str, str]], text: str) -> list[str]:
    """The rows whose address is on no interface or VLAN of *text* read
    back with *target*'s parser, or is not in the text at all."""
    out = get_codec(target).parse(text)
    held = {a.ip for i in out.interfaces for a in i.ipv4_addresses}
    held |= {a.ip for v in out.vlans for a in v.ipv4_addresses}
    return [
        f"{where} {ip} (gateway {vga})"
        for where, ip, vga in rows
        if ip not in held or ip not in text
    ]


def test_the_captures_hold_such_rows() -> None:
    """The check reads something: Junos, AOS-CX and NX-OS captures hold
    an address beside a gateway."""
    assert sum(len(rows) for *_, rows in WITH_ROWS) >= 54
    assert {codec for codec, *_ in WITH_ROWS} >= {"juniper_junos", "aruba_aoscx", "cisco_nxos"}


@pytest.mark.parametrize("target", PUBLIC)
def test_the_address_is_written(target: str) -> None:
    lost: list[str] = []
    for codec, label, raw, rows in WITH_ROWS:
        job = run_plan_with_checked_names(
            get_codec(codec), get_codec(target), raw, port_rename_map={},
        )
        missing = lost_addresses(target, rows, job.rendered or "")
        if missing and target in _WRITES_NO_SVI:
            assert job.status == MigrationJobStatus.partial, label
        lost += [f"{label}: {m}" for m in missing]
    assert len(lost) == _WRITES_NO_SVI.get(target, 0), lost[:10]


def test_the_pins_name_public_codecs() -> None:
    assert set(_WRITES_NO_SVI) <= set(PUBLIC)


def test_the_check_sees_an_address_left_out() -> None:
    """A FortiOS output with each such address taken out: the check
    lists every row."""
    codec, label, raw, rows = next(w for w in WITH_ROWS if w[0] == "aruba_aoscx")
    job = run_plan_with_checked_names(
        get_codec(codec), get_codec("fortigate_cli"), raw, port_rename_map={},
    )
    text = job.rendered or ""
    assert lost_addresses("fortigate_cli", rows, text) == []
    gone = "\n".join(
        line for line in text.splitlines()
        if not any(line.strip().startswith(f"set ip {ip} ") for _, ip, _ in rows)
    )
    assert len(lost_addresses("fortigate_cli", rows, gone)) == len(rows)
