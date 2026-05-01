# VLAN name constraints

Allowed characters and length limits on the VLAN-name string.

Sources:
- Arista: https://www.arista.com/en/um-eos/eos-vlan-configuration (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/ref/statement/vlans-bridging-qfx-series.html (retrieved 2026-05-01)

Citation ids: `arista-vlan-cg`, `junos-vlans-statement`.

## Arista EOS form

```
vlan 100
   name Production-Servers
```

VLAN name accepts letters, digits, and most printable ASCII.  The
practical max length is 32 characters; longer names truncate
silently in some show outputs but persist in `running-config`.

## Junos form

```
set vlans Production-Servers vlan-id 100
```

Junos VLAN names can be up to **255 characters** but the allowed
character set is restricted to letters, digits, hyphens (`-`), and
periods (`.`).  Underscores and spaces are NOT accepted unless the
name is double-quoted (and even then, some QFX models reject
quoted names in EVPN-VXLAN service contexts).

## Mapping notes

- Canonical `CanonicalVlan.name` is a free-form string.  The
  Arista → Junos render path needs to sanitise names to the Junos
  allowed-char set; the most common sanitisation is replacing
  underscores with hyphens.
- Names containing only `[A-Za-z0-9.-]` round-trip losslessly.
  Names with underscores survive the canonical model but the Junos
  render emits a sanitised form (typically logged with a banner).
- Names with spaces or non-ASCII don't round-trip cleanly in
  either direction; the operator's per-pane VLAN-rename surface is
  the workaround.
