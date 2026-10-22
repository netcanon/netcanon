# An interface's MTU: what the number counts, platform by platform

The same link is `mtu 1500` on IOS-XE and `mtu 1514` on Junos: the
platforms do not count the same bytes.  The canonical tree holds the
PAYLOAD -- the largest IP packet, with no Ethernet header, tag or FCS
-- and each parser and renderer converts at its own edge, from one
table (`MTU_BEYOND_THE_PAYLOAD` in
`netcanon/migration/codecs/_helpers.py`).  This is where the rows of
that table come from.  It is kept in this pair's file because the two
platforms of the pair are on opposite sides of it; it covers every
codec that reads an interface MTU.  Retrieved 2026-10-20.

| Platform | Interface `mtu` counts, beyond the payload | Default | Grade | Source |
|---|---|---|---|---|
| Junos (media MTU) | the 14-byte Ethernet header, and 4 more for each 802.1Q tag the device's tagging statement names (overhead 18 for one); not the FCS | 1514 | header: vendor sentence; a tag: inferred from the vendor's overhead table; 4 more under `flexible-vlan-tagging`: vendor sentence | J1, J2, J3 |
| Cisco IOS XR | the 14-byte Ethernet header, and 4 bytes per tag; not the FCS | 1514 (1518 with one tag) | vendor sentence | X1, X2, X3 |
| Dell OS10 (link MTU) | a frame: 22 bytes for a tagged member | 9216 since 10.5.4.4 (1532 before) | "frame size": vendor sentence; 22 bytes: from the vendor's tagged example | D1, D2 |
| Cisco IOS-XE | nothing: the payload | 1500 | vendor sentence | C1, C2 |
| Cisco NX-OS | nothing: the payload | 1500 | vendor sentence, in an APIC guide that names NX-OS | N1, N2 |
| Arista EOS | nothing: the IP MTU | 1500 | vendor sentence | A1 |
| Aruba AOS-CX | nothing: the Ethernet payload | 1500 | vendor sentence (VSG) | H1, H2 |
| MikroTik RouterOS (`mtu`) | nothing: the "Layer3" MTU | 1500 | vendor sentence | M1, M2 |
| FortiOS | nothing | 1500 | inferred: the MSS is the MTU less 40 | F1 |
| VyOS | nothing | 1500, from an example | inferred: the MSS is the MTU less 40; the vendor's pages disagree | V1, V2 |
| OPNsense | nothing | not stated | inferred: PPPoE's 8 bytes are added to 1500, and no header | O1 |
| Aruba AOS-S | has no interface MTU: `jumbo` is per VLAN, the frame size and IP MTU are global | -- | vendor sentences | H3, H4 |

### Sources

Quoted text is the vendor's.  Where a page could only be read in
fragments, "..." joins two fragments of one passage.

- **J1** -- Juniper, *Interfaces Fundamentals*, Media MTU:
  <https://www.juniper.net/documentation/us/en/software/junos/interfaces-fundamentals/topics/topic-map/media-mtu.html>.
  "The physical MTU for Ethernet interfaces does not include the
  4-byte frame check sequence (FCS) field of the Ethernet frame."
  "Increasing the protocol MTU size requires the media MTU to be equal
  to or greater than the protocol MTU and encapsulation overhead."
  Table 1, Encapsulation Overhead by Interface Encapsulation Type:
  "802.1Q/Ethernet version 2 | 18" ... "Ethernet version 2 | 14".
- **J2** -- Juniper, CLI reference, `mtu` (edit interfaces):
  <https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/mtu-edit-interfaces-ni.html>.
  "Default: INET, INET6, and ISO families: 1500 bytes EX Series switch
  interfaces: 1514 bytes"; "MTU for IRB interfaces is calculated by
  removing the Ethernet header overhead (6(DMAC)+6(SMAC)+2(EtherType))".
- **J3** -- Juniper, *Enabling VLAN Tagging* (retrieved 2026-10-21):
  <https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/task/interfaces-enabling-vlan-tagging.html>.
  "If you configure the physical interface MTU for mixed tagging,
  then you must increase the MTU to 4 bytes more" (than on a
  VLAN-tagged interface: 1022 where that is "1018 on a VLAN-tagged
  interface").  "The additional 4 bytes accommodates the future
  addition of a stacked VLAN tag configuration on the same physical
  interface."
- **X1** -- Cisco, *Troubleshoot MTU on IOS XR*:
  <https://www.cisco.com/c/en/us/support/docs/ios-nx-os-software/ios-xr-software/116350-trouble-ios-xr-mtu-00.html>.
  "the mtu command that configures the L2 MTU includes 14 bytes for an
  Ethernet interface" ... "A routed sub-interface MTU inherits the MTU
  of its parent main interface;" ... "add 4 bytes for each VLAN tag
  configured on the sub-interface."  The same article on classic IOS:
  "the interface mtu command configures the L2 payload size, but does
  not include the L2 header."
- **X2** -- Cisco, *Cisco 8000, IOS XR 7.3.x, Configuring Ethernet
  Interfaces*:
  <https://www.cisco.com/c/en/us/td/docs/iosxr/cisco8000/Interfaces/73x/configuration/guide/b-interfaces-config-guide-cisco8k-r73x/m-configuring-ethernet-interfaces-8k.html>.
  "The default value is 1514 for standard frames and 1518 for 802.1Q
  tagged frames." ... "These numbers exclude the 4-byte frame check
  sequence (FCS)."
- **X3** -- Cisco, *Cisco 8000, IP MTU*:
  <https://www.cisco.com/c/en/us/td/docs/iosxr/cisco8000/interfaces-and-hardware-component/configuration-guide/interfaces-and-hardware-component-config-cisco8000/mtu-overview/ip-mtu.html>.
  "When Ethernet MTU and no IP MTU is configured, IP MTU value in the
  hardware is Ethernet MTU-14B."
- **D1** -- Dell, *SmartFabric OS10 User Guide 10.5.6*, `mtu`:
  <https://www.dell.com/support/manuals/en-us/smartfabric-os10-emp-partner/smartfabric-os-user-guide-10-5-6/mtu?guid=guid-055fd9ec-d381-44a0-8e16-ca6d68b7a630&lang=en-us>.
  "Sets the link maximum transmission unit (MTU) frame size for an
  Ethernet L2 or L3 interface."  "Tagged members must have a link MTU
  4 bytes higher than untagged members to account for the packet
  tag."  "For example, the VLAN contains tagged members with Link MTU
  of 1522 and IP MTU of 1500 and untagged members with Link MTU of
  1518 and IP MTU of 1500."
- **D2** -- Dell, *OS10 User Guide 10.5.6*, Default MTU configuration:
  <https://www.dell.com/support/manuals/en-us/smartfabric-os10-emp-partner/smartfabric-os-user-guide-10-5-6/default-mtu-configuration?guid=guid-929ecde7-b507-49a8-a9e9-53bff7187110&lang=en-us>.
  "Starting from Release 10.5.4.4, the default MTU value is 9216
  bytes. Previously, the default value was 1532 bytes."
- **C1** -- Cisco, *Troubleshoot MTU on Catalyst 9000 Series*:
  <https://www.cisco.com/c/en/us/support/docs/switches/catalyst-9500-series-switches/217233-troubleshoot-mtu-on-catalyst-9000-series.html>.
  "In general, this Unit is the IP packet Length which includes the IP
  Header." ... "L2 headers like, Dot1q tag, MacSec, SVL header and so
  on, are not accounted in this calculation."
- **C2** -- Cisco, *ASR 920, IOS XE 17.1.1, Ethernet interfaces*:
  <https://www.cisco.com/c/en/us/td/docs/routers/asr920/configuration/guide/chassis/17-1-1/b-Chassis-Guide-xe-17-1-asr920/m-eth_im_config-asr920.html>.
  "The interface automatically adds an additional 22 bytes to the
  configured MTU size."
- **N1** -- Cisco, *APIC Basic Configuration Guide 3.x*, Basic User
  Tenant Configuration:
  <https://www.cisco.com/c/en/us/td/docs/switches/datacenter/aci/apic/sw/3-x/basic_config/b_APIC_Basic_Config_Guide_3_x/b_APIC_Basic_Config_Guide_3_x_chapter_0101.pdf>.
  "On some platforms, such as Cisco ACI, Cisco NX-OS, and Cisco IOS,
  the configurable MTU value does not take into account the Ethernet
  headers (matching IP MTU, and excluding the 14-18 Ethernet header
  size), while other platforms, such as IOS-XR, include the Ethernet
  header in the configured MTU value. A configured value of 9000
  results in a max IP packet size of 9000 bytes in Cisco ACI, Cisco
  NX-OS, and Cisco IOS, but results in a max IP packet size of 8986
  bytes for an IOS-XR untagged interface."
- **N2** -- Cisco, *Nexus 9000 NX-OS Interfaces Configuration Guide
  10.1(x)*:
  <https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/101x/configuration/interfaces/cisco-nexus-9000-nx-os-interfaces-configuration-guide-101x/b-cisco-nexus-9000-nx-os-interfaces-configuration-guide-93x_chapter_01110.html>.
  "By default, each interface uses an MTU of 1500 bytes".
- **A1** -- Arista, *EOS User Manual*, Data Transfer:
  <https://www.arista.com/en/um-eos/eos-data-transfer>.
  "The mtu command configures the IPv4 and IPv6 Maximum Transmission
  Unit (MTU) size" ... "The default MTU size is 1500 bytes."
- **H1** -- HPE Aruba Networking, *AOS-CX 10.15 Fundamentals*, `mtu`:
  <https://arubanetworking.hpe.com/techdocs/AOS-CX/10.15/HTML/fundamentals_8400/Content/Chp_IfaceCfg/Iface_cmds/mtu-10.htm>.
  "The largest possible layer 1 frame will be 18 bytes larger than the
  MTU value to allow for link layer headers and trailers."
- **H2** -- HPE Aruba Networking, *Validated Solution Guide*, Campus
  LAN design:
  <https://arubanetworking.hpe.com/techdocs/VSG/docs/010-campus-design/esp-campus-design-042-lan-design-routing-switching/>.
  "The AOS-CX Layer 2 MTU configuration value specifies the maximum
  Ethernet payload, which represents the same bytes as the Layer 3
  MTU."
- **H3** -- HPE Aruba Networking, *AOS-S 16.11*, Configuring a maximum
  frame size:
  <https://arubanetworking.hpe.com/techdocs/AOS-S/16.11/MCG/KB/content/kb/cnf-max-fra-siz.htm>.
  "The jumbo max-frame-size is set on a GLOBAL level."
- **H4** -- HPE Aruba Networking, *AOS-S 16.10*, Jumbo frames:
  <https://arubanetworking.hpe.com/techdocs/AOS-S/16.10/MCG/KB/content/kb/jum-fra.htm>.
  "You can enable inbound jumbo frames on a per-VLAN basis."
- **M1** -- MikroTik, *RouterOS*, Ethernet:
  <https://help.mikrotik.com/docs/display/ROS/Ethernet>.
  "mtu ( integer [0..65536] ; Default: 1500 ) Layer3 Maximum
  transmission unit".
- **M2** -- MikroTik, *MTU in RouterOS*:
  <https://help.mikrotik.com/docs/spaces/ROS/pages/21725296/MTU+in+RouterOS>.
  "L2MTU indicates the maximum size of the frame without the MAC
  header that can be sent by this interface."  (So `l2mtu` is not a
  Junos media MTU either: it leaves the header out.)
- **F1** -- Fortinet, *FortiOS 7.2.10 Administration Guide*, Interface
  MTU packet size:
  <https://docs.fortinet.com/document/fortigate/7.2.10/administration-guide/596096>.
  "The MSS is the MTU size of the interface minus the 20 byte IP header
  and 20 byte TCP header."
- **V1** -- VyOS, Ethernet (rolling):
  <https://docs.vyos.io/en/latest/configuration/interfaces/ethernet.html>.
  "This value defines the largest packet size, in bytes, that the
  interface transmits without fragmentation."  "The router
  automatically calculates the MSS to be the interface's MTU minus 40
  bytes for IPv4 traffic".
- **V2** -- VyOS, Ethernet (1.3):
  <https://docs.vyos.io/en/equuleus/configuration/interfaces/ethernet.html>.
  "It is the size (in bytes) of the largest ethernet frame sent on this
  link."  This page disagrees with V1.
- **O1** -- OPNsense, Devices:
  <https://docs.opnsense.org/manual/other-interfaces.html>.
  "To use a 1500 byte MTU on PPPoE in OPNsense, set the interface
  (usually Interfaces ‣ [WAN] ) to an MTU value of 1508 , in which
  case the tunnel itself will use the full 1500 bytes."

### Not established from a vendor's page

- **Junos**: a sentence that says the media MTU of a `vlan-tagging`
  port holds the tag, or that of a `stacked-vlan-tagging` port two.
  Both are read from J1's overhead table, which the media MTU must
  cover, at 4 bytes a tag; J3 then gives a `flexible-vlan-tagging`
  port 4 bytes more than a `vlan-tagging` one.  What a trunk in
  `family ethernet-switching` needs for its tags is not established
  either; the codec counts tags only for a port that states a
  tagging statement or whose units carry a tag.
- **NX-OS**: the Nexus 9000 guide itself does not say whether the
  header is counted; N1 is an APIC guide that names NX-OS.
- **OS10**: the 18 bytes of the untagged example in D1 against the 22
  of the tagged one.  The codec counts 22 for every interface: a 1500
  payload is `mtu 1522`, which carries it tagged or not.  D1 also
  gives a rule that the IP MTU be 32 bytes below the link MTU, which
  neither example meets.
- **FortiOS, VyOS, OPNsense**: no sentence says what the number counts.
- **AOS-S**: a sentence that says there is no per-interface MTU.
- **The IOS-XE NETCONF codec** reads OpenConfig's `config/mtu` into
  its own record and does not carry it into the tree, so it has no row.

### Mapping notes

- `CanonicalInterface.mtu` is the payload.  A parser subtracts what
  its platform's number counts beyond it and a renderer adds it back,
  so a job from a codec to itself writes the number it read.
- Only interfaces whose number is an Ethernet one are converted: a
  Junos port, aggregate or `irb`; an IOS XR port, management port or
  `Bundle-Ether` and their sub-interfaces; an OS10 port, lane,
  management port, `port-channel` or `vlan`.  A loopback, a tunnel,
  or a name the codec's own classifier does not read is copied as it
  stands -- what its number counts is not established here.
- A second tag (QinQ) adds 4 more bytes on IOS XR (`second-dot1q`).
  On Junos the tags counted are the ones the device's tagging
  statement names; a device that states none is counted by the tags
  its units carry (the renderer writes the statement its units need).
- A jumbo value near a platform's maximum can pass it once converted
  (IOS-XE `mtu 9216` is Junos `mtu 9230`, above the EX range of
  9216).  The device refuses such a line when the config is
  committed; nothing here checks a platform's range.
- The IP MTU (`ip mtu`, `family inet mtu`, `ipv4 mtu`) counts the same
  bytes on every platform; it is a field of its own, not this one.
