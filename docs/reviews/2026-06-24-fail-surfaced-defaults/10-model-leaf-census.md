# 10 — Canonical-model leaf census (the shared denominator)

**Agent:** `10-model-leaf-census` · Phase 1 (Census) · read-only
**Run:** 2026-06-24 · fail-surfaced-defaults · netcanon
**Scope:** the COMPLETE leaf set of `CanonicalIntent`, the denominator both
gap analyses (`11-walker-gap`, `12-sanitizer-gap`) depend on.

---

## 0. Method & conventions

- Source of truth read end-to-end: `netcanon/migration/canonical/intent.py`
  (17 model classes, root `CanonicalIntent`, lines 1–931).
- Xpath spelling taken from the **walker** (`netcanon/migration/canonical/
  xpath_walker.py`, `_walk_canonical`, lines 23–256) and confirmed against
  the per-codec capability matrices (e.g. `cisco_iosxe_cli/codec.py:106–260`)
  and the honesty-floor guard `tests/unit/migration/codecs/cisco_iosxe_cli/
  test_walk_canonical_coverage.py`. `CapabilityMatrix.classify` is
  exact-string-match, so the matrix/walker/census must speak the same strings.
- **Naming rule observed in the codebase:** python field `snake_case` →
  xpath segment `kebab-case`; nested models collapse to a hyphenated leaf
  (e.g. `CanonicalLAG.mode` → `/lags/lag/mode`); container plurals keep the
  `container/element` shape (`/interfaces/interface/...`, `/vlans/vlan/...`,
  `/routing-instances/instance/...`). System scalars/lists live under
  `/system/...`. A few list leaves are spelled singular at the element
  (`/system/dns-server` for `dns_servers`).
- Where the walker does NOT yet emit an xpath for a real model leaf, I give
  the **projected** xpath in the prevailing convention and mark it
  `WALKED = no`. Those projected spellings are the candidate strings a
  walk-everything design (class 1) would have to emit and the matrices would
  have to declare; agents 11/20 own that gap. Here they are census rows.

### Column legend

- **xpath** — schema xpath in the walker's convention (projected where the
  walker does not emit it; flagged in WALKED).
- **Class.field** — owning pydantic `Model.attribute`.
- **type** — python type hint as written (post `from __future__ import
  annotations`, all hints are strings; resolved type given).
- **default** — declared default (`Field(...)` default / literal / factory).
- **kind** — `scalar` / `list[scalar]` / `list[model]` (container) /
  `nested-model` / `dict`.
- **IP/HOST** — `IP_OR_HOST_BEARING`: the field can hold an IPv4/IPv6
  literal, a CIDR, a MAC, or a DNS hostname/domain (anything that identifies
  a real network or host). MAC is included because the sanitizer treats
  `anycast_gateway_mac`/`virtual_gateway_mac` as network-identifying-class.
- **SECRET** — `SECRET_BEARING`: passphrase / hash / community / shared key /
  auth token / engineID.
- **WALKED** — does `_walk_canonical` currently emit this xpath? (`yes` /
  `no` / `cond` = yes but only under a populated/condition guard).

> A leaf is counted once. Where the same canonical sub-model is reused on
> two parents (e.g. `CanonicalIPv4Address` on both `CanonicalInterface` and
> `CanonicalVlan`), it is listed under **both** parents because they have
> distinct xpaths and distinct codec handling — this is load-bearing for
> both gaps (the VLAN-SVI L3 leak #175 was exactly this reuse).

---

## 1. Top-level `CanonicalIntent` scalars / lists (intent.py:790–930)

| xpath | Class.field | type | default | kind | IP/HOST | SECRET | WALKED |
|---|---|---|---|---|---|---|---|
| `/system/hostname` | `CanonicalIntent.hostname` | str | `""` | scalar | yes¹ | no | cond |
| `/system/domain` | `CanonicalIntent.domain` | str | `""` | scalar | **yes** | no | cond |
| `/system/dns-server` | `CanonicalIntent.dns_servers` | list[str] | `[]` | list[scalar] | **yes** | no | cond |
| `/system/ntp-server` | `CanonicalIntent.ntp_servers` | list[str] | `[]` | list[scalar] | **yes** | no | cond |
| `/system/timezone` | `CanonicalIntent.timezone` | str | `""` | scalar | no | no | cond |
| `/system/syslog-server` | `CanonicalIntent.syslog_servers` | list[str] | `[]` | list[scalar] | **yes** | no | cond |
| `/anycast-gateway-mac` | `CanonicalIntent.anycast_gateway_mac` | str | `""` | scalar | **yes (MAC)** | no | cond |
| `raw_sections` | `CanonicalIntent.raw_sections` | dict[str,str] | `{}` | dict | **yes²** | **yes²** | no (Tier-3, not walked by design) |
| `dropped_tier3_sections` | `CanonicalIntent.dropped_tier3_sections` | list[str] | `[]` | list[scalar] | maybe² | no | no (notify-only) |
| `source_vendor` | `CanonicalIntent.source_vendor` | str | `""` | scalar (metadata) | no | no | no (metadata) |
| `source_format` | `CanonicalIntent.source_format` | str | `""` | scalar (metadata) | no | no | no (metadata) |
| `source_version` | `CanonicalIntent.source_version` | str | `""` | scalar (metadata) | no | no | no (metadata) |
| `apply_groups` | `CanonicalIntent.apply_groups` | list[str] | `[]` | list[scalar] | maybe² | no | no (provenance) |
| `group_content` | `CanonicalIntent.group_content` | dict[str,list[list[str]]] | `{}` | dict | **yes²** | **yes²** | no (provenance) |

¹ `hostname` is a host identifier (operator-traceable PII per AGENTS.md Hard
Rules) but the sanitizer does NOT redact it today — it is *passthrough*. I
mark IP/HOST=yes¹ because it is host-identifying even though it is not an
`ip_address()`-parseable string; a blanket `ip_address()` rule would NOT
catch it, which is a finding for agent 12 (free-text host identity escapes
an IP-only rule). It is not in this run's two named classes but is the same
disease shape.

² **Container/free-text leaves (`raw_sections`, `group_content`,
`dropped_tier3_sections`, `apply_groups`):** these hold *raw vendor config
text* / group set-line tails / stanza headers. They can contain ANYTHING —
IPs, hostnames, hashes — embedded in free text. The sanitizer DOES handle
the first three (`raw_sections`/`dropped_tier3_sections`/`group_content`/
`apply_groups` are stripped wholesale, categories `tier3-stripped` /
`apply-groups-stripped`, sanitize.py:683–787). They are **not** model
*leaves* in the structured sense (no typed scalar field), so a
type-driven/`ip_address()` enumeration (class-2 design C / blanket A) would
NOT reach inside them — they need their existing wholesale-strip handling.
**Census note for agents 20/22:** these are the leaves that defeat a
"reflect over typed scalar fields" guard; they must be an explicit,
self-justifying exemption (already strip-handled) in any completeness guard.

---

## 2. `CanonicalInterface` (intent.py:168–281) — element of `/interfaces/interface`

Scalars + nested lists. Container leaf: `/interfaces/interface/name` is the
list-element anchor.

| xpath | Class.field | type | default | kind | IP/HOST | SECRET | WALKED |
|---|---|---|---|---|---|---|---|
| `/interfaces/interface/name` | `.name` | str | (required) | scalar | no | no | cond |
| `/interfaces/interface/default-name` | `.default_name` | str | `""` | scalar | no | no | **no** |
| `/interfaces/interface/config/description` | `.description` | str | `""` | scalar | no³ | no | cond |
| `/interfaces/interface/config/enabled` | `.enabled` | bool | `True` | scalar | no | no | cond (always, per-iface) |
| `/interfaces/interface/config/type` | `.interface_type` | str | `""` | scalar | no | no | cond |
| `/interfaces/interface/config/mtu` | `.mtu` | int \| None | `None` | scalar | no | no | cond |
| `/interfaces/interface/switchport-mode` | `.switchport_mode` | str \| None | `None` | scalar | no | no | cond |
| `/interfaces/interface/access-vlan` | `.access_vlan` | int \| None | `None` | scalar | no | no | cond |
| `/interfaces/interface/trunk-allowed-vlans` | `.trunk_allowed_vlans` | list[int] | `[]` | list[scalar] | no | no | cond |
| `/interfaces/interface/trunk-native-vlan` | `.trunk_native_vlan` | int \| None | `None` | scalar | no | no | cond |
| `/interfaces/interface/voice-vlan` | `.voice_vlan` | int \| None | `None` | scalar | no | no | cond |
| `/interfaces/interface/lag-member-of` | `.lag_member_of` | str \| None | `None` | scalar | no | no | cond |
| `/interfaces/interface/dhcp-client` | `.dhcp_client` | bool | `False` | scalar | no | no | cond |
| `/interfaces/interface/dhcp-client-v6` | `.dhcp_client_v6` | str | `""` | scalar | no | no | cond |
| `/interfaces/interface/tunnel-type` | `.tunnel_type` | str | `""` | scalar | no | no | cond |
| `/interfaces/interface/config/vrf` | `.vrf` | str | `""` | scalar | no | no | cond |
| `/interfaces/interface/kind` | `.kind` | str | `""` | scalar | no | no | **no** |
| (sub-models below) | `.ipv4_addresses` | list[`CanonicalIPv4Address`] | `[]` | list[model] | — | — | — |
| (sub-models below) | `.ipv6_addresses` | list[`CanonicalIPv6Address`] | `[]` | list[model] | — | — | — |
| (sub-models below) | `.vrrp_groups` | list[`CanonicalVRRPGroup`] | `[]` | list[model] | — | — | — |

³ `description` is operator free text. Not IP-bearing as a class, BUT free
text CAN contain an IP-like substring or hostname (the VLAN-name/description
case #133 was exactly this). Flagged `no³` here because it is not a
structurally IP-typed field — this is the precise category agent 12 must
evaluate for the over-redaction risk of a blanket `ip_address()` rule (a
description like `"link to 10.0.0.1 core"` would partial-match). The
sanitizer does NOT touch interface `description` today.

**Two un-walked interface scalars:** `default-name` and `kind`. Both are
opaque vendor-mechanical strings (MikroTik factory port name; logical-role
override). Neither is IP/secret-bearing. They are silent-loss *candidates*
in the strict sense (a codec could drop them and `classify()` would say ok),
but they are low-risk metadata. Agent 11 should confirm whether any codec
populates them (e.g. mikrotik `default_name`); they are census rows here.

### 2a. `CanonicalIPv4Address` (intent.py:83–124) — on interface AND vlan

| xpath (interface) | Class.field | type | default | kind | IP/HOST | SECRET | WALKED |
|---|---|---|---|---|---|---|---|
| `/interfaces/interface/ipv4/address/ip` | `.ip` | str | (required) | scalar | **yes** | no | cond |
| `/interfaces/interface/ipv4/address/prefix-length` | `.prefix_length` | int (ge0 le32) | (required) | scalar | no | no | cond |
| `/interfaces/interface/ipv4/address/secondary-ip` | `.is_secondary` | bool | `False` | scalar | no | no | cond (only when secondary) |
| `/interfaces/interface/ipv4/address/virtual-gateway-address` | `.virtual_gateway_address` | str | `""` | scalar | **yes** | no | cond |
| `/interfaces/interface/ipv4/address/virtual-gateway-mac` | `.virtual_gateway_mac` | str | `""` | scalar | **yes (MAC)** | no | cond |

Same model reused on the VLAN record (distinct xpath, distinct handling — the
#175 leak surface):

| xpath (vlan SVI) | Class.field | type | default | kind | IP/HOST | SECRET | WALKED |
|---|---|---|---|---|---|---|---|
| `/vlans/vlan/ipv4/address/ip` | `.ip` | str | (required) | scalar | **yes** | no | cond |
| `/vlans/vlan/ipv4/address/prefix-length` | `.prefix_length` | int | (required) | scalar | no | no | **no** ⚠ |
| `/vlans/vlan/ipv4/address/secondary-ip` | `.is_secondary` | bool | `False` | scalar | no | no | **no** |
| `/vlans/vlan/ipv4/address/virtual-gateway-address` | `.virtual_gateway_address` | str | `""` | scalar | **yes** | no | **no** ⚠ |
| `/vlans/vlan/ipv4/address/virtual-gateway-mac` | `.virtual_gateway_mac` | str | `""` | scalar | **yes (MAC)** | no | **no** |

⚠ The walker yields only `/vlans/vlan/ipv4/address/ip` (xpath_walker.py:178–
179) for the VLAN-SVI address. `prefix-length`, `secondary-ip`,
`virtual-gateway-address`, `virtual-gateway-mac` on the **VLAN** copy are
NOT walked — the walker walks `ip` only there (the #175 fix walked just the
`ip` leaf). The interface copy walks the full set (xpath_walker.py:82–101).
This is an asymmetry worth flagging to agents 11/20 (the VLAN-SVI VGA is a
real anycast surface on Aruba/Junos IRB). The **sanitizer** DOES redact the
VLAN copy's `ip` + `virtual_gateway_address` (sanitize.py:406–427), so the
sanitizer is ahead of the walker here.

### 2b. `CanonicalIPv6Address` (intent.py:127–165) — on interface only

| xpath | Class.field | type | default | kind | IP/HOST | SECRET | WALKED |
|---|---|---|---|---|---|---|---|
| `/interfaces/interface/ipv6/address/ip` | `.ip` | str | (required) | scalar | **yes** | no | cond |
| `/interfaces/interface/ipv6/address/prefix-length` | `.prefix_length` | int (ge0 le128) | (required) | scalar | no | no | cond |
| `/interfaces/interface/ipv6/address/scope` | `.scope` | str | `"global"` | scalar | no | no | **no** |
| `/interfaces/interface/ipv6/address/secondary-ip` | `.is_secondary` | bool | `False` | scalar | no | no | cond (only when secondary) |
| `/interfaces/interface/ipv6/address/virtual-gateway-address` | `.virtual_gateway_address` | str | `""` | scalar | **yes** | no | cond |
| `/interfaces/interface/ipv6/address/virtual-gateway-mac` | `.virtual_gateway_mac` | str | `""` | scalar | **yes (MAC)** | no | cond |

`scope` (`"global"`/`"link-local"`) is NOT walked — discriminator string,
not IP/secret. Census row; low risk. (`CanonicalIPv6Address` is NOT reused on
the VLAN record — only IPv4 is, per `CanonicalVlan.ipv4_addresses`.)

### 2c. `CanonicalVRRPGroup` (intent.py:491–597) — on `/interfaces/interface/vrrp-groups/group`

| xpath | Class.field | type | default | kind | IP/HOST | SECRET | WALKED |
|---|---|---|---|---|---|---|---|
| `/interfaces/interface/vrrp-groups/group` | `.group_id` | int (ge1 le255) | (required) | scalar (anchor) | no | no | cond |
| `/interfaces/interface/vrrp-groups/group/mode` | `.mode` | str | `"vrrp"` | scalar | no | no | **no** |
| `/interfaces/interface/vrrp-groups/group/virtual-ips` | `.virtual_ips` | list[str] | `[]` | list[scalar] | **yes** | no | cond (only when >1) ⚠ |
| `/interfaces/interface/vrrp-groups/group/virtual-ipv6s` | `.virtual_ipv6s` | list[str] | `[]` | list[scalar] | **yes** | no | **no** ⚠ |
| `/interfaces/interface/vrrp-groups/group/virtual-mac` | `.virtual_mac` | str | `""` | scalar | **yes (MAC)** | no | cond |
| `/interfaces/interface/vrrp-groups/group/priority` | `.priority` | int (1-254) | `100` | scalar | no | no | **no** |
| `/interfaces/interface/vrrp-groups/group/preempt` | `.preempt` | bool | `True` | scalar | no | no | **no** |
| `/interfaces/interface/vrrp-groups/group/advertisement-interval` | `.advertisement_interval` | int | `1` | scalar | no | no | **no** |
| `/interfaces/interface/vrrp-groups/group/authentication` | `.authentication` | str | `""` | scalar | no | **yes** | **no** ⚠SECRET |
| `/interfaces/interface/vrrp-groups/group/track-interfaces` | `.track_interfaces` | list[str] | `[]` | list[scalar] | no | no | cond |
| `/interfaces/interface/vrrp-groups/group/description` | `.description` | str | `""` | scalar | no | no | **no** |

⚠ Walker subtlety (xpath_walker.py:146–158): the group anchor is walked
unconditionally per group; `virtual-ips` walked ONLY when `len > 1`;
`virtual-mac` + `track-interfaces` walked only when populated.
`virtual-ipv6s`, `mode`, `priority`, `preempt`, `advertisement-interval`,
`authentication`, `description` are **never** walked. The **sanitizer** DOES
redact `virtual_ips`, `virtual_ipv6s`, `authentication`, and `description`
(sanitize.py:309–368) — again the sanitizer is ahead of the walker on the
secret-bearing `authentication` and on `virtual_ipv6s`. `authentication` is
a **secret-bearing leaf the walker never yields** — a notable census row for
agent 11 (a codec dropping VRRP auth-token would classify `ok`).

---

## 3. `CanonicalVlan` (intent.py:284–298) — element of `/vlans/vlan`

| xpath | Class.field | type | default | kind | IP/HOST | SECRET | WALKED |
|---|---|---|---|---|---|---|---|
| `/vlans/vlan/id` | `.id` | int (ge1 le4094) | (required) | scalar (anchor) | no | no | cond |
| `/vlans/vlan/name` | `.name` | str | `""` | scalar | no³ | no | cond |
| `/vlans/vlan/description` | `.description` | str | `""` | scalar | no³ | no | cond |
| `/vlans/vlan/tagged-ports` | `.tagged_ports` | list[str] | `[]` | list[scalar] | no | no | cond |
| `/vlans/vlan/untagged-ports` | `.untagged_ports` | list[str] | `[]` | list[scalar] | no | no | cond |
| (sub-model) | `.ipv4_addresses` | list[`CanonicalIPv4Address`] | `[]` | list[model] | — | — | see §2a (vlan SVI rows) |

`name`/`description` are operator free text (the #133 / v0.4.0-self-audit
surface). Sanitizer DOES redact VLAN `name` + `description` (sanitize.py:
381–404 area) via a stable substitution table.

---

## 4. `CanonicalStaticRoute` (intent.py:301–331) — element of `/routing/static-route`

| xpath | Class.field | type | default | kind | IP/HOST | SECRET | WALKED |
|---|---|---|---|---|---|---|---|
| `/routing/static-route` | `.destination` | str (CIDR) | (required) | scalar (anchor) | **yes** | no | cond |
| `/routing/static-route/gateway`⁴ | `.gateway` | str | `""` | scalar | **yes** | no | **no** ⚠IP |
| `/routing/static-route/interface` | `.interface` | str | `""` | scalar | no | no | cond |
| `/routing/static-route/metric` | `.metric` | int | `0` | scalar | no | no | cond |
| `/routing/static-route/description` | `.description` | str | `""` | scalar | no | no | cond |
| `/routing/static-route/vrf` | `.vrf` | str | `""` | scalar | no | no | cond |

⁴ The route **gateway** (next-hop IP) is NOT walked (the walker walks
`/routing/static-route` anchor + `vrf` + `metric` + `description` +
`interface`, xpath_walker.py:180–196, but not a `gateway` leaf). The
**destination** CIDR is the anchor. So the IP-bearing `gateway` is an
un-walked IP leaf — but the **sanitizer** DOES redact it (sanitize.py:660–
669, category `ipv4-public`, private preserved). Projected xpath
`/routing/static-route/gateway` is my best guess at the convention; no
matrix declares it today, so agents 11/20 should treat the spelling as
TBD. (Walking the anchor effectively covers destination+gateway as one
record for loss-classification, which is why no codec has needed the split.)

---

## 5. `CanonicalDHCPPool` (intent.py:339–361) — element of `/dhcp-servers/pool`

The walker yields ONLY the anchor `/dhcp-servers/pool` (xpath_walker.py:215–
216) — every sub-field is unwalked. The sanitizer, however, redacts the IP
sub-fields.

| xpath | Class.field | type | default | kind | IP/HOST | SECRET | WALKED |
|---|---|---|---|---|---|---|---|
| `/dhcp-servers/pool` | (record anchor) | — | — | scalar (anchor) | — | — | cond |
| `/dhcp-servers/pool/interface` | `.interface` | str | `""` | scalar | no | no | **no** |
| `/dhcp-servers/pool/network` | `.network` | str (CIDR) | `""` | scalar | **yes** | no | **no** ⚠IP |
| `/dhcp-servers/pool/start-ip` | `.start_ip` | str | `""` | scalar | **yes** | no | **no** ⚠IP |
| `/dhcp-servers/pool/end-ip` | `.end_ip` | str | `""` | scalar | **yes** | no | **no** ⚠IP |
| `/dhcp-servers/pool/gateway` | `.gateway` | str | `""` | scalar | **yes** | no | **no** ⚠IP |
| `/dhcp-servers/pool/dns-servers` | `.dns_servers` | list[str] | `[]` | list[scalar] | **yes** | no | **no** ⚠IP |
| `/dhcp-servers/pool/lease-time` | `.lease_time` | int | `86400` | scalar | no | no | **no** |
| `/dhcp-servers/pool/domain-name` | `.domain_name` | str | `""` | scalar | **yes (host)** | no | **no** ⚠HOST |

Sanitizer coverage (sanitize.py:578–658): `network` (CIDR host-portion),
`start_ip`, `end_ip`, `gateway`, `dns_servers` (public→docs, private
preserved), `domain_name` (category `domain`). So **5 of the 6 IP/host-
bearing DHCP sub-fields are sanitizer-covered but walker-blind** — a clean
illustration of the two gaps' independence.

---

## 6. SNMP

### 6a. `CanonicalSNMP` (intent.py:450–471) — singleton `/snmp` (nullable)

| xpath | Class.field | type | default | kind | IP/HOST | SECRET | WALKED |
|---|---|---|---|---|---|---|---|
| `/snmp/community` | `.community` | str | `""` | scalar | no | **yes** | cond |
| `/snmp/location` | `.location` | str | `""` | scalar | no | no | cond |
| `/snmp/contact` | `.contact` | str | `""` | scalar | no⁵ | no | cond |
| `/snmp/trap-host` | `.trap_hosts` | list[str] | `[]` | list[scalar] | **yes** | no | cond |
| (sub-model) | `.v3_users` | list[`CanonicalSNMPv3User`] | `[]` | list[model] | — | — | see §6b |

⁵ `contact` is often an email/name (operator PII) — sanitizer redacts it
(category `snmp-contact`, sanitize.py:~480) and `location` (`snmp-location`,
~489). Not IP-bearing; not caught by an `ip_address()` rule. `community` is
the v1/v2c shared secret → sanitizer redacts (`snmp-community`, ~461).

### 6b. `CanonicalSNMPv3User` (intent.py:364–447) — element of `/snmp/v3-user`

| xpath | Class.field | type | default | kind | IP/HOST | SECRET | WALKED |
|---|---|---|---|---|---|---|---|
| `/snmp/v3-user` | `.name` | str | (required) | scalar (anchor) | no | no | cond |
| `/snmp/v3-user/group` | `.group` | str | `""` | scalar | no | no | **no** |
| `/snmp/v3-user/auth-protocol` | `.auth_protocol` | str | `""` | scalar | no | no | **no** |
| `/snmp/v3-user/auth-passphrase` | `.auth_passphrase` | str | `""` | scalar | no | **yes** | cond |
| `/snmp/v3-user/priv-protocol` | `.priv_protocol` | str | `""` | scalar | no | no | **no** |
| `/snmp/v3-user/priv-passphrase` | `.priv_passphrase` | str | `""` | scalar | no | **yes** | **no** ⚠SECRET |
| `/snmp/v3-user/engine-id` | `.engine_id` | str | `""` | scalar | no | **yes** | cond |

⚠ `priv_passphrase` is a **secret-bearing leaf the walker never yields**
(walker walks `/snmp/v3-user` anchor + `auth-passphrase` + `engine-id` only,
xpath_walker.py:209–214). The sanitizer DOES redact `auth_passphrase`,
`priv_passphrase`, `engine_id`, and even the v3 user `name`
(sanitize.py:519–551). So `priv_passphrase` joins VRRP `authentication` as a
secret leaf that is walker-blind. Census row for agent 11.

---

## 7. `CanonicalLAG` (intent.py:474–488) — element of `/lags/lag`

| xpath | Class.field | type | default | kind | IP/HOST | SECRET | WALKED |
|---|---|---|---|---|---|---|---|
| `/lags/lag/name` | `.name` | str | (required) | scalar | no | no | cond |
| `/lags/lag/members` | `.members` | list[str] | `[]` | list[scalar] | no | no | cond |
| `/lags/lag/mode` | `.mode` | str | `"active"` | scalar | no | no | cond |

Fully walked (xpath_walker.py:217–220 — all three yielded per LAG). No
IP/secret. No gap.

---

## 8. `CanonicalLocalUser` (intent.py:600–621) — element of `/local-users/user`

| xpath | Class.field | type | default | kind | IP/HOST | SECRET | WALKED |
|---|---|---|---|---|---|---|---|
| `/local-users/user/name` | `.name` | str | (required) | scalar | no | no | cond |
| `/local-users/user/privilege-level` | `.privilege_level` | int | `1` | scalar | no | no | cond |
| `/local-users/user/hashed-password` | `.hashed_password` | str | `""` | scalar | no | **yes** | cond |
| `/local-users/user/role` | `.role` | str | `""` | scalar | no | no | cond |

Fully walked (xpath_walker.py:221–227). `hashed_password` is secret-bearing
AND walked AND sanitized (sanitize.py:448–456, format-preserving fake hash).
Clean example of a fully-handled secret leaf.

---

## 9. `CanonicalRADIUSServer` (intent.py:624–638) — element of `/radius-servers/server`

| xpath | Class.field | type | default | kind | IP/HOST | SECRET | WALKED |
|---|---|---|---|---|---|---|---|
| `/radius-servers/server/host` | `.host` | str | (required) | scalar | **yes** | no | cond |
| `/radius-servers/server/key` | `.key` | str | `""` | scalar | no | **yes** | cond |
| `/radius-servers/server/auth-port` | `.auth_port` | int | `1812` | scalar | no | no | **no** |
| `/radius-servers/server/acct-port` | `.acct_port` | int | `1813` | scalar | no | no | **no** |

Walker yields `host` + `key` only (xpath_walker.py:228–230). `auth_port` /
`acct_port` unwalked (defaulted ports, low risk). `host` (IP) and `key`
(secret) both sanitized (sanitize.py:558–576).

---

## 10. `CanonicalVxlan` (intent.py:641–692) — element of `/vxlan-vnis`

Note the unusual xpath shape: the matrices/walker spell this `/vxlan-vnis/<leaf>`
(NOT `/vxlan-vnis/vni/<leaf>`), i.e. the record-element segment is implicit.

| xpath | Class.field | type | default | kind | IP/HOST | SECRET | WALKED |
|---|---|---|---|---|---|---|---|
| `/vxlan-vnis/vni` | `.vni` | int (1-16777215) | (required) | scalar (anchor) | no | no | cond |
| `/vxlan-vnis/vlan-id` | `.vlan_id` | int (1-4094) | (required) | scalar | no | no | cond |
| `/vxlan-vnis/mcast-group` | `.mcast_group` | str | `""` | scalar | **yes (mcast IP)** | no | cond |
| `/vxlan-vnis/flood-list` | `.flood_list` | list[str] | `[]` | list[scalar] | **yes (VTEP IPs)** | no | cond |
| `/vxlan-vnis/source-interface` | `.source_interface` | str | `""` | scalar | no | no | cond |
| `/vxlan-vnis/udp-port` | `.udp_port` | int | `4789` | scalar | no | no | cond |

Walker (xpath_walker.py:231–240): `vni`, `udp-port`, `vlan-id` always;
`source-interface`, `mcast-group`, `flood-list` when populated. `mcast_group`
+ `flood_list` are network-identifying and sanitizer-redacted (sanitize.py:
731–746, `redact_mcast_group` + `vtep-flood` — note redact_ipv4 PRESERVES
multicast, so a dedicated `redact_mcast_group` exists). No secret. No gap.

---

## 11. `CanonicalRoutingInstance` (intent.py:695–742) — element of `/routing-instances/instance`

| xpath | Class.field | type | default | kind | IP/HOST | SECRET | WALKED |
|---|---|---|---|---|---|---|---|
| `/routing-instances/instance` | (record anchor) | — | — | scalar (anchor) | no | no | cond |
| `/routing-instances/instance/name` | `.name` | str | (required) | scalar | no | no | cond |
| `/routing-instances/instance/instance-type` | `.instance_type` | str | `"vrf"` | scalar | no | no | **no** |
| `/routing-instances/instance/route-distinguisher` | `.route_distinguisher` | str | `""` | scalar | **yes (RD has IP:nn form)** | no | cond |
| `/routing-instances/instance/rt-imports` | `.rt_imports` | list[str] | `[]` | list[scalar] | **yes (RT)** | no | cond |
| `/routing-instances/instance/rt-exports` | `.rt_exports` | list[str] | `[]` | list[scalar] | **yes (RT)** | no | cond |
| `/routing-instances/instance/description` | `.description` | str | `""` | scalar | no | no | cond |
| `/routing-instances/instance/l3-vni` | `.l3_vni` | int \| None | `None` | scalar | no | no | cond |

Walker (xpath_walker.py:243–255): anchor + name always; description, RD,
rt-imports, rt-exports, l3-vni when populated. `instance_type` unwalked
(defaulted discriminator). RD + RTs are network-identifying (RD/RT can carry
an `<ip>:<nn>` admin field) → sanitizer redacts via `redact_route_target` /
`redact_overlay`-class (sanitize.py:709–728, categories `route-distinguisher`
/ route-target list). No secret. The #162 overlay-ID work covered these.

---

## 12. `CanonicalEvpnType5Route` (intent.py:745–782) — element of `/evpn-type5-routes`

| xpath | Class.field | type | default | kind | IP/HOST | SECRET | WALKED |
|---|---|---|---|---|---|---|---|
| `/evpn-type5-routes/route` | (record anchor) | — | — | scalar (anchor) | — | — | cond |
| `/evpn-type5-routes/route/vrf` | `.vrf` | str | (required) | scalar | no | no | **no** |
| `/evpn-type5-routes/route/prefix` | `.prefix` | str (CIDR) | (required) | scalar | **yes** | no | **no** ⚠IP |
| `/evpn-type5-routes/route/rt-imports` | `.rt_imports` | list[str] | `[]` | list[scalar] | **yes (RT)** | no | **no** ⚠IP |
| `/evpn-type5-routes/route/rt-exports` | `.rt_exports` | list[str] | `[]` | list[scalar] | **yes (RT)** | no | **no** ⚠IP |

Walker yields ONLY the anchor `/evpn-type5-routes/route` (xpath_walker.py:241–
242) — `prefix`, `rt_imports`, `rt_exports` are unwalked. The sanitizer DOES
redact all three (`prefix` → `evpn-type5-prefix`; rt lists → route-target,
sanitize.py:749–760). Note: NO codec populates `evpn_type5_routes` today
(it's lossy-by-default everywhere — see iosxe_cli matrix:206–219), so the
walker gap here is a *dead leaf* in practice. Agent 11 should confirm.

---

## 13. Counts (the denominator)

### Leaf totals

Counting every distinct scalar / list-of-scalar leaf as an xpath, treating
the reused `CanonicalIPv4Address` as two surfaces (interface + vlan), and
EXCLUDING the 4 metadata/provenance scalars (`source_vendor`,
`source_format`, `source_version`) + the container-of-raw-text leaves
(`raw_sections`, `group_content`, `dropped_tier3_sections`, `apply_groups`)
which are not structured scalar leaves:

| Category | Count |
|---|---|
| Top-level system scalars/lists (incl. anycast-gateway-mac) | 7 |
| `CanonicalInterface` own scalars/lists | 18 |
| `CanonicalIPv4Address` on interface | 5 |
| `CanonicalIPv4Address` on vlan (SVI) | 5 |
| `CanonicalIPv6Address` on interface | 6 |
| `CanonicalVRRPGroup` | 11 |
| `CanonicalVlan` own scalars/lists | 5 |
| `CanonicalStaticRoute` | 6 |
| `CanonicalDHCPPool` | 9 |
| `CanonicalSNMP` own | 4 |
| `CanonicalSNMPv3User` | 7 |
| `CanonicalLAG` | 3 |
| `CanonicalLocalUser` | 4 |
| `CanonicalRADIUSServer` | 4 |
| `CanonicalVxlan` | 6 |
| `CanonicalRoutingInstance` | 8 |
| `CanonicalEvpnType5Route` | 4 |
| **TOTAL structured leaves** | **112** |
| Excluded metadata/provenance/raw-container leaves | 7 |
| **GRAND TOTAL model leaves** | **119** |

(The 112 is the number both downstream gap analyses should treat as the
denominator for "leaves a walk-everything / type-driven rule must reach";
the 7 excluded are the explicit-exemption set discussed in §1 note ².)

### IP-or-host-bearing leaves (IP_OR_HOST_BEARING = yes)

26 structured leaves (+ `hostname` flagged yes¹ as host-identity-not-
ip_address, + the 2 raw-text containers that can embed IPs). Enumerated:

1. `/system/domain` (host)
2. `/system/dns-server`
3. `/system/ntp-server`
4. `/system/syslog-server`
5. `/anycast-gateway-mac` (MAC)
6. `/interfaces/interface/ipv4/address/ip`
7. `/interfaces/interface/ipv4/address/virtual-gateway-address`
8. `/interfaces/interface/ipv4/address/virtual-gateway-mac` (MAC)
9. `/interfaces/interface/ipv6/address/ip`
10. `/interfaces/interface/ipv6/address/virtual-gateway-address`
11. `/interfaces/interface/ipv6/address/virtual-gateway-mac` (MAC)
12. `/vlans/vlan/ipv4/address/ip`
13. `/vlans/vlan/ipv4/address/virtual-gateway-address`
14. `/vlans/vlan/ipv4/address/virtual-gateway-mac` (MAC)
15. `/interfaces/interface/vrrp-groups/group/virtual-ips`
16. `/interfaces/interface/vrrp-groups/group/virtual-ipv6s`
17. `/interfaces/interface/vrrp-groups/group/virtual-mac` (MAC)
18. `/routing/static-route` (destination CIDR)
19. `/routing/static-route/gateway`
20. `/dhcp-servers/pool/network`, `/start-ip`, `/end-ip`, `/gateway`,
    `/dns-servers`, `/domain-name` (host) — 6
21. `/snmp/trap-host`
22. `/radius-servers/server/host`
23. `/vxlan-vnis/mcast-group`, `/vxlan-vnis/flood-list` — 2
24. `/routing-instances/instance/route-distinguisher`, `/rt-imports`,
    `/rt-exports` — 3
25. `/evpn-type5-routes/route/prefix`, `/rt-imports`, `/rt-exports` — 3

Total IP/host-bearing structured leaves ≈ **31** (count of bullets expanded).
`hostname` is host-identifying but not `ip_address()`-parseable — the
key over-redaction-rule edge case for agent 12.

### Secret-bearing leaves (SECRET_BEARING = yes)

6 structured leaves:

1. `/snmp/community`
2. `/snmp/v3-user/auth-passphrase`
3. `/snmp/v3-user/priv-passphrase` ⚠ walker-blind
4. `/local-users/user/hashed-password`
5. `/radius-servers/server/key`
6. `/interfaces/interface/vrrp-groups/group/authentication` ⚠ walker-blind
   (+ `engine_id` is arguably secret-adjacent; sanitizer treats it as a
   redaction category. If counted, total = 7.)

(+ raw-text containers `raw_sections` / `group_content` can embed secrets —
handled by wholesale strip.)

---

## 14. Cross-cutting findings for downstream agents

1. **The two gaps are genuinely independent and the sanitizer is generally
   AHEAD of the walker.** Many IP/secret leaves are sanitizer-redacted but
   walker-blind: DHCP sub-fields (×6), static-route gateway, VRRP
   `authentication`/`virtual_ipv6s`, SNMPv3 `priv_passphrase`, VLAN-SVI
   `virtual_gateway_address`, EVPN Type-5 `prefix`/RTs. The walker gap is the
   bigger silent-loss surface; the sanitizer gap is narrower (most known
   IP/secret fields are already named). Agents 11 and 12 should not assume
   symmetric blast radius.

2. **Two secret-bearing leaves the walker never yields:** VRRP
   `authentication` and SNMPv3 `priv_passphrase`. A codec that drops either
   on render would classify `severity: ok`. These are concrete class-1
   silent-loss candidates beyond the audit-named instances — hand them to
   agent 11/20.

3. **The walker walks anchors but not all sub-leaves** for DHCP, EVPN-Type5,
   and (on the VLAN copy) IPv4-address sub-fields. A "walk EVERY leaf"
   design (class-1 form A) would multiply yields substantially (DHCP alone
   goes 1→9; EVPN-Type5 1→4). Agent 20 must quantify the phase4
   reclassification blast radius of expanding these.

4. **The raw-text containers (`raw_sections`, `group_content`,
   `dropped_tier3_sections`, `apply_groups`) are the natural exemption set**
   for any reflection-driven completeness guard: they are not typed scalar
   leaves, they hold opaque vendor text, and they already have wholesale
   strip handling in the sanitizer and are by-design-not-walked
   (Tier-3 / provenance). Model the exemption on #149's
   `_SYNTHETIC_NONWALKABLE` — each carries its reason. Likewise the 3
   `source_*` metadata scalars.

5. **Free-text fields are the over-redaction trap for class-2 design A**
   (blanket `ip_address()`): `hostname`, interface `description`, VLAN
   `name`/`description`, SNMP `contact`/`location`, DHCP `domain_name`,
   route `description`, VRRP `description`, routing-instance `description`,
   `instance_type`, `vxlan source_interface`, `tunnel_type`,
   `dhcp_client_v6`, `kind`, `scope`, `mode`. None are `ip_address()`-
   parseable as a whole, but several can CONTAIN an IP-like substring. A
   value-level `ip_address()` rule (parse the whole field) would NOT mangle
   these (they don't parse as a bare IP); a substring/regex rule WOULD. This
   is the decisive over-redaction distinction for agent 12.

6. **xpath spelling caveats** (so agents 11/20/12 reuse the right strings):
   - VXLAN leaves are `/vxlan-vnis/<leaf>` (no `/vni/` element segment).
   - Switchport leaves are `/interfaces/interface/<leaf>` (no `config/`
     segment) — `switchport-mode`, `access-vlan`, etc.
   - `description`/`enabled`/`type`/`mtu`/`vrf` on interface DO carry a
     `config/` segment (`/interfaces/interface/config/...`).
   - Several projected xpaths in this census (`/routing/static-route/
     gateway`, `/dhcp-servers/pool/*`, `/evpn-type5-routes/route/*`,
     vlan-SVI sub-fields, VRRP `mode`/`priority`/`preempt`/`auth`) are NOT
     declared by any matrix today — treat the spelling as the proposed
     convention, not an existing string.
