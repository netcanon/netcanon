"""A LAG is written as what the ports it faces are configured for.

What a LAG's ``mode`` (:class:`~netcanon.migration.canonical.intent.CanonicalLAG`)
decides on the wire is what the PEER has to be: an LACP partner, a static
aggregate of its own, or nothing at all.  The tree holds four values:

==================  ==================================================
``active``          LACP, active.
``passive``         LACP, passive.
``static``          A static aggregate: no LACP, frames hashed over
                    every member, and the peer's ports grouped as an
                    aggregate of their own (Cisco ``mode on``).
``active-backup``   A bond that needs no aggregate on its peer: Linux
                    ``active-backup`` and FreeBSD ``failover``, which
                    send through one port at a time, and Linux
                    ``balance-tlb`` and ``balance-alb``, which balance
                    what they send without the switch's help.
==================  ==================================================

Every switch parser reads ``static`` from the platform's static aggregate:
``channel-group ... mode on``, an AOS-S ``trunk``, an AOS-CX ``interface
lag`` with no ``lacp mode``, a Junos ``ae`` with no ``lacp``, a FortiOS
``lacp-mode static``.  The hosts that bond ports have both kinds, and the
kernel documentation says which is which: "The active-backup, balance-tlb
and balance-alb modes do not require any specific configuration of the
switch", while balance-rr, balance-xor and broadcast "generally require
that the switch have the appropriate ports grouped together" (Linux
bonding, Switch Configuration).  FreeBSD's ``failover`` sends through one
port and by default accepts what arrives on that port only; its
``loadbalance`` and ``fec`` are "a static setup" (lagg(4)).

Up to 2026-11 the RouterOS, VyOS and OPNsense parsers read the two kinds
as one value, ``static``, and their renderers wrote that value as a bond
that needs no aggregate: ``active-backup``, ``failover``, and on VyOS no
``mode`` line at all, which is ``802.3ad`` (VyOS's default).  A switch's
static port-channel came out on a router as a bond that drops what its
peer hashes onto the second port, in jobs that said ``completed``.

The rule
--------
A parser reads a bond that needs no aggregate on its peer as
``active-backup``, and every other bond without LACP as ``static``.  A
renderer writes ``static`` as its platform's static aggregate
(RouterOS ``balance-xor``, VyOS ``xor-hash``, OPNsense ``loadbalance``)
and ``active-backup`` as its own form of it where it has one
(:attr:`~netcanon.migration.codecs.base.CodecBase.active_backup_written_as`).
A switch has no bond of that kind: it writes the LAG as a static
aggregate, which its peer then has to be configured as, with a review
line beside it (:func:`active_backup_review`) and a warning in the job
(:func:`active_backup_warnings`).
"""

from __future__ import annotations

from collections.abc import Iterable

#: The tree's word for a bond whose peer needs no aggregate.
ACTIVE_BACKUP = "active-backup"


def active_backup_review(lag_name: str) -> str:
    """The text of the review line a target with no active-backup bond
    writes beside such a LAG, without the target's comment marker.

    Args:
        lag_name: The LAG's name as the output writes it.

    Returns:
        One line, beginning ``review:``.
    """
    return (
        f"review: {lag_name} is a bond in the source that needs no "
        "aggregate of its peer ports (active-backup or the like); this "
        "platform has no such bond, and it is written as a static "
        "aggregate, which its peer must be configured as"
    )


def active_backup_warnings(lags: Iterable[object]) -> list[str]:
    """The job's warnings for each active-backup LAG a target writes as
    a static aggregate.

    Args:
        lags: The tree's LAGs (records with ``name`` and ``mode``).

    Returns:
        One sentence for each LAG whose mode is :data:`ACTIVE_BACKUP`.
    """
    return [
        f"LAG {getattr(lag, 'name', '')}: a bond in the source that "
        "needs no aggregate of its peer ports (active-backup or the "
        "like); the target has no such bond, and it is written as a "
        "static aggregate, which its peer must be configured as."
        for lag in lags
        if getattr(lag, "mode", None) == ACTIVE_BACKUP
    ]
