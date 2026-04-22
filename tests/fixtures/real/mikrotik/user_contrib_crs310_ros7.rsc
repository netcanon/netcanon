# 2026-04-21 20:35:02 by RouterOS 7.18.2
# software id = XXXX-XXXX
#
# model = CRS310-8G+2S+
# serial number = XX00XXXXXXX
/interface bridge
add admin-mac=02:00:00:00:5A:66 ageing-time=5m arp=enabled arp-timeout=auto \
    auto-mac=no comment=defconf dhcp-snooping=no disabled=no fast-forward=yes \
    forward-delay=15s igmp-snooping=no max-learned-entries=auto \
    max-message-age=20s mtu=auto mvrp=no name=bridge port-cost-mode=long \
    priority=0x8000 protocol-mode=rstp transmit-hold-count=6 vlan-filtering=no
/interface ethernet
set [ find default-name=ether2 ] advertise="10M-baseT-half,10M-baseT-full,100M-\
    baseT-half,100M-baseT-full,1G-baseT-full,2.5G-baseT" arp=enabled \
    arp-timeout=auto auto-negotiation=yes bandwidth=unlimited/unlimited \
    disabled=no l2mtu=1592 loop-protect=default loop-protect-disable-time=5m \
    loop-protect-send-interval=5s mac-address=02:00:00:00:5A:67 mtu=1500 name=\
    "Access Point" orig-mac-address=02:00:00:00:5A:67 rx-flow-control=off \
    tx-flow-control=off
set [ find default-name=ether7 ] advertise="10M-baseT-half,10M-baseT-full,100M-\
    baseT-half,100M-baseT-full,1G-baseT-full,2.5G-baseT" arp=enabled \
    arp-timeout=auto auto-negotiation=yes bandwidth=unlimited/unlimited \
    disabled=no l2mtu=1592 loop-protect=default loop-protect-disable-time=5m \
    loop-protect-send-interval=5s mac-address=02:00:00:00:5A:6C mtu=1500 name=\
    "CLUSTER - PVE3" orig-mac-address=02:00:00:00:5A:6C rx-flow-control=off \
    tx-flow-control=off
set [ find default-name=ether5 ] advertise="10M-baseT-half,10M-baseT-full,100M-\
    baseT-half,100M-baseT-full,1G-baseT-full,2.5G-baseT" arp=enabled \
    arp-timeout=auto auto-negotiation=yes bandwidth=unlimited/unlimited \
    disabled=no l2mtu=1592 loop-protect=default loop-protect-disable-time=5m \
    loop-protect-send-interval=5s mac-address=02:00:00:00:5A:6A mtu=1500 name=\
    "CLUSTER - PVE5" orig-mac-address=02:00:00:00:5A:6A rx-flow-control=off \
    tx-flow-control=off
set [ find default-name=ether3 ] advertise="10M-baseT-half,10M-baseT-full,100M-\
    baseT-half,100M-baseT-full,1G-baseT-full,2.5G-baseT" arp=enabled \
    arp-timeout=auto auto-negotiation=yes bandwidth=unlimited/unlimited \
    disabled=no l2mtu=1592 loop-protect=default loop-protect-disable-time=5m \
    loop-protect-send-interval=5s mac-address=02:00:00:00:5A:68 mtu=1500 name=\
    "CLUSTER - PVENAS" orig-mac-address=02:00:00:00:5A:68 rx-flow-control=off \
    tx-flow-control=off
set [ find default-name=ether1 ] advertise="10M-baseT-half,10M-baseT-full,100M-\
    baseT-half,100M-baseT-full,1G-baseT-full,2.5G-baseT" arp=enabled \
    arp-timeout=auto auto-negotiation=yes bandwidth=unlimited/unlimited \
    disabled=no l2mtu=1592 loop-protect=default loop-protect-disable-time=5m \
    loop-protect-send-interval=5s mac-address=02:00:00:00:5A:66 mtu=1500 name=\
    Desktop orig-mac-address=02:00:00:00:5A:66 rx-flow-control=off \
    tx-flow-control=off
set [ find default-name=ether8 ] advertise="10M-baseT-half,10M-baseT-full,100M-\
    baseT-half,100M-baseT-full,1G-baseT-full,2.5G-baseT" arp=enabled \
    arp-timeout=auto auto-negotiation=yes bandwidth=unlimited/unlimited \
    disabled=no l2mtu=1592 loop-protect=default loop-protect-disable-time=5m \
    loop-protect-send-interval=5s mac-address=02:00:00:00:5A:6D mtu=1500 name=\
    "PROD - PVE3" orig-mac-address=02:00:00:00:5A:6D rx-flow-control=off \
    tx-flow-control=off
set [ find default-name=ether6 ] advertise="10M-baseT-half,10M-baseT-full,100M-\
    baseT-half,100M-baseT-full,1G-baseT-full,2.5G-baseT" arp=enabled \
    arp-timeout=auto auto-negotiation=yes bandwidth=unlimited/unlimited \
    disabled=no l2mtu=1592 loop-protect=default loop-protect-disable-time=5m \
    loop-protect-send-interval=5s mac-address=02:00:00:00:5A:6B mtu=1500 name=\
    "PROD - PVE5" orig-mac-address=02:00:00:00:5A:6B rx-flow-control=off \
    tx-flow-control=off
set [ find default-name=ether4 ] advertise="10M-baseT-half,10M-baseT-full,100M-\
    baseT-half,100M-baseT-full,1G-baseT-full,2.5G-baseT" arp=enabled \
    arp-timeout=auto auto-negotiation=yes bandwidth=unlimited/unlimited \
    disabled=no l2mtu=1592 loop-protect=default loop-protect-disable-time=5m \
    loop-protect-send-interval=5s mac-address=02:00:00:00:5A:69 mtu=1500 name=\
    "PROD - PVENAS" orig-mac-address=02:00:00:00:5A:69 rx-flow-control=off \
    tx-flow-control=off
set [ find default-name=sfp-sfpplus1 ] advertise="10M-baseT-half,10M-baseT-full\
    ,100M-baseT-half,100M-baseT-full,1G-baseT-half,1G-baseT-full,1G-baseX,2.5G-\
    baseT,2.5G-baseX,5G-baseT,10G-baseT,10G-baseSR-LR,10G-baseCR" arp=enabled \
    arp-timeout=auto auto-negotiation=yes bandwidth=unlimited/unlimited \
    disabled=no l2mtu=1592 loop-protect=default loop-protect-disable-time=5m \
    loop-protect-send-interval=5s mac-address=02:00:00:00:5A:6E mtu=1500 name=\
    UPLINKSFP orig-mac-address=02:00:00:00:5A:6E rx-flow-control=off \
    sfp-ignore-rx-los=no sfp-rate-select=high sfp-shutdown-temperature=95C \
    tx-flow-control=off
set [ find default-name=sfp-sfpplus2 ] advertise="10M-baseT-half,10M-baseT-full\
    ,100M-baseT-half,100M-baseT-full,1G-baseT-half,1G-baseT-full,1G-baseX,2.5G-\
    baseT,2.5G-baseX,5G-baseT,10G-baseT,10G-baseSR-LR,10G-baseCR" arp=enabled \
    arp-timeout=auto auto-negotiation=yes bandwidth=unlimited/unlimited \
    disabled=no l2mtu=1592 loop-protect=default loop-protect-disable-time=5m \
    loop-protect-send-interval=5s mac-address=02:00:00:00:5A:6F mtu=1500 name=\
    sfp-sfpplus2 orig-mac-address=02:00:00:00:5A:6F rx-flow-control=off \
    sfp-ignore-rx-los=no sfp-rate-select=high sfp-shutdown-temperature=95C \
    tx-flow-control=off
/queue interface
set bridge queue=no-queue
/interface vlan
add arp=enabled arp-timeout=auto comment=Cluster disabled=no interface=bridge \
    loop-protect=default loop-protect-disable-time=5m \
    loop-protect-send-interval=5s mtu=1500 mvrp=no name=clustervlan100 \
    use-service-tag=no vlan-id=100
add arp=enabled arp-timeout=auto comment=IOT disabled=no interface=bridge \
    loop-protect=default loop-protect-disable-time=5m \
    loop-protect-send-interval=5s mtu=1500 mvrp=no name=iotvlan150 \
    use-service-tag=no vlan-id=150
add arp=enabled arp-timeout=auto comment=Management disabled=no interface=\
    bridge loop-protect=default loop-protect-disable-time=5m \
    loop-protect-send-interval=5s mtu=1500 mvrp=no name=mgmtvlan11 \
    use-service-tag=no vlan-id=11
add arp=enabled arp-timeout=auto comment=Server disabled=no interface=bridge \
    loop-protect=default loop-protect-disable-time=5m \
    loop-protect-send-interval=5s mtu=1500 mvrp=no name=servervlan20 \
    use-service-tag=no vlan-id=20
add arp=enabled arp-timeout=auto comment=User disabled=no interface=bridge \
    loop-protect=default loop-protect-disable-time=5m \
    loop-protect-send-interval=5s mtu=1500 mvrp=no name=uservlan10 \
    use-service-tag=no vlan-id=10
/queue interface
set clustervlan100 queue=no-queue
set iotvlan150 queue=no-queue
set mgmtvlan11 queue=no-queue
set servervlan20 queue=no-queue
set uservlan10 queue=no-queue
/interface ethernet switch
set 0 !cpu-flow-control l3-hw-offloading=no mirror-target=none name=switch1 \
    qos-hw-offloading=no rspan=no rspan-egress-vlan-id=1 \
    rspan-ingress-vlan-id=1
/interface ethernet switch port
set 0 !egress-rate !ingress-rate l3-hw-offloading=yes limit-broadcasts=yes \
    limit-unknown-multicasts=no limit-unknown-unicasts=no mirror-egress=no \
    mirror-ingress=no storm-rate=100
set 1 !egress-rate !ingress-rate l3-hw-offloading=yes limit-broadcasts=yes \
    limit-unknown-multicasts=no limit-unknown-unicasts=no mirror-egress=no \
    mirror-ingress=no storm-rate=100
set 2 !egress-rate !ingress-rate l3-hw-offloading=yes limit-broadcasts=yes \
    limit-unknown-multicasts=no limit-unknown-unicasts=no mirror-egress=no \
    mirror-ingress=no storm-rate=100
set 3 !egress-rate !ingress-rate l3-hw-offloading=yes limit-broadcasts=yes \
    limit-unknown-multicasts=no limit-unknown-unicasts=no mirror-egress=no \
    mirror-ingress=no storm-rate=100
set 4 !egress-rate !ingress-rate l3-hw-offloading=yes limit-broadcasts=yes \
    limit-unknown-multicasts=no limit-unknown-unicasts=no mirror-egress=no \
    mirror-ingress=no storm-rate=100
set 5 !egress-rate !ingress-rate l3-hw-offloading=yes limit-broadcasts=yes \
    limit-unknown-multicasts=no limit-unknown-unicasts=no mirror-egress=no \
    mirror-ingress=no storm-rate=100
set 6 !egress-rate !ingress-rate l3-hw-offloading=yes limit-broadcasts=yes \
    limit-unknown-multicasts=no limit-unknown-unicasts=no mirror-egress=no \
    mirror-ingress=no storm-rate=100
set 7 !egress-rate !ingress-rate l3-hw-offloading=yes limit-broadcasts=yes \
    limit-unknown-multicasts=no limit-unknown-unicasts=no mirror-egress=no \
    mirror-ingress=no storm-rate=100
set 8 !egress-rate !ingress-rate l3-hw-offloading=yes limit-broadcasts=yes \
    limit-unknown-multicasts=no limit-unknown-unicasts=no mirror-egress=no \
    mirror-ingress=no storm-rate=100
set 9 !egress-rate !ingress-rate l3-hw-offloading=yes limit-broadcasts=yes \
    limit-unknown-multicasts=no limit-unknown-unicasts=no mirror-egress=no \
    mirror-ingress=no storm-rate=100
set 10 !egress-rate !ingress-rate limit-broadcasts=yes \
    limit-unknown-multicasts=no limit-unknown-unicasts=no mirror-egress=no \
    mirror-ingress=no storm-rate=100
/interface ethernet switch port-isolation
set 0 !forwarding-override
set 1 !forwarding-override
set 2 !forwarding-override
set 3 !forwarding-override
set 4 !forwarding-override
set 5 !forwarding-override
set 6 !forwarding-override
set 7 !forwarding-override
set 8 !forwarding-override
set 9 !forwarding-override
set 10 !forwarding-override
/interface ethernet switch qos port
set Desktop !egress-rate-queue0 !egress-rate-queue1 !egress-rate-queue2 \
    !egress-rate-queue3 !egress-rate-queue4 !egress-rate-queue5 \
    !egress-rate-queue6 !egress-rate-queue7 map=default profile=default \
    trust-l2=ignore trust-l3=ignore tx-manager=default
set "Access Point" !egress-rate-queue0 !egress-rate-queue1 !egress-rate-queue2 \
    !egress-rate-queue3 !egress-rate-queue4 !egress-rate-queue5 \
    !egress-rate-queue6 !egress-rate-queue7 map=default profile=default \
    trust-l2=ignore trust-l3=ignore tx-manager=default
set "CLUSTER - PVENAS" !egress-rate-queue0 !egress-rate-queue1 \
    !egress-rate-queue2 !egress-rate-queue3 !egress-rate-queue4 \
    !egress-rate-queue5 !egress-rate-queue6 !egress-rate-queue7 map=default \
    profile=default trust-l2=ignore trust-l3=ignore tx-manager=default
set "PROD - PVENAS" !egress-rate-queue0 !egress-rate-queue1 \
    !egress-rate-queue2 !egress-rate-queue3 !egress-rate-queue4 \
    !egress-rate-queue5 !egress-rate-queue6 !egress-rate-queue7 map=default \
    profile=default trust-l2=ignore trust-l3=ignore tx-manager=default
set "CLUSTER - PVE5" !egress-rate-queue0 !egress-rate-queue1 \
    !egress-rate-queue2 !egress-rate-queue3 !egress-rate-queue4 \
    !egress-rate-queue5 !egress-rate-queue6 !egress-rate-queue7 map=default \
    profile=default trust-l2=ignore trust-l3=ignore tx-manager=default
set "PROD - PVE5" !egress-rate-queue0 !egress-rate-queue1 !egress-rate-queue2 \
    !egress-rate-queue3 !egress-rate-queue4 !egress-rate-queue5 \
    !egress-rate-queue6 !egress-rate-queue7 map=default profile=default \
    trust-l2=ignore trust-l3=ignore tx-manager=default
set "CLUSTER - PVE3" !egress-rate-queue0 !egress-rate-queue1 \
    !egress-rate-queue2 !egress-rate-queue3 !egress-rate-queue4 \
    !egress-rate-queue5 !egress-rate-queue6 !egress-rate-queue7 map=default \
    profile=default trust-l2=ignore trust-l3=ignore tx-manager=default
set "PROD - PVE3" !egress-rate-queue0 !egress-rate-queue1 !egress-rate-queue2 \
    !egress-rate-queue3 !egress-rate-queue4 !egress-rate-queue5 \
    !egress-rate-queue6 !egress-rate-queue7 map=default profile=default \
    trust-l2=ignore trust-l3=ignore tx-manager=default
set UPLINKSFP !egress-rate-queue0 !egress-rate-queue1 !egress-rate-queue2 \
    !egress-rate-queue3 !egress-rate-queue4 !egress-rate-queue5 \
    !egress-rate-queue6 !egress-rate-queue7 map=default profile=default \
    trust-l2=ignore trust-l3=ignore tx-manager=default
set sfp-sfpplus2 !egress-rate-queue0 !egress-rate-queue1 !egress-rate-queue2 \
    !egress-rate-queue3 !egress-rate-queue4 !egress-rate-queue5 \
    !egress-rate-queue6 !egress-rate-queue7 map=default profile=default \
    trust-l2=ignore trust-l3=ignore tx-manager=default
set switch1-cpu !egress-rate-queue0 !egress-rate-queue1 !egress-rate-queue2 \
    !egress-rate-queue3 !egress-rate-queue4 !egress-rate-queue5 \
    !egress-rate-queue6 !egress-rate-queue7 map=default profile=default \
    trust-l2=keep trust-l3=keep tx-manager=default
/interface list
set [ find name=all ] comment="contains all interfaces" exclude="" include="" \
    name=all
set [ find name=none ] comment="contains no interfaces" exclude="" include="" \
    name=none
set [ find name=dynamic ] comment="contains dynamic interfaces" exclude="" \
    include="" name=dynamic
set [ find name=static ] comment="contains static interfaces" exclude="" \
    include="" name=static
add exclude="" include="" name=WAN
add exclude="" include="" name=LAN
/interface lte apn
set [ find default=yes ] add-default-route=yes apn=internet authentication=\
    none default-route-distance=2 ip-type=auto name=default use-network-apn=\
    yes use-peer-dns=yes
/interface macsec profile
set [ find default-name=default ] name=default server-priority=10
/ip dhcp-client option
set clientid_duid code=61 name=clientid_duid value="0xff\$(CLIENT_DUID)"
set clientid code=61 name=clientid value="0x01\$(CLIENT_MAC)"
set hostname code=12 name=hostname value="\$(HOSTNAME)"
/ip hotspot profile
set [ find default=yes ] dns-name="" hotspot-address=0.0.0.0 html-directory=\
    hotspot html-directory-override="" http-cookie-lifetime=3d http-proxy=\
    0.0.0.0:0 install-hotspot-queue=no login-by=cookie,http-chap name=default \
    smtp-server=0.0.0.0 split-user-domain=no use-radius=no
/ip hotspot user profile
set [ find default=yes ] add-mac-cookie=yes address-list="" idle-timeout=none \
    !insert-queue-before keepalive-timeout=2m mac-cookie-timeout=3d name=\
    default !parent-queue !queue-type shared-users=1 status-autorefresh=1m \
    transparent-proxy=no
/ip ipsec mode-config
set [ find default=yes ] name=request-only responder=no use-responder-dns=\
    exclusively
/ip ipsec policy group
set [ find default=yes ] name=default
/ip ipsec profile
set [ find default=yes ] dh-group=modp2048,modp1024 dpd-interval=8s \
    dpd-maximum-failures=4 enc-algorithm=aes-128,3des hash-algorithm=sha1 \
    lifetime=1d name=default nat-traversal=yes proposal-check=obey
/ip ipsec proposal
set [ find default=yes ] auth-algorithms=sha1 disabled=no enc-algorithms=\
    aes-256-cbc,aes-192-cbc,aes-128-cbc lifetime=30m name=default pfs-group=\
    modp1024
/ip smb users
set [ find default=yes ] disabled=no name=guest read-only=yes
/port
set 0 baud-rate=9600 data-bits=8 flow-control=none name=usb1 parity=none \
    stop-bits=1
/ppp profile
set *0 address-list="" !bridge !bridge-horizon bridge-learning=default \
    !bridge-path-cost !bridge-port-priority !bridge-port-trusted \
    !bridge-port-vid change-tcp-mss=yes !dns-server !idle-timeout \
    !incoming-filter !insert-queue-before !interface-list !local-address name=\
    default on-down="" on-up="" only-one=default !outgoing-filter \
    !parent-queue !queue-type !rate-limit !remote-address !session-timeout \
    use-compression=default use-encryption=default use-ipv6=yes use-mpls=\
    default use-upnp=default !wins-server
set *FFFFFFFE address-list="" !bridge !bridge-horizon bridge-learning=default \
    !bridge-path-cost !bridge-port-priority !bridge-port-trusted \
    !bridge-port-vid change-tcp-mss=yes !dns-server !idle-timeout \
    !incoming-filter !insert-queue-before !interface-list !local-address name=\
    default-encryption on-down="" on-up="" only-one=default !outgoing-filter \
    !parent-queue !queue-type !rate-limit !remote-address !session-timeout \
    use-compression=default use-encryption=yes use-ipv6=yes use-mpls=default \
    use-upnp=default !wins-server
/interface ppp-client
add add-default-route=yes allow=pap,chap,mschap1,mschap2 apn=internet \
    data-channel=0 default-route-distance=1 dial-command=ATDT dial-on-demand=\
    yes disabled=yes info-channel=0 keepalive-timeout=30 max-mru=1500 max-mtu=\
    1500 modem-init="" mrru=disabled name=ppp-out1 null-modem=no phone="" pin=\
    "" port=usb1 profile=default use-peer-dns=yes user=""
/queue interface
set ppp-out1 queue=no-queue
/queue type
set 0 kind=pfifo name=default pfifo-limit=50
set 1 kind=pfifo name=ethernet-default pfifo-limit=50
set 2 kind=sfq name=wireless-default sfq-allot=1514 sfq-perturb=5
set 3 kind=red name=synchronous-default red-avg-packet=1000 red-burst=20 \
    red-limit=60 red-max-threshold=50 red-min-threshold=10
set 4 kind=sfq name=hotspot-default sfq-allot=1514 sfq-perturb=5
set 5 kind=pcq name=pcq-upload-default pcq-burst-rate=0 pcq-burst-threshold=0 \
    pcq-burst-time=10s pcq-classifier=src-address pcq-dst-address-mask=32 \
    pcq-dst-address6-mask=128 pcq-limit=50KiB pcq-rate=0 pcq-src-address-mask=\
    32 pcq-src-address6-mask=128 pcq-total-limit=2000KiB
set 6 kind=pcq name=pcq-download-default pcq-burst-rate=0 pcq-burst-threshold=\
    0 pcq-burst-time=10s pcq-classifier=dst-address pcq-dst-address-mask=32 \
    pcq-dst-address6-mask=128 pcq-limit=50KiB pcq-rate=0 pcq-src-address-mask=\
    32 pcq-src-address6-mask=128 pcq-total-limit=2000KiB
set 7 kind=none name=only-hardware-queue
set 8 kind=mq-pfifo mq-pfifo-limit=50 name=multi-queue-ethernet-default
set 9 kind=pfifo name=default-small pfifo-limit=10
/queue interface
set "Access Point" queue=only-hardware-queue
set "CLUSTER - PVE3" queue=only-hardware-queue
set "CLUSTER - PVE5" queue=only-hardware-queue
set "CLUSTER - PVENAS" queue=only-hardware-queue
set Desktop queue=only-hardware-queue
set "PROD - PVE3" queue=only-hardware-queue
set "PROD - PVE5" queue=only-hardware-queue
set "PROD - PVENAS" queue=only-hardware-queue
set UPLINKSFP queue=only-hardware-queue
set sfp-sfpplus2 queue=only-hardware-queue
/routing bgp template
set default as=65530 name=default
/snmp community
set [ find default=yes ] addresses=::/0 authentication-protocol=MD5 disabled=\
    no encryption-protocol=DES name=public read-access=yes security=none \
    write-access=no
/system logging action
set 0 memory-lines=1000 memory-stop-on-full=no name=memory target=memory
set 1 disk-file-count=2 disk-file-name=flash/log disk-lines-per-file=1000 \
    disk-stop-on-full=no name=disk target=disk
set 2 name=echo remember=yes target=echo
set 3 name=remote remote=0.0.0.0 remote-log-format=default remote-port=514 \
    remote-protocol=udp src-address=0.0.0.0 syslog-facility=daemon \
    syslog-severity=auto syslog-time-format=bsd-syslog target=remote
/user group
set read name=read policy="local,telnet,ssh,reboot,read,test,winbox,password,we\
    b,sniff,sensitive,api,romon,rest-api,!ftp,!write,!policy" skin=default
set write name=write policy="local,telnet,ssh,reboot,read,write,test,winbox,pas\
    sword,web,sniff,sensitive,api,romon,rest-api,!ftp,!policy" skin=default
set full name=full policy="local,telnet,ssh,ftp,reboot,read,write,policy,test,w\
    inbox,password,web,sniff,sensitive,api,romon,rest-api" skin=default
/certificate settings
set crl-download=no crl-store=ram crl-use=no
/console settings
set log-script-errors=yes sanitize-names=no
/disk settings
set auto-media-interface=none auto-media-sharing=no auto-smb-sharing=no \
    auto-smb-user=guest default-mount-point-template="[slot]"
/ip smb
set comment=MikrotikSMB domain=MSHOME enabled=auto interfaces=all
/interface bridge mlag
# disabled
set bridge=none heartbeat=5s peer-port=none priority=128
/interface bridge port
add auto-isolate=no bpdu-guard=no bridge=bridge broadcast-flood=yes comment=\
    defconf disabled=no edge=auto fast-leave=no frame-types=admit-all horizon=\
    none hw=yes ingress-filtering=yes interface=Desktop !internal-path-cost \
    learn=auto multicast-router=temporary-query mvrp-applicant-state=\
    normal-participant mvrp-registrar-state=normal !path-cost point-to-point=\
    auto priority=0x80 pvid=1 restricted-role=no restricted-tcn=no \
    tag-stacking=no trusted=no unknown-multicast-flood=yes \
    unknown-unicast-flood=yes
add auto-isolate=no bpdu-guard=no bridge=bridge broadcast-flood=yes comment=\
    defconf disabled=no edge=auto fast-leave=no frame-types=admit-all horizon=\
    none hw=yes ingress-filtering=yes interface="Access Point" \
    !internal-path-cost learn=auto multicast-router=temporary-query \
    mvrp-applicant-state=normal-participant mvrp-registrar-state=normal \
    !path-cost point-to-point=auto priority=0x80 pvid=1 restricted-role=no \
    restricted-tcn=no tag-stacking=no trusted=no unknown-multicast-flood=yes \
    unknown-unicast-flood=yes
add auto-isolate=no bpdu-guard=no bridge=bridge broadcast-flood=yes comment=\
    defconf disabled=no edge=auto fast-leave=no frame-types=admit-all horizon=\
    none hw=yes ingress-filtering=yes interface="CLUSTER - PVENAS" \
    !internal-path-cost learn=auto multicast-router=temporary-query \
    mvrp-applicant-state=normal-participant mvrp-registrar-state=normal \
    !path-cost point-to-point=auto priority=0x80 pvid=1 restricted-role=no \
    restricted-tcn=no tag-stacking=no trusted=no unknown-multicast-flood=yes \
    unknown-unicast-flood=yes
add auto-isolate=no bpdu-guard=no bridge=bridge broadcast-flood=yes comment=\
    defconf disabled=no edge=auto fast-leave=no frame-types=admit-all horizon=\
    none hw=yes ingress-filtering=yes interface="PROD - PVENAS" \
    !internal-path-cost learn=auto multicast-router=temporary-query \
    mvrp-applicant-state=normal-participant mvrp-registrar-state=normal \
    !path-cost point-to-point=auto priority=0x80 pvid=1 restricted-role=no \
    restricted-tcn=no tag-stacking=no trusted=no unknown-multicast-flood=yes \
    unknown-unicast-flood=yes
add auto-isolate=no bpdu-guard=no bridge=bridge broadcast-flood=yes comment=\
    defconf disabled=no edge=auto fast-leave=no frame-types=admit-all horizon=\
    none hw=yes ingress-filtering=yes interface="CLUSTER - PVE5" \
    !internal-path-cost learn=auto multicast-router=temporary-query \
    mvrp-applicant-state=normal-participant mvrp-registrar-state=normal \
    !path-cost point-to-point=auto priority=0x80 pvid=1 restricted-role=no \
    restricted-tcn=no tag-stacking=no trusted=no unknown-multicast-flood=yes \
    unknown-unicast-flood=yes
add auto-isolate=no bpdu-guard=no bridge=bridge broadcast-flood=yes comment=\
    defconf disabled=no edge=auto fast-leave=no frame-types=admit-all horizon=\
    none hw=yes ingress-filtering=yes interface="PROD - PVE5" \
    !internal-path-cost learn=auto multicast-router=temporary-query \
    mvrp-applicant-state=normal-participant mvrp-registrar-state=normal \
    !path-cost point-to-point=auto priority=0x80 pvid=1 restricted-role=no \
    restricted-tcn=no tag-stacking=no trusted=no unknown-multicast-flood=yes \
    unknown-unicast-flood=yes
add auto-isolate=no bpdu-guard=no bridge=bridge broadcast-flood=yes comment=\
    defconf disabled=no edge=auto fast-leave=no frame-types=admit-all horizon=\
    none hw=yes ingress-filtering=yes interface="CLUSTER - PVE3" \
    !internal-path-cost learn=auto multicast-router=temporary-query \
    mvrp-applicant-state=normal-participant mvrp-registrar-state=normal \
    !path-cost point-to-point=auto priority=0x80 pvid=1 restricted-role=no \
    restricted-tcn=no tag-stacking=no trusted=no unknown-multicast-flood=yes \
    unknown-unicast-flood=yes
add auto-isolate=no bpdu-guard=no bridge=bridge broadcast-flood=yes comment=\
    defconf disabled=no edge=auto fast-leave=no frame-types=admit-all horizon=\
    none hw=yes ingress-filtering=yes interface="PROD - PVE3" \
    !internal-path-cost learn=auto multicast-router=temporary-query \
    mvrp-applicant-state=normal-participant mvrp-registrar-state=normal \
    !path-cost point-to-point=auto priority=0x80 pvid=1 restricted-role=no \
    restricted-tcn=no tag-stacking=no trusted=no unknown-multicast-flood=yes \
    unknown-unicast-flood=yes
add auto-isolate=no bpdu-guard=no bridge=bridge broadcast-flood=yes comment=\
    defconf disabled=no edge=auto fast-leave=no frame-types=admit-all horizon=\
    none hw=yes ingress-filtering=yes interface=UPLINKSFP !internal-path-cost \
    learn=auto multicast-router=temporary-query mvrp-applicant-state=\
    normal-participant mvrp-registrar-state=normal !path-cost point-to-point=\
    auto priority=0x80 pvid=1 restricted-role=no restricted-tcn=no \
    tag-stacking=no trusted=no unknown-multicast-flood=yes \
    unknown-unicast-flood=yes
add auto-isolate=no bpdu-guard=no bridge=bridge broadcast-flood=yes comment=\
    defconf disabled=no edge=auto fast-leave=no frame-types=admit-all horizon=\
    none hw=yes ingress-filtering=yes interface=sfp-sfpplus2 \
    !internal-path-cost learn=auto multicast-router=temporary-query \
    mvrp-applicant-state=normal-participant mvrp-registrar-state=normal \
    !path-cost point-to-point=auto priority=0x80 pvid=1 restricted-role=no \
    restricted-tcn=no tag-stacking=no trusted=no unknown-multicast-flood=yes \
    unknown-unicast-flood=yes
/interface bridge settings
set allow-fast-path=yes use-ip-firewall=no use-ip-firewall-for-pppoe=no \
    use-ip-firewall-for-vlan=no
/interface ethernet switch l3hw-settings
set autorestart=no icmp-reply-on-error=yes ipv6-hw=no
/interface ethernet switch l3hw-settings advanced
set neigh-discovery-burst-delay=300ms neigh-discovery-burst-limit=64 \
    neigh-discovery-interval=1m37s neigh-dump-retries=3 \
    neigh-keepalive-interval=15s route-index-delay-max=10s \
    route-index-delay-min=1s route-queue-limit-high=256 route-queue-limit-low=\
    0 shwp-reset-counter=128
/ip firewall connection tracking
set enabled=auto generic-timeout=10m icmp-timeout=10s loose-tcp-tracking=yes \
    tcp-close-timeout=10s tcp-close-wait-timeout=10s tcp-established-timeout=\
    1d tcp-fin-wait-timeout=10s tcp-last-ack-timeout=10s \
    tcp-max-retrans-timeout=5m tcp-syn-received-timeout=5s \
    tcp-syn-sent-timeout=5s tcp-time-wait-timeout=10s tcp-unacked-timeout=5m \
    udp-stream-timeout=3m udp-timeout=30s
/ip neighbor discovery-settings
set discover-interface-list=static discover-interval=30s lldp-dcbx=yes \
    lldp-mac-phy-config=no lldp-max-frame-size=no lldp-med-net-policy-vlan=\
    disabled lldp-vlan-info=no mode=tx-and-rx protocol=cdp,lldp,mndp
/ip settings
set accept-redirects=no accept-source-route=no allow-fast-path=yes \
    arp-timeout=30s icmp-errors-use-inbound-interface-address=no \
    icmp-rate-limit=10 icmp-rate-mask=0x1818 ip-forward=yes \
    ipv4-multipath-hash-policy=l3 max-neighbor-entries=8192 rp-filter=no \
    secure-redirects=yes send-redirects=yes tcp-syncookies=no tcp-timestamps=\
    random-offset
/ipv6 settings
set accept-redirects=yes-if-forwarding-disabled accept-router-advertisements=\
    yes-if-forwarding-disabled allow-fast-path=yes disable-ipv6=no \
    disable-link-local-address=no forward=yes max-neighbor-entries=4096 \
    min-neighbor-entries=1024 multipath-hash-policy=l3 \
    soft-max-neighbor-entries=2048 stale-neighbor-detect-interval=30 \
    stale-neighbor-timeout=60
/interface detect-internet
set detect-interface-list=none internet-interface-list=none \
    lan-interface-list=none wan-interface-list=none
/interface ethernet switch qos settings
set multicast-buffers=10% shared-buffers=40%
/interface ethernet switch qos tx-manager queue
set 0 queue-buffers=auto schedule=low-priority-group use-shared-buffers=no \
    weight=1
set 1 queue-buffers=auto schedule=low-priority-group use-shared-buffers=yes \
    weight=2
set 2 queue-buffers=auto schedule=low-priority-group use-shared-buffers=yes \
    weight=3
set 3 queue-buffers=auto schedule=high-priority-group use-shared-buffers=yes \
    weight=3
set 4 queue-buffers=auto schedule=high-priority-group use-shared-buffers=yes \
    weight=4
set 5 queue-buffers=auto schedule=high-priority-group use-shared-buffers=yes \
    weight=5
set 6 queue-buffers=auto schedule=strict-priority use-shared-buffers=yes
set 7 queue-buffers=auto schedule=strict-priority use-shared-buffers=yes
/interface l2tp-server server
set accept-proto-version=all accept-pseudowire-type=all allow-fast-path=no \
    authentication=pap,chap,mschap1,mschap2 caller-id-type=ip-address \
    default-profile=default-encryption enabled=no keepalive-timeout=30 \
    l2tpv3-circuit-id="" l2tpv3-cookie-length=0 l2tpv3-digest-hash=md5 \
    !l2tpv3-ether-interface-list max-mru=1450 max-mtu=1450 max-sessions=\
    unlimited mrru=disabled one-session-per-host=no use-ipsec=no
/interface list member
add disabled=no interface=Desktop list=WAN
add disabled=no interface="Access Point" list=LAN
add disabled=no interface="CLUSTER - PVENAS" list=LAN
add disabled=no interface="PROD - PVENAS" list=LAN
add disabled=no interface="CLUSTER - PVE5" list=LAN
add disabled=no interface="PROD - PVE5" list=LAN
add disabled=no interface="CLUSTER - PVE3" list=LAN
add disabled=no interface="PROD - PVE3" list=LAN
add disabled=no interface=UPLINKSFP list=LAN
add disabled=no interface=sfp-sfpplus2 list=LAN
/interface lte settings
set esim-channel=auto firmware-path=firmware mode=auto
/interface pptp-server server
# PPTP connections are considered unsafe, it is suggested to use a more modern VP
  protocol instead
set authentication=mschap1,mschap2 default-profile=default-encryption enabled=\
    no keepalive-timeout=30 max-mru=1450 max-mtu=1450 mrru=disabled
/interface sstp-server server
set authentication=pap,chap,mschap1,mschap2 certificate=none ciphers=\
    aes256-sha,aes256-gcm-sha384 default-profile=default enabled=no \
    keepalive-timeout=60 max-mru=1500 max-mtu=1500 mrru=disabled pfs=no port=\
    443 tls-version=any verify-client-certificate=no
/interface wifi cap
set enabled=no
/interface wifi capsman
set enabled=no
/ip address
add address=192.168.88.1/24 comment=defconf disabled=no interface=\
    "Access Point" network=192.168.88.0
add address=192.168.11.253/32 comment="switch mgmt vlan address" disabled=no \
    interface=mgmtvlan11 network=192.168.11.253
/ip cloud
set back-to-home-vpn=revoked-and-disabled ddns-enabled=auto \
    ddns-update-interval=none update-time=yes
/ip cloud advanced
set use-local-address=no
/ip dhcp-server config
set accounting=yes interim-update=0s radius-password=empty store-leases-disk=\
    5m
/ip dns
set address-list-extra-time=0s allow-remote-requests=no cache-max-ttl=1w \
    cache-size=2048KiB doh-max-concurrent-queries=50 \
    doh-max-server-connections=5 doh-timeout=5s max-concurrent-queries=100 \
    max-concurrent-tcp-sessions=20 max-udp-packet-size=4096 \
    mdns-repeat-ifaces="" query-server-timeout=2s query-total-timeout=10s \
    servers=192.168.88.2 use-doh-server="" verify-doh-cert=no vrf=main
/ip firewall service-port
set ftp disabled=no ports=21
set tftp disabled=no ports=69
set irc disabled=yes ports=6667
set h323 disabled=no
set sip disabled=no ports=5060,5061 sip-direct-media=yes sip-timeout=1h
set pptp disabled=no
set rtsp disabled=yes ports=554
set udplite disabled=no
set dccp disabled=no
set sctp disabled=no
/ip hotspot service-port
set ftp disabled=no ports=21
/ip hotspot user
set [ find default=yes ] comment="counters and limits for trial users" \
    disabled=no name=default-trial
/ip ipsec policy
set 0 disabled=no dst-address=::/0 group=default proposal=default protocol=all \
    src-address=::/0 template=yes
/ip ipsec settings
set accounting=yes interim-update=0s xauth-use-radius=no
/ip media settings
set thumbnails=""
/ip nat-pmp
set enabled=no
/ip proxy
# inactivated, not allowed by device-mode
set always-from-cache=no anonymous=no cache-administrator=webmaster \
    cache-hit-dscp=4 cache-on-disk=no cache-path=web-proxy enabled=no \
    max-cache-object-size=2048KiB max-cache-size=unlimited \
    max-client-connections=600 max-fresh-time=3d max-server-connections=600 \
    parent-proxy=:: parent-proxy-port=0 port=8080 serialize-connections=no \
    src-address=::
/ip service
set telnet address="" disabled=no max-sessions=20 port=23 vrf=main
set ftp address="" disabled=no max-sessions=20 port=21 vrf=main
set www address="" disabled=no max-sessions=20 port=80 vrf=main
set ssh address="" disabled=no max-sessions=20 port=22 vrf=main
set www-ssl address="" certificate=none disabled=yes max-sessions=20 port=443 \
    tls-version=any vrf=main
set api address="" disabled=no max-sessions=20 port=8728 vrf=main
set winbox address="" disabled=no max-sessions=20 port=8291 vrf=main
set api-ssl address="" certificate=none disabled=no max-sessions=20 port=8729 \
    tls-version=any vrf=main
/ip smb shares
set [ find default=yes ] directory=flash/pub disabled=yes invalid-users="" \
    name=pub read-only=no require-encryption=no valid-users=""
/ip socks
# inactivated, not allowed by device-mode
set auth-method=none connection-idle-timeout=2m enabled=no max-connections=200 \
    port=1080 version=4 vrf=main
/ip ssh
set always-allow-password-login=no ciphers=auto forwarding-enabled=no \
    host-key-size=2048 host-key-type=rsa strong-crypto=no
/ip tftp settings
set max-block-size=4096
/ip traffic-flow
set active-flow-timeout=30m cache-entries=64k enabled=no \
    inactive-flow-timeout=15s interfaces=all packet-sampling=no \
    sampling-interval=0 sampling-space=0
/ip traffic-flow ipfix
set bytes=yes dst-address=yes dst-address-mask=yes dst-mac-address=yes \
    dst-port=yes first-forwarded=yes gateway=yes icmp-code=yes icmp-type=yes \
    igmp-type=yes in-interface=yes ip-header-length=yes ip-total-length=yes \
    ipv6-flow-label=yes is-multicast=yes last-forwarded=yes nat-dst-address=\
    yes nat-dst-port=yes nat-events=no nat-src-address=yes nat-src-port=yes \
    out-interface=yes packets=yes protocol=yes src-address=yes \
    src-address-mask=yes src-mac-address=yes src-port=yes sys-init-time=yes \
    tcp-ack-num=yes tcp-flags=yes tcp-seq-num=yes tcp-window-size=yes tos=yes \
    ttl=yes udp-length=yes
/ip upnp
set allow-disable-external-interface=no enabled=no show-dummy-rule=yes
/ipv6 nd
set [ find default=yes ] advertise-dns=yes advertise-mac-address=yes disabled=\
    no hop-limit=unspecified interface=all managed-address-configuration=no \
    mtu=unspecified other-configuration=no ra-delay=3s ra-interval=3m20s-10m \
    ra-lifetime=30m ra-preference=medium reachable-time=unspecified \
    retransmit-interval=unspecified
/ipv6 nd prefix default
set autonomous=yes preferred-lifetime=1w valid-lifetime=4w2d
/mpls settings
set allow-fast-path=yes dynamic-label-range=16-1048575 propagate-ttl=yes
/ppp aaa
set accounting=yes enable-ipv6-accounting=no interim-update=0s \
    use-circuit-id-in-nas-port-id=no use-radius=no
/radius incoming
set accept=no port=3799 vrf=main
/routing igmp-proxy
set query-interval=2m5s query-response-interval=10s quick-leave=no
/routing settings
set single-process=no
/snmp
set contact="" enabled=no engine-id-suffix="" location="" src-address=:: \
    trap-community=public trap-generators=temp-exception trap-target="" \
    trap-version=1 vrf=main
/system clock
set time-zone-autodetect=yes time-zone-name=America/Los_Angeles
/system clock manual
set dst-delta=+00:00 dst-end="1970-01-01 00:00:00" dst-start=\
    "1970-01-01 00:00:00" time-zone=+00:00
/system health settings
set cpu-overtemp-check=no cpu-overtemp-startup-delay=1m \
    cpu-overtemp-threshold=105C fan-control-interval=30s fan-full-speed-temp=\
    65C fan-min-speed-percent=12% fan-target-temp=58C
/system identity
set name=MikroTik
/system leds
set 0 disabled=no interface=UPLINKSFP leds=sfp-sfpplus1-led1 type=\
    interface-activity
set 1 disabled=no interface=UPLINKSFP leds=sfp-sfpplus1-led2 type=\
    interface-speed
set 2 disabled=no interface=sfp-sfpplus2 leds=sfp-sfpplus2-led1 type=\
    interface-activity
set 3 disabled=no interface=sfp-sfpplus2 leds=sfp-sfpplus2-led2 type=\
    interface-speed
/system leds settings
set all-leds-off=never
/system logging
set 0 action=memory disabled=no prefix="" regex="" topics=info
set 1 action=memory disabled=no prefix="" regex="" topics=error
set 2 action=memory disabled=no prefix="" regex="" topics=warning
set 3 action=echo disabled=no prefix="" regex="" topics=critical
/system note
set note="" show-at-cli-login=no show-at-login=no
/system ntp client
set enabled=no mode=unicast servers="" vrf=main
/system ntp server
set auth-key=none broadcast=no broadcast-addresses="" enabled=no \
    local-clock-stratum=5 manycast=no multicast=no use-local-clock=no vrf=main
/system package local-update mirror
set check-interval=1d enabled=no primary-server=0.0.0.0 secondary-server=\
    0.0.0.0 user=""
/system resource irq
set 0 cpu=auto
set 1 cpu=auto
set 2 cpu=auto
/system resource irq rps
set Desktop disabled=yes
set "Access Point" disabled=yes
set "CLUSTER - PVENAS" disabled=yes
set "PROD - PVENAS" disabled=yes
set "CLUSTER - PVE5" disabled=yes
set "PROD - PVE5" disabled=yes
set "CLUSTER - PVE3" disabled=yes
set "PROD - PVE3" disabled=yes
set UPLINKSFP disabled=yes
set sfp-sfpplus2 disabled=yes
/system resource usb settings
set authorization=no
/system routerboard reset-button
set enabled=no hold-time=0s..1m on-event=""
/system routerboard settings
set auto-upgrade=no boot-device=nand-if-fail-then-ethernet boot-os=router-os \
    boot-protocol=bootp force-backup-booter=no preboot-etherboot=disabled \
    preboot-etherboot-server=any protected-routerboot=disabled \
    reformat-hold-button=20s reformat-hold-button-max=10m silent-boot=no
/system swos
set address-acquisition-mode=dhcp-with-fallback allow-from=0.0.0.0/0 \
    allow-from-ports=p1,p2,p3,p4,p5,p6,p7,p8,p9,p10 allow-from-vlan=0 \
    identity=Mikrotik static-ip-address=192.168.88.1
/system watchdog
set auto-send-supout=no automatic-supout=yes ping-start-after-boot=5m \
    ping-timeout=1m watch-address=none watchdog-timer=yes
/tool bandwidth-server
set allocate-udp-ports-from=2000 allowed-addresses4="" allowed-addresses6="" \
    authenticate=yes enabled=yes max-sessions=100
/tool e-mail
set from=<> port=25 server=0.0.0.0 tls=no user="" vrf=main
/tool graphing
set page-refresh=300 store-every=5min
/tool mac-server
set allowed-interface-list=all
/tool mac-server mac-winbox
set allowed-interface-list=all
/tool mac-server ping
set enabled=yes
/tool romon
set enabled=no id=00:00:00:00:00:00
/tool romon port
set [ find default=yes ] cost=100 disabled=no forbid=no interface=all
/tool sms
set allowed-number="" channel=0 polling=no port=none receive-enabled=no \
    sms-storage=sim
/tool sniffer
set file-limit=1000KiB file-name="" filter-cpu="" filter-direction=any \
    filter-dst-ip-address="" filter-dst-ipv6-address="" \
    filter-dst-mac-address="" filter-dst-port="" filter-interface="" \
    filter-ip-address="" filter-ip-protocol="" filter-ipv6-address="" \
    filter-mac-address="" filter-mac-protocol="" \
    filter-operator-between-entries=or filter-port="" filter-size="" \
    filter-src-ip-address="" filter-src-ipv6-address="" \
    filter-src-mac-address="" filter-src-port="" filter-stream=no filter-vlan=\
    "" memory-limit=100KiB memory-scroll=yes only-headers=no quick-rows=20 \
    quick-show-frame=no streaming-enabled=no streaming-server=0.0.0.0:37008
/tool traffic-generator
set latency-distribution-max=100us measure-out-of-order=no \
    stats-samples-to-keep=100 test-id=0
/user aaa
set accounting=yes default-group=read exclude-groups="" interim-update=0s \
    use-radius=no
/user settings
set minimum-categories=0 minimum-password-length=0
