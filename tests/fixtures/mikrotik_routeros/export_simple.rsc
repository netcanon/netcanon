# jan/15/2024 10:00:00 by RouterOS 7.13.5
# software id = ABCD-EFGH
#
# model = CCR2004-16G-2S+
# serial number = XXXXXXXXXXXX
/system identity
set name=edge-gw

/interface bridge
add admin-mac=AA:BB:CC:DD:EE:FF auto-mac=no comment="LAN bridge" name=bridge1

/interface ethernet
set [ find default-name=ether1 ] comment="WAN uplink" disabled=no
set [ find default-name=ether2 ] comment="LAN trunk" disabled=no
set [ find default-name=ether3 ] comment="Reserved" disabled=yes

/interface vlan
add comment="Corporate users" interface=bridge1 name=vlan10 vlan-id=10
add comment="Guest WiFi" interface=bridge1 name=vlan20 vlan-id=20

/ip address
add address=198.51.100.2/30 comment="WAN IP" interface=ether1 network=198.51.100.0
add address=192.168.10.1/24 comment="Corp SVI" interface=vlan10 network=192.168.10.0
add address=192.168.20.1/24 comment="Guest SVI" interface=vlan20 network=192.168.20.0

/ip route
add comment="Default route" distance=1 dst-address=0.0.0.0/0 gateway=198.51.100.1

/system dns
set servers=1.1.1.1,8.8.8.8

/system ntp client
set enabled=yes servers=pool.ntp.org,time.google.com
