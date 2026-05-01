# RADIUS / AAA: MikroTik RouterOS versus Cisco IOS-XE

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

`service=` is a comma-separated list of RouterOS services that
authenticate against this server (`login`, `ppp`, `wireless`,
`hotspot`, `dhcp`, `ipsec`).

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
```

## Cross-vendor mapping

The canonical surface is

```
CanonicalRADIUSServer(host, key, auth_port, acct_port)
```

### MikroTik -> Cisco round-trip

`host` / `auth_port` / `acct_port` round-trip cleanly.

`key` (shared secret): RouterOS's `secret=` is opaque (not
hash-encoded; just whatever the operator typed).  Cisco's
`key 7 ...` form auto-obfuscates plaintext on entry; if the
RouterOS source provides plaintext, the Cisco render stamps it
verbatim and the receiving Cisco device may auto-encode on
write.  Cross-vendor round-trip-equivalent in semantic but the
on-disk byte representation differs.

`service=` (RouterOS) / method-list + server-group (Cisco) is
not modelled canonically.  Cisco render emits a default `aaa
authentication login default group radius local` line; richer
RouterOS service bindings drop to `raw_sections`.

### Disposition

| Field | Disposition (MikroTik -> Cisco) |
|---|---|
| `radius_servers[].host` | good |
| `radius_servers[].key` | lossy (vendor-specific secret encoding) |
| `radius_servers[].auth_port` | good |
| `radius_servers[].acct_port` | good |
| Service-binding (RouterOS) / method-list (Cisco) | unsupported (no canonical model) |
