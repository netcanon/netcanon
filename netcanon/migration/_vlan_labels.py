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

A target whose VLAN is called by its name
(``CodecBase.vlans_have_only_a_name``: ``vlan 10`` / ``name X`` on
IOS-XE, NX-OS, EOS and AOS-S, ``set vlans X`` on Junos, the one
``description`` of an OS10 ``interface vlan``) wrote that interface
name, and the label was lost: after OPNsense's VLAN was named after
its device, ``USER VLAN`` came out as ``name vlan0.10`` on IOS-XE.
So on such a target the label is the name, where the name is only an
interface name or empty.  A name the config chose for the VLAN itself
is kept (an AOS-CX ``name``), and its label is lost there, as each
matrix declares -- save on Junos, which writes it beside the name
(``set vlans X description``).

Applied twice, to the same effect: by ``run_plan`` right after the
parse, before the port translator renames the interface the name
matches -- after it, ``vlan0.10`` names no interface of the tree --
and at the render boundary (``CodecBase``), for a caller that renders
a parsed tree with no pipeline (the cross-mesh audit).  The second is
a no-op on a tree the first has seen.  The label is MOVED: the
description is emptied, so the validation report does not count it
lost, and the name it replaces is the name of an interface that still
has it.

A target whose VLAN IS an interface (RouterOS ``/interface vlan``,
FortiOS ``set type vlan``) names it as an interface and labels it as
one, with ``comment=`` or ``set alias``.  Its renderer writes the
interface's own description there and, where the interface states
none, the VLAN's label (:func:`vlan_labels`); where the interface has a
description of its own, the label is written in a review line beside
it.  The renderer asks after the port translator, which renames the
interface and leaves the VLAN's name as it was, so "the name is an
interface's" cannot be read from the tree there: it is read from the
platform the tree was parsed from (``NAMES_A_VLAN_AFTER_ITS_INTERFACE``).
"""

from __future__ import annotations

from collections.abc import Set as AbstractSet
from typing import Any

from .canonical.intent import CanonicalIntent, CanonicalVlan

#: The platforms (``CanonicalIntent.source_vendor``) whose parser names
#: every VLAN after the interface it is defined on: OPNsense after its
#: device (``vlan0.10``), RouterOS and FortiOS after the VLAN
#: interface.  On their trees a VLAN's name is never a label, though
#: once the port translator has renamed the interface it is the name of
#: none.  Measured, not assumed: ``test_a_vlan_label_on_its_interface.py``
#: holds the set equal to the parsers that do so on the committed
#: captures.
NAMES_A_VLAN_AFTER_ITS_INTERFACE = frozenset({
    "fortigate", "mikrotik_routeros", "opnsense",
})


def vlan_labels(tree: CanonicalIntent) -> dict[int, str]:
    """What the config calls each VLAN of *tree*, apart from an
    interface's name, by VLAN id.

    A VLAN's name, where the config chose one: not empty, not the name
    of an interface of *tree*, and from a platform that does not name
    a VLAN after its interface.  Otherwise its description.  A VLAN
    with both a name and a description of its own (AOS-CX) is called
    by its name; its description is lost on a target with one label,
    as that target's matrix declares.  The first VLAN of an id is the
    one asked, as the renderers find a VLAN by its id.

    Args:
        tree: The tree being rendered, after any transform.

    Returns:
        ``{VLAN id: label}``, the label ``""`` where a VLAN has none.
    """
    names = {iface.name for iface in tree.interfaces}
    named_after_one = tree.source_vendor in NAMES_A_VLAN_AFTER_ITS_INTERFACE
    labels: dict[int, str] = {}
    for vlan in tree.vlans:
        if vlan.id in labels:
            continue
        if vlan.name.strip() and not named_after_one and vlan.name not in names:
            labels[vlan.id] = vlan.name
        elif vlan.description.strip():
            labels[vlan.id] = vlan.description
        else:
            labels[vlan.id] = ""
    return labels


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
