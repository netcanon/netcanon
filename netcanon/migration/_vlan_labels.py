"""A VLAN's label, where the target has a name and nothing else.

A VLAN is stated with a name and, on some platforms, a label apart
from it: OPNsense names its VLAN device ``vlan0.10`` and labels it
``<descr>``; RouterOS names the VLAN interface and labels it
``comment=``; AOS-CX has a ``name`` and a ``description``.  The tree
holds the two as ``CanonicalVlan.name`` and ``.description``.  Where
the name is only the name of an interface of the config, or there is
none, the name says nothing an operator chose for the VLAN: OPNsense
and RouterOS name the VLAN after the interface the tag is defined on,
so that their renderers (and FortiOS's) find the tag by it.

A target whose VLAN has a name and nothing else
(``CodecBase.vlans_have_only_a_name``: ``vlan 10`` / ``name X`` on
IOS-XE, NX-OS, EOS and AOS-S, ``set vlans X`` on Junos) wrote that
interface name, and the label was lost: after OPNsense's VLAN was
named after its device, ``USER VLAN`` came out as ``name vlan0.10``
on IOS-XE.
So on such a target the label is the name, where the name is only an
interface name or empty.  A name the config chose for the VLAN itself
is kept (an AOS-CX ``name``), and its label is lost there, as each
matrix declares.

Applied twice, to the same effect: by ``run_plan`` right after the
parse, before the port translator renames the interface the name
matches -- after it, ``vlan0.10`` names no interface of the tree --
and at the render boundary (``CodecBase``), for a caller that renders
a parsed tree with no pipeline (the cross-mesh audit).  The second is
a no-op on a tree the first has seen.  The label is MOVED: the
description is emptied, so the validation report does not count it
lost, and the name it replaces is the name of an interface that still
has it.
"""

from __future__ import annotations

from collections.abc import Set as AbstractSet
from typing import Any

from .canonical.intent import CanonicalIntent, CanonicalVlan


def label_is_its_name(vlan: CanonicalVlan, interface_names: AbstractSet[str]) -> bool:
    """Whether *vlan*'s label is to be written as its name.

    Args:
        vlan: The VLAN.
        interface_names: The name of every interface of its tree.

    Returns:
        ``True`` where the VLAN has a label (a description that is not
        blank and is not its name) and its name is empty or the name of
        an interface of the tree.
    """
    if not vlan.description.strip() or vlan.description == vlan.name:
        return False
    return not vlan.name.strip() or vlan.name in interface_names


def vlan_labels_as_names(tree: Any) -> Any:
    """*tree* with each VLAN's label as its name, where
    :func:`label_is_its_name` says so.

    Never changes *tree*: where a VLAN is changed, the result is a
    copy with a new VLAN list (the cross-mesh audit compares the tree
    it rendered with what came back).  A tree that is not a
    :class:`CanonicalIntent`, or that has no such VLAN, is returned as
    it is.

    Args:
        tree: A parsed tree.

    Returns:
        The tree to render.
    """
    if not isinstance(tree, CanonicalIntent) or not tree.vlans:
        return tree
    names = {iface.name for iface in tree.interfaces}
    if not any(label_is_its_name(vlan, names) for vlan in tree.vlans):
        return tree
    return tree.model_copy(update={"vlans": [
        vlan.model_copy(update={"name": vlan.description, "description": ""})
        if label_is_its_name(vlan, names) else vlan
        for vlan in tree.vlans
    ]})
