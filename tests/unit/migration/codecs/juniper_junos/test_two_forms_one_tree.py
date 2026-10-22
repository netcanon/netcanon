"""A Junos config in its two forms, each typed out.

The parser reads the hierarchical form by writing it as set-form and
reading that.  A test that sets one hierarchical text beside another
sends both through the same tokeniser, and what the tokeniser gets
wrong in both is equal on both: a wildcard cut as a comment
(``member ge-0/*/*;``) took whole blocks out of each side alike, and
every such comparison passed.

So each hierarchical text here has its ``show configuration | display
set`` twin written by hand, which is another road to the same tree:
it shares the set-form reader and nothing before it.  Three things
are asked of every pair:

* the two forms give one tree, the rows of what was not translated
  included;
* the lines the hierarchical form is written as are the lines typed
  by hand -- none lost, none invented;
* the tree holds what the text says, typed a third time, so that two
  trees that are equally empty do not pass for agreement.

The texts are the shapes Juniper's own pages print (the samples under
``show configuration``, ``deactivate``, ``protect``, ``annotate``, the
``display`` pipes, the load-file operators) and the shapes real
captures have, each written with made-up values.
"""

from __future__ import annotations

import shlex
from typing import Any

import pytest

from netcanon.migration.codecs.juniper_junos.parse import (
    _blockform_to_setform,
    _looks_like_blockform,
)
from netcanon.migration.codecs.registry import get_codec

pytestmark = pytest.mark.unit

_INACTIVE = " (deactivated in the source; not translated)"
_DELETED = " (marked for deletion in a load file; not translated)"

#: name -> (the hierarchical text, the set-form text, what the tree holds).
PAIRS: dict[str, tuple[str, str, dict[str, Any]]] = {}


def _pair(name: str, printed: str, as_set: str, **holds: Any) -> None:
    assert name not in PAIRS, name
    PAIRS[name] = (printed.lstrip("\n"), as_set.lstrip("\n"), holds)


# ---------------------------------------------------------------------------
# What a device prints
# ---------------------------------------------------------------------------

_pair(
    "as printed",
    r"""
## Last commit: 2024-01-01 00:00:00 UTC by admin
version 21.4R3.15;
system {
    host-name r1;
    root-authentication {
        encrypted-password "$6$fake$roothash"; ## SECRET-DATA
    }
    login {
        user admin {
            uid 2000;
            class super-user;
            authentication {
                encrypted-password "$6$fake$adminhash"; ## SECRET-DATA
            }
        }
    }
    name-server {
        192.0.2.53;
    }
}
interfaces {
    ge-0/0/1 {
        description "uplink # 1";
        unit 0 {
            family inet {
                address 10.0.0.1/24;
            }
        }
    }
}
snmp {
    community fakeCommunity { ## SECRET-DATA
        authorization read-only;
    }
}
""",
    r"""
set version 21.4R3.15
set system host-name r1
set system root-authentication encrypted-password "$6$fake$roothash"
set system login user admin uid 2000
set system login user admin class super-user
set system login user admin authentication encrypted-password "$6$fake$adminhash"
set system name-server 192.0.2.53
set interfaces ge-0/0/1 description "uplink # 1"
set interfaces ge-0/0/1 unit 0 family inet address 10.0.0.1/24
set snmp community fakeCommunity authorization read-only
""",
    hostname="r1", version="21.4R3.15", interfaces={"ge-0/0/1": ["10.0.0.1/24"]},
    users={"admin": "junos:$6$fake$adminhash"}, dns=["192.0.2.53"], community="fakeCommunity", rows=[],
)

_pair(
    "display detail",
    r"""
## Last commit: 2024-01-01 00:00:00 UTC by admin
##
## version: Software version information
## require: system
##
version 23.1R1.8;
##
## groups: Configuration groups
##
groups {
    ##
    ## Group name
    ## range: 1 .. 254
    ##
    global {
        system {
            login {
                ##
                ## User name (login)
                ## match (regex): ^[[:alnum:]_]{1,}[.]{0,1}[[:alnum:]_-]{0,}$
                ##
                user ops {
                    class operator;
                }
            }
        }
    }
}
apply-groups global;
##
## system: System parameters
##
system {
    ##
    ## host-name: Hostname for this router
    ## match (regex): ^[[:alnum:]._-]+$
    ##
    host-name r2;
}
""",
    r"""
set version 23.1R1.8
set groups global system login user ops class operator
set apply-groups global
set system host-name r2
""",
    hostname="r2", version="23.1R1.8", users={"ops": ""}, groups=["global"], rows=[],
)

_pair(
    "protect, and an inactive list under it",
    r"""
protect: system {
    host-name r3;
    inactive: domain-search [ a.example b.example ];
    login {
        deny-sources {
            protect: address [ 192.0.2.19 192.0.2.173 ];
        }
    }
    name-server {
        192.0.2.53;
    }
}
""",
    r"""
set system host-name r3
set system domain-search a.example
set system domain-search b.example
deactivate system domain-search
set system login deny-sources address 192.0.2.19
set system login deny-sources address 192.0.2.173
set system name-server 192.0.2.53
protect system
protect system login deny-sources address
""",
    hostname="r3", dns=["192.0.2.53"], rows=["inactive: system domain-search" + _INACTIVE],
)

_pair(
    "a deactivated leaf",
    r"""
system {
    host-name r4;
    internet-options {
        inactive: tcp-mss 1280;
    }
}
chassis {
    redundancy {
        inactive: graceful-switchover;
    }
    fpc 2 {
        pic 0 {
            tunnel-services {
                bandwidth 1g;
            }
        }
    }
}
""",
    r"""
set system host-name r4
set system internet-options tcp-mss 1280
deactivate system internet-options tcp-mss
set chassis redundancy graceful-switchover
deactivate chassis redundancy graceful-switchover
set chassis fpc 2 pic 0 tunnel-services bandwidth 1g
""",
    hostname="r4", rows=[
        "inactive: system internet-options tcp-mss" + _INACTIVE,
        "inactive: chassis redundancy graceful-switchover" + _INACTIVE,
    ],
)

_pair(
    "a deactivated unit",
    r"""
interfaces {
    ge-0/0/0 {
        unit 0 {
            family inet {
                address 192.0.2.230/24;
            }
        }
    }
    xe-0/0/0 {
        unit 0 {
            family inet {
                address 198.51.100.1/24;
            }
            family iso;
            family mpls;
        }
        inactive: unit 1 {
            family inet {
                address 10.0.0.1/8;
            }
        }
    }
}
""",
    r"""
set interfaces ge-0/0/0 unit 0 family inet address 192.0.2.230/24
set interfaces xe-0/0/0 unit 0 family inet address 198.51.100.1/24
set interfaces xe-0/0/0 unit 0 family iso
set interfaces xe-0/0/0 unit 0 family mpls
set interfaces xe-0/0/0 unit 1 family inet address 10.0.0.1/8
deactivate interfaces xe-0/0/0 unit 1
""",
    interfaces={"ge-0/0/0": ["192.0.2.230/24"], "xe-0/0/0": ["198.51.100.1/24"]},
    absent=["xe-0/0/0.1", "inactive:"], rows=["inactive: interfaces xe-0/0/0 unit 1" + _INACTIVE],
)

_pair(
    "annotations",
    r"""
/* This comment goes with routing-options */
routing-options {
    /* This comment goes with routing-options traceoptions */
    traceoptions {
        /* This comment goes with the file */
        file rpd size 1m files 10;
        flag task;
    }
    autonomous-system 64500;    /* This comment is dropped */
    static {
        route 10.9.0.0/16 next-hop 10.0.0.9;
    }
}
system {
    host-name r6;
}
""",
    r"""
set routing-options traceoptions file rpd size 1m files 10
set routing-options traceoptions flag task
set routing-options autonomous-system 64500
set routing-options static route 10.9.0.0/16 next-hop 10.0.0.9
set system host-name r6
""",
    hostname="r6", routes=[("10.9.0.0/16", "10.0.0.9")], rows=[],
)

_pair(
    "a comment after a brace and after a statement",
    r"""
groups { # "groups" is a top-level statement
    global { # User-defined group name
        system {
            name-server {
                192.0.2.53;
            }
        }
    }
}
apply-groups global;
interfaces {
    so-1/1/0 {
        apply-groups-except global;  # Disables inheritance from group "global"
        # so-1/1/0 uses default value for "hold-time"
        # and "link-mode"
        unit 0 {
            family inet {
                address 10.10.1.1/30;
            }
        }
    }
}
""",
    r"""
set groups global system name-server 192.0.2.53
set apply-groups global
set interfaces so-1/1/0 apply-groups-except global
set interfaces so-1/1/0 unit 0 family inet address 10.10.1.1/30
""",
    interfaces={"so-1/1/0": ["10.10.1.1/30"]}, dns=["192.0.2.53"], groups=["global"], rows=[],
)

_pair(
    "blocks that are omitted",
    "system {\n\troot-authentication { /* OMITTED */ };\n\tlogin { /* OMITTED */ };\n    host-name r8;\n}\n"
    "interfaces {\n    ge-0/0/1 {\n        unit 0 {\n            family inet {\n"
    "                address 10.11.1.1/24;\n            }\n        }\n    }\n}\n",
    r"""
set system root-authentication
set system login
set system host-name r8
set interfaces ge-0/0/1 unit 0 family inet address 10.11.1.1/24
""",
    hostname="r8", interfaces={"ge-0/0/1": ["10.11.1.1/24"]}, users={}, rows=[],
)

_pair(
    "display inheritance",
    r"""
snmp {
    location "West of Nowhere";
    ##
    ## 'My Engineering Group' was inherited from group 'basic'
    ##
    contact "My Engineering Group";
    ##
    ## 'fakeCommunity' was inherited from group 'basic'
    ##
    community fakeCommunity {
        ##
        ## 'read-only' was inherited from group 'basic'
        ##
        authorization read-only;
    }
}
system {
    ##
    ## 'r9' was inherited from group 'basic'
    ##
    host-name r9;
}
""",
    r"""
set snmp location "West of Nowhere"
set snmp contact "My Engineering Group"
set snmp community fakeCommunity authorization read-only
set system host-name r9
""",
    hostname="r9", community="fakeCommunity", rows=[],
)

_pair(
    "display inheritance terse",
    r"""
system {
    host-name r10; ## inherited from group 'global'
    login {
        class readonly {
            permissions [ interface network view ]; ## inherited from group 'global'; inherited from group 'global'
        }
        user ops {
            class readonly;
        }
    }
}
""",
    r"""
set system host-name r10
set system login class readonly permissions interface
set system login class readonly permissions network
set system login class readonly permissions view
set system login user ops class readonly
""",
    hostname="r10", users={"ops": ""}, rows=[],
)

_pair(
    "display max-depth",
    r"""
interfaces {
    ge-0/0/0 {
        unit 0 {
            family inet { ... }
        }
    }
}
system {
    host-name r14;
}
protocols { ... }
""",
    r"""
set interfaces ge-0/0/0 unit 0 family inet
set system host-name r14
set protocols
""",
    hostname="r14", interfaces={"ge-0/0/0": []}, absent=["..."], rows=[],
)

_pair(
    "a secret the viewer is not shown",
    r"""
system {
    host-name r15;
    tacplus-server {
        192.0.2.4 {
            secret /* SECRET-DATA */;
        }
    }
    login {
        user bob {
            class super-user;
            authentication {
                encrypted-password /* SECRET-DATA */; ## SECRET-DATA
            }
        }
    }
}
""",
    r"""
set system host-name r15
set system tacplus-server 192.0.2.4 secret /* SECRET-DATA */
set system login user bob class super-user
set system login user bob authentication encrypted-password /* SECRET-DATA */
""",
    hostname="r15", users={"bob": "junos:/*"}, rows=[],
)

_pair(
    "a warning that a statement is missing",
    r"""
system {
    host-name r16;
}
protocols {
    pim {
        interface so-0/0/0 {
            priority 4;
            version 2;
            # Warning: missing mandatory statement(s): 'mode'
        }
    }
}
interfaces {
    so-0/0/0 {
        unit 0 {
            family inet {
                address 10.21.1.1/30;
            }
        }
    }
}
""",
    r"""
set system host-name r16
set protocols pim interface so-0/0/0 priority 4
set protocols pim interface so-0/0/0 version 2
set interfaces so-0/0/0 unit 0 family inet address 10.21.1.1/30
""",
    hostname="r16", version="", interfaces={"so-0/0/0": ["10.21.1.1/30"]}, rows=[],
)

_pair(
    "what `| except SECRET-DATA` leaves",
    r"""
## Last commit: 2024-01-01 00:00:00 UTC by admin
version 21.4R3.15;
system {
    host-name r26;
    root-authentication {
    }
    login {
        user admin {
            uid 2000;
            class super-user;
            authentication {
            }
        }
        user second {
            class read-only;
            authentication {
            }
        }
    }
}
snmp {
    community fakeCommunity {
        authorization read-only;
    }
}
""",
    r"""
set version 21.4R3.15
set system host-name r26
set system root-authentication
set system login user admin uid 2000
set system login user admin class super-user
set system login user admin authentication
set system login user second class read-only
set system login user second authentication
set snmp community fakeCommunity authorization read-only
""",
    hostname="r26", users={"admin": "", "second": ""}, community="fakeCommunity", rows=[],
)

_pair(
    # The sample under ``show configuration`` in the CLI reference: a
    # version in quotes, a secret the viewer is not shown, and ``...``
    # where the page leaves lines out.
    "the vendor's sample of the command",
    r"""
## Last commit: 2024-01-01 00:00:00 UTC by admin
version "8.2I0 [builder]"; ## last changed: 2024-01-01 00:00:00 UTC
system {
    host-name r41;
    domain-name example.net;
    name-server {
        192.0.2.254;
        192.0.2.249;
    }
    services {
        telnet;
    }
    tacplus-server {
        192.0.2.4 {
            secret /* SECRET-DATA */;
            ...
        }
    }
}
interfaces {
    ...
}
protocols {
    isis {
        export "direct routes";
    }
}
policy-options {
    policy-statement "direct routes" {
        from protocol direct;
        then accept;
    }
}
""",
    r"""
set version "8.2I0 [builder]"
set system host-name r41
set system domain-name example.net
set system name-server 192.0.2.254
set system name-server 192.0.2.249
set system services telnet
set system tacplus-server 192.0.2.4 secret /* SECRET-DATA */
set system tacplus-server 192.0.2.4
set interfaces
set protocols isis export "direct routes"
set policy-options policy-statement "direct routes" from protocol direct
set policy-options policy-statement "direct routes" then accept
""",
    hostname="r41", version="8.2I0 [builder]", dns=["192.0.2.254", "192.0.2.249"], absent=["..."],
    rows=['set policy-options policy-statement "direct'],
)

_pair(
    # ``show configuration groups junos-defaults applications``: a
    # header that names a tag in a comment, and ``#`` annotations.
    "annotations that begin with a hash",
    r"""
## protect: groups junos-defaults
##
#
# File Transfer Protocol
#
application junos-ftp {
    application-protocol ftp;
    protocol tcp;
    destination-port 21;
}
#
# Trivial File Transfer Protocol
#
application junos-tftp {
    application-protocol tftp;
    protocol udp;
    destination-port 69;
}
system {
    host-name r42;
}
""",
    r"""
set application junos-ftp application-protocol ftp
set application junos-ftp protocol tcp
set application junos-ftp destination-port 21
set application junos-tftp application-protocol tftp
set application junos-tftp protocol udp
set application junos-tftp destination-port 69
set system host-name r42
""",
    hostname="r42", rows=[],
)

# ---------------------------------------------------------------------------
# What the tokeniser has to leave alone
# ---------------------------------------------------------------------------

_pair(
    "quoted strings that hold what ends a statement",
    r"""
version 21.4R3.15;
system {
    host-name r17;
    login {
        message "#### AUTHORISED; USE {ONLY} ####\nSecond \"line\" # here";
        user ops {
            full-name "Ops; #1 {team}";
            class operator;
        }
    }
}
interfaces {
    ge-0/0/1 {
        description "uplink #1; to {core} \"A\"";
        unit 0 {
            family inet {
                address 10.1.1.1/24;
            }
        }
    }
    ge-0/0/2 {
        description "after";
        unit 0 {
            family inet {
                address 10.2.2.1/24;
            }
        }
    }
}
""",
    r"""
set version 21.4R3.15
set system host-name r17
set system login message "#### AUTHORISED; USE {ONLY} ####\nSecond \"line\" # here"
set system login user ops full-name "Ops; #1 {team}"
set system login user ops class operator
set interfaces ge-0/0/1 description "uplink #1; to {core} \"A\""
set interfaces ge-0/0/1 unit 0 family inet address 10.1.1.1/24
set interfaces ge-0/0/2 description "after"
set interfaces ge-0/0/2 unit 0 family inet address 10.2.2.1/24
""",
    hostname="r17", interfaces={"ge-0/0/1": ["10.1.1.1/24"], "ge-0/0/2": ["10.2.2.1/24"]},
    descriptions={"ge-0/0/1": 'uplink #1; to {core} "A"', "ge-0/0/2": "after"}, users={"ops": ""}, rows=[],
)

_pair(
    "a slash and a star inside a quoted string",
    r"""
version 21.4R3.15;
system {
    host-name r18;
    syslog {
        file messages {
            any notice;
            match "!(/var/tmp/*)";
        }
    }
}
interfaces {
    ge-0/0/1 {
        unit 0 {
            family inet {
                address 10.1.1.1/24;
            }
        }
    }
    ge-0/0/2 {
        /* uplink */
        unit 0 {
            family inet {
                address 10.2.2.1/24;
            }
        }
    }
    ge-0/0/3 {
        unit 0 {
            family inet {
                address 10.3.3.1/24;
            }
        }
    }
}
""",
    r"""
set version 21.4R3.15
set system host-name r18
set system syslog file messages any notice
set system syslog file messages match "!(/var/tmp/*)"
set interfaces ge-0/0/1 unit 0 family inet address 10.1.1.1/24
set interfaces ge-0/0/2 unit 0 family inet address 10.2.2.1/24
set interfaces ge-0/0/3 unit 0 family inet address 10.3.3.1/24
""",
    hostname="r18", rows=[],
    interfaces={"ge-0/0/1": ["10.1.1.1/24"], "ge-0/0/2": ["10.2.2.1/24"], "ge-0/0/3": ["10.3.3.1/24"]},
)

_pair(
    "range members with a wildcard, an annotation after them",
    r"""
version 20.2R3-S2.5;
system {
    host-name r19;
}
interfaces {
    interface-range edge {
        member ge-*/*/*;
        member xe-*/*/*;
        mtu 9216;
    }
    ge-0/0/1 {
        unit 0 {
            family inet {
                address 10.1.1.1/24;
            }
        }
    }
    ge-0/0/2 {
        /* uplink */
        unit 0 {
            family inet {
                address 10.2.2.1/24;
            }
        }
    }
    ge-0/0/3 {
        unit 0 {
            family inet {
                address 10.3.3.1/24;
            }
        }
    }
}
""",
    r"""
set version 20.2R3-S2.5
set system host-name r19
set interfaces interface-range edge member ge-*/*/*
set interfaces interface-range edge member xe-*/*/*
set interfaces interface-range edge mtu 9216
set interfaces ge-0/0/1 unit 0 family inet address 10.1.1.1/24
set interfaces ge-0/0/2 unit 0 family inet address 10.2.2.1/24
set interfaces ge-0/0/3 unit 0 family inet address 10.3.3.1/24
""",
    hostname="r19", absent=["ge-*", "ge-0/0"], rows=[],
    interfaces={"ge-0/0/1": ["10.1.1.1/24"], "ge-0/0/2": ["10.2.2.1/24"], "ge-0/0/3": ["10.3.3.1/24"]},
)

_pair(
    # "Expanded Interface Range Statements", Interface Ranges for
    # Physical Interfaces: the member line, and the comment under it.
    "the vendor's interface-range sample",
    r"""
system {
    host-name r20;
}
interfaces {
    interface-range range1 {
        member et-5/[0-5]/*;
        /*Common configuration is added as part of the interface-range definition*/
        mtu 256;
        hold-time up 10;
        ether-options {
            flow-control;
        }
    }
    et-10/1/1 {
        mtu 256;
    }
}
""",
    r"""
set system host-name r20
set interfaces interface-range range1 member et-5/[0-5]/*
set interfaces interface-range range1 mtu 256
set interfaces interface-range range1 hold-time up 10
set interfaces interface-range range1 ether-options flow-control
set interfaces et-10/1/1 mtu 256
""",
    # A name the classifier does not read keeps the number as it stands.
    hostname="r20", mtus={"et-5/[0-5]/*": 256, "et-10/1/1": 242}, absent=["et-5/[0-5]"], rows=[],
)

_pair(
    "a member with one wildcard, an annotation further down",
    r"""
version 20.2R3-S2.5;
system {
    host-name r21;
}
interfaces {
    interface-range access {
        member ge-0/0/*;
        unit 0 {
            family ethernet-switching;
        }
    }
    ge-0/1/0 {
        unit 0 {
            family inet {
                address 10.1.1.1/24;
            }
        }
    }
    ge-0/1/1 {
        unit 0 {
            /* to core */
            family inet {
                address 10.2.2.1/24;
            }
        }
    }
}
""",
    r"""
set version 20.2R3-S2.5
set system host-name r21
set interfaces interface-range access member ge-0/0/*
set interfaces interface-range access unit 0 family ethernet-switching
set interfaces ge-0/1/0 unit 0 family inet address 10.1.1.1/24
set interfaces ge-0/1/1 unit 0 family inet address 10.2.2.1/24
""",
    hostname="r21", interfaces={"ge-0/1/0": ["10.1.1.1/24"], "ge-0/1/1": ["10.2.2.1/24"]}, absent=["ge-0/0"],
    rows=[],
)

_pair(
    "a group's wildcard, and an omitted block after it",
    r"""
system {
    host-name r37;
}
groups {
    ifstats {
        interfaces {
            <*/*> {
                traps;
            }
        }
        system {
            name-server {
                192.0.2.53;
            }
        }
    }
    other {
        system {
            ntp {
                server 192.0.2.123;
            }
        }
    }
}
apply-groups [ ifstats other ];
event-options { /* OMITTED */ };
interfaces {
    ge-0/0/1 {
        unit 0 {
            family inet {
                address 10.1.1.1/24;
            }
        }
    }
}
""",
    r"""
set system host-name r37
set groups ifstats interfaces <*/*> traps
set groups ifstats system name-server 192.0.2.53
set groups other system ntp server 192.0.2.123
set apply-groups ifstats
set apply-groups other
set event-options
set interfaces ge-0/0/1 unit 0 family inet address 10.1.1.1/24
""",
    hostname="r37", interfaces={"ge-0/0/1": ["10.1.1.1/24"]}, absent=["<*"], dns=["192.0.2.53"],
    ntp=["192.0.2.123"], groups=["ifstats", "other"], rows=[],
)

_pair(
    "a value that begins with a hash, not in quotes",
    r"""
system {
    host-name r22;
}
interfaces {
    ge-0/0/1 {
        description #1-uplink;
        mtu 9000;
        unit 0 {
            family inet {
                address 10.1.1.1/24;
            }
        }
    }
}
""",
    r"""
set system host-name r22
set interfaces ge-0/0/1 description #1-uplink
set interfaces ge-0/0/1 mtu 9000
set interfaces ge-0/0/1 unit 0 family inet address 10.1.1.1/24
""",
    hostname="r22", interfaces={"ge-0/0/1": ["10.1.1.1/24"]}, descriptions={"ge-0/0/1": "#1-uplink"},
    mtus={"ge-0/0/1": 8986}, rows=[],
)

_pair(
    "a comment mark inside a line comment",
    r"""
system {
    host-name r23; ## see /* below
}
interfaces {
    ge-0/0/1 {
        mtu 9000; /* jumbo */
        unit 0 {
            family inet {
                address 10.1.1.1/24;
            }
        }
    }
}
""",
    r"""
set system host-name r23
set interfaces ge-0/0/1 mtu 9000
set interfaces ge-0/0/1 unit 0 family inet address 10.1.1.1/24
""",
    hostname="r23", interfaces={"ge-0/0/1": ["10.1.1.1/24"]}, mtus={"ge-0/0/1": 8986}, rows=[],
)

_pair(
    "a quoted version with a space in it",
    r"""
version "8.2I0 [builder]";
system {
    host-name r24;
}
interfaces {
    fe-0/0/0 {
        unit 0 {
            family inet {
                address 10.8.1.1/24;
            }
        }
    }
}
""",
    r"""
set version "8.2I0 [builder]"
set system host-name r24
set interfaces fe-0/0/0 unit 0 family inet address 10.8.1.1/24
""",
    hostname="r24", version="8.2I0 [builder]", interfaces={"fe-0/0/0": ["10.8.1.1/24"]}, rows=[],
)

_pair(
    "groups first, the host-name only in a group",
    r"""
version 18.4R2.7;
groups {
    re0 {
        system {
            host-name r25-re0;
        }
    }
    re1 {
        system {
            host-name r25-re1;
        }
    }
}
apply-groups [ re0 re1 ];
chassis {
    redundancy {
        graceful-switchover;
    }
}
interfaces {
    ge-0/0/0 {
        unit 0 {
            family inet {
                address 10.8.2.1/24;
            }
        }
    }
}
""",
    r"""
set version 18.4R2.7
set groups re0 system host-name r25-re0
set groups re1 system host-name r25-re1
set apply-groups re0
set apply-groups re1
set chassis redundancy graceful-switchover
set interfaces ge-0/0/0 unit 0 family inet address 10.8.2.1/24
""",
    hostname="r25-re0", version="18.4R2.7", interfaces={"ge-0/0/0": ["10.8.2.1/24"]}, groups=["re0", "re1"],
    rows=[],
)

_pair(
    "an annotation over several lines",
    r"""
/*
 * Site: lab
 * Owner: "ops"; {do not edit}
 */
system {
    host-name r27;
}
""",
    r"""
set system host-name r27
""",
    hostname="r27", rows=[],
)

# ---------------------------------------------------------------------------
# What a config holds and does not run
# ---------------------------------------------------------------------------

_pair(
    "apply-groups deactivated",
    r"""
system {
    host-name r30;
}
groups {
    G {
        interfaces {
            ge-0/0/9 {
                unit 0 {
                    family inet {
                        address 10.9.9.1/24;
                    }
                }
            }
        }
    }
}
inactive: apply-groups G;
interfaces {
    ge-0/0/1 {
        unit 0 {
            family inet {
                address 10.1.1.1/24;
            }
        }
    }
}
""",
    r"""
set system host-name r30
set groups G interfaces ge-0/0/9 unit 0 family inet address 10.9.9.1/24
set apply-groups G
deactivate apply-groups
set interfaces ge-0/0/1 unit 0 family inet address 10.1.1.1/24
""",
    hostname="r30", interfaces={"ge-0/0/1": ["10.1.1.1/24"]}, absent=["ge-0/0/9"], groups=[],
    rows=["inactive: apply-groups" + _INACTIVE],
)

_pair(
    "a group deactivated and still applied",
    r"""
system {
    host-name r31;
}
groups {
    inactive: G {
        interfaces {
            ge-0/0/9 {
                unit 0 {
                    family inet {
                        address 10.9.9.1/24;
                    }
                }
            }
        }
    }
}
apply-groups G;
interfaces {
    ge-0/0/1 {
        unit 0 {
            family inet {
                address 10.1.1.1/24;
            }
        }
    }
}
""",
    r"""
set system host-name r31
set groups G interfaces ge-0/0/9 unit 0 family inet address 10.9.9.1/24
deactivate groups G
set apply-groups G
set interfaces ge-0/0/1 unit 0 family inet address 10.1.1.1/24
""",
    hostname="r31", interfaces={"ge-0/0/1": ["10.1.1.1/24"]}, absent=["ge-0/0/9"], groups=[],
    rows=["inactive: groups G" + _INACTIVE],
)

_pair(
    "one statement of an applied group deactivated",
    r"""
system {
    host-name r32;
}
groups {
    G {
        interfaces {
            inactive: ge-0/0/8 {
                unit 0 {
                    family inet {
                        address 10.8.8.1/24;
                    }
                }
            }
            ge-0/0/9 {
                unit 0 {
                    family inet {
                        address 10.9.9.1/24;
                    }
                }
            }
        }
    }
}
apply-groups G;
""",
    r"""
set system host-name r32
set groups G interfaces ge-0/0/8 unit 0 family inet address 10.8.8.1/24
deactivate groups G interfaces ge-0/0/8
set groups G interfaces ge-0/0/9 unit 0 family inet address 10.9.9.1/24
set apply-groups G
""",
    hostname="r32", interfaces={"ge-0/0/9": ["10.9.9.1/24"]}, absent=["ge-0/0/8"], groups=["G"],
    rows=["inactive: groups G interfaces ge-0/0/8" + _INACTIVE],
)

_pair(
    "deactivated at the top, the same path in an applied group",
    r"""
system {
    host-name r33;
}
groups {
    G {
        interfaces {
            ge-0/0/1 {
                unit 0 {
                    family inet {
                        address 10.9.9.1/24;
                    }
                }
            }
        }
        system {
            name-server {
                192.0.2.53;
            }
        }
    }
}
apply-groups G;
interfaces {
    inactive: ge-0/0/1 {
        description "switched off";
        unit 0 {
            family inet {
                address 10.1.1.1/24;
            }
        }
    }
    ge-0/0/2 {
        unit 0 {
            family inet {
                address 10.2.2.1/24;
            }
        }
    }
}
""",
    r"""
set system host-name r33
set groups G interfaces ge-0/0/1 unit 0 family inet address 10.9.9.1/24
set groups G system name-server 192.0.2.53
set apply-groups G
set interfaces ge-0/0/1 description "switched off"
set interfaces ge-0/0/1 unit 0 family inet address 10.1.1.1/24
deactivate interfaces ge-0/0/1
set interfaces ge-0/0/2 unit 0 family inet address 10.2.2.1/24
""",
    hostname="r33", interfaces={"ge-0/0/2": ["10.2.2.1/24"]}, absent=["ge-0/0/1"], groups=["G"],
    dns=["192.0.2.53"], rows=["inactive: interfaces ge-0/0/1" + _INACTIVE],
)

_pair(
    "a member of an interface-range that is itself deactivated",
    r"""
system {
    host-name r34;
}
interfaces {
    interface-range uplinks {
        member ge-0/0/1;
        member ge-0/0/2;
        description "from the range";
        mtu 9100;
        unit 0 {
            family inet {
                address 10.50.0.1/24;
            }
        }
    }
    inactive: ge-0/0/1 {
        description "switched off";
    }
    ge-0/0/2 {
        description "on";
    }
}
""",
    r"""
set system host-name r34
set interfaces interface-range uplinks member ge-0/0/1
set interfaces interface-range uplinks member ge-0/0/2
set interfaces interface-range uplinks description "from the range"
set interfaces interface-range uplinks mtu 9100
set interfaces interface-range uplinks unit 0 family inet address 10.50.0.1/24
set interfaces ge-0/0/1 description "switched off"
deactivate interfaces ge-0/0/1
set interfaces ge-0/0/2 description on
""",
    hostname="r34", interfaces={"ge-0/0/2": ["10.50.0.1/24"]}, absent=["ge-0/0/1"], mtus={"ge-0/0/2": 9086},
    descriptions={"ge-0/0/2": "on"}, rows=["inactive: interfaces ge-0/0/1" + _INACTIVE],
)

_pair(
    "a deactivated `disable`",
    r"""
system {
    host-name r35;
}
interfaces {
    ge-0/0/1 {
        inactive: disable;
        unit 0 {
            family inet {
                address 10.1.1.1/24;
            }
        }
    }
    ge-0/0/2 {
        disable;
        unit 0 {
            family inet {
                address 10.2.2.1/24;
            }
        }
    }
}
""",
    r"""
set system host-name r35
set interfaces ge-0/0/1 disable
deactivate interfaces ge-0/0/1 disable
set interfaces ge-0/0/1 unit 0 family inet address 10.1.1.1/24
set interfaces ge-0/0/2 disable
set interfaces ge-0/0/2 unit 0 family inet address 10.2.2.1/24
""",
    hostname="r35", interfaces={"ge-0/0/1": ["10.1.1.1/24"], "ge-0/0/2": ["10.2.2.1/24"]},
    enabled={"ge-0/0/1": True, "ge-0/0/2": False}, rows=["inactive: interfaces ge-0/0/1 disable" + _INACTIVE],
)

_pair(
    "a deactivated irb unit a VLAN still names",
    r"""
system {
    host-name r38;
}
interfaces {
    irb {
        unit 100 {
            family inet {
                address 10.100.0.1/24;
            }
        }
        inactive: unit 200 {
            family inet {
                address 10.200.0.1/24;
            }
        }
    }
}
vlans {
    v100 {
        vlan-id 100;
        l3-interface irb.100;
    }
    v200 {
        vlan-id 200;
        l3-interface irb.200;
    }
}
""",
    r"""
set system host-name r38
set interfaces irb unit 100 family inet address 10.100.0.1/24
set interfaces irb unit 200 family inet address 10.200.0.1/24
deactivate interfaces irb unit 200
set vlans v100 vlan-id 100
set vlans v100 l3-interface irb.100
set vlans v200 vlan-id 200
set vlans v200 l3-interface irb.200
""",
    hostname="r38", vlans={100: ["10.100.0.1/24"], 200: []}, rows=["inactive: interfaces irb unit 200" + _INACTIVE],
)

_pair(
    "a port whose LAG membership is deactivated",
    r"""
system {
    host-name r39;
}
interfaces {
    ge-0/0/1 {
        ether-options {
            802.3ad ae0;
        }
    }
    ge-0/0/2 {
        inactive: ether-options {
            802.3ad ae0;
        }
    }
    ae0 {
        unit 0 {
            family inet {
                address 10.10.0.1/24;
            }
        }
    }
}
""",
    r"""
set system host-name r39
set interfaces ge-0/0/1 ether-options 802.3ad ae0
set interfaces ge-0/0/2 ether-options 802.3ad ae0
deactivate interfaces ge-0/0/2 ether-options
set interfaces ae0 unit 0 family inet address 10.10.0.1/24
""",
    hostname="r39", lags={"ae0": ["ge-0/0/1"]}, rows=["inactive: interfaces ge-0/0/2 ether-options" + _INACTIVE],
)

_pair(
    "one inside another, two tags, and sections that are not translated",
    r"""
system {
    host-name r36;
}
interfaces {
    inactive: ge-0/0/2 {
        inactive: unit 0 {
            family inet {
                address 10.0.2.1/24;
            }
        }
        unit 7 {
            family inet {
                address 10.0.7.1/24;
            }
        }
    }
    inactive: protect: ge-0/0/3 {
        mtu 9000;
    }
    protect: inactive: ge-0/0/4 {
        mtu 9100;
    }
    ge-0/0/1 {
        unit 0 {
            family inet {
                address 10.0.0.1/24;
            }
        }
    }
}
firewall {
    family inet {
        filter PROTECT {
            term 1 {
                then accept;
            }
        }
        inactive: filter OLD {
            term 1 {
                then discard;
            }
        }
    }
}
security {
    policies {
        default-policy {
            permit-all;
        }
    }
}
policy-options {
    policy-statement EXPORT {
        then accept;
    }
    prefix-list EMPTY {
    }
    inactive: prefix-list UNUSED {
        192.0.2.0/24;
    }
}
class-of-service {
    forwarding-classes {
        queue 0 best-effort;
    }
}
""",
    r"""
set system host-name r36
set interfaces ge-0/0/2 unit 0 family inet address 10.0.2.1/24
deactivate interfaces ge-0/0/2 unit 0
set interfaces ge-0/0/2 unit 7 family inet address 10.0.7.1/24
deactivate interfaces ge-0/0/2
set interfaces ge-0/0/3 mtu 9000
deactivate interfaces ge-0/0/3
protect interfaces ge-0/0/3
set interfaces ge-0/0/4 mtu 9100
deactivate interfaces ge-0/0/4
protect interfaces ge-0/0/4
set interfaces ge-0/0/1 unit 0 family inet address 10.0.0.1/24
set firewall family inet filter PROTECT term 1 then accept
set firewall family inet filter OLD term 1 then discard
deactivate firewall family inet filter OLD
set security policies default-policy permit-all
set policy-options policy-statement EXPORT then accept
set policy-options prefix-list EMPTY
set policy-options prefix-list UNUSED 192.0.2.0/24
deactivate policy-options prefix-list UNUSED
set class-of-service forwarding-classes queue 0 best-effort
""",
    hostname="r36", interfaces={"ge-0/0/1": ["10.0.0.1/24"]},
    absent=["ge-0/0/2", "ge-0/0/2.7", "ge-0/0/3", "ge-0/0/4", "inactive:", "protect:"],
    rows=[
        "inactive: interfaces ge-0/0/2" + _INACTIVE,
        "inactive: interfaces ge-0/0/3" + _INACTIVE,
        "inactive: interfaces ge-0/0/4" + _INACTIVE,
        "inactive: firewall family inet filter OLD" + _INACTIVE,
        "inactive: policy-options prefix-list UNUSED" + _INACTIVE,
        "set firewall family inet filter PROTECT",
        "set security policies",
        "set policy-options policy-statement EXPORT",
        "set policy-options prefix-list EMPTY",
        "set class-of-service",
    ],
)

_pair(
    "a name in quotes, deactivated",
    r"""
system {
    host-name r40;
}
policy-options {
    inactive: policy-statement "direct routes" {
        then accept;
    }
}
""",
    r"""
set system host-name r40
set policy-options policy-statement "direct routes" then accept
deactivate policy-options policy-statement "direct routes"
""",
    hostname="r40", rows=['inactive: policy-options policy-statement "direct routes"' + _INACTIVE],
)

# ---------------------------------------------------------------------------
# A load file.  No device prints these operators; a file handed to
# ``load replace`` or ``load update`` holds them.  A statement under
# ``delete:`` has no set-form twin -- it is not in the config the file
# makes -- so the set form here is that config, and the rows of the
# hierarchical form are typed beside it.
# ---------------------------------------------------------------------------

_pair(
    "replace on a line of its own",
    r"""
system {
    host-name r11;
    login {
        replace:
        class admin {
            permissions [ configure admin-control ];
        }
    }
}
""",
    r"""
set system host-name r11
set system login class admin permissions configure
set system login class admin permissions admin-control
""",
    hostname="r11", rows=[],
)

_pair(
    "inactive on the line above replace",
    r"""
system {
    host-name r12;
}
protocols {
    bgp {
        inactive:
        replace: group G3 {
            type external;
            peer-as 65000;
            neighbor 10.0.0.1;
        }
    }
}
interfaces {
    inactive:
    replace: ge-0/0/3 {
        unit 0 {
            family inet {
                address 10.3.3.1/24;
            }
        }
    }
    ge-0/0/4 {
        unit 0 {
            family inet {
                address 10.4.4.1/24;
            }
        }
    }
}
""",
    r"""
set system host-name r12
set protocols bgp group G3 type external
set protocols bgp group G3 peer-as 65000
set protocols bgp group G3 neighbor 10.0.0.1
deactivate protocols bgp group G3
set interfaces ge-0/0/3 unit 0 family inet address 10.3.3.1/24
deactivate interfaces ge-0/0/3
set interfaces ge-0/0/4 unit 0 family inet address 10.4.4.1/24
""",
    hostname="r12", interfaces={"ge-0/0/4": ["10.4.4.1/24"]}, absent=["ge-0/0/3", "inactive:", "replace:"],
    rows=["inactive: protocols bgp group G3" + _INACTIVE, "inactive: interfaces ge-0/0/3" + _INACTIVE],
)

_pair(
    "delete, active and unprotect",
    r"""
system {
    replace: host-name "r13";
}
interfaces {
    xe-0/0/0 {
        delete: unit 0 {
            family inet {
                address 10.17.0.1/24;
            }
        }
        unit 1 {
            family inet {
                address 10.17.1.1/24;
            }
        }
    }
    active: xe-0/0/1 {
        unit 0 {
            family inet {
                address 10.17.2.1/24;
            }
        }
    }
    unprotect: xe-0/0/2 {
        mtu 9000;
    }
    delete: xe-0/0/3 {
        mtu 1500;
    }
}
delete: snmp;
""",
    r"""
set system host-name r13
set interfaces xe-0/0/0 unit 1 family inet address 10.17.1.1/24
set interfaces xe-0/0/1 unit 0 family inet address 10.17.2.1/24
set interfaces xe-0/0/2 mtu 9000
""",
    hostname="r13", interfaces={"xe-0/0/0.1": ["10.17.1.1/24"], "xe-0/0/1": ["10.17.2.1/24"], "xe-0/0/2": []},
    absent=["xe-0/0/3", "active:", "delete:", "unprotect:", "replace:"], mtus={"xe-0/0/2": 8986},
    only_printed_rows=[
        "delete: interfaces xe-0/0/0 unit 0" + _DELETED,
        "delete: interfaces xe-0/0/3" + _DELETED,
        "delete: snmp" + _DELETED,
    ],
)

NAMES = sorted(PAIRS)


def _parse(text: str):
    return get_codec("juniper_junos").parse(text)


def _lines(text: str, verb: str) -> list[list[str]]:
    """The lines of *text* that begin with *verb*, each as its words,
    in order of the words: how a line is quoted and where it stands
    are the writer's."""
    return sorted(shlex.split(line) for line in text.splitlines() if line.startswith(verb + " "))


def test_there_are_pairs() -> None:
    """A table that came out empty would pass every test below."""
    assert len(NAMES) > 30
    assert all(printed.strip() and as_set.strip() for printed, as_set, _holds in PAIRS.values())


@pytest.mark.parametrize("name", NAMES)
def test_each_form_is_taken_for_what_it_is(name: str) -> None:
    printed, as_set, _holds = PAIRS[name]
    assert _looks_like_blockform(printed)
    assert not _looks_like_blockform(as_set)


@pytest.mark.parametrize("name", NAMES)
def test_both_forms_give_one_tree(name: str) -> None:
    printed, as_set, holds = PAIRS[name]
    from_printed, from_set = _parse(printed).model_dump(), _parse(as_set).model_dump()
    if "only_printed_rows" in holds:
        assert from_printed.pop("dropped_tier3_sections") == holds["only_printed_rows"]
        assert from_set.pop("dropped_tier3_sections") == []
    assert from_printed == from_set


@pytest.mark.parametrize("name", NAMES)
def test_the_lines_are_those_typed_by_hand(name: str) -> None:
    """Every ``set`` line the hierarchical form is written as, against
    the set form typed out: a block that was cut, or a comment read as
    a statement, is a line too few or too many here whatever the tree
    makes of it."""
    printed, as_set, holds = PAIRS[name]
    written = _blockform_to_setform(printed)
    if "only_printed_rows" in holds:
        # What is under ``delete:`` is written too, with a
        # ``deactivate`` line for the reader to leave it out by; the
        # hand form has neither.
        assert all(line in _lines(written, "set") for line in _lines(as_set, "set"))
        assert len(_lines(written, "deactivate")) == len(holds["only_printed_rows"])
        return
    assert _lines(written, "set") == _lines(as_set, "set")
    assert len(_lines(written, "deactivate")) == len(_lines(as_set, "deactivate"))


@pytest.mark.parametrize("form", ["printed", "set"])
@pytest.mark.parametrize("name", NAMES)
def test_the_tree_holds_what_the_text_says(name: str, form: str) -> None:
    printed, as_set, holds = PAIRS[name]
    tree = _parse(printed if form == "printed" else as_set)
    by_name = {iface.name: iface for iface in tree.interfaces}
    for key, value in holds.items():
        if key == "hostname":
            assert tree.hostname == value
        elif key == "version":
            assert tree.source_version == value
        elif key == "interfaces":
            assert {
                port: [f"{a.ip}/{a.prefix_length}" for a in by_name[port].ipv4_addresses] for port in value
            } == value, sorted(by_name)
        elif key == "absent":
            assert not [port for port in value if port in by_name], sorted(by_name)
        elif key == "descriptions":
            assert {port: by_name[port].description for port in value} == value
        elif key == "mtus":
            # The tree's MTU is the payload: a port's media MTU less its
            # Ethernet header (``MTU_BEYOND_THE_PAYLOAD``).
            assert {port: by_name[port].mtu for port in value} == value
        elif key == "enabled":
            assert {port: by_name[port].enabled for port in value} == value
        elif key == "users":
            assert {user.name: user.hashed_password for user in tree.local_users} == value
        elif key == "dns":
            assert tree.dns_servers == value
        elif key == "ntp":
            assert tree.ntp_servers == value
        elif key == "community":
            assert tree.snmp is not None and tree.snmp.community == value
        elif key == "groups":
            assert tree.apply_groups == value
        elif key == "routes":
            assert [(route.destination, route.gateway) for route in tree.static_routes] == value
        elif key == "vlans":
            assert {
                vlan.id: [f"{a.ip}/{a.prefix_length}" for a in vlan.ipv4_addresses] for vlan in tree.vlans
            } == value
        elif key == "lags":
            assert {lag.name: lag.members for lag in tree.lags} == value
        elif key == "rows":
            assert tree.dropped_tier3_sections == value
        elif key == "only_printed_rows":
            assert tree.dropped_tier3_sections == (value if form == "printed" else [])
        else:  # a fact nothing reads is a fact nothing checks
            raise AssertionError(f"{name}: no check for {key!r}")
