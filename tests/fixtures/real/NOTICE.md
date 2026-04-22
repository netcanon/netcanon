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

## fortigate/

| File | Origin | License | Notes |
|---|---|---|---|
| `kevinguenay_fgt_70g_branch.conf` | [KevinGuenay/fortinet-resources](https://github.com/KevinGuenay/fortinet-resources) `blog_resources/fortigate_ztp/fortigate_configurations/FGT-70G-BRANCH.conf` | MIT | Real FortiOS 7.6.6 branch config for a FortiGate 70G ZTP deployment.  12,317 lines covering system global, interfaces (including `fortilink` + `LAG_INTERNAL` aggregates), VLAN subinterfaces (named `VL_100` / `VL_101`), BGP loopback, SD-WAN, IPsec, firewall policies, VIPs, web filtering, antivirus, IPS.  Our codec extracts the subset it models; the rest is silently carried past. |
| `kevinguenay_fgt_vm_hub.conf` | [KevinGuenay/fortinet-resources](https://github.com/KevinGuenay/fortinet-resources) `blog_resources/fortigate_ztp/fortigate_configurations/FGT-VM-HUB.conf` | MIT | Real FortiOS 7.6.6 VM-based hub config — 13,827 lines.  Hub-side counterpart to the branch config above.  Same OS version (gap to `certified` tier — need a fixture from a different OS version). |

## aruba_aoss/

| File | Origin | License | Notes |
|---|---|---|---|
| `aruba_central_5memberstack_rendered.cfg` | [aruba/central-sample-bulk-configurations](https://github.com/aruba/central-sample-bulk-configurations) `ArubaOS-Switch Templates/5MemberStack - Template/5memberStack - Template.txt` | BSD-2-Clause *(upstream)* | **Rendered** from Aruba Central's bulk-config template via `scripts/render_aruba_central_template.py` (defensible-defaults substitution + top-level-keyword dedent post-pass).  Real AOS-S grammar, but with placeholder values — see `aruba_aoss/README.md` for the "do better later" note. |

---

## Adding new captures

1. Fetch from an unambiguously-licensed public source (Apache, MIT, BSD).
2. Drop into `<vendor>/` with a filename that encodes origin + feature.
3. Update this NOTICE with an entry covering origin URL, license, and
   what the file stresses.
4. The parametrized harness at `tests/unit/migration/test_real_captures.py`
   picks up every `*.txt` / `*.cfg` / `*.xml` under `<vendor>/`
   automatically — no further wiring needed.
