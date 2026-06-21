# Source: https://github.com/networktocode/ntc-templates (tests/mikrotik_routeros/ip_address_export_verbose/mikrotik_routeros_ip_address_export_verbose.raw)
# License: Apache-2.0
# Snapshot: RouterOS 6.48.6 `/export verbose` snippet -- `# ... by RouterOS` banner + `/ip address` section with quoted comments.
# jul/21/2023 09:42:42 by RouterOS 6.48.6
# software id = 1234-ABCD
#
# model = RB750UPr2
# serial number = AB12345CD789
/ip address
add address=10.159.1.159/30 disabled=no interface=ether2 network=10.159.1.158
add address=10.80.90.5/27 comment="test comment" disabled=yes interface=eth3_vlan1 network=10.80.90.0
