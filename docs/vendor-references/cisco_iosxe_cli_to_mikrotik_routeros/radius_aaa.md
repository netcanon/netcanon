# RADIUS / AAA: Cisco IOS-XE versus MikroTik RouterOS

## Cisco IOS-XE

Source: Cisco IOS XE Security Configuration Guide — RADIUS.

Modern (named) form:

```
radius server PRIMARY
 address ipv4 10.0.0.10 auth-port 1812 acct-port 1813
 key 7 0822455D0A16

aaa group server radius CORP-RADIUS
 server name PRIMARY

aaa authentication login default group CORP-RADIUS local
aaa authorization exec default group CORP-RADIUS local
```

Legacy global form (still accepted):

```
radius-server host 10.0.0.10 auth-port 1812 acct-port 1813 key 7 0822455D
```

## MikroTik RouterOS

Source: [RADIUS Client — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/13402205/RADIUS)

Retrieved: 2026-04-30

```
/radius
add address=10.0.0.10 secret=S3cretKey service=login,ppp,wireless \
    authentication-port=1812 accounting-port=1813 \
    timeout=300ms

/user aaa
set use-radius=yes default-group=read
```

Two structural differences:

- RouterOS's `/radius` entry takes a `service=` parameter (a
  comma-separated list of which RouterOS services authenticate
  against this server).  Cisco's `aaa group server radius / aaa
  authentication ...` chain is conceptually equivalent but lives
  in a separate plane (server group definition + per-service
  method-list).
- RouterOS stores the shared secret as opaque on `secret=`;
  `/export` redacts it by default unless `show-sensitive` is
  passed.  Cisco emits the secret as a type-7-obfuscated blob via
  `key 7 ...` (reversible obfuscation, not encryption).

## Cross-vendor mapping

The canonical surface is

```
CanonicalRADIUSServer(host, key: str, auth_port: int, acct_port: int)
```

Both codecs round-trip the four-field tuple cleanly.  Default port
semantics are identical (1812 auth, 1813 acct).

### Lossy points

- **Shared secret**: Cisco's type-7 obfuscation can be reversed to
  plaintext; RouterOS's `secret=` is stored verbatim.  Cross-vendor
  migration would require a re-keying step if the operator wants
  to break the obfuscation chain.  In practice, both codecs
  pass-through the opaque blob; the receiving vendor's RADIUS
  daemon will reject if it does not match the server's expectation,
  and the operator re-enters the secret.
- **Service-binding (RouterOS) vs server-group/method-list (Cisco)**:
  RouterOS's `service=login,ppp,wireless` and Cisco's `aaa group
  server / aaa authentication login default group ... local`
  express the same operator intent but live on different sides of
  the canonical scope.  Neither shape is modelled today; cross-
  vendor render emits a default service binding and the rich
  Cisco method-list lands in `raw_sections`.

### Disposition

| Field | Disposition |
|---|---|
| `radius_servers[].host` | good |
| `radius_servers[].key` | lossy (vendor-specific encoding; effectively re-key on migration) |
| `radius_servers[].auth_port` | good |
| `radius_servers[].acct_port` | good |
| Server-group / method-list (Cisco) / service-binding (MikroTik) | unsupported (no canonical model) |

TACACS+ servers have no canonical model in v1; both codecs leave
TACACS+ entries in `raw_sections`.
