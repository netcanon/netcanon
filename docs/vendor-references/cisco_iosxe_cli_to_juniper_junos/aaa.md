# AAA (RADIUS / TACACS+): Cisco IOS-XE versus Juniper Junos

How RADIUS and TACACS+ servers are declared.

Sources:
- Cisco: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/security/m1/sec-m1-cr-book/sec-cr-r1.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/radius-server-edit-system.html (retrieved 2026-04-30)
- Juniper (TACACS+): https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/tacplus-server-edit-system.html (retrieved 2026-04-30)

Citation ids: `cisco-aaa-cli`, `junos-radius-cli`, `junos-tacplus-cli`.

## Cisco IOS-XE form

Modern RADIUS server configuration (named-server form):

```
radius server NPS1
 address ipv4 10.0.0.20 auth-port 1812 acct-port 1813
 key 7 <obfuscated>

aaa group server radius CORP-RADIUS
 server name NPS1

aaa authentication login default group CORP-RADIUS local
```

Legacy positional form (still accepted):

```
radius-server host 10.0.0.20 auth-port 1812 acct-port 1813 key SecretValue
```

TACACS+:

```
tacacs server CORP-TACACS
 address ipv4 10.0.0.21
 key 7 <obfuscated>
```

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
separate `set` line.

## Mapping notes

- **Canonical surface.** `CanonicalRADIUSServer{host, key,
  auth_port, acct_port}` carries the cross-vendor RADIUS surface.
  TACACS+ has no canonical model in v1.
- **RADIUS round-trip.** Both vendors round-trip host, secret,
  auth/acct port cleanly.  Cisco emits the key with a type-7
  obfuscation marker (`key 7 <hex>`); Junos emits it as `$9$...`
  reversible-encrypted.  Bytes do NOT cross-decrypt.  Operator
  must re-set the shared secret on the target.
- **Named-server versus IP-keyed.** Cisco's modern `radius server
  <name> / address ipv4` form parses to the same canonical
  `host: <addr>` as Junos's IP-keyed form; the named handle is
  Cisco-internal.  Group structure (`aaa group server radius`) is
  not modelled canonically.
- **Authentication ordering.** Cisco's `aaa authentication login
  default group ... local` and Junos's `set system
  authentication-order [ radius password ]` are not modelled
  canonically; the codec parsers ignore the ordering directive.
- **TACACS+ deferred.** No `CanonicalTACACSServer` in v1; both
  codecs would parse-and-ignore TACACS+ blocks today.

Disposition: **lossy** on RADIUS (key bytes don't cross-decrypt;
re-key required); **unsupported** on TACACS+ (no canonical model).
