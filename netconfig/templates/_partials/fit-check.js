  /* ── Rename-modal hardware fit-check banner ───────────────────────────
   * When a target profile is selected, compares source-side port
   * counts (grouped by kind) against the profile's effective
   * capacity (chassis + selected module) and surfaces the deltas
   * so the operator sees capacity overage before committing
   * mappings.  Module-aware via currentRenameModuleSku().
   *
   * MVP scope: per-kind count + overage flag.  Fancier dimensions
   * (speed-downshift warnings, LAG headroom, PoE budget) are
   * deferred — this is the "one-glance" check, not an audit.
   *
   * Depends on module-scope state:
   *   _lastJob, _renameProfiles
   *
   * And module-scope helpers (some in partials, some still inline):
   *   _guessKind, _looksLikeUplink            (classify.js)
   *   currentRenameProfileKey, effectivePortsFor,
   *   currentRenameModuleSku                   (migrate.html inline)
   * ────────────────────────────────────────────────────────────────── */

  /** Hardware fit-check banner.  When a target profile is selected,
   *  compare source-side port counts (grouped by kind) against the
   *  profile's effective capacity (chassis + selected module) and
   *  surface the deltas so the operator sees capacity overage before
   *  they commit mappings.
   *
   *  Hidden when:
   *    * No profile selected (can't compute capacity → no banner).
   *    * Profile is module-variant and no module selected (shouldn't
   *      happen in practice — the UI pre-selects a default — but
   *      guards against the edge case). */
  function renderFitCheck() {
    var el = document.getElementById('mig-rename-fitcheck');
    if (!el) return;
    var profileKey = currentRenameProfileKey();
    var profile = profileKey && _renameProfiles.find(function(p) {
      return (p.vendor + '/' + p.model) === profileKey;
    });
    if (!profile || !_lastJob) {
      el.style.display = 'none';
      el.className = '';
      return;
    }
    // Count source interfaces by kind.  Sources come from three
    // places in the job: port_renames (successfully auto-translated),
    // port_drops (auto-dropped), warnings (unclassified / complexity
    // cases).  Union them to cover the full source universe.
    var seenSources = new Set();
    var sourceByKind = {};
    function bumpSource(name) {
      if (!name || seenSources.has(name)) return;
      seenSources.add(name);
      var kind = _guessKind(name);
      // Roll uplink-looking physical into 'uplink' bucket for the
      // fitcheck math — matches how target-dropdown options are
      // routed in profileOptionsFor().  Otherwise a Cat 9300
      // source FortyGigabitEthernet would get tallied as access
      // against the target's access ports, inflating overage noise.
      if (kind === 'physical' && _looksLikeUplink(name)) {
        kind = 'uplink';
      }
      sourceByKind[kind] = (sourceByKind[kind] || 0) + 1;
    }
    var applied = (_lastJob.port_renames) || {};
    Object.keys(applied).forEach(bumpSource);
    var drops = (_lastJob.port_drops) || [];
    drops.forEach(bumpSource);
    var warns = (_lastJob.warnings) || [];
    warns.forEach(function(w) {
      var m = w.match(/'([^']+)'/);
      if (m) bumpSource(m[1]);
    });

    // Count target capacity by kind using the effective port list
    // (chassis + selected module, mirrors backend effective_ports()).
    var effectivePorts = effectivePortsFor(profile);
    var targetByKind = {};
    effectivePorts.forEach(function(p) {
      targetByKind[p.kind] = (targetByKind[p.kind] || 0) + 1;
    });

    // Compose the banner.  Kinds shown in a stable order, empty
    // categories suppressed so the banner stays compact.
    var KIND_ORDER = ['physical', 'uplink', 'mgmt'];
    var KIND_LABEL = {
      physical: 'access',
      uplink: 'uplink',
      mgmt: 'mgmt',
    };
    var worstState = 'ok';
    var parts = [];
    KIND_ORDER.forEach(function(kind) {
      var src = sourceByKind[kind] || 0;
      var tgt = targetByKind[kind] || 0;
      if (src === 0 && tgt === 0) return;
      var overage = src > tgt ? (src - tgt) : 0;
      if (overage > 0) worstState = 'warn';
      var html = '<span class="mig-fitcheck-kind" '
        + 'data-testid="migrate-fitcheck-kind-' + kind + '">'
        + '<strong>' + KIND_LABEL[kind] + ':</strong> '
        + src + ' / ' + tgt;
      if (overage > 0) {
        html += ' <span class="mig-fitcheck-over">(+' + overage
          + ' over capacity)</span>';
      }
      html += '</span>';
      parts.push(html);
    });
    // Module-awareness note: surface the SKU so the operator
    // understands which hardware variant the numbers are counted
    // against.  Omitted for legacy profiles.
    var sku = currentRenameModuleSku();
    if (sku) {
      parts.push('<span class="mig-fitcheck-note" '
        + 'data-testid="migrate-fitcheck-module-note">'
        + '(module: ' + sku + ')</span>');
    }
    if (parts.length === 0) {
      el.style.display = 'none';
      el.className = '';
      return;
    }
    el.className = 'fit-' + worstState;
    el.innerHTML = parts.join(' ');
    el.style.display = '';
  }
