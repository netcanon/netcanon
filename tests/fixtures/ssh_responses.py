"""
Canned SSH output strings keyed by vendor.

Use these constants in unit tests that exercise output-processing logic, or
as the ``output`` argument when constructing ``FakeCollector`` instances in
integration and E2E tests.

All strings faithfully represent real device output as it would arrive from
the underlying SSH transport — including the trailing prompt line that a
prompt-stripping layer would remove.
"""

CISCO_RUNNING_CONFIG = """\
Building configuration...

Current configuration : 2048 bytes
!
version 17.9
service timestamps debug datetime msec
service timestamps log datetime msec
!
hostname Router
!
boot-start-marker
boot-end-marker
!
no aaa new-model
!
interface GigabitEthernet0/0
 description WAN
 ip address 192.168.1.1 255.255.255.0
 duplex auto
 speed auto
!
interface GigabitEthernet0/1
 description LAN
 ip address 10.0.0.1 255.255.255.0
 duplex auto
 speed auto
!
ip route 0.0.0.0 0.0.0.0 192.168.1.254
!
end

Router#
"""

FORTIGATE_FULL_CONFIG = """\
#config-version=FGVM64-7.4.1-FW-build2463-231117:opmode=0:vdom=0:user=admin
#conf_file_ver=50
#buildno=2463
#global_vdom=1
config system global
    set hostname FortiGate
    set timezone 04
end
config system interface
    edit "wan1"
        set ip 192.168.1.1 255.255.255.0
    next
end

FortiGate #
"""

OPNSENSE_CONFIG_XML = """\
<?xml version="1.0"?>
<opnsense>
  <version>25.1.2</version>
  <system>
    <hostname>opnsense</hostname>
    <domain>local</domain>
  </system>
  <interfaces>
    <wan>
      <if>em0</if>
      <ipaddr>dhcp</ipaddr>
    </wan>
  </interfaces>
</opnsense>
"""

MIKROTIK_EXPORT = """\
# RouterOS 7.12
# software id = XXXX-YYYY
#
# model = hEX S
# serial number = 123456789
/interface bridge
add name=bridge1
/ip address
add address=192.168.88.1/24 interface=bridge1 network=192.168.88.0
/ip route
add gateway=192.168.88.254

[admin@MikroTik] >
"""

# Cisco output with --More-- prompts embedded mid-stream.
# Reflects the raw bytes before space-injection paging is applied.
CISCO_MORE_PAGED = """\
Building configuration...

Current configuration : 512 bytes
!
version 17.9
hostname Router
 --More--
interface GigabitEthernet0/0
 description WAN
 --More--
end

Router#
"""
