# AAA (RADIUS / TACACS+): Juniper Junos versus Cisco IOS-XE

Sources:
- Juniper (RADIUS): https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/radius-server-edit-system.html (retrieved 2026-04-30)
- Juniper (TACACS+): https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/tacplus-server-edit-system.html (retrieved 2026-04-30)
- Cisco: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/security/m1/sec-m1-cr-book/sec-cr-r1.html (retrieved 2026-04-30)

Citation ids: `junos-radius-cli`, `junos-tacplus-cli`, `cisco-aaa-cli`.

## Junos form

```
set system radius-server 10.0.0.20 secret "$9$..."
set system radius-server 10.0.0.20 port 1812
set system radius-server 10.0.0.20 accounting-port 1813
set system authentication-order [ radius password ]

set system tacplus-server 10.0.0.21 secret "$9$..."
set system tacplus-server 10.0.0.21 port 49
```

Junos addresses servers by IP (not by name); each property is a
separate `set` line.  Secrets are stored in the `$9$...`
reversible-encrypted form.

## Cisco IOS-XE form

```
radius server NPS1
 address ipv4 10.0.0.20 auth-port 1812 acct-port 1813
 key 7 <obfuscated>

aaa group server radius CORP-RADIUS
 server name NPS1

aaa authentication login default group CORP-RADIUS local

tacacs server CORP-TACACS
 address ipv4 10.0.0.21
 key 7 <obfuscated>
```

Cisco's modern named-server form (`radius server <name>`)
deprecates the legacy positional form (`radius-server host
<addr> ...`).

## Mapping notes

- **Canonical surface.** `CanonicalRADIUSServer{host, key,
  auth_port, acct_port}` carries cross-vendor RADIUS surface.
  TACACS+ has no canonical model in v1.
- **RADIUS round-trip.** Both vendors round-trip host, secret,
  auth/acct port cleanly.  Bytes do NOT cross-decrypt between
  Junos `$9$...` and Cisco type-7; operator must re-set the
  shared secret on the target.
- **Named-server versus IP-keyed.** Junos's IP-keyed form maps
  directly to canonical `host: <addr>`; Cisco's modern named-
  server form parses the IP via the inner `address ipv4` line.
  Group structure (`aaa group server radius`) is not modelled
  canonically.
- **Authentication ordering.** Junos's `set system
  authentication-order [ radius password ]` and Cisco's `aaa
  authentication login default group ... local` are not modelled
  canonically; the codec parsers ignore the ordering directive.
- **TACACS+ deferred.** No `CanonicalTACACSServer` in v1; both
  codecs would parse-and-ignore TACACS+ blocks today.

Disposition: **lossy** on RADIUS (key bytes don't cross-decrypt;
re-key required); **unsupported** on TACACS+ (no canonical model).
