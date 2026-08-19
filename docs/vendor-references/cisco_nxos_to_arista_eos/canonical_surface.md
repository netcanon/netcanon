# NX-OS -> Arista EOS: measured canonical surface

Source: `netcanon/migration/codecs/cisco_nxos/codec.py` and
`netcanon/migration/codecs/arista_eos/codec.py` (`CapabilityMatrix`), joined
against a full `tools/run_full_mesh.py` run over the committed corpus.
Retrieved: 2026-08-19

Both codecs declare `device_classes = [switch, router]`, so this is a
switch-to-switch pair with a wide shared surface — the DC-leaf migration case.
13 fixture cells; **0 render errors, 0 re-parse errors**.

## Per-field measurement (13 cells)

| field | preserved | drifted | untested | what drifts |
|---|---:|---:|---:|---|
| `hostname` | 13 | 0 | 0 | — |
| `domain` | 2 | 0 | 11 | — |
| `ntp_servers` | 1 | 0 | 12 | — |
| `syslog_servers` | 1 | 0 | 12 | — |
| `static_routes` | 8 | 0 | 5 | — |
| `anycast_gateway_mac` | 7 | 0 | 6 | — |
| `routing_instances` | 11 | 1 | 1 | VRF `description` dropped |
| `vlans` | 9 | 4 | 0 | SVI `ipv4_addresses` on the VLAN record |
| `snmp` | 7 | 4 | 2 | `v3_users` |
| `vxlan_vnis` | 6 | 2 | 5 | `mcast_group` dropped |
| `interfaces` | 1 | 12 | 0 | `lag_member_of`, `interface_type` |
| `local_users` | 0 | 9 | 4 | hash re-tagged `arista:5:$5$…` |
| `lags` | 0 | 5 | 8 | whole record — see `lag_naming.md` |

`dns_servers`, `timezone`, `dhcp_servers`, `radius_servers`,
`evpn_type5_routes`, `raw_sections`, `apply_groups`, `group_content` are
untested by the corpus (no fixture populates them on this pair).

## Notes grounding the dispositions

* **`local_users`** — drift is representational, not a loss. The NX-OS source
  carries `5 $5$<salt>$<digest>`; the Arista target re-tags it `arista:5:$5$<salt>$<digest>`,
  preserving the digest verbatim and adding a vendor/type marker. The secret
  survives; its spelling does not.
* **`interfaces`** — dominated by `lag_member_of` going `null` (the LAG-naming
  effect, see `lag_naming.md`) plus `interface_type` (`ianaift:ethernetCsmacd`)
  dropping on `mgmt0`. Interface identity, addressing and state survive.
* **`vxlan_vnis`** — VNI and VLAN binding survive; the multicast replication
  group (`mcast_group`, e.g. `239.11.11.10`) is dropped, so a multicast-mode
  VXLAN fabric re-renders without its underlay group.
* **`vlans`** — VLAN id and name survive; an L3 address carried on the VLAN
  record itself (the SVI-on-VLAN shape, incl. `virtual_gateway_address`) drops.
* **`timezone`** — both matrices declare `/system/timezone` unsupported with
  the same reason ("Render emits no clock/timezone stanza"), so this is a
  target-side drop regardless of whether a fixture exercises it.
* **`dhcp_servers` / `radius_servers`** — the gap is SOURCE-side: the NX-OS
  codec never populates these (0 of 13 cells), so there is nothing for the
  Arista target to lose. Arista *can* render DHCP pools, so closing the NX-OS
  parse side would move `dhcp_servers` off `not_applicable`.
