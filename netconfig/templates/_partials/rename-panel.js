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
    if (vlanAuto || vlanOverrides || vlanDrops) {
      html += ' &middot; <span data-testid="migrate-rename-summary-vlans">'
        + 'VLAN: ' + vlanAuto + ' auto';
      if (vlanOverrides) html += ' / ' + vlanOverrides + ' override'
        + (vlanOverrides > 1 ? 's' : '');
      if (vlanDrops) html += ' / <span class="mig-rename-summary-drop">'
        + vlanDrops + ' drop' + (vlanDrops > 1 ? 's' : '') + '</span>';
      html += '</span>';
    }
    summ.innerHTML = html;

    // Disable Apply when collisions exist.
    var applyBtn = document.getElementById('mig-rename-apply-btn');
    if (applyBtn) applyBtn.disabled = collisions > 0;

    // Fit-check banner is re-rendered whenever the summary is —
    // same inputs (job state + user overrides can change source
    // drops/keeps) and same triggering events (profile/model/module
    // change, modal open, apply complete).  Inlining this call here
    // means every summary call-site automatically refreshes the
    // banner without touching all 9 chains.
    renderFitCheck();
  }
