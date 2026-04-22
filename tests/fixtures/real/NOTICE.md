# Real-capture fixture provenance

Third-party Cisco / Aruba / FortiGate / OPNsense / MikroTik config snippets
used as **real-world parser validation fixtures**.  None of these files are
authored by netconfig; they are included verbatim under their upstream
licenses for the sole purpose of exercising our codec parsers against
configs the project didn't itself design.

This directory is intentionally *not* a `.gitignore`d downloads folder —
the fixtures are committed so CI can detect regressions against the exact
bytes we validated against, and so future contributors don't have to
re-discover them.

---

## cisco_iosxe/

| File | Origin | License | Notes |
|---|---|---|---|
| `ntc_carrier_interfaces.txt` | [networktocode/ntc-templates](https://github.com/networktocode/ntc-templates) `tests/cisco_ios/show_running-config_interface/cisco_ios_show_running-config_interface.raw` | Apache-2.0 | Carrier-grade IOS interfaces with VRFs, sub-interfaces (dot1Q Q-in-Q), QoS service-policies, uRPF, ACL groups.  Stress-tests features our codec doesn't model. |
| `batfish_cisco_interface.txt` | [batfish/batfish](https://github.com/batfish/batfish) `tests/parsing-tests/networks/unit-tests/configs/cisco_interface` | Apache-2.0 | Grammar kitchen-sink — every interface sub-command Batfish's parser supports on one Ethernet.  "Parse doesn't crash" stress test. |
| `batfish_cisco_ip_route.txt` | [batfish/batfish](https://github.com/batfish/batfish) `tests/parsing-tests/networks/unit-tests/configs/cisco_ip_route` | Apache-2.0 | Static-route variants including `ip route ... name`, `track`, administrative distance, tag, `permanent`. |
| `batfish_cisco_aaa.txt` | [batfish/batfish](https://github.com/batfish/batfish) `tests/parsing-tests/networks/unit-tests/configs/cisco_aaa` | Apache-2.0 | AAA accounting/authentication/authorization stanzas — tests the parser's tolerance for commands it doesn't model yet. |
| `batfish_cisco_snmp.txt` | [batfish/batfish](https://github.com/batfish/batfish) `tests/parsing-tests/networks/unit-tests/configs/cisco_snmp` | Apache-2.0 | `snmp-server community`, `snmp-server group`, `snmp-server user`, and trap destinations.  Real community names / view definitions. |
| `batfish_cisco_logging.txt` | [batfish/batfish](https://github.com/batfish/batfish) `tests/parsing-tests/networks/unit-tests/configs/cisco_logging` | Apache-2.0 | `logging host`, `logging buffered`, `logging facility`, etc.  Not canonically modelled yet — serves as "parse doesn't crash" validation. |
| `racc_csr1_iosxe173_umbrella_sig.txt` | [nickrusso42518/racc](https://github.com/nickrusso42518/racc) `samples_nohash/csr1_20210629T142431/show_running-config.txt` | BSD-3-Clause | Real `show running-config` from a CSR1000v on **IOS-XE 17.3** — 398 lines.  Exercises EIGRP CITYNET, OSPF, 22 static routes (Cisco Umbrella SIG anycast targets + default via Tunnel100), IKEv2 + IPsec profiles, SIG tunnel interface with `tunnel protection ipsec profile`, SSH pubkey-chain + `key-hash`, `ip access-list standard`, guestshell app-hosting, NETCONF-YANG candidate-datastore, 2 local users (admin priv 15 + ec2-user priv 15), PKI self-signed + SLA trustpoints. |
| `racc_csr1000v_iosxe169_bgp_ospf.txt` | [nickrusso42518/racc](https://github.com/nickrusso42518/racc) `samples_hash/csr2_20230811T074823/show_running-config.txt` | BSD-3-Clause | Real `show running-config` from a CSR1000v on **IOS-XE 16.9** — 280 lines.  Exercises BGP AS 65001 (with vpnv4 + rtfilter address-families), OSPF process 1, 11 interfaces (8 Loopbacks + 3 GigabitEthernet), class-map + policy-map QoS policies applied per-interface, logging-host syslog targets, `ip access-list extended`, NETCONF-YANG + RESTCONF, 2 local users (`developer` + `root` priv 15), `enable secret`, MOTD banner.  16.9 LTS is the oldest well-supported LTS we wire through; canary for pre-17.x grammar quirks. |
| `racc_cat8000v_iosxe179_netconf.txt` | [nickrusso42518/racc](https://github.com/nickrusso42518/racc) `samples_hash/csr1_20230811T074823/show_running-config.txt` | BSD-3-Clause | Real `show running-config` from a Cat8000V on **IOS-XE 17.9** — 343 lines.  Exercises `ip nat inside source list ... overload` (PAT), `ip access-list extended NAT-ACL`, `telemetry ietf subscription` (YANG-push periodic update-policy over grpc-tcp), `app-hosting appid guestshell`, PKI self-signed + SLA trustpoints, RESTCONF + NETCONF-YANG, AAA local + SSH pubkey, `username X secret 9 $9$...` (type-9 hash).  Cat8000V is the C-line (Catalyst) virtual router — same codec, different platform image. |

## opnsense/

| File | Origin | License | Notes |
|---|---|---|---|
| `opnsense_core_default.xml` | [opnsense/core](https://github.com/opnsense/core) `src/etc/config.xml.sample` | BSD-2-Clause | Upstream default `config.xml` template.  Includes system, users, groups, webgui, timeservers, bogons, firewall bits. |
| `opnsense_service_test_config.xml` | [opnsense/core](https://github.com/opnsense/core) `src/opnsense/service/tests/config/config.xml` | BSD-2-Clause | Service-layer test config with real interface zones (wan/lan), DHCP client settings, DHCPv6 prefix delegation, gateway tracking. |
| `opnsense_acl_test_config.xml` | [opnsense/core](https://github.com/opnsense/core) `src/opnsense/mvc/tests/app/models/OPNsense/ACL/AclConfig/config.xml` | BSD-2-Clause | ACL model test — 4 groups (admins + 3 test groups with distinct priv lists) + 5 users (root + 3 per-group testers + restricted admin).  Richest local_users surface in the corpus. |

## mikrotik/

| File | Origin | License | Notes |
|---|---|---|---|
| `ntc_ip_address_export.rsc` | [networktocode/ntc-templates](https://github.com/networktocode/ntc-templates) `tests/mikrotik_routeros/ip_address_export_verbose/mikrotik_routeros_ip_address_export_verbose.raw` | Apache-2.0 | Real RouterOS 6.48.6 `/export verbose` snippet.  Exercises the `# ... by RouterOS` banner + `/ip address` section with quoted comments. |
| `routeros_diff_verbose_export.rsc` | [adamcharnock/routeros-diff](https://github.com/adamcharnock/routeros-diff) `tests/test_files/verbose_export.rsc` | MIT | Real RouterOS 6.48.1 `/export verbose` — 484 lines from an RB952Ui-5ac2nD home router ("Quinta Router").  Covers `/interface bridge`, `/interface vlan` (named `gn-mgmt`), `/ip address`, `/ip dhcp-server network` + `/ip pool`, `/snmp`, `/interface wireless`, `/queue tree`.  Different OS version (6.48.1 vs 6.48.6). |
| `taqavi_initial_provisioning.rsc` | [AmirArsalanTaqavi/Mikrotik-Config-Examples](https://github.com/AmirArsalanTaqavi/Mikrotik-Config-Examples) `initial-provisioning.rsc` | MIT | Real MikroTik provisioning script (not a `/export` capture — a script an admin runs to provision an L009UiGS-2HaxD router).  Covers `/interface bridge` + `/interface bridge port`, `/interface ethernet` with per-port comments, `/ip service` restrictions, `/user add`, DHCP, WireGuard, firewall.  Password field contains the placeholder `ChangeMe123!` (called out in the source's own comment) — no real credential. |
| `user_contrib_crs310_ros7.rsc` | User-contributed real `/export verbose` from a CRS310-8G+2S+ running RouterOS 7.18.2.  Sanitised by `scripts/` (serial + software-id + MAC addresses replaced with non-identifying placeholders; infrastructure-describing interface names and RFC1918 IPs retained for grammar coverage). | CC0-1.0 *(user contribution)* | Real home-lab switch backing a Proxmox cluster + NAS.  630 lines covering a renamed ethernet port fleet (Desktop, Access Point, CLUSTER - PVE3/5/NAS, PROD - PVE3/5/NAS, UPLINKSFP), 5 VLANs (cluster/IOT/mgmt/server/user), bridge + bridge port, BGP template stub, IPv6 ND, l2tp-server, sstp-server, MPLS settings, system clock, system leds, system watchdog, tools, and a trove of other RouterOS 7 sections.  Third OS version for MikroTik (6.48.1 / 6.48.6 / 7.18.2) — the fixture that crossed MikroTik's `certified` threshold. |

## fortigate/

| File | Origin | License | Notes |
|---|---|---|---|
| `kevinguenay_fgt_70g_branch.conf` | [KevinGuenay/fortinet-resources](https://github.com/KevinGuenay/fortinet-resources) `blog_resources/fortigate_ztp/fortigate_configurations/FGT-70G-BRANCH.conf` | MIT | Real FortiOS 7.6.6 branch config for a FortiGate 70G ZTP deployment.  12,317 lines covering system global, interfaces (including `fortilink` + `LAG_INTERNAL` aggregates), VLAN subinterfaces (named `VL_100` / `VL_101`), BGP loopback, SD-WAN, IPsec, firewall policies, VIPs, web filtering, antivirus, IPS.  Our codec extracts the subset it models; the rest is silently carried past. |
| `kevinguenay_fgt_vm_hub.conf` | [KevinGuenay/fortinet-resources](https://github.com/KevinGuenay/fortinet-resources) `blog_resources/fortigate_ztp/fortigate_configurations/FGT-VM-HUB.conf` | MIT | Real FortiOS 7.6.6 VM-based hub config — 13,827 lines.  Hub-side counterpart to the branch config above.  Same OS version (gap to `certified` tier — need a fixture from a different OS version). |

## aruba_aoss/

| File | Origin | License | Notes |
|---|---|---|---|
| `aruba_central_5memberstack_rendered.cfg` | [aruba/central-sample-bulk-configurations](https://github.com/aruba/central-sample-bulk-configurations) `ArubaOS-Switch Templates/5MemberStack - Template/5memberStack - Template.txt` | BSD-2-Clause *(upstream)* | **Rendered** from Aruba Central's bulk-config template via `scripts/render_aruba_central_template.py` (defensible-defaults substitution + top-level-keyword dedent post-pass).  Real AOS-S grammar, but with placeholder values — see `aruba_aoss/README.md` for the "do better later" note. |
| `hpe_community_2930f_wc1607_intervlan.cfg` | [HPE Community forum thread 7026923](https://community.hpe.com/t5/aruba-provision-based/routing-not-working-as-expected-on-2930f-48g/td-p/7026923) | Forum share (user paste for troubleshooting) | Real 2930F `show running-config` on **WC.16.07.0002**.  12 VLANs with inter-VLAN L3, `ip helper-address` DHCP relay on 10 VLANs, `ip forward-protocol udp X dns` / `ntp`, 4 static routes (incl. `ip default-gateway` + `ip route 0.0.0.0/0`), `ip dns server-address`, `primary-vlan`, `timesync ntp`, `time daylight-time-rule`.  Email contact sanitised to `netadmin@example.test`; all addresses RFC1918. |
| `hpe_community_2920_wb1608_dhcp_snooping.cfg` | [HPE Community forum thread 7051607](https://community.hpe.com/t5/hpe-aruba-networking-provision/a-lot-of-packet-loss-in-switching-infrastructure/td-p/7051607) | Forum share (user paste for troubleshooting) | Real 2920 `show running-config` on **WB.16.08.0001** — different OS family (WB vs WC) and major version from the other captures.  Exercises `dhcp-snooping` with 13 `authorized-server` entries + VLAN scope + trust-port list, `ntp unicast` with `iburst` on peer, `ntp server <public>`, `web-management ssl`, `ip authorized-managers` ACLs, `snmp-server host ... trap-level critical`.  SNMP community already obscured `xxxx` by poster; all IPs RFC1918 except `194.25.134.196` (PTB public NTP, kept as real grammar). |
| `hpe_community_2930f_wc1610_dhcp_server.cfg` | [HPE Community forum thread 7084768](https://community.hpe.com/t5/aruba-provision-based/2930f-dhcp-server-vlan-setup/td-p/7084768) | Forum share (user paste for troubleshooting) | Real 2930F `show running-config` on **WC.16.10.0005**.  `dhcp-server pool` grammar exercised with 3 pools (default-router + dns-server + network + range per pool), 4 VLANs with `dhcp-server` enable flag, `allow-unsupported-transceiver`.  All IPs RFC1918 except public DNS `62.179.104.196, 213.46.228.196` (Ziggo Belgium ISP resolvers). |

---

## Adding new captures

1. Fetch from an unambiguously-licensed public source (Apache, MIT, BSD).
2. Drop into `<vendor>/` with a filename that encodes origin + feature.
3. Update this NOTICE with an entry covering origin URL, license, and
   what the file stresses.
4. The parametrized harness at `tests/unit/migration/test_real_captures.py`
   picks up every `*.txt` / `*.cfg` / `*.xml` under `<vendor>/`
   automatically — no further wiring needed.
