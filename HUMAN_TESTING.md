# Human testing queue

Things to try in the UI / desktop app / API when a human sits down with
the tool.  Assistant keeps this up to date as features ship, bugs are
fixed, or flows are touched.

Format: newest items on top, grouped by area.  A `[x]` prefix means
it's been exercised at least once (leave them here as a regression
list, don't delete).

---

## Backup — Probe phase + layered definitions (P1C3, ship-fresh)

- [ ] **Definition probe opt-in**: edit a Cisco IOS-XE definition
      YAML and add `probe: { command: "show version", patterns:
      { detected_os_version: "Version\\s+([\\d.]+)", detected_model:
      "Model Number\\s+:\\s+(\\S+)" } }`.  Restart the server, run
      a backup against a real Cisco switch.  The devices page edit
      form's "Detected facts" panel should populate with the
      current OS version + model + probe_timestamp.
- [ ] **Probe failure is non-fatal**: point the probe at a device
      where auth would fail (wrong port/creds).  Backup should
      still run against the family-base definition; server log
      shows a WARNING about probe failure but backup job status
      reaches `completed`.
- [ ] **Pinned overrides detected facts**: set `os_version: 17.12`
      on a DeviceProfile + keep probe configured.  Backup should
      use the 17.12 overlay regardless of what the device
      actually reports; detected_facts still populate (for
      display) from the probe output.
- [ ] **No pin + no probe**: legacy setup with neither pin nor
      probe declaration — backup picks the family-base definition
      (same as pre-P1C3 behaviour).

## Migration — Rename modal VLAN pane + persistence (P2C3, ship-fresh)

- [ ] **Left-rail renders**: translate a Cisco config with multiple
      VLANs to Aruba.  Open the rename modal.  Left rail shows
      "Ports" (active by default) and "VLANs" with row-count
      badges on each.
- [ ] **Switch to VLANs pane**: click the VLANs rail button.
      Center pane swaps from ports to a VLAN ID table.  Ports pane
      hides (display:none via CSS class toggle).  Preview pane on
      the right stays visible.
- [ ] **VLAN override**: type `999` in VLAN 10's override input.
      Summary above Apply shows "VLAN: 0 auto / 1 override".
      Click Apply — rendered output's VLAN 10 blocks now emit
      as VLAN 999.
- [ ] **VLAN drop**: click "drop" link next to VLAN 20.  Row dims
      + strikes through.  After Apply, VLAN 20 is absent from
      rendered output; interfaces that were on VLAN 20 are
      detached (operator advisory surfaces in summary warnings).
- [ ] **Collision detection**: override VLAN 10 → 30 AND
      VLAN 20 → 30.  Both rows highlight red.  Collision icon
      appears.  Apply still works (server merges), but the UI
      surfaces the collision visibly.
- [ ] **localStorage persistence**: override VLAN 10 → 555.  Hard-
      reload the page.  Re-run the same translation.  Open the
      rename modal.  The 10→555 override is already populated and
      the status line says "Restored prior overrides (0 port,
      1 VLAN) from just now".
- [ ] **Reset clears persistence**: click "Reset all" in the
      modal header.  All overrides clear AND the localStorage
      entry is removed (verify via DevTools → Application →
      Local Storage → no `netconfig.rename-ack.v1:…` entry
      remains for the current codec pair).
- [ ] **Different hostname = fresh slate**: translate a Cisco
      config with `hostname A`, set an override.  Reset textarea
      + paste a config with `hostname B`, re-translate.  Open
      rename modal — no restore notice appears; state is fresh
      (hostname is part of the persistence key).

## Migration — Port-name translation (Tier 3 UI, ship-fresh)

- [ ] **Cisco → Aruba /0/ strip**: on the Migrate page, translate the
      Cat 9300-24UX real fixture to Aruba AOS-S.  Rendered output
      should show `interface 1/1` / `interface 1/24` (NOT
      `GigabitEthernet1/0/*`), `Trk1` (NOT `Port-channel1`), and
      absorb VLAN SVIs into the VLAN stanza.  "Interface rename"
      button appears below the output.
- [ ] **Open rename modal**: click "Interface rename" — draggable
      modal opens with mapping table (left) + live preview (right).
      First non-empty section auto-expands; others collapsed.
- [ ] **Draggable**: grab the modal header (the ⋮⋮ grip + title) and
      drag it around the page.  Does NOT block content underneath.
- [ ] **Target profile selector**: pick "Aruba 2930F-48G-PoEP
      (JL256A)" from the toolbar dropdown.  Physical-port override
      cells should change from free-form text inputs to dropdowns
      listing ports 1-48 + A1/A2.
- [ ] **User override**: type a custom target in one row's override
      field (e.g. change `1/1` to `1/5`).  Row highlights as an
      override (bold teal target).  Preview pane text updates live.
- [ ] **Collision detection**: type the same target name in two rows.
      Both rows highlight red, summary shows "2 collisions", Apply
      button disables.  Clear one to un-collide.
- [ ] **Apply**: with overrides set and no collisions, click
      "Apply & regenerate".  Modal stays open; main output pane
      updates with the new rendered text.  Status text at bottom of
      modal shows "Applied. Rendered output refreshed."
- [ ] **Reset all**: with overrides set, click "Reset all" in the
      modal header.  All override cells clear back to placeholder
      "(auto: N/N)".  Apply button re-enables.
- [ ] **Close modal**: click × in the header OR "Cancel" button.
      Modal hides.  Main output unchanged (unless Apply was clicked
      first).
- [ ] **Badge count**: after a translation with warnings (e.g. Cat
      9300 with loopbacks and uplink modules), the orange badge on
      the Interface rename button shows the warning count.
- [ ] **Collapsible sections**: sections with warnings default
      open (⚠ icon in summary).  Clean sections collapsed.  Click
      summary to toggle.

## Migration — Fidelity polish (ship-fresh)

- [ ] **MTU** (Cisco -> OPNsense): paste Cisco config with `interface
      GigabitEthernet1/0/1 / mtu 9000`; target OPNsense should emit
      `<mtu>9000</mtu>` inside the corresponding interface zone.
- [ ] **MTU** (Cisco -> FortiGate): paste same; target FortiGate
      should emit both `set mtu-override enable` AND `set mtu 9000`
      (the override flag is needed for mtu to take effect).
- [ ] **MTU on Aruba** (expected lossy): paste same; target Aruba
      should NOT emit any per-port mtu (AOS-S doesn't support it).
      The data is silently dropped — this is the documented lossy
      path for this field.
- [ ] **MikroTik bridge render**: paste a MikroTik config with
      `/interface bridge / add name=bridge-lan comment="Main LAN"`;
      target MikroTik should emit the same.  Previously rendered
      nothing.
- [ ] **MikroTik VLAN name preservation**: paste a MikroTik config
      with `/interface vlan / add interface=ether3 name=gn-mgmt
      vlan-id=84`; target MikroTik should emit `name=gn-mgmt` not
      `name=vlan84`.

## Migration — Tier 2 wire-throughs (ship-fresh)

- [ ] **local_users**: paste a Cisco config with `username admin
      privilege 15 secret 9 $9$...`; target Aruba should emit
      `password manager user-name "admin" plaintext "..."` (the
      Cisco-type-9 hash gets wrapped under AOS-S's `plaintext`
      keyword — AOS-S will reject at deploy but the data isn't
      silently dropped).
- [ ] **DHCP pool (Cisco -> OPNsense)**: paste a Cisco config with
      `ip dhcp pool X / network N M / default-router G / dns-server D
      / lease 7`; target OPNsense should emit `<dhcpd>/<zone>` with
      gateway, dnsserver, defaultleasetime=604800.
- [ ] **DHCP pool (FortiGate -> Aruba)**: upload the real FortiGate
      fixture; target Aruba should NOT drop the LAG_INTERNAL DHCP
      pool — instead emit a `; DHCP pools ... AOS-S` comment block
      summarising it for the reviewer.
- [ ] **RADIUS (Cisco -> OPNsense)**: paste Cisco `radius server X /
      address ipv4 10.0.0.4 auth-port 1812 / key 7 abc123`; target
      OPNsense should emit `<authserver><type>radius</type>` with
      host + secret + port preserved.
- [ ] **RADIUS (Aruba global-key backfill)**: paste an AOS-S config
      with two `radius-server host` lines + one `radius-server key
      "fallback"`; parsed canonical should show both servers carry
      `fallback` as their key.

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