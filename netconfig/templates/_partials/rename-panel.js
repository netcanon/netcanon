  /* ── Rename-modal supplementary panels ────────────────────────────────
   * Preview + summary renderers — the "what would this do?" views
   * that live alongside the rename table inside the modal.  They
   * re-render on every user override so operators see the effect of
   * their changes before clicking Apply.
   *
   * Both functions depend on module-scope state declared in
   * migrate.html:
   *
   *   _lastJob               — most recent server job response
   *   _renameUserMap         — {source_name: target_name | null}
   *
   * And module-scope helpers:
   *
   *   renderFitCheck()       — inline fit-check banner (still in
   *                            migrate.html; called at the end of
   *                            renderRenameSummary so the banner
   *                            refreshes on every state change)
   * ────────────────────────────────────────────────────────────────── */

  /** Client-side approximation of the target output with current
   *  user overrides applied via whole-word string replacement.  Not
   *  canonical — the Apply button re-runs the server-side render
   *  for the authoritative result — but gives the operator an
   *  immediate "here's what this change looks like" view. */
  function renderRenamePreview() {
    var preview = document.getElementById('mig-rename-preview');
    if (!preview || !_lastJob) return;
    var text = _lastJob.rendered || '';
    // Combined map = applied (baseline) with user overrides layered on top.
    var appliedBaseline = {};
    if (_lastJob.port_renames) {
      Object.keys(_lastJob.port_renames).forEach(function(src) {
        // Server already rewrote the rendered text; for preview we
        // want to show the user's FURTHER edits relative to that.
        // So baseline = identity mapping for already-rewritten names.
      });
    }
    // Apply overrides: replace occurrences of (currently-effective
    // target) with the user's chosen name.
    var effective = {};
    Object.keys(_renameUserMap).forEach(function(src) {
      // The rendered text already shows auto-target; user override
      // means "replace that auto-target with my chosen name".
      var autoTarget = _lastJob.port_renames
        ? _lastJob.port_renames[src]
        : src;
      var userTarget = _renameUserMap[src];
      if (autoTarget && userTarget && autoTarget !== userTarget) {
        effective[autoTarget] = userTarget;
      } else if (!autoTarget && userTarget) {
        // Source wasn't auto-rewritten; replace source in text.
        effective[src] = userTarget;
      }
    });
    Object.keys(effective).forEach(function(from) {
      // Word-boundary replacement to avoid partial matches (e.g.
      // "Trk1" inside "Trk10").
      var esc = from.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      var re = new RegExp('(^|[^A-Za-z0-9/_.-])' + esc
                          + '([^A-Za-z0-9/_.-]|$)', 'g');
      text = text.replace(re, '$1' + effective[from] + '$2');
    });

    // VLAN + local-user rename previews — same whole-word
    // substitution technique.  Scope is strictly RENAMES (drops
    // require stanza-level removal which isn't safe client-side;
    // Apply is the authoritative re-render for those).
    //
    // Baseline: server already rewrote the text for any entries in
    // _lastJob.vlan_renames / local_user_renames.  User overrides
    // are interpreted as "replace the CURRENTLY-EFFECTIVE target
    // with my chosen value" — same idiom as ports above.
    function applySubstitutionPreview(userMap, appliedMap) {
      if (!userMap || typeof userMap !== 'object') return;
      var subs = {};
      Object.keys(userMap).forEach(function(src) {
        var userTarget = userMap[src];
        if (userTarget === null || userTarget === undefined) return;
        var srcKey = String(src);
        var autoTarget = appliedMap && appliedMap[srcKey] !== undefined
          ? String(appliedMap[srcKey])
          : (appliedMap && appliedMap[src] !== undefined
              ? String(appliedMap[src])
              : srcKey);
        var tgtStr = String(userTarget);
        if (autoTarget === tgtStr) return;  // no-op
        subs[autoTarget] = tgtStr;
      });
      Object.keys(subs).forEach(function(from) {
        var esc = from.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        var re = new RegExp('(^|[^A-Za-z0-9/_.-])' + esc
                            + '([^A-Za-z0-9/_.-]|$)', 'g');
        text = text.replace(re, '$1' + subs[from] + '$2');
      });
    }
    applySubstitutionPreview(
      _renameVlanUserMap,
      _lastJob && _lastJob.vlan_renames,
    );
    applySubstitutionPreview(
      _renameLocalUserMap,
      _lastJob && _lastJob.local_user_renames,
    );
    // SNMP community rename preview — single-entry map but shares the
    // same whole-word-substitution technique as VLAN / local_users.
    // Drops (community cleared) still require a server re-render since
    // the whole SNMP stanza disappears; preview just shows the
    // rename case.
    applySubstitutionPreview(
      _renameSnmpCommunityMap,
      _lastJob && _lastJob.snmp_community_renames,
    );

    preview.textContent = text;
  }

  /** Summary line above the rename modal's Apply button.  Reports:
   *    * total auto-applied renames from the server
   *    * user override count
   *    * drop count (auto + user, minus user-verbatim-keeps)
   *    * warning count (from server)
   *    * collision count (targets assigned to more than one source)
   *
   *  Also disables the Apply button when collisions exist — the
   *  rendered output would have duplicated port stanzas which is
   *  never the operator's intent.  Triggers renderFitCheck() at
   *  the end so the hardware-capacity banner refreshes in lockstep. */
  function renderRenameSummary() {
    var summ = document.getElementById('mig-rename-summary');
    if (!summ || !_lastJob) return;
    var auto = _lastJob.port_renames
      ? Object.keys(_lastJob.port_renames).length : 0;
    // Effective drop set = auto-drops from server + user drops -
    // user overrides that reverse auto-drops (verbatim-keep or
    // explicit rename).
    var autoDroppedSet = new Set(_lastJob.port_drops || []);
    var autoDrops = Array.from(autoDroppedSet).filter(function(k) {
      // If user hasn't touched the row, the auto-drop stands.
      // If user has a non-null value in the map (verbatim keep or
      // rename), the auto-drop is reversed.
      return _renameUserMap[k] === undefined;
    }).length;
    var userDrops = Object.keys(_renameUserMap).filter(function(k) {
      return _renameUserMap[k] === null;
    }).length;
    var drops = autoDrops + userDrops;
    var overrides = Object.keys(_renameUserMap).filter(function(k) {
      return _renameUserMap[k] !== null;
    }).length;
    var warnings = (_lastJob.warnings || []).length;

    // Collision count re-compute.  Dropped sources don't contribute
    // (they won't reach the target).
    var targetCounts = {};
    var seenSources = new Set();
    function tally(src, tgt) {
      if (!tgt || seenSources.has(src)) return;
      seenSources.add(src);
      targetCounts[tgt] = (targetCounts[tgt] || 0) + 1;
    }
    Object.keys(_renameUserMap).forEach(function(src) {
      if (_renameUserMap[src] === null) return;  // dropped
      tally(src, _renameUserMap[src]);
    });
    if (_lastJob.port_renames) {
      Object.keys(_lastJob.port_renames).forEach(function(src) {
        if (_renameUserMap[src] === undefined) {
          tally(src, _lastJob.port_renames[src]);
        }
      });
    }
    var collisions = 0;
    Object.keys(targetCounts).forEach(function(t) {
      if (targetCounts[t] > 1) collisions += targetCounts[t];
    });

    // VLAN-category totals — parallel port stats.  Counted from
    // the user map so the summary moves with the operator's edits
    // BEFORE they click Apply (post-Apply, the server's job.vlan_*
    // fields also populate).
    var vlanOverrides = 0, vlanDrops = 0;
    if (typeof _renameVlanUserMap === 'object' && _renameVlanUserMap) {
      Object.keys(_renameVlanUserMap).forEach(function(k) {
        if (_renameVlanUserMap[k] === null) vlanDrops += 1;
        else vlanOverrides += 1;
      });
    }
    // Server-side auto-applied VLAN rewrites (from a prior Apply
    // round-trip) count toward the summary too.
    var vlanAuto = (_lastJob && _lastJob.vlan_renames)
      ? Object.keys(_lastJob.vlan_renames).length : 0;

    // Local-users category totals — same pattern as VLANs above.
    var userOverrides = 0, userDrops = 0;
    if (typeof _renameLocalUserMap === 'object' && _renameLocalUserMap) {
      Object.keys(_renameLocalUserMap).forEach(function(k) {
        if (_renameLocalUserMap[k] === null) userDrops += 1;
        else userOverrides += 1;
      });
    }
    var userAuto = (_lastJob && _lastJob.local_user_renames)
      ? Object.keys(_lastJob.local_user_renames).length : 0;

    // SNMP-community category totals — scalar canonical surface so
    // the counts are 0/1, but using the same shape as ports / VLANs /
    // users keeps the summary renderer symmetric.
    var snmpOverrides = 0, snmpDrops = 0;
    if (typeof _renameSnmpCommunityMap === 'object' && _renameSnmpCommunityMap) {
      Object.keys(_renameSnmpCommunityMap).forEach(function(k) {
        if (_renameSnmpCommunityMap[k] === null) snmpDrops += 1;
        else snmpOverrides += 1;
      });
    }
    var snmpAuto = (_lastJob && _lastJob.snmp_community_renames)
      ? Object.keys(_lastJob.snmp_community_renames).length : 0;

    // Collision counts for VLANs + users — parity with the port
    // collision logic above so collisions in ANY pane disable Apply.
    // Rationale: feature-parity with ports pane.  Even though the
    // server auto-merges VLAN + user collisions (union-by-policy),
    // a collision almost always indicates operator confusion or
    // typo — better to block Apply and let them explicitly resolve
    // than to ship silently-merged output.
    function countCollisions(userMap, autoMap, dropsSet) {
      if (!userMap && !autoMap) return 0;
      var hits = {};
      var seen = new Set();
      function t(src, tgt) {
        if (tgt === null || tgt === undefined) return;
        if (seen.has(src)) return;
        seen.add(src);
        hits[tgt] = (hits[tgt] || 0) + 1;
      }
      if (userMap) {
        Object.keys(userMap).forEach(function(s) { t(s, userMap[s]); });
      }
      if (autoMap) {
        Object.keys(autoMap).forEach(function(s) {
          if (userMap && userMap[s] !== undefined) return;
          if (dropsSet && dropsSet.has(s)) return;
          t(s, autoMap[s]);
        });
      }
      var total = 0;
      Object.keys(hits).forEach(function(tgt) {
        if (hits[tgt] > 1) total += hits[tgt];
      });
      return total;
    }
    var vlanAutoDrops = new Set(
      (_lastJob && _lastJob.vlan_drops) || []
    );
    var userAutoDrops = new Set(
      (_lastJob && _lastJob.local_user_drops) || []
    );
    var vlanCollisions = countCollisions(
      _renameVlanUserMap,
      _lastJob && _lastJob.vlan_renames,
      vlanAutoDrops,
    );
    var userCollisions = countCollisions(
      _renameLocalUserMap,
      _lastJob && _lastJob.local_user_renames,
      userAutoDrops,
    );
    // SNMP community is a scalar — collisions are definitionally
    // impossible (one slot, one value).  Pass through countCollisions
    // for uniformity; always returns 0.
    var snmpAutoDrops = new Set(
      (_lastJob && _lastJob.snmp_community_drops) || []
    );
    var snmpCollisions = countCollisions(
      _renameSnmpCommunityMap,
      _lastJob && _lastJob.snmp_community_renames,
      snmpAutoDrops,
    );

    var html = auto + ' auto';
    if (overrides) html += ' / ' + overrides + ' override' + (overrides > 1 ? 's' : '');
    if (drops) html += ' / <span class="mig-rename-summary-drop">'
                      + drops + ' drop' + (drops > 1 ? 's' : '') + '</span>';
    if (warnings) html += ' / <span class="mig-rename-summary-warn">'
                        + warnings + ' ⚠</span>';
    if (collisions) html += ' / <span class="mig-rename-summary-collision">'
                          + collisions + ' collision' + (collisions > 1 ? 's' : '')
                          + '</span>';
    // VLAN-category sub-summary — only surfaces when something
    // VLAN-related is happening, so port-only sessions don't see
    // extra noise.
    if (vlanAuto || vlanOverrides || vlanDrops || vlanCollisions) {
      html += ' &middot; <span data-testid="migrate-rename-summary-vlans">'
        + 'VLAN: ' + vlanAuto + ' auto';
      if (vlanOverrides) html += ' / ' + vlanOverrides + ' override'
        + (vlanOverrides > 1 ? 's' : '');
      if (vlanDrops) html += ' / <span class="mig-rename-summary-drop">'
        + vlanDrops + ' drop' + (vlanDrops > 1 ? 's' : '') + '</span>';
      if (vlanCollisions) html += ' / <span class="mig-rename-summary-collision">'
        + vlanCollisions + ' collision'
        + (vlanCollisions > 1 ? 's' : '') + '</span>';
      html += '</span>';
    }
    // Local-users sub-summary — same gate-on-any-state pattern.
    if (userAuto || userOverrides || userDrops || userCollisions) {
      html += ' &middot; <span data-testid="migrate-rename-summary-local-users">'
        + 'Users: ' + userAuto + ' auto';
      if (userOverrides) html += ' / ' + userOverrides + ' override'
        + (userOverrides > 1 ? 's' : '');
      if (userDrops) html += ' / <span class="mig-rename-summary-drop">'
        + userDrops + ' drop' + (userDrops > 1 ? 's' : '') + '</span>';
      if (userCollisions) html += ' / <span class="mig-rename-summary-collision">'
        + userCollisions + ' collision'
        + (userCollisions > 1 ? 's' : '') + '</span>';
      html += '</span>';
    }
    // SNMP sub-summary — shows only when SNMP-related activity exists.
    // Uses "cleared" wording instead of "drop" because clearing the
    // community is less dramatic than dropping a user — it just omits
    // the SNMP stanza rather than removing an identity.
    if (snmpAuto || snmpOverrides || snmpDrops) {
      html += ' &middot; <span data-testid="migrate-rename-summary-snmp">'
        + 'SNMP: ' + snmpAuto + ' auto';
      if (snmpOverrides) html += ' / ' + snmpOverrides + ' override';
      if (snmpDrops) html += ' / <span class="mig-rename-summary-drop">'
        + snmpDrops + ' clear</span>';
      html += '</span>';
    }
    summ.innerHTML = html;

    // Disable Apply when collisions exist in ANY pane — feature
    // parity across categories.  Even though the server auto-merges
    // VLAN + user collisions (union-by-policy) and wouldn't produce
    // duplicate stanzas, silently shipping a merge is almost always
    // an operator confusion rather than intent.  Forcing the operator
    // to resolve or explicitly drop prevents accidental merges.
    var totalCollisions = collisions + vlanCollisions + userCollisions
      + snmpCollisions;
    var applyBtn = document.getElementById('mig-rename-apply-btn');
    if (applyBtn) applyBtn.disabled = totalCollisions > 0;

    // Fit-check banner is re-rendered whenever the summary is —
    // same inputs (job state + user overrides can change source
    // drops/keeps) and same triggering events (profile/model/module
    // change, modal open, apply complete).  Inlining this call here
    // means every summary call-site automatically refreshes the
    // banner without touching all 9 chains.
    renderFitCheck();

    // Per-pane fit-check banners (VLANs + local_users).  Same
    // summary-is-the-universal-chokepoint pattern as renderFitCheck
    // above — all profile/module change handlers + override-mutating
    // paths flow through here.
    if (typeof renderPerPaneFitCheck === 'function') {
      renderPerPaneFitCheck();
    }

    // localStorage ack persistence — strict super-set of every
    // override-mutating callsite, so wiring save here means
    // partials don't need persistence awareness.  Idempotent on
    // equal state; safe to call freely.
    if (typeof saveRenameAck === 'function') saveRenameAck();
  }
