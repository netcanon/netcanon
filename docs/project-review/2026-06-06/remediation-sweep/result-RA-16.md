# result-RA-16 — R-16 / CF-04: redact the sanitiser's PII / network tail

**Finding:** R-16 (register P3, `CF-04`). Sanitiser misses non-secret
PII/network fields: `snmp.contact`, VLAN-SVI IPv4, RADIUS/trap/DHCP
hosts.
**Scope:** READ-ONLY investigation; apply-ready edits below for the
orchestrator. Target code file: `netcanon/tools/sanitize.py`. Docs:
`SECURITY.md`, `BUG_REPORTING.md`. Tests: `tests/unit/tools/test_sanitize.py`.
**Model:** opus. **Confidence:** HIGH on the leaks + the in-scope set;
MEDIUM on the two judgment-call inclusions (`snmp.location`, DHCP
`gateway`) — both flagged below for the orchestrator to accept/trim.

---

## 1. Finding + current state (verified against the tree)

`sanitize_intent` (`netcanon/tools/sanitize.py:171-385`) walks 12
canonical surfaces but leaves five identifying PII/network fields
untouched. All five are **live** — populated by parsers and emitted by
renderers (not dead-code targets). Verified field-by-field:

| Field | Populated by (parse) | Emitted by (render) | Leak? |
|---|---|---|---|
| `CanonicalSNMP.contact` | opnsense `parse.py:460`, fortigate `:538`, junos `:2146`, cisco_iosxe_cli `:1654`, mikrotik `:934`, aruba `:834`, arista `:433` | arista `render.py:205`, cisco `:581`, junos `:1026`, aruba `:415`, mikrotik `:544`, fortigate `:762`, opnsense `:381` | **YES — PII (email/name)** |
| `CanonicalSNMP.location` | same 7 parsers | junos `render.py:1022`, cisco `:579`, arista, aruba, mikrotik, fortigate, opnsense | **YES — site/address PII** |
| `CanonicalSNMP.trap_hosts[]` | aruba `parse.py:842`, cisco `:1655`, opnsense `:463`, mikrotik `:941`, arista `:436`, junos `:2153`, fortigate `:568` | aruba `render.py:416`, cisco `:583`, arista `:206`, mikrotik `:549`, junos `:1028`, opnsense `:382`, fortigate `:780` | **YES — public IP** |
| `CanonicalRADIUSServer.host` | arista `parse.py:521`, opnsense `:254`, cisco `:1531/1550`, mikrotik `:971`, aruba `:992`, fortigate `:776` | cisco `render.py:566-567`, aruba `:458/461/464`, arista `:317`, mikrotik `:611`, opnsense `:116`, fortigate `:889` | **YES — public IP** |
| `CanonicalDHCPPool.gateway` | fortigate `parse.py:812`, mikrotik, opnsense | cisco `render.py:554`, fortigate `:911`, opnsense `:346`, junos `:1136`, mikrotik `:649` | **YES — usually private; public possible** |

### 1.1 The VLAN-SVI leak — confirmed, the most material of the five

The task asked me to **confirm whether SVI IPs are already covered by
the `interfaces[].ipv4_addresses` walk or live on a separate field**.
**Answer: they live on a separate field — `CanonicalVlan.ipv4_addresses`
(`intent.py:298`) — which `sanitize_intent` NEVER walks.** This is a
real, demonstrable leak, not a theoretical one:

* **Aruba AOS-S** populates `vlan.ipv4_addresses` directly from the
  `vlan N { ip address X/Y }` stanza (`aruba_aoss/parse.py:531,540`).
  The Aruba renderer emits those IPs back from the **vlan record**:
  `addrs = list(vlan.ipv4_addresses)` → `ip address {addr.ip}/...`
  (`aruba_aoss/render.py:606,618-622`). On AOS-S the SVI is a property
  of the VLAN, **not** a sibling `CanonicalInterface`, so the address
  is reachable *only* via the (un-walked) vlans list. A public SVI IP
  on an Aruba VLAN survives `netcanon sanitize` verbatim.
* **Juniper Junos** folds IRB unit addresses onto `vlan.ipv4_addresses`
  (`juniper_junos/parse.py:631,658`) and renders SVI/IRB addressing.
* **Cisco IOS-XE CLI** (`parse.py:1219,1228`) and **Arista EOS**
  (`parse.py:550` comment + SVI synthesis) *copy* the SVI
  `iface.ipv4_addresses` into a synthesised `CanonicalVlan`. Here the
  IP is also on the interface (which *is* walked), but the **copy on
  the vlan record is independent state** and is emitted by the render
  path — so it leaks too.

Because `redact_ipv4` is cache-keyed by the IP string
(`sanitize.py:433-462`), redacting the vlan copy yields the **same**
docs-range substitute the interface copy already got — cross-reference
stability holds automatically (a Cisco/Arista SVI shows the identical
redacted IP on both the `interface Vlan10` and the synthesised vlan
record).

### 1.2 Why the `TestSecretRedactionCoverage` reverse guard does NOT fire

The reverse-introspection guard (`test_sanitize.py:738-762`) matches
field names against `_SECRET_NAME_RE`
(`passphrase|password|secret|community|^authentication$|(^|_)key$`).
None of `contact`, `location`, `host`, `trap_hosts`, `gateway` match
that regex, so adding/omitting their redaction does **not** trip the
guard, and they must **not** be added to `_REGISTERED_SECRET_FIELDS`
(they are PII/network, not secrets — adding them would falsely widen
the secret contract and break the `stale` assertion). Coverage for
these is enforced by a **separate forward test** I add in §4.

---

## 2. Scoping decision — INCLUDE vs deliberately SKIP

### INCLUDE (redact)

| Field | Redaction | Rationale |
|---|---|---|
| `CanonicalSNMP.contact` | `"<contact redacted>"` placeholder | Explicitly named in R-16. Commonly an operator email / name (`admin@corp.example`, `"Jane Doe x4012"`). Free-text PII — mirrors the `description redacted` placeholder pattern, not an IP. |
| `CanonicalSNMP.location` | `"<location redacted>"` placeholder | **Judgment-call inclusion.** Same class as `contact` (operator-supplied free-text identifying the org / physical site — street addresses appear here). CF-04 lists it as a "GAP (minor)". Cheap + consistent; trim if the orchestrator wants strict R-16 scope. |
| `CanonicalSNMP.trap_hosts[]` | `redact_ip_string` (public IPv4 → docs range; private/hostname preserved) | Explicitly named. Trap targets are NMS server IPs — public ones are WAN-identifying. |
| `CanonicalRADIUSServer.host` | `redact_ip_string` (public IPv4 only) | Explicitly named. RADIUS server IP; public-only redaction matches the IP policy everywhere else. Hostname-form hosts preserved (out of scope — see SKIP). |
| `CanonicalDHCPPool.gateway` | `redact_ip_string` (public IPv4 only) | **Judgment-call inclusion.** The clearest DHCP "host" analog and a direct sibling of `static_routes[].gateway`, which IS already redacted (`sanitize.py:362-372`). Almost always private (preserved as no-op); public-only redaction is harmless + symmetric. |

All IP redactions reuse `redact_ip_string` → `redact_ipv4`, so the
existing **private/loopback/link-local/multicast/reserved/docs-range/
CGNAT preservation** rules apply unchanged, and substitutions are
counter-per-session stable + cross-referenced with every other IP.

### SKIP (deliberately, with rationale)

| Field | Why skipped |
|---|---|
| `CanonicalSNMP.trap_hosts` / `radius_servers[].host` **hostname form** | `redact_ip_string` only acts on bare IPv4; a hostname target (`nms.corp.example`) passes through. Redacting arbitrary hostnames here would need a host-name redactor + cross-ref table keyed differently from `hostname`/`domain`. Out of R-16's "public IPs … redact like other public IPv4" framing; left as a documented residual (BUG_REPORTING limitations). |
| `CanonicalDHCPPool.start_ip` / `end_ip` / `network` | Pool addressing, effectively always RFC-1918. `start_ip`/`end_ip` would be no-ops under public-only redaction (private preserved); `network` is CIDR (`192.0.2.0/24`) which `redact_ip_string` can't parse as a bare `IPv4Address` (no-op). Adding them is pure churn with ~zero real-world effect — skipped to keep the diff minimal and the named scope tight. |
| `CanonicalDHCPPool.domain_name` | DNS search domain (PII-ish). The `redact_domain` mapping (`example-N.test`) is cross-ref-keyed against `intent.domain`; wiring a *different* free-text field into it is a scope expansion better handled deliberately. Left as a documented residual. |
| `CanonicalStaticRoute.destination` | Destination prefix (CIDR). Lower-risk network metadata; CIDR not a bare IP. Out of scope. |
| `CanonicalIPv6Address.ip` (interface + any SVI v6) | **Documented separate limitation** — the sanitiser is IPv4-only at v0.1.0 (`SECURITY.md:324-326`, `BUG_REPORTING.md:164-166`). Out of scope by existing decision; NOT touched here. |
| `CanonicalSNMPv3User.engine_id` | Device-derived hex; CF-04 marks acceptable. |
| `CanonicalVxlan.mcast_group` / `flood_list` | Overlay IPs; CF-04 "GAP (minor)". Out of R-16's named scope. |
| `CanonicalIntent.raw_sections` | Separate finding (CF-01 §4.2.2). Latent (no parser populates it). The R-01/CF-01 batch owns the defence-in-depth strip; not duplicated here. |

---

## 3. Apply-ready edits

### 3.1 `netcanon/tools/sanitize.py` — the walk additions

There are **three** insertion points: the SNMP block (contact +
location + trap_hosts), the RADIUS loop (host), and the DHCP loop
(gateway). All are additive — no existing line changes behaviour.

#### Edit 3.1a — SNMP block: add contact + location + trap_hosts

Anchor: the SNMP `if sanitized.snmp:` block. Insert the three new
redactions **immediately after** the existing community block and
**before** the `for j, v3user in ...` loop.

**OLD** (`sanitize.py:291-302`):
```python
    if sanitized.snmp:
        if sanitized.snmp.community:
            new_value = table.redact_community(sanitized.snmp.community)
            subs.append(Substitution(
                category="snmp-community",
                field="snmp.community",
                original=sanitized.snmp.community,
                redacted=new_value,
            ))
            sanitized.snmp.community = new_value

        for j, v3user in enumerate(sanitized.snmp.v3_users):
```

**NEW:**
```python
    if sanitized.snmp:
        if sanitized.snmp.community:
            new_value = table.redact_community(sanitized.snmp.community)
            subs.append(Substitution(
                category="snmp-community",
                field="snmp.community",
                original=sanitized.snmp.community,
                redacted=new_value,
            ))
            sanitized.snmp.community = new_value

        # R-16 / CF-04: SNMP contact + location are operator PII.
        # ``contact`` commonly carries an email / name
        # (``admin@corp.example``, ``"Jane Doe x4012"``); ``location``
        # carries a physical site / street address.  Free-text →
        # opaque placeholder (mirrors the ``description redacted``
        # pattern), NOT an IP redaction.
        if sanitized.snmp.contact:
            redacted_contact = "<contact redacted>"
            subs.append(Substitution(
                category="snmp-contact",
                field="snmp.contact",
                original=sanitized.snmp.contact,
                redacted=redacted_contact,
            ))
            sanitized.snmp.contact = redacted_contact

        if sanitized.snmp.location:
            redacted_location = "<location redacted>"
            subs.append(Substitution(
                category="snmp-location",
                field="snmp.location",
                original=sanitized.snmp.location,
                redacted=redacted_location,
            ))
            sanitized.snmp.location = redacted_location

        # R-16 / CF-04: SNMP trap-target hosts.  Public IPv4 → docs
        # range; private / loopback / hostname forms preserved (same
        # policy as every other IP field).
        new_traps: list[str] = []
        for j, host in enumerate(sanitized.snmp.trap_hosts):
            new_host = table.redact_ip_string(host)
            if new_host != host:
                subs.append(Substitution(
                    category="ipv4-public",
                    field=f"snmp.trap_hosts[{j}]",
                    original=host,
                    redacted=new_host,
                ))
            new_traps.append(new_host)
        sanitized.snmp.trap_hosts = new_traps

        for j, v3user in enumerate(sanitized.snmp.v3_users):
```

#### Edit 3.1b — RADIUS loop: redact `host`

Anchor: the existing RADIUS shared-secret loop. Add a `host` redaction
**before** the existing `if server.key:` check so both fields are
handled in one pass.

**OLD** (`sanitize.py:334-344`):
```python
    # ---- RADIUS shared secrets (canonical field name: ``key``) ----
    for i, server in enumerate(sanitized.radius_servers):
        if server.key:
            new_value = table.redact_secret("RADIUS")
            subs.append(Substitution(
                category="radius-shared-secret",
                field=f"radius_servers[{i}].key",
                original=server.key,
                redacted=new_value,
            ))
            server.key = new_value
```

**NEW:**
```python
    # ---- RADIUS server host + shared secret (field name: ``key``) ----
    for i, server in enumerate(sanitized.radius_servers):
        # R-16 / CF-04: the RADIUS server address is network-
        # identifying.  Public IPv4 → docs range; private / hostname
        # preserved (same IP policy as everywhere else).
        if server.host:
            new_host = table.redact_ip_string(server.host)
            if new_host != server.host:
                subs.append(Substitution(
                    category="ipv4-public",
                    field=f"radius_servers[{i}].host",
                    original=server.host,
                    redacted=new_host,
                ))
                server.host = new_host
        if server.key:
            new_value = table.redact_secret("RADIUS")
            subs.append(Substitution(
                category="radius-shared-secret",
                field=f"radius_servers[{i}].key",
                original=server.key,
                redacted=new_value,
            ))
            server.key = new_value
```

#### Edit 3.1c — DHCP loop: redact `gateway`

Anchor: the existing DHCP-pool dns_servers loop. Add a `gateway`
redaction **after** the dns_servers rebuild, inside the same
`for i, pool in ...` loop.

**OLD** (`sanitize.py:346-359`):
```python
    # ---- DHCP pool DNS servers ----
    for i, pool in enumerate(sanitized.dhcp_servers):
        new_dns = []
        for j, ip in enumerate(pool.dns_servers):
            new_ip = table.redact_ip_string(ip)
            if new_ip != ip:
                subs.append(Substitution(
                    category="ipv4-public",
                    field=f"dhcp_servers[{i}].dns_servers[{j}]",
                    original=ip,
                    redacted=new_ip,
                ))
            new_dns.append(new_ip)
        pool.dns_servers = new_dns
```

**NEW:**
```python
    # ---- DHCP pool DNS servers + gateway ----
    for i, pool in enumerate(sanitized.dhcp_servers):
        new_dns = []
        for j, ip in enumerate(pool.dns_servers):
            new_ip = table.redact_ip_string(ip)
            if new_ip != ip:
                subs.append(Substitution(
                    category="ipv4-public",
                    field=f"dhcp_servers[{i}].dns_servers[{j}]",
                    original=ip,
                    redacted=new_ip,
                ))
            new_dns.append(new_ip)
        pool.dns_servers = new_dns

        # R-16 / CF-04: pool gateway (sibling of the already-redacted
        # static-route gateway).  Public IPv4 → docs range; private
        # preserved (the common case for a LAN default-gateway).
        if pool.gateway:
            new_gw = table.redact_ip_string(pool.gateway)
            if new_gw != pool.gateway:
                subs.append(Substitution(
                    category="ipv4-public",
                    field=f"dhcp_servers[{i}].gateway",
                    original=pool.gateway,
                    redacted=new_gw,
                ))
                pool.gateway = new_gw
```

#### Edit 3.1d — VLAN-SVI IPv4 (the material leak): NEW walk block

There is **no** existing vlans loop in `sanitize_intent`. Add a new
block. Cleanest insertion point: **immediately after the `for i, iface
in enumerate(sanitized.interfaces):` block closes** (i.e. right after
the VRRP-auth redaction at `sanitize.py:259`, before the `# ---- local
users` block at `:261`), so all L3-address redaction is adjacent.

**OLD** (`sanitize.py:259-270` — the seam between the interface loop
and the local-users block):
```python
                group.authentication = new_auth

    # ---- local users (usernames + hashed passwords) ----
    # Phase-3 R6.1: redact the username too.  Operator-chosen
```

**NEW:**
```python
                group.authentication = new_auth

    # ---- VLAN SVI IPv4 addresses ----
    # R-16 / CF-04: SVI L3 addressing lives on ``CanonicalVlan.
    # ipv4_addresses`` (intent.py), a SEPARATE field from
    # ``interfaces[].ipv4_addresses``.  The interface walk above does
    # NOT reach it.  On Aruba AOS-S the SVI is a property of the VLAN
    # (no sibling interface) and renders straight off this list, so a
    # public SVI IP would otherwise survive sanitisation verbatim;
    # Junos IRB folds here too, and Cisco/Arista keep an independent
    # synthesised copy.  ``redact_ipv4`` is cache-keyed by IP string,
    # so a copy that mirrors an interface address resolves to the SAME
    # docs-range substitute (cross-reference stable).
    for i, vlan in enumerate(sanitized.vlans):
        for j, addr in enumerate(vlan.ipv4_addresses):
            new_ip = table.redact_ipv4(addr.ip)
            if new_ip != addr.ip:
                subs.append(Substitution(
                    category="ipv4-public",
                    field=f"vlans[{i}].ipv4_addresses[{j}].ip",
                    original=addr.ip,
                    redacted=new_ip,
                ))
                addr.ip = new_ip

    # ---- local users (usernames + hashed passwords) ----
    # Phase-3 R6.1: redact the username too.  Operator-chosen
```

### 3.2 `netcanon/tools/sanitize.py` — module-docstring rule list

The docstring's "Field-typed rules" list (`sanitize.py:16-46`) must
gain the new rows. Insert after the `CanonicalSNMP.community` line
and extend the RADIUS / DHCP rows.

**OLD** (`sanitize.py:30`):
```python
* ``CanonicalSNMP.community`` → ``public_redacted_N``
```

**NEW:**
```python
* ``CanonicalSNMP.community`` → ``public_redacted_N``
* ``CanonicalSNMP.contact`` → ``<contact redacted>`` (operator PII —
  email / name)
* ``CanonicalSNMP.location`` → ``<location redacted>`` (operator PII —
  site / address)
* ``CanonicalSNMP.trap_hosts`` (public entries) → docs range
```

**OLD** (`sanitize.py:35`):
```python
* ``CanonicalRADIUSServer.key`` → ``REDACTED-RADIUS-N``
```

**NEW:**
```python
* ``CanonicalRADIUSServer.key`` → ``REDACTED-RADIUS-N``
* ``CanonicalRADIUSServer.host`` (public) → docs range
```

**OLD** (`sanitize.py:42-43`):
```python
* ``CanonicalDHCPPool.dns_servers`` (public entries) → docs range
* ``CanonicalStaticRoute.gateway`` (public) → docs range
```

**NEW:**
```python
* ``CanonicalDHCPPool.dns_servers`` (public entries) → docs range
* ``CanonicalDHCPPool.gateway`` (public) → docs range
* ``CanonicalVlan.ipv4_addresses`` (public SVI L3 addresses) → docs
  range — SEPARATE field from ``interfaces[].ipv4_addresses``; the
  Aruba / Junos SVI-on-VLAN model renders these directly
* ``CanonicalStaticRoute.gateway`` (public) → docs range
```

Also extend the docstring **Limitations** block (`sanitize.py:47-58`)
to name the residual host-as-hostname passthrough. Insert after the
existing first limitation bullet (the canonical-model-is-the-AST one,
ending `…banners are typically parse-and-ignore.` at `:53`):

**OLD** (`sanitize.py:51-53`):
```python
  Tier-3 content is dropped on parse, banners are typically
  parse-and-ignore.
```

**NEW:**
```python
  Tier-3 content is dropped on parse, banners are typically
  parse-and-ignore.
* IP-typed redaction (interface / SVI / DHCP / RADIUS / trap-target
  addresses) acts on IPv4 only.  IPv6 addresses and host fields given
  as DNS NAMES (e.g. a RADIUS / trap target of ``nms.corp.example``)
  pass through verbatim — hand-edit those before sharing.
```

### 3.3 `SECURITY.md` § Sanitiser table

**OLD** (`SECURITY.md:311-316`):
```markdown
| SNMP communities | `public_redacted_N` |
| SNMPv3 auth/priv passphrases | `REDACTED-AUTH-N` / `REDACTED-PRIV-N` |
| RADIUS shared secrets | `REDACTED-RADIUS-N` |
| VRRP / CARP / HSRP authentication keys | `<scheme>:REDACTED-VRRP-AUTH-N` (scheme prefix preserved, secret value redacted) |
| Interface descriptions | `description redacted` |
| Tier-3 sections (firewall / NAT / VPN) | Stripped entirely |
```

**NEW:**
```markdown
| SNMP communities | `public_redacted_N` |
| SNMP contact / location (operator PII) | `<contact redacted>` / `<location redacted>` |
| SNMPv3 auth/priv passphrases | `REDACTED-AUTH-N` / `REDACTED-PRIV-N` |
| RADIUS shared secrets | `REDACTED-RADIUS-N` |
| RADIUS server / SNMP trap-target / DHCP-gateway hosts (public IPv4) | RFC 5737 docs ranges |
| VLAN-SVI IPv4 addresses (public) | RFC 5737 docs ranges |
| VRRP / CARP / HSRP authentication keys | `<scheme>:REDACTED-VRRP-AUTH-N` (scheme prefix preserved, secret value redacted) |
| Interface descriptions | `description redacted` |
| Tier-3 sections (firewall / NAT / VPN) | Stripped entirely |
```

Update the known-limitations pointer just below the table to name the
hostname residual.

**OLD** (`SECURITY.md:323-326`):
```markdown
Known limitations are listed in
[`BUG_REPORTING.md`](BUG_REPORTING.md) — notably IPv6-public redaction
is IPv4-only at v0.1.0; banner / comment text is parse-and-ignored
rather than redacted.
```

**NEW:**
```markdown
Known limitations are listed in
[`BUG_REPORTING.md`](BUG_REPORTING.md) — notably IPv6-public redaction
is IPv4-only at v0.1.0; host fields given as DNS names (a RADIUS / trap
target like `nms.corp.example`) pass through; banner / comment text is
parse-and-ignored rather than redacted.
```

### 3.4 `BUG_REPORTING.md` § "What gets sanitised" table + limitations

**OLD** (`BUG_REPORTING.md:143-149`):
```markdown
| SNMP communities | `public_redacted_N` |
| SNMPv3 user names (USM securityName) | `snmpv3userN` (independent counter from local-user-name) |
| SNMPv3 auth/priv passphrases | `REDACTED-AUTH-N` / `REDACTED-PRIV-N` |
| RADIUS shared secrets | `REDACTED-RADIUS-N` |
| VRRP / CARP / HSRP authentication keys | `<scheme>:REDACTED-VRRP-AUTH-N` (scheme prefix preserved, secret value redacted) |
| Interface descriptions | `description redacted` |
| Tier-3 sections (firewall, NAT, VPN) | Stripped entirely |
```

**NEW:**
```markdown
| SNMP communities | `public_redacted_N` |
| SNMP contact / location (operator PII — email / name / site) | `<contact redacted>` / `<location redacted>` |
| SNMPv3 user names (USM securityName) | `snmpv3userN` (independent counter from local-user-name) |
| SNMPv3 auth/priv passphrases | `REDACTED-AUTH-N` / `REDACTED-PRIV-N` |
| RADIUS shared secrets | `REDACTED-RADIUS-N` |
| RADIUS server / SNMP trap-target / DHCP-gateway hosts | Public IPv4 → docs ranges; private / hostname preserved |
| VLAN-SVI IPv4 addresses (the VLAN interface's L3 config) | Public IPv4 → docs ranges; private preserved |
| VRRP / CARP / HSRP authentication keys | `<scheme>:REDACTED-VRRP-AUTH-N` (scheme prefix preserved, secret value redacted) |
| Interface descriptions | `description redacted` |
| Tier-3 sections (firewall, NAT, VPN) | Stripped entirely |
```

Add a limitations bullet for the hostname residual. The IPv6 bullet
already exists (`BUG_REPORTING.md:164-166`) — leave it; add one more
after it.

**OLD** (`BUG_REPORTING.md:164-166`):
```markdown
- **IPv6-public redaction is IPv4-only at v0.1.0.**  IPv6 addresses
  pass through verbatim.  If your config has public IPv6 addresses,
  hand-redact those before submitting.
```

**NEW:**
```markdown
- **IPv6-public redaction is IPv4-only at v0.1.0.**  IPv6 addresses
  pass through verbatim.  If your config has public IPv6 addresses,
  hand-redact those before submitting.
- **Host fields given as DNS names pass through.**  IP-typed
  redaction (RADIUS server, SNMP trap target, DHCP gateway) acts on
  bare IPv4 only; a target written as a hostname (`nms.corp.example`)
  is preserved.  Hand-edit name-form hosts if they are identifying.
```

> **Note for the orchestrator on "Known limitations" pruning.** The
> task said "remove the now-addressed items from any 'Known
> limitations'." I checked both docs — neither `SECURITY.md` nor
> `BUG_REPORTING.md` currently lists `snmp.contact` / SVI-IP /
> RADIUS-host as a *known limitation* (these gaps were never
> documented; CF-04 §4.2 notes they were silent). So there is **nothing
> to remove** — the edits above are purely additive (new coverage rows
> + one new hostname-residual limitation). The only "limitation" that
> stays is IPv6, which remains correct.

---

## 4. Test plan

### 4.1 Tests to run

```
py -m pytest tests/unit/tools/test_sanitize.py -q
```

Plus the two-sided secret guard must stay green (proves the new PII
fields did NOT get mis-registered as secrets):

```
py -m pytest tests/unit/tools/test_sanitize.py::TestSecretRedactionCoverage -q
```

Full unit lane as a regression check (the canonical model + every codec
render path are exercised indirectly):

```
py -m pytest -m unit -q
```

### 4.2 New test cases — full content

Append the following to `tests/unit/tools/test_sanitize.py`. It adds
two import lines and four new test classes. The imports `CanonicalSNMP`,
`CanonicalDHCPPool`, `CanonicalRADIUSServer`, `CanonicalIPv4Address`,
`CanonicalInterface`, `CanonicalIntent` are **already imported** at the
top of the file (`test_sanitize.py:30-41`); only `CanonicalVlan` is new.

**Add to the existing import block** (`test_sanitize.py:30-41`):

**OLD:**
```python
from netcanon.migration.canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIPv4Address,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLocalUser,
    CanonicalRADIUSServer,
    CanonicalSNMP,
    CanonicalSNMPv3User,
    CanonicalStaticRoute,
    CanonicalVRRPGroup,
)
```

**NEW:**
```python
from netcanon.migration.canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIPv4Address,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLocalUser,
    CanonicalRADIUSServer,
    CanonicalSNMP,
    CanonicalSNMPv3User,
    CanonicalStaticRoute,
    CanonicalVlan,
    CanonicalVRRPGroup,
)
```

**Append at the end of the file** (after `TestSecretRedactionCoverage`,
i.e. after `test_sanitize.py:762`):

```python
# ---------------------------------------------------------------------------
# R-16 / CF-04 — PII / network tail redaction
#
# Non-secret-but-identifying fields the sanitiser previously left
# untouched: SNMP contact/location (operator PII), SNMP trap-target +
# RADIUS server + DHCP-gateway hosts (public IPv4), and VLAN-SVI IPv4
# (a SEPARATE canonical field from interfaces[].ipv4_addresses).
#
# These are PII/network, not secrets, so they are intentionally NOT in
# _REGISTERED_SECRET_FIELDS and do NOT trip TestSecretRedactionCoverage
# (that guard introspects secret-NAMED fields only).  This forward
# block is the durable "these PII fields don't survive" check.
# ---------------------------------------------------------------------------


class TestSNMPContactLocationRedaction:
    """SNMP contact (email/name) + location (site/address) are operator
    PII.  Free-text → opaque placeholder, not an IP redaction."""

    def test_contact_redacted_to_placeholder(self):
        intent = CanonicalIntent(
            snmp=CanonicalSNMP(community="", contact="admin@corp.example")
        )
        sanitized, subs = sanitize_intent(intent)
        assert sanitized.snmp.contact == "<contact redacted>"
        assert "admin@corp.example" not in sanitized.snmp.contact
        assert any(
            s.category == "snmp-contact" and s.original == "admin@corp.example"
            for s in subs
        )

    def test_location_redacted_to_placeholder(self):
        intent = CanonicalIntent(
            snmp=CanonicalSNMP(community="", location="Rack 7, 12 Real Street")
        )
        sanitized, subs = sanitize_intent(intent)
        assert sanitized.snmp.location == "<location redacted>"
        assert any(s.category == "snmp-location" for s in subs)

    def test_empty_contact_and_location_no_substitution(self):
        intent = CanonicalIntent(snmp=CanonicalSNMP(community="x"))
        sanitized, subs = sanitize_intent(intent)
        assert sanitized.snmp.contact == ""
        assert sanitized.snmp.location == ""
        assert not any(s.category == "snmp-contact" for s in subs)
        assert not any(s.category == "snmp-location" for s in subs)


class TestSNMPTrapHostRedaction:
    """SNMP trap-target hosts: public IPv4 → docs range, private
    preserved, hostname preserved."""

    def test_public_trap_host_redacted_private_preserved(self):
        intent = CanonicalIntent(
            snmp=CanonicalSNMP(
                community="",
                trap_hosts=["8.8.8.8", "192.168.50.5"],
            )
        )
        sanitized, subs = sanitize_intent(intent)
        assert sanitized.snmp.trap_hosts[0] != "8.8.8.8"
        assert sanitized.snmp.trap_hosts[0].startswith(
            ("192.0.2.", "198.51.100.", "203.0.113.")
        )
        assert sanitized.snmp.trap_hosts[1] == "192.168.50.5"  # private kept
        assert len([s for s in subs if s.category == "ipv4-public"]) == 1

    def test_hostname_trap_target_preserved(self):
        intent = CanonicalIntent(
            snmp=CanonicalSNMP(community="", trap_hosts=["nms.corp.example"])
        )
        sanitized, _ = sanitize_intent(intent)
        # Documented residual: name-form hosts pass through.
        assert sanitized.snmp.trap_hosts[0] == "nms.corp.example"


class TestRADIUSHostRedaction:
    """RADIUS server host: public IPv4 → docs range, private preserved.
    Complements the existing key-redaction test."""

    def test_public_host_redacted(self):
        intent = CanonicalIntent(
            radius_servers=[
                CanonicalRADIUSServer(host="203.0.113.200", key="s"),
                CanonicalRADIUSServer(host="9.9.9.9", key="s2"),
            ]
        )
        sanitized, subs = sanitize_intent(intent)
        # 203.0.113.x is already a docs range -> preserved as-is.
        assert sanitized.radius_servers[0].host == "203.0.113.200"
        # 9.9.9.9 is public -> redacted.
        assert sanitized.radius_servers[1].host != "9.9.9.9"
        assert sanitized.radius_servers[1].host.startswith(
            ("192.0.2.", "198.51.100.", "203.0.113.")
        )
        assert any(
            s.category == "ipv4-public"
            and s.field == "radius_servers[1].host"
            for s in subs
        )

    def test_private_host_preserved(self):
        intent = CanonicalIntent(
            radius_servers=[CanonicalRADIUSServer(host="10.0.0.5", key="s")]
        )
        sanitized, _ = sanitize_intent(intent)
        assert sanitized.radius_servers[0].host == "10.0.0.5"


class TestDHCPGatewayRedaction:
    """DHCP pool gateway: sibling of the already-redacted static-route
    gateway.  Public IPv4 → docs range; private (the common case)
    preserved."""

    def test_public_gateway_redacted_private_preserved(self):
        intent = CanonicalIntent(
            dhcp_servers=[
                CanonicalDHCPPool(network="10.0.0.0/24", gateway="1.1.1.1"),
                CanonicalDHCPPool(network="10.1.0.0/24", gateway="10.1.0.1"),
            ]
        )
        sanitized, subs = sanitize_intent(intent)
        assert sanitized.dhcp_servers[0].gateway != "1.1.1.1"
        assert sanitized.dhcp_servers[1].gateway == "10.1.0.1"  # private kept
        assert any(
            s.field == "dhcp_servers[0].gateway" for s in subs
        )


class TestVlanSviIPv4Redaction:
    """The material R-16 leak: SVI L3 addresses live on
    CanonicalVlan.ipv4_addresses — a SEPARATE field the interface walk
    never reaches.  On Aruba / Junos these render straight off the VLAN
    record, so a public SVI IP previously survived sanitisation."""

    def test_public_svi_ip_redacted_private_preserved(self):
        intent = CanonicalIntent(
            vlans=[
                CanonicalVlan(
                    id=10,
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="8.8.4.4", prefix_length=24),
                        CanonicalIPv4Address(ip="192.168.10.1", prefix_length=24),
                    ],
                )
            ]
        )
        sanitized, subs = sanitize_intent(intent)
        svi = sanitized.vlans[0].ipv4_addresses
        assert svi[0].ip != "8.8.4.4"
        assert svi[0].ip.startswith(("192.0.2.", "198.51.100.", "203.0.113."))
        assert svi[1].ip == "192.168.10.1"  # private SVI gateway preserved
        assert any(
            s.category == "ipv4-public"
            and s.field == "vlans[0].ipv4_addresses[0].ip"
            for s in subs
        )

    def test_svi_copy_matches_interface_copy_cross_reference(self):
        """Cisco/Arista keep an independent synthesised vlan copy of the
        SVI interface address.  Because redact_ipv4 is cache-keyed by IP
        string, the same public IP on both the interface and the vlan
        record resolves to the SAME docs-range substitute."""
        shared_ip = "203.0.113.0"  # not a docs host (last octet 0); still public-shaped
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="Vlan10",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="11.22.33.44", prefix_length=24)
                    ],
                )
            ],
            vlans=[
                CanonicalVlan(
                    id=10,
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="11.22.33.44", prefix_length=24)
                    ],
                )
            ],
        )
        sanitized, _ = sanitize_intent(intent)
        iface_ip = sanitized.interfaces[0].ipv4_addresses[0].ip
        vlan_ip = sanitized.vlans[0].ipv4_addresses[0].ip
        assert iface_ip != "11.22.33.44"
        assert vlan_ip == iface_ip  # cross-reference stable


class TestPiiTailRenderedOutputClean:
    """End-to-end: sanitize_intent -> render must not emit the original
    PII.  Exercises the Aruba SVI-on-VLAN render path (the field that
    leaked) plus SNMP contact."""

    def test_aruba_svi_and_contact_absent_from_render(self):
        from netcanon.migration.codecs.registry import get_codec

        intent = CanonicalIntent(
            hostname="r1",
            vlans=[
                CanonicalVlan(
                    id=10,
                    name="USERS",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="9.9.9.9", prefix_length=24)
                    ],
                )
            ],
            snmp=CanonicalSNMP(community="", contact="admin@corp.example"),
        )
        sanitized, _ = sanitize_intent(intent)
        rendered = get_codec("aruba_aoss").render(sanitized)
        assert "9.9.9.9" not in rendered            # SVI leak closed
        assert "admin@corp.example" not in rendered   # contact leak closed
```

> One assertion to watch at actuation: `test_aruba_svi_and_contact_absent_from_render`
> assumes the Aruba renderer emits the synthesised-VLAN SVI address and
> the SNMP contact line for this minimal tree. Both paths are confirmed
> present (`aruba_aoss/render.py:606,618-622` for SVI; `:414-415` for
> contact). If Aruba's render gates the vlan stanza on extra fields the
> minimal tree doesn't set, swap the codec to `juniper_junos` (which
> renders IRB addresses + `set snmp contact`) — the assertion is
> codec-agnostic. Verify at apply time.

---

## 5. Risk + blast radius

* **Additive only.** Every edit adds a new redaction branch or a new
  docstring/doc row; no existing line changes behaviour. The five new
  IP redactions reuse `redact_ip_string` / `redact_ipv4` verbatim, so
  the established private/loopback/docs/CGNAT preservation and
  counter-per-session stability are inherited unchanged.
* **No new `_SubstitutionTable` state.** Contact/location use inline
  literals (like `description redacted`); the IP fields reuse the
  existing `_ipv4` cache. No new dict, no new counter — zero risk to
  the counter-numbering invariants the existing tests pin.
* **Secret-guard untouched.** `_REGISTERED_SECRET_FIELDS` is NOT
  modified (these are PII/network, not secrets). `TestSecretRedactionCoverage`
  stays green — verified the new field names don't match `_SECRET_NAME_RE`.
* **Round-trip fidelity.** SVI/RADIUS/DHCP IPs render in the same docs
  ranges the interface IPs already use, so the sanitised config remains
  a valid same-vendor reshape. The contact/location placeholders are
  free-text values the renderers emit inside quotes
  (`snmp-server contact "<contact redacted>"`, etc.) — syntactically
  valid; non-functional by design (matches the "deliberately
  non-functional placeholder" banner promise in BUG_REPORTING §A).
* **Substitution-count drift.** The end-to-end fixture test
  (`TestSanitizeTextEndToEnd`) asserts `len(substitutions) > 0` (not an
  exact count), so more substitutions won't break it. No test pins an
  exact total.
* **Lowest-risk omissions are documented**, not silent: the hostname-
  form host residual + the IPv4-only scope are now in both
  `SECURITY.md` and `BUG_REPORTING.md` limitations.

---

## 6. Self-assessment

**Confidence: HIGH** that the five named fields leak (traced parse →
render across all codecs that populate them) and that the redactions
are correct + additive. **HIGH** specifically on the VLAN-SVI leak
being real and material — the Aruba SVI-on-VLAN render path
(`render.py:606`) reads straight off the un-walked `vlan.ipv4_addresses`
list, so a public SVI IP demonstrably survives today.

**MEDIUM** on two judgment-call inclusions, both flagged inline for the
orchestrator:
1. **`snmp.location`** — not named in R-16; included because it's the
   same PII class as `contact` and trivially adjacent. Trim if you want
   strict-scope (delete the location branch in 3.1a + its docstring/doc
   rows + `test_location_redacted_to_placeholder`).
2. **DHCP `gateway`** — included as the clearest DHCP "host" analog and
   a direct sibling of the already-redacted static-route gateway;
   almost always a private no-op in practice.

**Open questions for the orchestrator:**
1. **Accept `snmp.location` + DHCP `gateway`?** Both are defensible but
   beyond R-16's literal "contact / SVI / RADIUS-trap-DHCP-hosts" list.
   Easy to drop without touching the rest.
2. **Hostname-form hosts** (RADIUS / trap target as a DNS name) are left
   passing through, documented as a limitation. If you'd rather redact
   them too, that needs a new host-name redactor + cross-ref table —
   bigger than R-16; recommend a follow-up finding rather than folding
   it in here.
3. **`raw_sections` strip** — deliberately NOT duplicated here; it's
   CF-01 §4.2.2's defence-in-depth item and belongs in the R-01/CF-01
   batch. Confirm that batch owns it so it doesn't fall between stools.
4. **`TestPiiTailRenderedOutputClean` codec choice** — verify Aruba
   renders the minimal SVI tree at apply time; fallback to Junos noted
   inline if Aruba gates the vlan stanza.

---

## 7. Return summary

* **Result path:** `docs/project-review/2026-06-06/remediation-sweep/result-RA-16.md`
* **Fields redacted (INCLUDE):**
  * `CanonicalSNMP.contact` → `<contact redacted>` (PII placeholder)
  * `CanonicalSNMP.location` → `<location redacted>` (PII placeholder; judgment-call)
  * `CanonicalSNMP.trap_hosts[]` → public IPv4 to docs range
  * `CanonicalRADIUSServer.host` → public IPv4 to docs range
  * `CanonicalDHCPPool.gateway` → public IPv4 to docs range (judgment-call)
  * `CanonicalVlan.ipv4_addresses[].ip` (SVI) → public IPv4 to docs range — **the material leak; was a separate, un-walked field**
* **Deliberately SKIPPED (+ why):**
  * IPv6 everywhere — documented pre-existing IPv4-only limitation
  * Hostname-form RADIUS/trap hosts — out of "public IPs" scope; needs a host-name redactor (documented residual)
  * DHCP `start_ip`/`end_ip`/`network`/`domain_name`, `static_routes[].destination` — near-zero real effect (private/CIDR/no-op) or scope creep
  * `engine_id`, VXLAN overlay IPs — CF-04 "minor/acceptable"
  * `raw_sections` — belongs to the CF-01 batch (latent; no parser populates it)
* **"Known limitations" pruning:** nothing to remove — these gaps were never documented; all doc edits are additive (new coverage rows + one new hostname-residual limitation).
* **Confidence:** HIGH on the leak set + correctness; MEDIUM on the two judgment-call inclusions (flagged for accept/trim).
* **Blockers:** none. Two apply-time checks flagged: (a) confirm the Aruba render path in the end-to-end test (Junos fallback noted), (b) accept/trim `snmp.location` + DHCP `gateway`.
