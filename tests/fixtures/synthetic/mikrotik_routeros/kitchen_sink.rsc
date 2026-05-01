# may/01/2026 10:00:00 by RouterOS 7.13
# software id = SYNT-HETC
#
# model = SYNTHETIC-KS
# Synthetic kitchen-sink fixture for the mikrotik_routeros codec.
# Intentionally exercises every canonical field declared 'supported'
# or 'lossy' in MikroTikRouterOSCodec._CAPS, plus the LAG / local-user /
# DHCP / RADIUS / SNMPv3 surfaces the parser populates.  Hashes /
# secrets are FAKE per CLAUDE.md — they look real but are not actual
# credentials.
#
# RouterOS 6/7 compatible: uses the section + add/set grammar that
# both major lines accept.  Sections that the codec does not parse
# (timezone, syslog, pppoe-client, loopback bridge) are present as
# realistic context — the codec silently ignores them today, but a
# round-trip parse(render()) is still stable because nothing in
# render emits them either.

/system identity
set name=ks-edge-01

/interface ethernet
set [ find default-name=ether1 ] comment="WAN uplink to ISP" disabled=no mtu=1500
set [ find default-name=ether2 ] comment="LAN trunk - bridge member" disabled=no mtu=1500
set [ find default-name=ether3 ] comment="Bond1 member A" disabled=no
set [ find default-name=ether4 ] comment="Bond1 member B" disabled=no
set [ find default-name=ether5 ] comment="Bond2 member A" disabled=no
set [ find default-name=ether6 ] comment="Bond2 member B - admin disabled" disabled=yes

/interface bridge
add comment="Primary LAN bridge" name=bridge1

/interface bonding
add comment="LACP bond to upstream core" name=bond1 slaves=ether3,ether4 mode=802.3ad
add comment="Active/backup bond to secondary" name=bond2 slaves=ether5,ether6 mode=active-backup

/interface vlan
add comment="Users VLAN" interface=bridge1 name=vlan100 vlan-id=100
add comment="Voice VLAN" interface=bridge1 name=vlan200 vlan-id=200
add comment="Management VLAN" interface=bridge1 name=vlan300 vlan-id=300

# /interface bridge port — context only; not in parser scope.
/interface bridge port
add bridge=bridge1 interface=ether2
add bridge=bridge1 interface=bond1

# /interface pppoe-client — context only; codec does not model PPPoE.
/interface pppoe-client
add name=pppoe-out1 interface=ether1 user=isp-user password="fake-isp-secret" \
    add-default-route=yes disabled=no

/ip address
add address=198.51.100.2/30 interface=ether1
add address=10.0.0.1/24 interface=bridge1
add address=10.100.0.1/24 interface=vlan100
add address=10.200.0.1/24 interface=vlan200
add address=10.255.0.1/32 interface=bond1

/ipv6 address
add address=2001:db8:0:1::2/64 interface=ether1
add address=fe80::1/64 interface=ether1 advertise=no
add address=2001:db8:100::1/64 interface=vlan100
add address=2001:db8:255::1/128 interface=bond1

/ip route
add comment="Default route to ISP" dst-address=0.0.0.0/0 gateway=198.51.100.1
add comment="Branch network via core" dst-address=10.50.0.0/16 gateway=10.0.0.254
add comment="Blackhole RFC1918 leakage" dst-address=192.168.99.0/24 gateway=bridge1
add comment="IPv6 default" dst-address=::/0 gateway=2001:db8:0:1::1

/snmp
set enabled=yes contact="noc@example.net" location="Synthetic Lab Rack 7" \
    trap-target=10.0.0.250

/snmp community
set [ find default=yes ] name=public
add name=write-rw
add name=monitor-v3 authentication-protocol=SHA1 \
    authentication-password="fake-auth-passphrase-1" \
    encryption-protocol=AES \
    encryption-password="fake-priv-passphrase-1"
add name=audit-v3 authentication-protocol=SHA256 \
    authentication-password="fake-auth-passphrase-2" \
    encryption-protocol=aes-256-cfb \
    encryption-password="fake-priv-passphrase-2"

/radius
add address=10.0.0.10 secret=fake-radius-shared-secret-1 service=login \
    authentication-port=1812 accounting-port=1813
add address=10.0.0.11 secret=fake-radius-shared-secret-2 service=login,dhcp \
    authentication-port=1645 accounting-port=1646

/ip pool
add name=lan_pool ranges=10.0.0.100-10.0.0.200
add name=users_pool ranges=10.100.0.100-10.100.0.200

/ip dhcp-server
add address-pool=lan_pool authoritative=yes disabled=no interface=bridge1 \
    lease-time=1h name=lan-dhcp
add address-pool=users_pool authoritative=yes disabled=no interface=vlan100 \
    lease-time=8h name=users-dhcp

/ip dhcp-server network
add address=10.0.0.0/24 gateway=10.0.0.1 dns-server=10.0.0.1,1.1.1.1 \
    domain=lab.example.net
add address=10.100.0.0/24 gateway=10.100.0.1 dns-server=10.100.0.1 \
    domain=users.example.net

/user
add group=full name=admin
add group=write name=operator
add group=read name=auditor

# /system clock — timezone context; codec does not model it today.
/system clock
set time-zone-name=America/New_York

# /system logging action — syslog context; codec does not model it today.
/system logging action
add bsd-syslog=no name=remote-syslog remote=10.0.0.20 remote-port=514 \
    target=remote

/system dns
set servers=1.1.1.1,8.8.8.8

/system ntp client
set enabled=yes servers=10.0.0.123,pool.ntp.org
