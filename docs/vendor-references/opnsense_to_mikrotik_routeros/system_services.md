# System services (hostname / domain / DNS / NTP / timezone / syslog): OPNsense versus MikroTik RouterOS

## OPNsense

Source: [OPNsense General Settings — System: Settings: General](https://docs.opnsense.org/manual/settingsmenu.html)

Retrieved: 2026-04-30

```xml
<opnsense>
  <system>
    <hostname>fw-kitchensink</hostname>
    <domain>example.net</domain>
    <timezone>Etc/UTC</timezone>
    <timeservers>0.opnsense.pool.ntp.org 1.opnsense.pool.ntp.org</timeservers>
    <dnsserver>1.1.1.1</dnsserver>
    <dnsserver>9.9.9.9</dnsserver>
    <syslog>
      <remoteserver>10.0.0.200</remoteserver>
    </syslog>
  </system>
</opnsense>
```

OPNsense aggregates system identity inside ``<system>``:
``<hostname>`` (bare short name), ``<domain>`` (DNS suffix),
repeated ``<dnsserver>`` elements, space-separated
``<timeservers>``, Olson zoneinfo ``<timezone>`` and
``<syslog>/<remoteserver>``.

## MikroTik RouterOS

Sources:
- [Identity — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/40992856/Identity)
- [DNS — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/37945004/DNS)
- [NTP Client — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/37224622/NTP+Client+and+Server)
- [Clock — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/40992866/Clock)
- [Log — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/14091786/Log)

Retrieved: 2026-04-30

```
/system identity
set name=fw-kitchensink

/ip dns
set servers=1.1.1.1,9.9.9.9

/system ntp client
set enabled=yes servers=0.opnsense.pool.ntp.org,1.opnsense.pool.ntp.org

/system clock
set time-zone-name=Etc/UTC

/system logging action
add bsd-syslog=no name=remote-syslog remote=10.0.0.200 \
    remote-port=514 target=remote
/system logging
add action=remote-syslog topics=info
```

RouterOS keeps each service in its own ``/system <area>`` section.
``/system identity`` carries only the bare short name; FQDN context
lives on the DNS resolver (``/ip dns``) instead.  ``/ip dns set
servers=`` is a single comma-separated value.  ``/system ntp client``
accepts a single comma-separated server list.  Timezone uses the
IANA tz database name.  Syslog destinations are split between
``/system logging action`` (where) and ``/system logging`` (filter).

## Cross-vendor mapping

The canonical surface is

```
hostname: str
domain: str
dns_servers: list[str]
ntp_servers: list[str]
timezone: str
syslog_servers: list[str]
```

### hostname

OPNsense ``<system>/<hostname>`` ↔ RouterOS ``/system identity / set
name=X``.  Lossless round-trip for the bare short name.

### domain

OPNsense ``<system>/<domain>`` is a first-class DNS suffix scalar.
RouterOS does NOT surface a top-level FQDN identity field — the
nearest analogue is the DNS resolver search list (``/ip dns set
domain=...``) which is a different scope.  Cross-pair render emits
no clean RouterOS line for the domain; the canonical value
preserves but the RouterOS render typically drops it.

### dns_servers

OPNsense's repeated ``<dnsserver>`` elements would map to RouterOS's
single comma-separated ``/ip dns set servers=`` value.  The OPNsense
codec does not currently parse ``<dnsserver>`` into the canonical
``dns_servers`` list — the canonical list is empty from an OPNsense
source today.  Cross-pair therefore emits no RouterOS DNS resolver
config.  Lands when OPNsense parse wire-up completes.

### ntp_servers

OPNsense's space-separated ``<timeservers>`` would map to RouterOS's
comma-separated ``/system ntp client / set servers=``.  OPNsense
codec does not currently parse ``<timeservers>`` into the canonical
``ntp_servers`` list.

### timezone

OPNsense's Olson zoneinfo ID (``<timezone>America/Los_Angeles``)
matches RouterOS's IANA tz database name directly — string shape is
compatible.  But the OPNsense codec does not currently parse
``<timezone>`` into canonical, so cross-pair drops on parse pending
wire-up.

### syslog_servers

OPNsense ``<system>/<syslog>/<remoteserver>`` would map to RouterOS
``/system logging action add target=remote remote=X``.  OPNsense
codec does not currently parse syslog into canonical.  Per-severity
/ per-facility filter context is not modelled on canonical (host
list only) — drops regardless of wire-up.

### Disposition summary

| Field | Disposition |
|---|---|
| `hostname` | good |
| `domain` | lossy (no clean RouterOS render — domain attached to DNS resolver) |
| `dns_servers` | lossy (OPNsense parse wire-up pending) |
| `ntp_servers` | lossy (OPNsense parse wire-up pending; per-server options drop) |
| `timezone` | lossy (OPNsense parse wire-up pending; otherwise IANA-equal) |
| `syslog_servers` | lossy (OPNsense parse wire-up pending; filter context drops) |
