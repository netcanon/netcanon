# AAA / TACACS+ / RADIUS: Cisco IOS-XE versus Arista EOS

## Cisco IOS-XE

Source: Cisco IOS XE Security Configuration Guide — AAA / TACACS+ /
RADIUS server config.

```
aaa new-model
aaa authentication login default group tacacs+ local
aaa authorization exec default group tacacs+ local
aaa accounting exec default start-stop group tacacs+

tacacs server PRIMARY
 address ipv4 10.0.0.10
 key 7 0822455D0A16
 timeout 5

radius server PRIMARY
 address ipv4 10.0.0.20 auth-port 1812 acct-port 1813
 key 7 0822455D0A16
```

The legacy single-line forms (`tacacs-server host 10.0.0.10 key XXX`,
`radius-server host 10.0.0.20 ...`) are still accepted but deprecated.

## Arista EOS

Source: [EOS 4.36.0F — User Security (AAA / TACACS+ / RADIUS)](https://www.arista.com/en/um-eos/eos-user-security)
Retrieved: 2026-04-30

```
aaa authentication login default group tacacs+ local
aaa authorization commands all default local
aaa accounting exec default start-stop group tacacs+

tacacs-server host 10.0.0.10 key 7 0822455D0A16 timeout 5
radius-server host 10.0.0.20 auth-port 1812 acct-port 1813 key 7 0822455D0A16

aaa group server tacacs+ TACGRP
 server 10.0.0.10
```

Arista keeps the single-line `tacacs-server host` / `radius-server
host` form as the primary syntax (no nested config block by default,
though group-based variants exist).

## Cross-vendor mapping

The canonical surface is `CanonicalRADIUSServer`:

```
class CanonicalRADIUSServer(BaseModel):
    host: str
    key: str = ""             # shared secret (opaque)
    auth_port: int = 1812
    acct_port: int = 1813
```

Both codecs declare RADIUS server parsing in their capability
matrices.  TACACS+ has no equivalent canonical model in v1 —
`CanonicalTACACSServer` does not exist; TACACS+ config is currently
parse-and-ignore on both codecs, landing as `raw_sections` text.

Quoting the Arista codec capability matrix:

```
"/aaa/authentication/users/user/config/username",
"/aaa/authentication/users/user/config/password",
"/aaa/authentication/users/user/config/role",
```

These cover the local user surface (already documented in
`local_users.md`); they do NOT cover external AAA servers.

Disposition for RADIUS server records: **good** (canonical surface
is small; both vendors round-trip the host / key / port tuple).

Disposition for TACACS+: **unsupported** (no canonical model;
parse-and-ignore on both vendors).  Reason: deferred to subsequent
audit pass.

Disposition for `aaa authentication / authorization / accounting`
policy lines: **unsupported** (no canonical model; lands in
`raw_sections` for display).  Reason: cross-vendor policy semantics
diverge subtly (Cisco's `aaa new-model` toggle has no Arista
equivalent; Arista's `aaa authorization commands all` has no Cisco
equivalent without explicit `aaa authorization commands <level>`).
