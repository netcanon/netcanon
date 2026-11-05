"""No row of ``dropped_tier3_sections`` holds a secret.

A row is painted on the migrate page and returned in every job's
answer, so it shows a statement's path and never a value.  A detector
that takes a header's whole line took what the line holds, and an IOS
``crypto isakmp key <key> address <peer>`` line holds the pre-shared
key: its row was the key, in plain text or type 6, from the IOS-XE CLI,
EOS, AOS-S and NX-OS parsers, in a job onto every target -- and so was
the PIN of ``crypto pki token <name> user-pin <pin>``.  Nothing else
said so: the output holds no such line, and a check that compares two
trees never reads a row.  A label is now cut after the first word that
names a secret (``_tier3_detection._shown_label``).

The guard does not ask the detectors which lines they take.  It writes,
into every committed capture of each codec, the lines of that codec's
grammar that hold a secret, each secret a marker of its own -- and, for
the four parsers whose detectors take the IOS family's ``crypto`` lines
whole, those lines too: a pasted text is whatever was pasted.  It looks
for every marker in every row the parse makes, a detector's or the
parser's own, and in the rows of a job onto every public codec.  It is
handed the defect: with the cut taken out, it finds the secrets it was
written for, and no others.

What it cannot see: a secret in a grammar's line that is not written
here, and a row made from a line no capture leads a parser to.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from netcanon.migration import _tier3_detection
from netcanon.migration._tier3_detection import detect_tier3_sections_iosxe_cli
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
PUBLIC = list_public_codecs()

_NOT_A_CAPTURE = {".md", ".json", ".yaml", ".yml", ".py"}

#: The IOS family's ``crypto`` lines that hold a secret on the header
#: line itself.  The IOS-XE CLI, EOS and AOS-S detectors take a
#: ``crypto isakmp|ipsec|map|pki`` line whole; the NX-OS one, every
#: ``crypto`` line.
IOS_CRYPTO = (
    "crypto isakmp key {m} address 0.0.0.0",
    "crypto isakmp key 0 {m} hostname peer.example.net",
    "crypto isakmp key 6 {m} address 192.0.2.1 no-xauth",
    "crypto pki token default user-pin {m}",
)

#: Each codec's lines that hold a secret, ``{m}`` where the secret is.
#: Typed by hand from each grammar; none is a detector's pattern.
PLANTS: dict[str, tuple[str, ...]] = {
    "cisco_iosxe_cli": (
        *IOS_CRYPTO,
        "crypto keyring KR1\n pre-shared-key address 192.0.2.2 key {m}",
        "crypto isakmp client configuration group G1\n key {m}",
        "crypto ikev2 keyring K2\n peer P1\n  pre-shared-key {m}",
        "snmp-server community {m} RO",
        "snmp-server user U1 G1 v3 auth sha {m} priv aes 128 {m}",
        "enable secret 0 {m}",
        "username planted privilege 15 secret 0 {m}",
        "tacacs-server key {m}",
        "radius-server key {m}",
        "key chain KC1\n key 1\n  key-string {m}",
        "ntp authentication-key 1 md5 {m}",
        "interface Loopback901\n ip ospf authentication-key {m}",
        "router bgp 65000\n neighbor 192.0.2.9 password {m}",
        "line vty 0 4\n password {m}",
    ),
    "arista_eos": (
        *IOS_CRYPTO,
        "username planted privilege 15 secret 0 {m}",
        "snmp-server community {m} ro",
        "radius-server host 192.0.2.5 key 0 {m}",
        "tacacs-server host 192.0.2.6 key 0 {m}",
        "interface Loopback901\n   ip ospf authentication-key 0 {m}",
        "router bgp 65000\n   neighbor 192.0.2.9 password 0 {m}",
    ),
    "aruba_aoss": (
        *IOS_CRYPTO,
        'password manager user-name "planted" plaintext "{m}"',
        'snmp-server community "{m}" unrestricted',
        'snmpv3 user "planted" auth sha "{m}" priv aes "{m}"',
        'radius-server host 192.0.2.5 key "{m}"',
        'tacacs-server host 192.0.2.6 key "{m}"',
        "tacacs-server key {m}",
    ),
    "cisco_nxos": (
        *IOS_CRYPTO,
        "username planted password 0 {m} role network-admin",
        "snmp-server community {m} group network-operator",
        "snmp-server user planted network-admin auth sha {m} priv aes-128 {m}",
        'tacacs-server key 0 "{m}"',
        'radius-server host 192.0.2.5 key 0 "{m}"',
        "key chain KC1\n  key 1\n    key-string 0 {m}",
        "ntp authentication-key 1 md5 {m} 0",
        "interface loopback901\n  ip ospf authentication-key 0 {m}",
        "router bgp 65000\n  neighbor 192.0.2.9\n    password 0 {m}",
    ),
    "cisco_iosxr": (
        "username planted\n group root-lr\n secret 0 {m}",
        "snmp-server community {m} RO",
        "snmp-server user planted G1 v3 auth sha clear {m} priv aes 128 clear {m}",
        "router bgp 65000\n neighbor 192.0.2.9\n  password clear {m}",
        "key chain KC1\n key 1\n  key-string clear {m}",
        "tacacs-server host 192.0.2.5 port 49\n key 7 {m}",
        "radius-server host 192.0.2.6 auth-port 1812 acct-port 1813\n key 7 {m}",
    ),
    "aruba_aoscx": (
        "user planted group administrators password plaintext {m}",
        "snmp-server community {m}",
        "snmpv3 user planted auth sha auth-pass plaintext {m} priv aes priv-pass plaintext {m}",
        "radius-server host 192.0.2.5 key plaintext {m}",
        "tacacs-server host 192.0.2.6 key plaintext {m}",
        "router bgp 65000\n    neighbor 192.0.2.9 password plaintext {m}",
    ),
    "dell_os10": (
        "username planted password {m} role sysadmin",
        "snmp-server community {m} ro",
        "snmp-server user planted G1 3 auth sha {m} priv aes {m}",
        "radius-server host 192.0.2.5 key {m}",
        "tacacs-server host 192.0.2.6 key {m}",
        "system-user linuxadmin password {m}",
        "router bgp 65000\n neighbor 192.0.2.9\n  password {m}",
    ),
    "fortigate_cli": (
        'config system admin\n    edit "planted"\n        set password {m}\n    next\nend',
        'config vpn ipsec phase1-interface\n    edit "v1"\n        set psksecret {m}\n    next\nend',
        'config system snmp community\n    edit 9\n        set name "{m}"\n    next\nend',
        'config user radius\n    edit "r1"\n        set secret {m}\n    next\nend',
        'config user tacacs+\n    edit "t1"\n        set key {m}\n    next\nend',
    ),
    "juniper_junos": (
        "set system login user planted authentication encrypted-password {m}",
        "set snmp community {m} authorization read-only",
        "set security ike policy P1 pre-shared-key ascii-text {m}",
        "set protocols bgp group G1 authentication-key {m}",
        "set protocols ospf area 0.0.0.0 interface lo0.0 authentication md5 1 key {m}",
        "set system radius-server 192.0.2.5 secret {m}",
        "set system tacplus-server 192.0.2.6 secret {m}",
        # Deactivated: a left-out row, which shows the path.
        "set system radius-server 192.0.2.7 secret {m}\ndeactivate system radius-server 192.0.2.7",
        "set snmp community {m} authorization read-write\ndeactivate snmp community {m}",
    ),
    "mikrotik_routeros": (
        "/user\nadd group=full name=planted password={m}",
        "/snmp community\nadd name={m}",
        "/ip ipsec identity\nadd peer=p1 secret={m}",
        "/radius\nadd address=192.0.2.5 secret={m}",
        "/interface wireless security-profiles\nadd name=p1 wpa2-pre-shared-key={m}",
        "/routing bgp connection\nadd name=b1 remote.address=192.0.2.9 tcp-md5-key={m}",
    ),
    "vyos": (
        "system {{\n    login {{\n        user planted {{\n            authentication {{\n"
        "                plaintext-password {m}\n            }}\n        }}\n    }}\n}}",
        "service {{\n    snmp {{\n        community {m} {{\n            authorization ro\n"
        "        }}\n    }}\n}}",
        "vpn {{\n    ipsec {{\n        site-to-site {{\n            peer 192.0.2.9 {{\n"
        "                authentication {{\n                    pre-shared-secret {m}\n"
        "                }}\n            }}\n        }}\n    }}\n}}",
        "protocols {{\n    bgp 65000 {{\n        neighbor 192.0.2.9 {{\n"
        "            password {m}\n        }}\n    }}\n}}",
    ),
    "opnsense": (
        "<ipsec><phase1><pre-shared-key>{m}</pre-shared-key></phase1></ipsec>",
        "<openvpn><openvpn-server><shared_key>{m}</shared_key></openvpn-server></openvpn>",
        "<snmpd><rocommunity>{m}</rocommunity></snmpd>",
    ),
}

#: A public codec with no lines above, and why.
NOT_PLANTED = {
    "cisco_iosxe": (
        "its detector reads no text (a NETCONF document's rows are none), "
        "which test_a_netconf_document_has_no_row holds it to"
    ),
}

#: A Junos config as the device prints it (braces), typed by hand: the
#: committed Junos captures are all in ``display set`` form.
JUNOS_AS_PRINTED = (
    "system {{\n    host-name planted;\n    radius-server {{\n"
    "        192.0.2.5 secret \"{radius}\";\n    }}\n}}\n"
    "snmp {{\n    inactive: community {community} {{\n        authorization read-only;\n    }}\n}}\n"
    "security {{\n    ike {{\n        policy P1 {{\n"
    "            pre-shared-key ascii-text \"{ike}\";\n        }}\n    }}\n}}\n"
    "interfaces {{\n    ge-0/0/0 {{\n        unit 0 {{\n            family inet {{\n"
    "                address 192.0.2.1/24;\n            }}\n        }}\n    }}\n}}\n"
)

#: The lines whose secret is in a row when the cut is taken out: the
#: IOS family's ``crypto`` lines, from the four parsers that take them
#: whole.  Compared for equality with what is found.
WITHOUT_THE_CUT = {
    codec: set(IOS_CRYPTO)
    for codec in ("cisco_iosxe_cli", "arista_eos", "aruba_aoss", "cisco_nxos")
}


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


def _markers(codec: str) -> dict[str, str]:
    """A marker of its own for each of the codec's lines: marker -> line."""
    return {f"zqMark{n:02d}{sorted(PLANTS).index(codec):02d}x": form for n, form in enumerate(PLANTS[codec])}


def _planted(codec: str, raw: str) -> str:
    """*raw* with the codec's lines in it, each holding its marker.

    At the end of the text, as a pasted text has them; before an
    IOS-family ``end``, which some parsers stop at; inside the
    OPNsense document's root."""
    block = "".join(form.format(m=marker) + "\n" for marker, form in _markers(codec).items())
    if codec == "opnsense":
        at = raw.rfind("</opnsense>")
        assert at >= 0
        return raw[:at] + block + raw[at:]
    lines = raw.rstrip("\n").split("\n")
    if lines[-1].strip() == "end" and codec in ("cisco_iosxe_cli", "cisco_iosxr", "arista_eos"):
        return "\n".join(lines[:-1]) + "\n" + block + "end\n"
    return raw.rstrip("\n") + "\n" + block


def _found(rows: list[str], markers: dict[str, str]) -> set[str]:
    """The lines whose marker is in a row."""
    text = "\n".join(rows)
    return {form for marker, form in markers.items() if marker in text}


def _planted_captures() -> Iterator[tuple[str, str, str]]:
    """(codec, label, planted text) for every committed capture of a
    codec with lines above."""
    for codec, label, path in _captures():
        if codec in PLANTS:
            yield codec, label, _planted(codec, path.read_text(encoding="utf-8"))


def _smallest_planted() -> dict[str, str]:
    """The planted text of each codec's smallest committed capture."""
    smallest: dict[str, tuple[int, str]] = {}
    for codec, _label, text in _planted_captures():
        if codec not in smallest or len(text) < smallest[codec][0]:
            smallest[codec] = (len(text), text)
    return {codec: text for codec, (_size, text) in smallest.items()}


def _hits(texts: Iterator[tuple[str, str, str]]) -> tuple[dict[str, set[str]], dict[str, int]]:
    """What each codec's parse puts in a row: codec -> lines; and how
    many texts of each codec were read."""
    hits: dict[str, set[str]] = {}
    read: dict[str, int] = {}
    for codec, _label, text in texts:
        rows = get_codec(codec).parse(text).dropped_tier3_sections
        read[codec] = read.get(codec, 0) + 1
        found = _found(rows, _markers(codec))
        if found:
            hits.setdefault(codec, set()).update(found)
    return hits, read


# ---------------------------------------------------------------------------
# The cut
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "shown"),
    [
        ("crypto isakmp key 6 S1 address 192.0.2.1", "crypto isakmp key ..."),
        ("crypto isakmp key S1 hostname peer.example.net", "crypto isakmp key ..."),
        ("crypto pki token default user-pin S1", "crypto pki token default user-pin ..."),
        ("CRYPTO ISAKMP KEY S1 address 0.0.0.0", "CRYPTO ISAKMP KEY ..."),
        ("crypto  isakmp key S1", "crypto isakmp key ..."),
        ("crypto isakmp profile P1 pre_shared_key S1", "crypto isakmp profile P1 pre_shared_key ..."),
        # A name with such a part is cut too: a row may lose a word of
        # its path, which is the safe side.
        ("crypto map KEY-MAP 10 ipsec-isakmp", "crypto map KEY-MAP ..."),
    ],
)
def test_a_label_is_cut_after_a_word_that_names_a_secret(label: str, shown: str) -> None:
    assert _tier3_detection._shown_label(label) == shown


@pytest.mark.parametrize(
    "label",
    [
        # Nothing after the word: no value to hide.
        "crypto isakmp key",
        "class-map match-any KEY-TRAFFIC",
        # A secret's name inside another word is not a part of it.
        "crypto keyring KR1",
        "ip nat inside source static 192.0.2.5 198.51.100.5 extendable mapping",
        # A path whose words are not secrets; `community` and
        # `authentication` are words of a path in a detector's line.
        "crypto isakmp keepalive 10 3",
        "crypto isakmp policy 10",
        "extcommunity-set opaque COLOR",
        "set policy-options community BLUE",
        "aaa authentication login default group tacacs+ local",
        "switch 1 provision c9300-48p",
    ],
)
def test_a_label_with_no_secret_is_whole(label: str) -> None:
    assert _tier3_detection._shown_label(label) == label


def test_two_keys_are_one_row() -> None:
    text = (
        "crypto isakmp policy 10\n encryption aes\n"
        "crypto isakmp key S1 address 0.0.0.0\n"
        "crypto isakmp key 6 S2 address 192.0.2.1\n"
    )
    assert detect_tier3_sections_iosxe_cli(text) == ["crypto isakmp policy 10", "crypto isakmp key ..."]


# ---------------------------------------------------------------------------
# Every capture, every row
# ---------------------------------------------------------------------------


def test_every_public_codec_is_planted_or_named() -> None:
    assert not set(PLANTS) & set(NOT_PLANTED)
    assert set(PLANTS) | set(NOT_PLANTED) == set(PUBLIC)


def test_no_secret_reaches_a_row() -> None:
    hits, read = _hits(_planted_captures())
    assert hits == {}
    # Every codec's captures were read, planted, and asked.
    assert set(read) == set(PLANTS)


def test_a_junos_config_as_printed() -> None:
    markers = {f"zqMarkJ{n}x": slot for n, slot in enumerate(("radius", "community", "ike"))}
    text = JUNOS_AS_PRINTED.format(**{slot: marker for marker, slot in markers.items()})
    tree = get_codec("juniper_junos").parse(text)
    # The text was read, and the deactivated community is a row.
    assert tree.hostname == "planted"
    assert "inactive: snmp community ... (deactivated in the source; not translated)" in (
        tree.dropped_tier3_sections
    )
    assert _found(tree.dropped_tier3_sections, markers) == set()


def test_a_netconf_document_has_no_row() -> None:
    documents = [path for codec, _label, path in _captures() if codec == "cisco_iosxe"]
    assert documents
    for path in documents:
        assert get_codec("cisco_iosxe").parse(path.read_text(encoding="utf-8")).dropped_tier3_sections == []


@pytest.mark.parametrize("target", sorted(PUBLIC))
def test_no_secret_reaches_a_jobs_rows(target: str) -> None:
    """The job's rows are the ones the page paints and the answer
    carries: no marker in them, from any source, onto any target."""
    found: dict[str, set[str]] = {}
    for codec, text in sorted(_smallest_planted().items()):
        job = run_plan_with_checked_names(get_codec(codec), get_codec(target), text, port_rename_map={})
        hit = _found(job.dropped_tier3_sections, _markers(codec))
        if hit:
            found[codec] = hit
    assert found == {}


def test_the_check_finds_the_secrets_without_the_cut(monkeypatch: pytest.MonkeyPatch) -> None:
    """Handed the defect -- the cut taken out -- the check finds the
    secrets of the IOS family's ``crypto`` lines, from the four parsers
    that take them whole, and nothing else."""
    monkeypatch.setattr(_tier3_detection, "_shown_label", lambda label: label)
    smallest = _smallest_planted()
    hits, _read = _hits((codec, codec, text) for codec, text in smallest.items())
    assert hits == WITHOUT_THE_CUT
