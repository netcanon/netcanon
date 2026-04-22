  /* ── Shared client-side port classifiers ──────────────────────────────
   * Pure helpers used by the rename table and the fit-check banner to
   * group/route ports by kind on the client side.  Mirrors the codec
   * classify_port_name regex patterns; the server is still the
   * authoritative classifier — these are UI grouping only.
   *
   * Included by migrate.html BEFORE rename-table.js so both renderers
   * reach the same shared definitions at module scope.  (JS function
   * declarations are hoisted within the script block, so include order
   * is a readability guarantee, not a correctness requirement.)
   * ────────────────────────────────────────────────────────────────── */

  /** Client-side kind classifier shared between renderRenameTable
   *  and renderFitCheck.  Mirrors codec classify_port_name regex
   *  patterns; server-side is still the authoritative classifier —
   *  this is UI grouping only. */
  function _guessKind(name) {
    if (/^(Port-channel|Trk|trk|LAG|bond|lagg)\d/i.test(name)) return 'lag';
    if (/^Vlan\d|^vlan\d/.test(name)) return 'svi';
    if (/\.\d+$/.test(name)) return 'svi';  // OPN/MT dotted form
    if (/^Loopback\d|^lo$|^loopback\d/i.test(name)) return 'loopback';
    if (/^(Tunnel|wg|gre|ipip|eoip|gif|ovpn)/i.test(name)) return 'tunnel';
    if (/^VirtualPortGroup|^bridge|^br-/i.test(name)) return 'virtual';
    if (/^(ssl\.|tunnel)/i.test(name)) return 'tunnel';
    if (/^(mgmt|management)$/i.test(name)) return 'mgmt';
    return 'physical';
  }

  /** Client-side uplink heuristic — distinguishes uplink-role physical
   *  ports from access-role physical ports by source-side naming
   *  conventions.  Used to pick profile dropdown options (a FortyGig on
   *  Cat 9300 NM slot should get uplink-port target options, not access-
   *  port options) and to drive the fit-check banner's per-kind tallies.
   *
   *  Heuristics (target-vendor-agnostic):
   *    * Cisco 3-part Gi/TenG/FortyGig/...1/<N>/<port> where <N>
   *      is not 0 — line-card / NM-slot uplink.
   *    * Prefix indicates faster-than-access optics:
   *      FortyGigabitEthernet, TwentyFiveGigE, HundredGigE,
   *      FourHundredGigE on any Cisco chassis = uplink.
   *    * Explicit letter-slot forms (Aruba A1/B1, MikroTik
   *      sfp-sfpplus, qsfpplus) — those are uplinks by convention.
   *    * FortiGate wan<N> — uplink role. */
  function _looksLikeUplink(name) {
    var m = name.match(
      /^(FastEthernet|GigabitEthernet|TwoGigabitEthernet|FiveGigabitEthernet|TenGigabitEthernet|TwentyFiveGigE|FortyGigabitEthernet|HundredGigE|FourHundredGigE|AppGigabitEthernet)(\d+)\/(\d+)\/(\d+)(\/\d+)?$/i
    );
    if (m && parseInt(m[3], 10) !== 0) return true;
    if (/^(TwentyFiveGigE|FortyGigabitEthernet|HundredGigE|FourHundredGigE)/i.test(name)) return true;
    if (/^\d+\/[A-Za-z]\d+$/.test(name)) return true;
    if (/^(sfp|sfp-sfpplus|sfpplus|qsfpplus)\d/i.test(name)) return true;
    if (/^wan\d*$/i.test(name)) return true;
    return false;
  }
