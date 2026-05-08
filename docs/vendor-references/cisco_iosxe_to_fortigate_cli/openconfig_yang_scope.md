# OpenConfig YANG scope — what the `cisco_iosxe` codec actually parses

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

Source: [Programmability Configuration Guide, Cisco IOS XE 17.15.x — NETCONF Protocol](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/prog/configuration/1715/b_1715_programmability_cg/m_1715_prog_yang_netconf.html)
Retrieved: 2026-05-01

Source: [Native, IETF, OpenConfig... Why so many YANG models? (Cisco Blogs)](https://blogs.cisco.com/developer/which-yang-model-to-use)
Retrieved: 2026-05-01

## What a real `<get-config>` reply carries

A Catalyst 9K / ISR4K device responding to a NETCONF
`<get-config source=running>` filter in the OpenConfig namespace
emits a multi-subtree document including (in declaration order):

```
<rpc-reply>
  <data>
    <interfaces xmlns="http://openconfig.net/yang/interfaces">...</interfaces>
    <system xmlns="http://openconfig.net/yang/system">
      <config>
        <hostname>...</hostname>
        <domain-name>...</domain-name>
      </config>
      <dns>...</dns>
      <ntp>...</ntp>
      <logging><remote-servers>...</remote-servers></logging>
      <clock><config><timezone-name>...</timezone-name></config></clock>
      <aaa>
        <authentication><users>...</users></authentication>
        <server-groups>...</server-groups>
      </aaa>
    </system>
    <network-instances xmlns="http://openconfig.net/yang/network-instance">
      <network-instance>
        <protocols>
          <protocol identifier="STATIC">...</protocol>
        </protocols>
        <vlans>...</vlans>
      </network-instance>
    </network-instances>
    <snmp xmlns="http://cisco.com/ns/yang/Cisco-IOS-XE-snmp">...</snmp>
  </data>
</rpc-reply>
```

The OpenConfig ecosystem does model all of these subtrees in
shipping YANG modules.  Cisco IOS-XE 17.x exposes them via the
NETCONF agent.  The structural surface is real.

## What the `netcanon.migration.codecs.cisco_iosxe` parser reads

The codec's `parse()` ignores everything except the `<interfaces>`
subtree.  Looking at the parser entry point in
`netcanon/migration/codecs/cisco_iosxe/codec.py`:

```python
intent = CanonicalIntent(
    source_vendor="cisco_iosxe",
    source_format="xml-netconf",
)
for idx, iface_el in enumerate(interfaces_el.findall(_q("interface"))):
    raw_iface = _parse_interface(iface_el, idx=idx)
    intent.interfaces.append(_iface_dict_to_canonical(raw_iface))
return intent
```

There is no equivalent walk of `<system>`, `<network-instances>`,
`<snmp>`, etc.  After parse:

* `intent.hostname` = `""`
* `intent.domain` = `""`
* `intent.dns_servers` = `[]`
* `intent.ntp_servers` = `[]`
* `intent.timezone` = `""`
* `intent.syslog_servers` = `[]`
* `intent.vlans` = `[]`
* `intent.static_routes` = `[]`
* `intent.dhcp_servers` = `[]`
* `intent.snmp` = `None`
* `intent.lags` = `[]`
* `intent.local_users` = `[]`
* `intent.radius_servers` = `[]`
* `intent.routing_instances` = `[]`
* `intent.vxlan_vnis` = `[]`
* `intent.evpn_type5_routes` = `[]`

Only `intent.interfaces` carries data.

## Implications for the FortiGate target

The FortiGate codec accepts the full canonical surface and would
render hostname, DNS, NTP, syslog, VLANs (with caveats — see
`vlan_render_gap.md`), static-routes, SNMP (v1/v2c + v3 USM),
LAGs, local-users, RADIUS, and DHCP server pools when those
canonical fields are populated.  But on this direction they are
all structurally absent at the canonical layer because the
`cisco_iosxe` parser never wrote them.

Disposition for these fields is therefore `not_applicable` (source
structurally absent) rather than `lossy` (would imply the
canonical layer dropped data the source had).  This is the same
classification rule used in the
`cisco_iosxe__cisco_iosxe_cli.yaml` reverse direction: when the
source wire format already lost the data before the codec saw it,
the loss is `not_applicable` on the cross-pair.

## Disposition

| Source field after parse | Disposition on render | Rationale |
|---|---|---|
| `intent.interfaces` populated | varied (see `interface_fields.md`) | The only canonical surface carried by parser |
| Everything else empty | `not_applicable` | NETCONF parser never populates |

When the `cisco_iosxe` parser is extended to walk `<system>`,
`<network-instances>`, etc., these dispositions flip to `good` /
`lossy` as the cross-vendor render machinery applies.  This YAML
file is an honest snapshot of today's behaviour, not a prediction
of post-wire-up.
