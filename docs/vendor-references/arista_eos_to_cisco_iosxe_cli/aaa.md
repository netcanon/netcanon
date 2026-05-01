# AAA / TACACS+ / RADIUS: Arista EOS versus Cisco IOS-XE

## Arista EOS

Source: [EOS 4.36.0F — User Security (Authentication, Authorization, Accounting)](https://www.arista.com/en/um-eos/eos-user-security)
Retrieved: 2026-04-30

RADIUS server config (legacy single-line form):

```
radius-server host 10.0.0.10 key 7 SecretBlob
radius-server host 10.0.0.10 auth-port 1812 acct-port 1813 key 7 SecretBlob
```

TACACS+ server config:

```
tacacs-server host 10.0.0.20 key 7 TacSecretBlob
tacacs-server host 10.0.0.20 single-connection
```

AAA method-list selection:

```
aaa authentication login default group radius local
aaa authorization exec default group tacacs+ local
aaa accounting commands all default start-stop group tacacs+
```

## Cisco IOS-XE

Source: [Cisco IOS XE Security Command Reference — RADIUS / TACACS+](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/security/m1/sec-cr-m1.html)
Retrieved: 2026-04-30

Modern Cisco IOS-XE uses a named-server form:

```
radius server PRIMARY
 address ipv4 10.0.0.10 auth-port 1812 acct-port 1813
 key SecretBlob

aaa group server radius RAD-GROUP
 server name PRIMARY
```

Legacy single-line form (still accepted):

```
radius-server host 10.0.0.10 auth-port 1812 acct-port 1813 key SecretBlob
```

TACACS+:

```
tacacs server PRIMARY-T
 address ipv4 10.0.0.20
 key TacSecretBlob

aaa group server tacacs+ TAC-GROUP
 server name PRIMARY-T
```

AAA method-list selection:

```
aaa authentication login default group radius local
aaa authorization exec default group tacacs+ local
aaa accounting commands 15 default start-stop group tacacs+
```

## Cross-vendor mapping

The canonical model is `CanonicalRADIUSServer`:

```
class CanonicalRADIUSServer(BaseModel):
    host: str
    key: str = ""                   # shared secret (opaque)
    auth_port: int = 1812
    acct_port: int = 1813
```

This covers RADIUS adequately for the cross-vendor surface (host /
key / auth_port / acct_port).  Round-trip is good for the canonical
fields:

- Arista source: `radius-server host <ip> [auth-port N] [acct-port N]
  [key X]` parses to a `CanonicalRADIUSServer`.
- Cisco target: render emits the modern named-server form (`radius
  server <name> / address ipv4 <ip> / key X`) using a synthetic
  server name derived from the host.

TACACS+ servers: NO canonical model exists in v1
(`CanonicalTACACSServer` not yet defined).  Tacacs config silently
drops on round-trip in either direction.

AAA method lists: also NO canonical model.  All `aaa authentication`
/ `aaa authorization` / `aaa accounting` lines parse-and-ignore on
both codecs.

Shared-secret encoding: Arista's `key 7 <blob>` carries a Type-7
reversible obfuscation; Cisco accepts the same `7 <blob>` form.  Both
codecs pass the opaque blob through verbatim.

Disposition: **good** for RADIUS host/key/ports surface; **lossy**
for AAA method lists and TACACS+ (canonical model gap).
