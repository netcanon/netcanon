# Banner + CLI-only directives — what gets stripped going to NETCONF

The biggest qualitative gap between IOS-XE CLI and OpenConfig NETCONF
is that CLI carries a long tail of **operator-typed text** that has
no OpenConfig representation.  This file enumerates the canonical
fields where CLI source is structurally richer than the OpenConfig
target.

## Banner (motd / login / exec / incoming)

CLI form:

```
banner motd ^
*** Authorised access only ***
*** Disconnect immediately if you are not an authorised user ***
^
banner login ^
*** Login banner ***
^
```

The native YANG `Cisco-IOS-XE-native` model carries banner text via
its `banner` container (motd / login / exec / prompt-timeout
sub-containers).  Source: [Cisco-IOS-XE-native.yang vendor model —
YangModels GitHub](https://github.com/YangModels/yang/blob/main/vendor/cisco/xe/1761/Cisco-IOS-XE-native.yang)
(retrieved 2026-04-30).

OpenConfig has no banner model — `openconfig-system` covers DNS, NTP,
clock, logging, AAA, but not banner motd.  An OpenConfig-only NETCONF
codec strips the banner entirely.

The canonical intent tree in this repository **does not model
banners** — there is no `CanonicalIntent.banner_motd` field — so
banner text is dropped on parse by the CLI codec already.  The text
survives in `raw_sections` (Tier-3 informational) on parse but does
not auto-render on either side.

Cross-pair disposition: `not_applicable` (the canonical tree has no
slot, so neither direction "loses" anything beyond what's already
absent from the model).

## `service timestamps`

CLI form:

```
service timestamps debug datetime msec localtime show-timezone
service timestamps log datetime msec localtime show-timezone
```

Cisco-IOS-XE-native models this; OpenConfig has no equivalent.  The
canonical tree does not model it either.  Same disposition as banner:
`not_applicable`.

## EXEC commands and ordering directives

CLI ordering matters in places (e.g. ACL line numbers, route-map
sequence numbers, BGP neighbor activation order).  NETCONF YANG-tree
serialisation collapses to whatever the model's list-key dictates;
operator-typed ordering hints (`!` separators, blank lines, top-of-
file comments) are stripped on parse-and-re-render through any YANG
codec.

Concretely lost when going CLI -> NETCONF:

* `! Last configuration change at 14:23:45 PST Mon Apr 30 2026`
  comment lines
* `!` stanza separators (purely visual)
* Inter-stanza blank lines
* Operator-comment lines starting with `!` followed by free text
* `do show ...` debug echoes
* End-of-config `end` marker

None of these are in the canonical tree; the CLI codec already
strips them on parse.  Disposition for the CLI -> NETCONF cross-
pair: not modelled = `not_applicable`.

## ACLs / route-maps / crypto / QoS / class-map

CLI form is rich; OpenConfig models exist (`openconfig-acl`,
`openconfig-routing-policy`, `openconfig-qos`) but the codec in this
repository does not wire them.  The CLI codec also does not parse
them — see its own docstring:

> "Routing protocols (BGP/OSPF), ACLs, crypto, AAA-policy, QoS, and
> route-maps are silently skipped on parse and not emitted on render
> — out of canonical scope."

Disposition for these surfaces: `not_applicable` on both directions
of the cross-pair (out of canonical scope on both codecs).

## Summary

The **CLI is structurally richer than the OpenConfig stub** in this
repository, but the **canonical intent model is the gating
constraint** — fields not modelled in `CanonicalIntent` are dropped
on the CLI parser already, so the cross-pair "loss" is invisible in
the validation report.  This is a feature, not a bug: the canonical
model was designed for cross-vendor portability, so vendor-specific
presentation (banners, comments, EXEC echoes) is intentionally
out of scope.
