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

---

## Adding new captures

1. Fetch from an unambiguously-licensed public source (Apache, MIT, BSD).
2. Drop into `<vendor>/` with a filename that encodes origin + feature.
3. Update this NOTICE with an entry covering origin URL, license, and
   what the file stresses.
4. The parametrized harness at `tests/unit/migration/test_real_captures.py`
   picks up every `*.txt` / `*.cfg` / `*.xml` under `<vendor>/`
   automatically — no further wiring needed.
