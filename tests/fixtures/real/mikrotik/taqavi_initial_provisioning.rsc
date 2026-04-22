# MikroTik RouterOS - Initial Provisioning Script
# Based on Model: L009UiGS-2HaxD (ARM)
# Description: Basic setup including Bridge, DHCP, WireGuard, and Firewall hardening.

# -------------------------------------------------------------------
# 1. SYSTEM IDENTITY & SECURITY
# -------------------------------------------------------------------
/system identity set name="MikroTik-Office"

# Create a secure admin user (CHANGE PASSWORD AFTER IMPORT)
/user add name=netadmin group=full password="ChangeMe123!" comment="Main Admin"
/user disable [find name=admin]

# Disable unused services for security
/ip service
set telnet disabled=yes
set ftp disabled=yes
set www disabled=yes
set api disabled=yes
set api-ssl disabled=yes
set winbox port=8291 address=192.168.1.0/24 comment="Restrict WinBox to LAN"
set ssh port=22 address=192.168.1.0/24

# -------------------------------------------------------------------
# 2. INTERFACES & BRIDGE
# -------------------------------------------------------------------
/interface bridge
add name=bridge-lan port-cost-mode=short protocol-mode=rstp comment="Main LAN Switch"

/interface ethernet
set [ find default-name=ether2 ] comment="LAN Access"
set [ find default-name=ether3 ] comment="WAN Primary"
set [ find default-name=ether4 ] comment="Server/iLO"
set [ find default-name=ether5 ] comment="WiFi AP"
set [ find default-name=ether6 ] comment="Guest/IoT"

# Add ports to Bridge
/interface bridge port
add bridge=bridge-lan interface=ether2
add bridge=bridge-lan interface=ether4 trusted=yes
add bridge=bridge-lan interface=ether5
add bridge=bridge-lan interface=ether6
# ether3 is reserved for WAN, so it is NOT added to the bridge

# -------------------------------------------------------------------
# 3. IP ADDRESSING & DNS
# -------------------------------------------------------------------
# LAN IP (Standardized to .1 for the repository)
/ip address
add address=192.168.1.1/24 interface=bridge-lan network=192.168.1.0 comment="LAN Gateway"

# DNS Settings (Google & Level3)
/ip dns
set allow-remote-requests=yes servers=8.8.8.8,4.2.2.4
/ip dns static
add address=192.168.1.1 name=router.lan type=A

# -------------------------------------------------------------------
# 4. DHCP SERVER
# -------------------------------------------------------------------
/ip pool
add name=pool-lan ranges=192.168.1.20-192.168.1.199

/ip dhcp-server network
add address=192.168.1.0/24 dns-server=192.168.1.1,8.8.8.8 gateway=192.168.1.1 domain=office.local

/ip dhcp-server
add address-pool=pool-lan interface=bridge-lan lease-time=24h name=dhcp-lan disabled=no

# -------------------------------------------------------------------
# 5. WIREGUARD VPN (Server)
# -------------------------------------------------------------------
/interface wireguard
add listen-port=51820 mtu=1420 name=wireguard-office comment="VPN Access"

/ip address
add address=10.100.100.1/24 interface=wireguard-office network=10.100.100.0

# Peers (Templates - Users must add their own keys)
# /interface wireguard peers
# add interface=wireguard-office public-key="CLIENT_PUBLIC_KEY" allowed-address=10.100.100.2/32 comment="Client 1"

# -------------------------------------------------------------------
# 6. FIREWALL - FILTER RULES (Security)
# -------------------------------------------------------------------
/ip firewall filter

# --- Input Chain (Traffic to the Router) ---
add action=accept chain=input connection-state=established,related comment="Accept Established"
add action=drop chain=input connection-state=invalid comment="Drop Invalid"
add action=accept chain=input protocol=icmp comment="Allow Ping"
add action=accept chain=input dst-port=51820 protocol=udp comment="Allow WireGuard Handshake"
add action=accept chain=input in-interface=bridge-lan comment="Allow Management from LAN"
add action=drop chain=input comment="Drop everything else"

# --- Forward Chain (Traffic passing through) ---
add action=accept chain=forward connection-state=established,related comment="Accept Established"
add action=drop chain=forward connection-state=invalid comment="Drop Invalid"
add action=accept chain=forward in-interface=wireguard-office comment="Allow VPN traffic to LAN"
add action=accept chain=forward in-interface=bridge-lan out-interface=wireguard-office comment="Allow LAN traffic to VPN"
add action=drop chain=forward connection-nat-state=!dstnat connection-state=new in-interface=ether3 comment="Block WAN incoming (except Port Forwarding)"

# -------------------------------------------------------------------
# 7. FIREWALL - NAT
# -------------------------------------------------------------------
/ip firewall nat
# Masquerade (Internet Access)
add action=masquerade chain=srcnat out-interface=ether3 comment="WAN Masquerade"
# Masquerade VPN traffic (optional, for accessing LAN devices without return routes)
add action=masquerade chain=srcnat src-address=10.100.100.0/24 dst-address=192.168.1.0/24 comment="VPN NAT"

# Port Forwarding Examples (Disabled by default for safety)
# add action=dst-nat chain=dstnat protocol=tcp dst-port=3389 in-interface=ether3 to-addresses=192.168.1.5 to-ports=3389 comment="RDP Server" disabled=yes

# -------------------------------------------------------------------
# 8. SYSTEM MAINTENANCE & LOGGING
# -------------------------------------------------------------------
/system clock
set time-zone-name=Asia/Tehran

/system ntp client
set enabled=yes
/system ntp client servers
add address=time.google.com

/tool bandwidth-server set enabled=no
/tool mac-server set allowed-interface-list=none
/tool mac-server mac-winbox set allowed-interface-list=none
/tool mac-server ping set enabled=no

# Optimize Neighbor Discovery (Security)
/ip neighbor discovery-settings set discover-interface-list=bridge-lan

/log info "Initial Provisioning Completed Successfully."