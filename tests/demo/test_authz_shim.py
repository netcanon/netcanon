"""Regression tests for the demo warden's create-body authz shim (Trusted
Computing Base).

Locks the container-escape the 2026-07 adversarial review found: a case-sensitive
Python denylist let lowercase HostConfig keys (``binds``/``privileged``/``capadd``)
smuggle host root past the shim, because Docker's Go decoder matches struct fields
case-INSENSITIVELY. The shim is now a case-folded positive allowlist; these tests
assert the escape stays closed.
"""

import copy
import json
import os

import pytest

os.environ.setdefault("NETCANON_INSTANCE_IMAGE", "ghcr.io/netcanon/netcanon@sha256:test")
os.environ.setdefault("NETCANON_INSTANCE_NETWORK", "demo-int")

from demo.warden import authz_shim  # noqa: E402
from demo.warden import constants as C  # noqa: E402

IMG = C.INSTANCE_IMAGE

CANON = {
    "Image": IMG,
    "Labels": {"demo.created_at": "1", "demo.instance": "a"},
    "Env": ["NETCANON_API_KEY=x"],
    "HostConfig": {
        "ReadonlyRootfs": True,
        "Tmpfs": {"/tmp": "rw"},
        "NetworkMode": "demo-int",
        "Memory": 268435456,
        "MemorySwap": 268435456,
        "NanoCpus": 500000000,
        "PidsLimit": 128,
        "CapDrop": ["ALL"],
        "SecurityOpt": ["no-new-privileges:true"],
        "LogConfig": {"Type": "none"},
    },
}


def _mutate(**hostconfig):
    b = copy.deepcopy(CANON)
    b["HostConfig"].update(hostconfig)
    return b


def test_canonical_body_accepted():
    assert authz_shim.validate_create_body(CANON) is None


def test_lowercase_escape_keys_rejected():
    # The critical finding: lowercase binds/privileged/capadd a case-sensitive
    # denylist missed but Docker's case-insensitive decoder would honour.
    assert (
        authz_shim.validate_create_body(
            _mutate(binds=["/:/hostfs"], privileged=True, capadd=["SYS_ADMIN"])
        )
        is not None
    )


def test_securityopt_append_rejected():
    assert (
        authz_shim.validate_create_body(
            _mutate(SecurityOpt=["no-new-privileges:true", "seccomp=unconfined"])
        )
        is not None
    )


@pytest.mark.parametrize(
    "key,val",
    [
        ("CgroupnsMode", "host"),
        ("MaskedPaths", []),
        ("Devices", [{"PathOnHost": "/dev/sda"}]),
        ("Binds", ["/etc:/etc"]),
        ("Ulimits", [{"Name": "nofile", "Soft": 1, "Hard": 1}]),
    ],
)
def test_forbidden_hostconfig_keys_rejected(key, val):
    assert authz_shim.validate_create_body(_mutate(**{key: val})) is not None


def test_top_level_networkingconfig_rejected():
    b = copy.deepcopy(CANON)
    b["NetworkingConfig"] = {"EndpointsConfig": {"caddy-net": {}}}
    assert authz_shim.validate_create_body(b) is not None


def test_wrong_image_rejected():
    b = copy.deepcopy(CANON)
    b["Image"] = "evil@sha256:x"
    assert authz_shim.validate_create_body(b) is not None


def test_dup_case_last_wins_rejected():
    # Python (_fold last-wins) and Go (duplicate-key last-wins) resolve to the same
    # object; a trailing lowercase hostconfig carrying binds must be rejected.
    b = json.loads(
        '{"Image":"%s","HostConfig":{"ReadonlyRootfs":true},"hostconfig":{"binds":["/:/h"]}}' % IMG
    )
    assert authz_shim.validate_create_body(b) is not None
