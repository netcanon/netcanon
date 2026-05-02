# Firewall / NAT / VPN / IPsec / VDOMs / per-interface VRF: FortiGate FortiOS versus Arista EOS

## FortiGate FortiOS — firewall + multi-tenancy product surface

Source: [Fortinet Document Library — Firewall Policies (FortiOS 7.4 Cookbook)](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/)
Source: [Fortinet Document Library — VRF support (FortiOS 7.x Admin Guide)](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/)
Source: [Fortinet Document Library — VDOM configuration (FortiOS 7.4 Admin Guide)](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/)
Retrieved: 2026-05-01

```
config firewall policy
    edit 1
        set name "allow-internal-to-wan"
        set srcintf "internal"
        set dstintf "wan1"
        set srcaddr "all"
        set dstaddr "all"
        set service "ALL"
        set action accept
        set nat enable
        set utm-status enable
        set ssl-ssh-profile "deep-inspection"
        set av-profile "default"
    next
end
config firewall vip
    edit "web-server-vip"
        set extip 198.51.100.10
        set mappedip "10.10.10.10"
        set extport 443
        set mappedport 443
    next
end
config vpn ipsec phase1-interface
    edit "to-branch-A"
        set interface "wan1"
        set peertype any
        set net-device disable
        set proposal aes256-sha256
        set remote-gw 203.0.113.5
        set psksecret ENC fakeIPsecPSK11111111==
    next
end
config system interface
    edit "port4"
        set vrf 10            ; FortiOS 7.x per-interface integer VRF
        ...
    next
end
config vdom
    edit root
        ...
    next
    edit tenantA
        ...
    next
end
```

The FortiGate product centres on:

- **Firewall policy** (`config firewall policy`) — session-based,
  zone-aware, with UTM (AV / IPS / web-filter / app-control / SSL
  inspection) profile attachment.
- **NAT** baked into firewall policy via `set nat enable` plus VIP
  (`config firewall vip`) for inbound port-forwarding.
- **VPN / IPsec** — `config vpn ipsec phase1-interface` /
  `phase2-interface` for site-to-site; `config vpn ssl settings`
  for SSL-VPN.
- **Per-interface integer VRF** (FortiOS 7.x) via `set vrf <id>`
  inside the interface stanza — closer to Cisco VRF-Lite than to
  Arista's named-VRF + RD + RT model.
- **VDOMs** — heavyweight multi-tenancy primitive.  Each VDOM
  carries an independent firewall policy table, address-object
  database, admin sessions, routing table, and (in FortiOS 7.x)
  per-VDOM resource limits.

## Arista EOS — none of the above (in canonical-renderable form)

Source: [Arista EOS User Manual — Access Control Lists (4.35.2F)](https://www.arista.com/en/um-eos/eos-access-control-lists)
Source: [Arista EOS User Manual — VRF (4.35.2F)](https://www.arista.com/en/um-eos/eos-vrf)
Retrieved: 2026-05-01

Arista EOS as a DC switch has different roles:

- **No stateful firewall.**  Arista has stateless ACLs (`ip
  access-list`) and Tier-3 informational MAC ACLs but no session-
  table-based firewall policy.  Canonical model has no firewall-
  policy representation.
- **No NAT** in the canonical-renderable sense.  Arista PE/SE
  routing doesn't expose Cisco-NAT-style or FortiGate-policy-NAT
  primitives.
- **No VPN / IPsec** product surface on a typical leaf switch.
- **VRFs are different in shape.**  Arista has `vrf instance <name>`
  with full RD / RT / route-distinguisher / route-target import-
  export semantics — it's a named-VRF + MP-BGP model, structurally
  different from FortiGate's per-interface integer-VRF or VDOM
  multi-tenancy.
- **No multi-tenancy primitive** at the appliance level.  Arista
  achieves tenant separation via VRFs + EVPN-VXLAN, not via
  parallel security contexts.

## Cross-vendor mapping (FortiGate -> Arista)

Canonical surface (none of these populate from FortiGate parse in
v1):

```
routing_instances: list[CanonicalRoutingInstance]
interfaces[].vrf: str
```

- **routing_instances** — `unsupported`.  FortiGate codec does not
  parse `set vrf <id>` (per-interface integer VRF) into
  CanonicalRoutingInstance records in v1.  Even if it did,
  FortiOS 7.x integer-VRF is structurally different from Arista's
  named-VRF + RD + RT model — the integer doesn't carry the
  RD/RT semantics Arista needs.  VDOMs are a heavier-weight
  primitive (independent firewall policy + address-objects +
  admin sessions) that don't map 1:1 to Arista VRFs.  Cross-
  vendor migration of FortiGate multi-tenancy intent to Arista
  requires manual reconstruction via `vrf instance` + EVPN
  fabric.
- **interfaces[].vrf** — `unsupported`.  Same root cause as
  routing_instances — FortiGate codec doesn't parse `set vrf
  <id>` into the canonical field.

## Tier-3 informational surfaces (raw_sections)

The FortiGate codec carries `config firewall policy`, `config
firewall vip`, `config firewall address`, `config vpn ipsec
phase1-interface`, `config vpn ipsec phase2-interface`, and `config
vdom` blocks as Tier-3 raw_sections content.  These are
**informational only** — never auto-rendered to the Arista target.
The Arista codec has no firewall-policy / NAT / IPsec equivalent
that the canonical model could capture.

Operators consolidating a FortiGate edge into an Arista DC-switch
role (uncommon — typical migrations go the other way) must:

1. Accept that firewall policy, NAT, VPN, UTM are all lost on
   migration — those duties shift back to a separate firewall
   appliance.
2. Manually reconstruct VRF separation via Arista `vrf instance`
   + EVPN-VXLAN if multi-tenancy is required.
3. Rebuild address-object / service / schedule libraries (FortiOS
   `config firewall address` / `config firewall service`) outside
   the migration tree.

Disposition summary: **unsupported across the entire firewall +
multi-tenancy surface**.  FortiGate's primary product role does not
exist on Arista EOS, and the canonical model intentionally has no
representation for it (Tier-3 by design).  Per-interface integer
VRF and VDOMs are also unsupported (codec parse gap + structural
model mismatch).
