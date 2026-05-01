# System services — NETCONF source rendered to IOS-XE CLI

For full bidirectional content (CLI form, openconfig-system XML form)
see the sibling file
`../cisco_iosxe_cli_to_cisco_iosxe/system-services.md`.

## Direction-specific disposition

The OpenConfig NETCONF codec does not parse `<system>` XML.  Its
parse path walks `<interfaces>` only.

| Canonical field | NETCONF -> CLI |
|---|---|
| `hostname` | not_applicable — parser never populates |
| `domain` | not_applicable |
| `dns_servers` | not_applicable |
| `ntp_servers` | not_applicable |
| `timezone` | not_applicable |
| `syslog_servers` | not_applicable |

Once the NETCONF codec wires `<system>` parsing, the cross-pair
flips to:

* `hostname`, `domain`, `dns_servers`, `ntp_servers`,
  `syslog_servers` -> `good`.  Same vendor, same database, host-list
  surface round-trips.
* `timezone` -> `lossy`.  OpenConfig `<clock><config><timezone-name>`
  prefers IANA tz database identifiers (`America/Los_Angeles`); CLI
  emits `clock timezone PST -8 0` (Cisco's named-zone-with-offset
  form).  Cross-format mapping requires an operator-curated table.
  DST behaviour (`clock summer-time`) is a separate CLI concept
  with no OpenConfig equivalent.

Per-server NTP options (`prefer`, `iburst`, `key`, `source`) are
not modelled in the canonical tree; `ntp_servers: list[str]` is
host-only.  Per-host syslog severity / facility tokens are not
modelled; `syslog_servers: list[str]` is host-only.  Both
limitations are pre-existing canonical-model decisions, not
introduced by this codec pair.
