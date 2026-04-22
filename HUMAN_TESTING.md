# Human testing queue

Things to try in the UI / desktop app / API when a human sits down with
the tool.  Assistant keeps this up to date as features ship, bugs are
fixed, or flows are touched.

Format: newest items on top, grouped by area.  A `[x]` prefix means
it's been exercised at least once (leave them here as a regression
list, don't delete).

---

## Migration — data-loss bug regressions (fixed, should hold)

- [ ] **Bug 4** — `ip default-gateway X` on Cisco CLI.  Paste a
      Cisco config containing `ip default-gateway 192.168.11.1` into
      the Migrate page, source `cisco_iosxe_cli`, target
      `aruba_aoss`.  Aruba output should contain literal
      `ip default-gateway 192.168.11.1`.
- [ ] **Bug 3** — switchport → VLAN-centric transpose.  Paste a
      Cisco config with per-port `switchport access vlan 10` and
      `switchport trunk allowed vlan 10,20`; target Aruba should
      emit those ports under VLAN 10's `untagged` and VLAN 10/20's
      `tagged` lists.
- [ ] **Bug 2** — LAG/port-channel members.  Paste
      `interface Port-channel1` + two physical ports each with
      `channel-group 1 mode active`; Aruba output should show
      `trunk <port1>,<port2> trk1 lacp`.
- [ ] **Bug 1** — VLAN SVI IPs.  Paste
      `interface Vlan11 / ip address 192.168.11.252 255.255.255.0`
      (no matching `vlan 11` stanza); Aruba output should include a
      `vlan 11` stanza carrying that IP.

## Migration — real-capture fidelity smoke tests

- [ ] Upload `tests/fixtures/real/fortigate/kevinguenay_fgt_70g_branch.conf`
      (~348K, 12K lines of real FortiOS 7.6.6).  Target OPNsense XML.
      Output should preserve hostname + 2 DNS + 21 interfaces + 2
      VLANs.
- [ ] Upload `tests/fixtures/real/opnsense/opnsense_core_default.xml`.
      Target Cisco IOS-XE NETCONF.  Basic round-trip should survive.
- [ ] Upload `tests/fixtures/real/mikrotik/ntc_ip_address_export.rsc`.
      Target Aruba.  Interface names (`ether2`, `eth3_vlan1`) should
      appear verbatim in the trunk/vlan membership.
- [ ] Upload `tests/fixtures/real/aruba_aoss/aruba_central_5memberstack_rendered.cfg`.
      Target FortiGate.  48 interfaces + 3 VLANs + LAG should survive.

## Migration — auto-detection (R5)

- [ ] Paste a config without pre-selecting source codec.  Detect
      banner should propose the right codec with confidence ≥50.
      Try each of: Cisco CLI, Aruba running-config, OPNsense XML,
      MikroTik `/export`, FortiOS `config/edit/set` — each should
      light up a different single-codec suggestion.
- [ ] Paste something deliberately ambiguous (e.g. just
      `hostname foo`) — banner should either suggest multiple or
      gracefully fall back to "no suggestion, pick manually".

## Settings / UI polish

*(nothing queued)*

## Desktop platform parity

- [ ] Spin up the desktop shell (`python -m netconfig_desktop`).
      Confirm migrate page works identically to web — same
      `data-testid`s, same detect banner, same fixture upload flow.
- [ ] System tray icon shows / hides the window.  Close button
      minimises to tray (doesn't kill the server).
- [ ] "Open in text editor" button on a backup config (desktop only)
      launches the system's default editor via `os.startfile`.

## API direct

- [ ] `GET /api/v1/migration/adapters` — returns all 7 codecs with
      new metadata fields (description, sample_input,
      output_extension).
- [ ] `POST /api/v1/migration/detect` — accepts raw config in body,
      returns ranked `DetectCandidate` list.
- [ ] Swagger UI at `/docs` — all migration endpoints documented
      with example payloads.

---

## Adding items

Assistant maintains this file.  When shipping a feature or fix that
a human should exercise before trusting, append a new bullet to the
right section.  Keep items concise (one sentence plus a concrete
paste-this / click-this instruction).  Don't remove checked items —
they're regression reminders.