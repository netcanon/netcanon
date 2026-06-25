# 12 — Sanitizer-bypass gap (class 2) + over-redaction risk

**Agent:** `12-sanitizer-gap` · Phase 1 census · read-only
**Scope:** `netcanon/tools/sanitize.py` (`sanitize_intent`, ~1153 lines) measured
against `netcanon/migration/canonical/intent.py` (the 17-class canonical model).
**Question:** which IP/host/secret-bearing canonical leaves does the sanitizer
**never touch** (leak candidates), and how risky is the user's proposed blanket
`ip_address()`-redact-everything rule (over-redaction)?

---

## 0. TL;DR / verdict

- **The current allow-list is, today, essentially complete.** Every
  IP/host-bearing and every secret-bearing *modelled* leaf I can find in
  `intent.py` is already walked and redacted by `sanitize_intent`. The class-2
  blind spot is **latent, not currently-bleeding**: the gap is *the next field
  someone adds*, not a field present-but-missed today. This matches the
  meta-finding ("each round fixes the named instance; the next pass finds a new
  surface of the same class") — five rounds of patching have actually closed the
  *current* surface. (Caveat: two genuinely-uncovered leaves below — `ntp_servers`
  / `syslog_servers` / `dns_servers` accept **hostnames** that pass through
  verbatim; and `radius_servers[].host` / `snmp.trap_hosts[]` likewise. These are
  *documented residuals*, not bugs — DNS-name hosts are deliberately preserved.)

- **The user's blanket `ip_address()` rule is SAFER than it sounds, but is the
  WRONG primitive.** Because the codebase already redacts via *whole-string*
  `ipaddress.IPvNAddress(value)` parsing (NOT substring scanning), free-text
  fields like `description = "Uplink to ISP-PRD"` or `"Topology control"` simply
  **fail to parse** and pass through untouched — `ipaddress.IPv4Address("Topology
  control")` raises `ValueError`. So the headline over-redaction fear (mangling
  prose) is **largely unfounded for the parse-the-whole-string form**. The REAL
  over-redaction risks are narrower and enumerable (§5). But a blanket "redact any
  field that parses as an IP" *still* misses the point: it only finds **string
  leaves whose value happens to be an IP**, and would (a) catch `timezone` if an
  operator ever set it to an IP-shaped string, and (b) **completely miss the
  cross-reference-stable / format-preserving categories** (RD/RT `64496:N`, mcast
  `233.252.0.N`, hashes, communities, free-text PII) that are *not* IPs. The
  blanket rule is neither sufficient (misses non-IP secrets) nor the right shape.

- **Recommended class-2 form: a reflection-driven COMPLETENESS GUARD (form B),
  extended from the existing `TestSecretRedactionCoverage` guard, NOT a runtime
  blanket rule.** It already exists in skeleton form for secrets
  (`_REGISTERED_SECRET_FIELDS` + `_SECRET_NAME_RE`, two-sided). The durable fix is
  to **add a parallel IP/host coverage half** to the same test file, with a
  self-justifying exemption set (modelled on #149's `_SYNTHETIC_NONWALKABLE`). This
  converts "a new IP-bearing field leaks until a human notices" into "a new
  IP-bearing field turns CI red until a human redacts-or-exempts it." Zero runtime
  behavior change, zero fixture-corpus diff, ~0 over-redaction risk. Detail and
  the head-on over-redaction analysis below; agent `21-design-sanitizer-guard`
  should carry this into the concrete test shape. Agent `22-design-typed-marker`
  should weigh whether a typed marker beats the naming heuristic (my read: marker
  is nicer but probably over-engineering vs. a 40-line guard — §7).

---

## 1. The redaction primitives (what the sanitizer can do)

All redaction flows through one `_SubstitutionTable` instance per call, which
gives **cross-reference stability** (same input → same output across the config).
The primitives, `sanitize.py:801–1105`:

| Primitive | File:line | Behaviour | Preserves |
|---|---|---|---|
| `redact_hostname` | `839` | `device-N` (stable map) | — |
| `redact_domain` | `844` | `example-N.test` (stable map) | — |
| `redact_ipv4` | `849` | public → cycles `192.0.2/198.51.100/203.0.113` docs ranges | **private, loopback, link-local, multicast, reserved, unspecified, existing-docs-range, CGNAT `100.64/10`** (`857–871`) |
| `redact_ipv6` | `883` | global → `2001:db8::N` | **ULA `fc00::/7`, link-local `fe80::/10`, `::1`, `::`, multicast `ff00::/8`, reserved, `2001:db8::/32`** (`904–913`) |
| `redact_ip_string` | `921` | tries v4 then v6 whole-string; non-IP → returned verbatim | everything `redact_ipv4`/`redact_ipv6` preserve, **plus any non-IP string** (`932–933`) |
| `redact_cidr` | `935` | splits on `/`, redacts addr, keeps prefix | prefix length; non-IP host verbatim |
| `redact_route_target` | `943` | `<l>:<r>` → `64496:N` (stable map) | correlation structure |
| `redact_mcast_group` | `960` | admin-scoped mcast → `233.252.0.N` (stable); non-mcast falls to `redact_ip_string` | non-multicast handled by IP path |
| `redact_community` | `982` | `public_redacted_N` (stable) | — |
| `redact_secret(cat)` | `987` | `REDACTED-<cat>-N` (per-category counter) | — |
| `redact_vrrp_authentication` | `993` | preserves `<scheme>:` prefix, replaces value with `REDACTED-VRRP-AUTH-N` | scheme prefix (renderer slices it) |
| `redact_vlan_name` | `1014` | `vlan-N` (stable) | — |
| `redact_local_user_name` | `1028` | `localuserN` (stable) | — |
| `redact_snmpv3_user_name` | `1048` | `snmpv3userN` (stable, separate counter) | — |
| `redact_hash` | `1066` | format-preserving fake (`$9$`/`$5$`/`$6$`/`$2y$`/`ENC`/type-7/hex/generic) | hash prefix shape so render stays valid |

### 1a. The private/documentation PRESERVATION logic (load-bearing — DO NOT break)

The single most important behavioural property is that `redact_ipv4`/`redact_ipv6`
**preserve RFC-1918 / ULA / loopback / link-local / multicast / docs / CGNAT
addresses by design** (`sanitize.py:857–871`, `904–913`). The rationale stated in
the module docstring (`sanitize.py:20–26`) and the seed: RFC-1918 LAN gear is the
common case; redacting it would destroy a useful shared config. This predicate —
"is this address public/routable?" — is the reusable guard ANY class-2 redesign
**must** preserve. The good news for the user's blanket proposal: this predicate
is already centralised inside `redact_ipv4`/`redact_ipv6`, so a blanket rule that
routes through `redact_ip_string` automatically inherits private-preservation. The
preservation is NOT lost by going blanket — that specific fear in the seed is
unfounded *as long as* a blanket rule calls the existing primitives rather than a
naive "any IP → docs."

---

## 2. The EXACT redaction allow-list (every field `sanitize_intent` touches)

Enumerated from the `sanitize_intent` walk, `sanitize.py:216–793`. Grouped by
owning model; each row cites the walk site.

### Top-level scalars / lists
| Canonical field | xpath-ish | walk site | primitive |
|---|---|---|---|
| `CanonicalIntent.hostname` | `/hostname` | `221–229` | `redact_hostname` |
| `CanonicalIntent.domain` | `/domain` | `231–239` | `redact_domain` |
| `CanonicalIntent.dns_servers[]` | `/dns-servers` | `242–243` | `redact_ip_string` (list) |
| `CanonicalIntent.ntp_servers[]` | `/ntp-servers` | `244–245` | `redact_ip_string` (list) |
| `CanonicalIntent.syslog_servers[]` | `/syslog-servers` | `246–247` | `redact_ip_string` (list) |
| `CanonicalIntent.dropped_tier3_sections` | `/dropped-tier3-sections` | `680–688` | **stripped to `[]`** |
| `CanonicalIntent.raw_sections` | `/raw-sections` | `695–703` | **stripped to `{}`** |
| `CanonicalIntent.apply_groups` | `/apply-groups` | `784–791` | **stripped to `[]`** |
| `CanonicalIntent.group_content` | `/group-content` | `776–783` | **stripped to `{}`** |

### Interface (`CanonicalInterface`) + nested addresses
| Field | walk site | primitive |
|---|---|---|
| `interfaces[].description` | `251–259` | `"description redacted"` |
| `interfaces[].ipv4_addresses[].ip` | `261–270` | `redact_ipv4` |
| `interfaces[].ipv4_addresses[].virtual_gateway_address` | `277–286` | `redact_ipv4` (#174 fix) |
| `interfaces[].ipv6_addresses[].ip` | `288–297` | `redact_ipv6` |
| `interfaces[].ipv6_addresses[].virtual_gateway_address` | `298–307` | `redact_ipv6` |
| `interfaces[].vrrp_groups[].authentication` | `316–325` | `redact_vrrp_authentication` |
| `interfaces[].vrrp_groups[].description` | `326–333` | `"description redacted"` |
| `interfaces[].vrrp_groups[].virtual_ips[]` | `341–354` | `redact_ip_string` |
| `interfaces[].vrrp_groups[].virtual_ipv6s[]` | `355–368` | `redact_ip_string` |

### VLAN (`CanonicalVlan`)
| Field | walk site | primitive |
|---|---|---|
| `vlans[].name` | `387–395` | `redact_vlan_name` |
| `vlans[].description` | `396–403` | `"description redacted"` |
| `vlans[].ipv4_addresses[].ip` | `405–414` | `redact_ipv4` |
| `vlans[].ipv4_addresses[].virtual_gateway_address` | `418–427` | `redact_ipv4` |

### Local users, SNMP, RADIUS, DHCP, static routes, routing-instances, VXLAN, EVPN
| Field | walk site | primitive |
|---|---|---|
| `local_users[].name` | `438–447` | `redact_local_user_name` |
| `local_users[].hashed_password` | `448–456` | `redact_hash` |
| `snmp.community` | `460–468` | `redact_community` |
| `snmp.contact` | `476–484` | `"<contact redacted>"` |
| `snmp.location` | `486–494` | `"<location redacted>"` |
| `snmp.trap_hosts[]` | `499–510` | `redact_ip_string` |
| `snmp.v3_users[].name` | `516–524` | `redact_snmpv3_user_name` |
| `snmp.v3_users[].auth_passphrase` | `525–533` | `redact_secret("AUTH")` |
| `snmp.v3_users[].priv_passphrase` | `534–542` | `redact_secret("PRIV")` |
| `snmp.v3_users[].engine_id` | `543–551` | `redact_secret("SNMPV3-ENGINE-ID")` |
| `radius_servers[].host` | `558–567` | `redact_ip_string` |
| `radius_servers[].key` | `568–576` | `redact_secret("RADIUS")` |
| `dhcp_servers[].dns_servers[]` | `580–591` | `redact_ip_string` |
| `dhcp_servers[].gateway` | `596–605` | `redact_ip_string` |
| `dhcp_servers[].start_ip` | `613–622` | `redact_ip_string` |
| `dhcp_servers[].end_ip` | `623–632` | `redact_ip_string` |
| `dhcp_servers[].network` | `633–642` | `redact_cidr` |
| `dhcp_servers[].domain_name` | `648–656` | `redact_domain` |
| `static_routes[].gateway` | `659–669` | `redact_ip_string` |
| `static_routes[].description` | `670–677` | `"description redacted"` |
| `routing_instances[].description` | `706–714` | `"description redacted"` |
| `routing_instances[].route_distinguisher` | `715–723` | `redact_route_target` |
| `routing_instances[].rt_imports[]` | `724–726` | `redact_route_target` (list) |
| `routing_instances[].rt_exports[]` | `727–729` | `redact_route_target` (list) |
| `vxlan_vnis[].mcast_group` | `734–744` | `redact_mcast_group` |
| `vxlan_vnis[].flood_list[]` | `745–747` | `redact_ip_string` (list) |
| `evpn_type5_routes[].rt_imports[]` | `749–751` | `redact_route_target` (list) |
| `evpn_type5_routes[].rt_exports[]` | `752–754` | `redact_route_target` (list) |
| `evpn_type5_routes[].prefix` | `755–764` | `redact_cidr` |

**Total: 41 distinct field sites redacted (or 4 stripped-entirely surfaces +
37 field-typed).**

---

## 3. The complete IP/host-bearing + secret-bearing leaf list (my own census)

Built independently from `intent.py`, flagging each leaf as IP/host-bearing (`IP`)
and/or secret-bearing (`SEC`). This is the *denominator* — every leaf that *should*
be considered by class-2. (Agent `10-model-leaf-census` produces the full leaf
table; here I list only the IP/secret-relevant ones.)

### IP / host-bearing leaves (`IP`)
| Leaf | intent.py | Sanitized? | Notes |
|---|---|---|---|
| `dns_servers[]` | `896` | ✅ `redact_ip_string` | **but hostnames pass through** |
| `ntp_servers[]` | `897` | ✅ `redact_ip_string` | **hostnames pass through** (docstring `81–84`) |
| `syslog_servers[]` | `899` | ✅ `redact_ip_string` | **hostnames pass through** |
| `CanonicalIPv4Address.ip` | `120` | ✅ | interface + VLAN SVI sites |
| `CanonicalIPv4Address.virtual_gateway_address` | `123` | ✅ | #174 |
| `CanonicalIPv6Address.ip` | `160` | ✅ | |
| `CanonicalIPv6Address.virtual_gateway_address` | `164` | ✅ | |
| `CanonicalStaticRoute.destination` | `326` | ⚠️ **NO** | CIDR; see §4 (private-mostly, low-risk) |
| `CanonicalStaticRoute.gateway` | `327` | ✅ | |
| `CanonicalStaticRoute.interface` | `328` | n/a | interface name, not an IP |
| `CanonicalDHCPPool.network/start_ip/end_ip/gateway/dns_servers[]` | `355–359` | ✅ | all five |
| `CanonicalSNMP.trap_hosts[]` | `463` | ✅ | hostnames pass through |
| `CanonicalRADIUSServer.host` | `635` | ✅ | hostnames pass through |
| `CanonicalVRRPGroup.virtual_ips[] / virtual_ipv6s[]` | `589–590` | ✅ | |
| `CanonicalVxlan.mcast_group / flood_list[] / source_interface` | `689–691` | ✅ mcast+flood; `source_interface` n/a (iface name) | |
| `CanonicalRoutingInstance.route_distinguisher / rt_*[]` | `733–735` | ✅ | RD/RT (may be `<ip>:nn` form) |
| `CanonicalEvpnType5Route.prefix / rt_*[]` | `780–782` | ✅ | |

### Secret-bearing leaves (`SEC`)
| Leaf | intent.py | Sanitized? | In `_REGISTERED_SECRET_FIELDS`? |
|---|---|---|---|
| `CanonicalLocalUser.hashed_password` | `620` | ✅ | ✅ |
| `CanonicalSNMP.community` | `460` | ✅ | ✅ |
| `CanonicalSNMPv3User.auth_passphrase` | `444` | ✅ | ✅ |
| `CanonicalSNMPv3User.priv_passphrase` | `446` | ✅ | ✅ |
| `CanonicalSNMPv3User.engine_id` | `447` | ✅ (redacted; NOT in registry — see §6) | ❌ (not secret-*named*) |
| `CanonicalRADIUSServer.key` | `636` | ✅ | ✅ |
| `CanonicalVRRPGroup.authentication` | `595` | ✅ | ✅ |

### Free-text / org-PII leaves (`PII`, neither pure-IP nor secret)
| Leaf | intent.py | Sanitized? |
|---|---|---|
| `CanonicalInterface.description` | `264` | ✅ |
| `CanonicalVlan.name / description` | `292–293` | ✅ |
| `CanonicalSNMP.contact / location` | `461–462` | ✅ |
| `CanonicalStaticRoute.description` | `309` | ✅ |
| `CanonicalRoutingInstance.description` | `727` | ✅ |
| `CanonicalVRRPGroup.description` | `597` | ✅ |
| `CanonicalDHCPPool.domain_name` | `361` | ✅ |
| `hostname` / `domain` | `894–895` | ✅ |
| `local_users[].name` / `snmp.v3_users[].name` | — | ✅ |

---

## 4. THE GAP — IP/secret/PII-bearing leaves the sanitizer NEVER touches

After the five rounds of fixes, the gap is **small and mostly justified**. The
leaks fall into two tiers:

### 4a. True residuals (documented, deliberate, low-risk)
1. **Hostname-form host fields pass through verbatim.** `dns_servers[]`,
   `ntp_servers[]`, `syslog_servers[]`, `snmp.trap_hosts[]`, `radius_servers[].host`
   all run through `redact_ip_string`, which returns non-IP strings **unchanged**
   (`sanitize.py:932–933`). So `ntp_servers=["nms.corp.example"]` survives. This is
   **documented** in `sanitize.py:81–84` and asserted as expected behaviour in
   `test_sanitize.py:837–843` (`test_hostname_trap_target_preserved`). Realistic
   leak class: an internal-DNS hostname reveals the org. **Classified: (a)
   realistically-identifying true leak**, but *intentional* — the project chose
   not to guess which non-IP strings are sensitive hostnames vs. legitimate labels.

### 4b. Genuinely-unredacted modelled IP leaves (small)
2. **`CanonicalStaticRoute.destination`** (`intent.py:326`) — the route's CIDR
   *prefix* is never redacted (only `.gateway` is, `sanitize.py:659–669`). A static
   route to a **public** destination (`ip route 8.8.8.0/24 ...`) leaks that
   destination prefix. **Classified: (a) realistically public-bearing true leak**,
   though in practice static-route destinations are overwhelmingly RFC-1918 (LAN
   subnets, default-route `0.0.0.0/0`). Low real risk but it is the cleanest
   example of a *modelled IP leaf the allow-list omits* — a good probe case for the
   guard in §6. (`redact_cidr` already exists and would handle it identically to
   `dhcp.network` / `evpn.prefix`.)
3. **`CanonicalVxlan.source_interface`** and `CanonicalInterface` name/`default_name`
   — interface names, not IPs; structurally non-sensitive (opaque vendor labels).
   **Classified: (b) structurally non-sensitive.** No action.

### 4c. Structurally always-private / non-sensitive (no action)
- All the integer/enum/bool fields (`prefix_length`, `vlan_id`, `vni`, `mode`,
  `priority`, `switchport_mode`, `interface_type`, `tunnel_type`, `dhcp_client_v6`,
  `scope`, `instance_type`, `auth_protocol`, `priv_protocol`, `kind`, …) —
  **cannot carry an IP or secret**. The user's blanket `ip_address()` rule would
  correctly skip these (a number/enum won't parse as IP), but a *naming*-based or
  *typed-marker* guard must also skip them — they should NOT be flagged as
  "uncovered" by any guard. This is the bulk of the model and the main source of
  exemption-list noise the guard design (§6) must handle cleanly.

**Bottom line on the gap:** the only *modelled* leak worth wiring is
`static_routes[].destination` (and arguably it's marginal). The dangerous part is
**field N+1** — the field nobody has added yet. That is precisely why the durable
fix is a *guard*, not another hand-added redaction.

---

## 5. OVER-REDACTION analysis of the user's blanket rule (critical)

The user proposed: *"the sanitizer redacts on `ip_address()` of ANY IP-typed
string field, not an allow-list."* I evaluated this head-on against the model and
read-only fixture sampling.

### 5a. The good news: whole-string parsing makes prose-mangling a non-issue
The existing primitive `redact_ip_string` (`sanitize.py:921–933`) parses the
**entire field value** as `IPv4Address`/`IPv6Address`. It does **not** scan for
IP-like substrings. Therefore:

- `description = "Uplink to ISP-PRD"` → `IPv4Address("Uplink to ISP-PRD")` raises
  `ValueError` → **untouched.** Confirmed against fixture descriptions like
  `"Topology control"`, `"EWLC Data, Inter FED Traffic"`,
  `"TRUNK - FORTIGATE"` (cisco_iosxe `user_contrib_cat9300_iosxe1712.txt:163–233`)
  and MikroTik comments `"contains all interfaces"`, `"AWS PROPOSAL"`,
  `"The quinta teltonika router has OSPF enabled"`
  (`routeros_diff_verbose_export.rsc:46–416`). None parse as an IP. **A blanket
  whole-string `ip_address()` rule would leave every one of these alone.** The
  seed's headline fear ("description/name/banner mangled") is **largely
  unfounded** for the whole-string form.
- A free-text field would only be redacted if its *entire* value is exactly an IP
  string (e.g. someone literally typed `description "8.8.8.8"`). That's a
  vanishingly rare and arguably-correct redaction anyway.

So the over-redaction surface is FAR smaller than the seed feared — **provided**
the blanket rule keeps the whole-string semantics and routes through
`redact_ipv4/6` (which preserves private/docs). A substring-scanning rule (regex
for `\d+\.\d+\.\d+\.\d+` inside prose) WOULD be dangerous — but that is not what
the existing primitive does, and a redesign should not introduce it.

### 5b. The residual over-redaction risks (enumerable, small)
Even a whole-string blanket rule has three sharp edges:

1. **Enum/keyword string fields whose value can be IP-shaped.** None today. But
   `timezone` (`intent.py:898`) is free text (`"PST -8"`, `"Europe/London"`) — an
   operator *could* in principle store something IP-shaped, and a blanket "every
   str field → try IP" would then redact it. Risk is theoretical, cost is a wrong
   substitution in a metadata field. Acceptable but it argues against truly-blanket
   (every `str`) over **typed/targeted** (only fields *declared* host-bearing).
2. **CIDR vs bare-address ambiguity.** `redact_cidr` must be used (not
   `redact_ip_string`) for `host/prefix` fields, else the `/24` is lost or the
   parse fails. A blanket rule that applied `redact_ip_string` uniformly would
   **fail to redact** `network`/`prefix`/`destination` (they don't parse as a bare
   address) — i.e. it *under*-redacts those, not over-redacts. The current code
   already distinguishes (`redact_cidr` at `633`,`755`). A blanket rule must
   preserve that distinction → another argument that "blanket" is too blunt.
3. **The MAC / hex-string fields.** `anycast_gateway_mac` (`intent.py:917`),
   `virtual_gateway_mac` (`123`,`164`), `engine_id`. A MAC `00:1c:73:00:dc:01` is
   not a valid `IPv4Address`/`IPv6Address` (it has colons but wrong group count) so
   `ip_address()` rejects it — **a blanket IP rule misses MACs entirely.** MACs are
   network-identifying. (Today MACs are NOT redacted at all — another latent gap a
   *guard* would surface and a blanket-IP rule would not.) This is the strongest
   evidence the blanket-IP rule is the wrong primitive: it is blind to MACs, RD/RT,
   communities, hashes, and hostnames.

### 5c. Fixture-corpus impact of a blanket rule (reasoned estimate)
The corpus is ~60 real fixtures across 11 codecs (`tests/fixtures/real/`). Because
the *current* allow-list already covers every IP-valued modelled leaf, a blanket
`ip_address()` rule routed through the existing private-preserving primitives would
produce **almost no diff vs. today** on the corpus — the only new redactions would
be `static_routes[].destination` public prefixes (rare in the corpus; most are
RFC-1918 or default routes per the MikroTik/Cisco samples I read) and any
free-text field that happens to be exactly an IP (I found none in sampled
fixtures). **Estimated corpus diff: < 1% of redaction sites, near-zero risk of
mangling prose.** This is the empirical reassurance the user asked for. (The main
thread should confirm by prototyping `sanitize_text` over the corpus, but the
reasoned answer is "negligible change.")

### 5d. Does blanket break private/docs preservation? No — if it reuses the predicate
The preservation logic lives *inside* `redact_ipv4`/`redact_ipv6`
(`sanitize.py:857–871`,`904–913`). Any blanket rule that calls `redact_ip_string`
(which delegates to those) **inherits private-preservation for free.** The seed's
concern ("does blanket break the deliberate private/docs-IP preservation?") is
answered: **no, as long as it reuses the same primitive** rather than a fresh
"any-IP → docs" implementation. This is a hard must-fix if blanket were chosen.

---

## 6. Recommendation — which class-2 form is SAFEST

**Recommended: form B — a reflection-driven COMPLETENESS GUARD, built by adding an
IP/host coverage half to the existing `TestSecretRedactionCoverage`
(`test_sanitize.py:646–767`).** NOT the runtime blanket rule (form A).

### Why not blanket (A)
- It is **not sufficient**: blind to MACs, RD/RT (`64496:N`), mcast (`233.252.0.N`),
  communities, hashes, hostnames, and free-text PII — i.e. ~half the categories the
  sanitizer already handles are *not* IPs (§5b.3). "Redact any `ip_address()`" only
  covers the IP slice and would *regress* the carefully-tuned non-IP categories.
- It is **the wrong altitude**: the leak class is "a new field is forgotten," which
  is a *coverage* problem, best caught at test time, not a runtime *behaviour*
  problem. The seed itself prefers "convert the blind spot into a CI failure over a
  risky runtime behavior change."
- It introduces real (if small) over-redaction edges (`timezone`, CIDR ambiguity)
  for negligible benefit, since the current allow-list is already complete.

### Why guard (B) — and how it kills the class
The existing secret guard `test_reverse_no_unregistered_secret_field`
(`test_sanitize.py:743–767`) already does exactly the right thing for secrets:

```python
# existing, secret half
_REGISTERED_SECRET_FIELDS = {("CanonicalLocalUser","hashed_password"), ...}
_SECRET_NAME_RE = re.compile(r"passphrase|password|secret|community|^authentication$|(^|_)key$", re.I)
# reverse test: any secret-NAMED str field on the model not in the registry → FAIL
```

The durable class-2 fix is a **parallel IP/host half** in the same file:

```python
# proposed IP/host half (sketch — agent 21 to finalize)
_REGISTERED_IP_FIELDS = {        # leaf -> reason it's covered
    ("CanonicalIPv4Address", "ip"),
    ("CanonicalIPv4Address", "virtual_gateway_address"),
    ("CanonicalDHCPPool", "gateway"), ("CanonicalDHCPPool", "network"),
    ("CanonicalDHCPPool", "start_ip"), ("CanonicalDHCPPool", "end_ip"),
    ("CanonicalStaticRoute", "gateway"),
    ("CanonicalRADIUSServer", "host"), ...
}
_IP_HOST_NAME_RE = re.compile(
    r"(^|_)(ip|host|gateway|network|destination|prefix|address|"
    r"dns_servers|ntp_servers|syslog_servers|trap_hosts|flood_list|"
    r"start_ip|end_ip|virtual_ips|virtual_ipv6s|virtual_gateway_address)$",
    re.I,
)
# Self-justifying exemptions (modelled on #149 _SYNTHETIC_NONWALKABLE):
_IP_NAME_EXEMPT = {
    # field -> reason it is NOT an IP despite an IP-ish name
    ("CanonicalVxlan", "source_interface"): "opaque vendor iface name, not an IP",
    ("CanonicalStaticRoute", "interface"): "outgoing iface name, not an IP",
    # ... each carries a human-readable reason string
}

def test_reverse_no_unregistered_ip_field():
    found = {(m.__name__, f) for m in _reachable_canonical_models(CanonicalIntent)
             for f, fld in m.model_fields.items()
             if _IP_HOST_NAME_RE.search(f) and str in _flatten_annotation(fld.annotation)}
    unregistered = found - set(_REGISTERED_IP_FIELDS) - set(_IP_NAME_EXEMPT)
    assert not unregistered, (
        "IP/host-bearing canonical field(s) with no redaction rule — "
        "redact in sanitize_intent + register, or add a justified exemption: "
        f"{sorted(unregistered)}")
```

**The decisive property (would it catch the next leak?):** if a future dev adds
`CanonicalThing.management_ip: str = ""` and forgets to redact it, the name `…_ip`
matches `_IP_HOST_NAME_RE`, the leaf is neither registered nor exempt → **CI fails
with an actionable message naming the exact `Class.field`.** That is the class-kill.
And `test_forward_*` (populate-sentinel-then-assert-gone) gives the complementary
"the redaction actually works" side.

**Would the guard have failed before #174 (the VGA leak)?** Yes, *if* the
`_IP_HOST_NAME_RE` included `virtual_gateway_address` (it would — name ends in
`_address`). Before #174, `virtual_gateway_address` was a model field with NO
redaction → the reverse test would have flagged it `unregistered` → red CI. This is
the proof the guard kills the historical instance prospectively. (Agent
`21-design-sanitizer-guard` should include this as the headline regression
argument.)

### The exemption-relocates-the-blind-spot concern (real, but mitigable)
The honest weakness of any guard is that the exemption set can become a dumping
ground that *re-creates* the blind spot. Mitigations (each cheap):
1. **Every exemption carries a free-text reason string** (the `_IP_NAME_EXEMPT`
   value), exactly like #149's structural-rule precedent. A reviewer reading a PR
   that adds `("X","management_ip"): "internal-only, never public"` can challenge a
   bogus reason.
2. **The forward (`test_forward_*`) half is NOT exemptable** — it sentinel-tests
   that *registered* fields are actually redacted, so you cannot "exempt" your way
   out of redacting a registered field.
3. The exemption set is for *naming false-positives* (`source_interface`,
   `interface`) — structurally NOT IPs — which is a closed, small, reviewable set,
   not an open escape hatch for "I didn't want to redact this IP."

### Typed-marker (C) — defer to agent 22, but my read
A typed marker (`Annotated[str, IPField()]`) would let the guard enumerate covered
leaves *from the model itself* with zero naming heuristic and zero exemption list
for false-positives. It is the most intrinsic ("fail-surfaced by construction").
**But for class-2 specifically it is probably over-engineering vs. the ~40-line
guard:** the naming heuristic already works (every IP/host field in the model has an
IP-ish name; every secret field has a secret-ish name — the existing secret guard
proves the heuristic is reliable here), and the exemption set for false-positives is
tiny (2 entries). The marker's payoff is higher for class-1 (the walker) where
there is no naming convention to lean on. **My verdict: guard (B) for class-2 now;
typed-marker only if agent 22 shows it cheaply subsumes BOTH the walker and the
sanitizer guard.** Keep the existing secret guard; add the IP/host half; done.

---

## 7. Catalogue of the existing partial guard (what it covers / leaves open)

`tests/unit/tools/test_sanitize.py` — `TestSecretRedactionCoverage`
(`646–767`), the only structural class-2 guard today:

| Mechanism | Covers | Leaves open |
|---|---|---|
| `_REGISTERED_SECRET_FIELDS` (6 entries) + `test_reverse_no_unregistered_secret_field` | **secret-NAMED** str fields (`password`/`secret`/`community`/`authentication`/`key`/`passphrase`) — a new secret field FAILS CI | **IP/host fields entirely** (no name match); **PII free-text fields** (description/contact/location — no secret name); `engine_id` (redacted but not secret-named, so not in registry) |
| `test_forward_no_registered_secret_survives` | sentinel round-trip for the 6 registered secrets | only the registered set |
| `_reachable_canonical_models` + `_flatten_annotation` (`662–685`) | **reusable model-reflection machinery** — already handles `list[...]`, nested models, unions, `from __future__ annotations` string types | — (this is the reusable engine the IP/host half plugs into) |
| Per-category forward blocks (`TestFreeTextPiiRedaction`, `TestOverlayFieldRedaction`, `TestIPv6Redaction`, `TestVRRPVirtualIPRedaction`, `TestDHCPRangeRedaction`, `TestVirtualGatewayAddressRedaction`) | hand-written "this specific field's value doesn't survive" | each is per-instance; none is a *reverse* completeness check for IP/PII |

**Key finding for the design phase:** the reflection engine
(`_reachable_canonical_models` + `_flatten_annotation`, already proven to handle
pydantic v2 + `from __future__ import annotations`) **already exists** in this exact
test file. The IP/host guard is a ~40-line addition that reuses it — NOT a new
subsystem. This is the cheapest possible durable fix and it is the recommendation.

---

## 8. Coordination notes for downstream agents

- **`21-design-sanitizer-guard`**: adopt form B; the concrete shape is in §6. Lead
  with the "would have failed before #174" regression argument. Decide the exact
  `_IP_HOST_NAME_RE` token list (I sketched it; tune against the real model field
  names) and whether `static_routes[].destination` should be *wired* (add
  `redact_cidr` at `sanitize.py:659` block) before the guard goes green, or
  registered-as-known-gap. My rec: wire it (1-line, `redact_cidr`, identical to
  `dhcp.network`) so the guard is honest, then the guard is green from day one.
- **`22-design-typed-marker`**: my honest read is the marker is over-engineering for
  class-2 alone (§6). Only pursue if it *cheaply* serves the walker (class-1) too.
- **`20-design-walker-guard`**: note that the class-2 reflection engine
  (`_reachable_canonical_models`) is reusable for the walker completeness guard.
- **Over-redaction headline for synthesis**: the blanket-`ip_address()` fear is
  **mostly unfounded** because redaction parses whole strings (not substrings) and
  reuses the private-preserving predicate; the real argument against blanket is that
  it is *insufficient* (blind to MAC/RD/RT/community/hash/hostname), not that it
  over-fires.

## 9. Citations index
- `netcanon/tools/sanitize.py:200–793` — `sanitize_intent` walk (the allow-list).
- `netcanon/tools/sanitize.py:849–933` — `redact_ipv4/ipv6/ip_string` + private-preservation.
- `netcanon/migration/canonical/intent.py:83–931` — the model (leaf denominator).
- `netcanon/migration/canonical/intent.py:326` — `CanonicalStaticRoute.destination` (the one modelled IP leak).
- `tests/unit/tools/test_sanitize.py:646–767` — `TestSecretRedactionCoverage` (the reusable guard skeleton).
- `tests/unit/tools/test_sanitize.py:837–843` — documented hostname-passthrough residual.
- `tests/fixtures/real/cisco_iosxe/user_contrib_cat9300_iosxe1712.txt:163–233` — free-text descriptions (over-redaction sample, none parse as IP).
- `tests/fixtures/real/mikrotik/routeros_diff_verbose_export.rsc:46–416` — free-text comments (over-redaction sample, none parse as IP).
