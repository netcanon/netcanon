  /* ── Rename-modal hardware fit-check banner ───────────────────────────
   * When a target device is selected -- a flat profile, or a model
   * from a model family -- compares source-side port counts (grouped
   * by kind) against the device's capacity (a profile's chassis plus
   * its selected module; a family model's compiled inventory) and
   * surfaces the deltas so the operator sees capacity overage before
   * committing mappings.  Hidden while a port plan is applied: the
   * plan answers the capacity question by name, in its own strip.
   *
   * MVP scope: per-kind count + overage flag.  Fancier dimensions
   * (speed-downshift warnings, LAG headroom, PoE budget) are
   * deferred — this is the "one-glance" check, not an audit.
   *
   * Also home to renderProfileNotice(), the target-profile provenance
   * notice (deployment state / evidence grade / caveat), which shares
   * this banner's lifecycle and is driven from renderFitCheck().
   *
   * Depends on module-scope state:
   *   _lastJob, _renameProfiles, _deviceInventory
   *
   * And module-scope helpers (some in partials, some still inline):
   *   _guessKind, _looksLikeUplink            (classify.js)
   *   currentTargetDevice, currentPortPlan,
   *   renderPortPlan                           (device-models.js)
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
    // The provenance notice shares this banner's lifecycle (every
    // caller that refreshes the fit-check has just changed, or may
    // have changed, the selected profile), so it is driven from here
    // rather than from a second set of call sites.
    // Guarded: the notice is advisory, and a fault in it must never
    // take the capacity banner down with it.
    try { renderProfileNotice(); } catch (_) { /* notice is cosmetic */ }
    // The port-plan strip shares the lifecycle too: it depends on the
    // devices, the job and the operator's overrides.
    try {
      if (typeof renderPortPlan === 'function') renderPortPlan();
    } catch (_) { /* the strip is advisory */ }
    var el = document.getElementById('mig-rename-fitcheck');
    if (!el) return;
    // Ports pane only.  This function runs on every summary refresh,
    // including ones fired from the VLAN / user panes; without this
    // guard an override edit there brought the ports banner back.
    var portsPaneEl = document.getElementById('mig-rename-ports-pane');
    if (portsPaneEl && !portsPaneEl.classList.contains('active')) {
      el.style.display = 'none';
      return;
    }
    // The target device: a profile, or a model from a model family.
    var profile = (typeof currentTargetDevice === 'function')
      ? currentTargetDevice() : null;
    // A port plan answers the capacity question by name -- which
    // ports were paired, which have no place -- so the per-kind
    // counts, which are guessed from the shape of the names, give
    // way to the plan strip.
    var activePlan = (typeof currentPortPlan === 'function')
      ? currentPortPlan() : null;
    if (!profile || !_lastJob || (activePlan && activePlan.applied)) {
      el.style.display = 'none';
      el.className = '';
      return;
    }
    // Count source interfaces by kind.  Sources come from four
    // places in the job: port_renames (successfully auto-translated),
    // port_drops (auto-dropped), warnings (unclassified / complexity
    // cases), and source_ports (every hardware port the config uses --
    // on a same-vendor translation the first three are empty, and the
    // banner said "0 / 48" in green over a table of 52 ports).
    var seenSources = new Set();
    var sourceByKind = {};
    // Where the source device is declared and compiled, a port's kind
    // is its role in that device, not a guess from its name.
    var declaredKind = Object.create(null);
    var sourceInv = (typeof _deviceInventory === 'object' && _deviceInventory)
      ? _deviceInventory.source : null;
    ((sourceInv && sourceInv.ports) || []).forEach(function(p) {
      declaredKind[p.name] = p.role === 'access' ? 'physical' : p.role;
    });
    function bumpSource(name) {
      if (!name || seenSources.has(name)) return;
      seenSources.add(name);
      if (declaredKind[name]) {
        sourceByKind[declaredKind[name]] = (sourceByKind[declaredKind[name]] || 0) + 1;
        return;
      }
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
    (_lastJob.source_ports || []).forEach(bumpSource);
    // A warning can quote a name of the TARGET ("multiple source
    // ports map to '1/1'"): a name a rename ends on, that the job
    // names as a source nowhere, is not a source port.
    var renameTargets = new Set();
    Object.keys(applied).forEach(function(src) {
      if (typeof applied[src] === 'string') renameTargets.add(applied[src]);
    });
    var namedAsSource = new Set(Object.keys(applied).concat(drops)
      .concat(_lastJob.source_ports || []));
    var warns = (_lastJob.warnings) || [];
    warns.forEach(function(w) {
      var m = w.match(/'([^']+)'/);
      if (!m) return;
      if (renameTargets.has(m[1]) && !namedAsSource.has(m[1])) return;
      bumpSource(m[1]);
    });

    // Count target capacity by kind using the effective port list
    // (chassis + selected module, mirrors backend effective_ports()).
    var effectivePorts = profile.ports;
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
      // Escaped: the SKU is a profile-YAML dict key, and profile YAML
      // is operator-authorable.
      parts.push('<span class="mig-fitcheck-note" '
        + 'data-testid="migrate-fitcheck-module-note">'
        + '(module: ' + escapeHtml(sku) + ')</span>');
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

  /** Human wording for each ``TargetProfile.evidence`` grade.  The
   *  grade describes the profile's PORT NAMES AND COUNTS — the ids an
   *  operator picks here are written verbatim into the target config. */
  var _PROFILE_EVIDENCE_LABEL = {
    'capture': 'Port names checked against a real capture of this model',
    'vendor-doc': 'Port names from published sources (no capture of this model here)',
    'inferred': 'Port names NOT verified for this target',
  };
  /** Shown when the profile declares no grade.  Unset is "nobody has
   *  checked", not "fine" — so it is said, not left blank. */
  var _PROFILE_UNGRADED_LABEL = 'Port names not yet graded';

  /** Target-profile provenance notice.  Shows, for the selected
   *  profile: which deployment state its port names describe
   *  (``deployment_state`` — an Aruba 2930F port is ``24`` standalone
   *  and ``1/24`` as a VSF member), how well those names are
   *  established (``evidence``), and any ``caveat``.
   *
   *  Hidden only when no profile is selected (or the profile lists no
   *  ports and declares nothing).  A profile with no grade is shown
   *  as "not yet graded" rather than left blank, so silence can never
   *  be read as a clean bill of health.  Amber only when the grade is
   *  ``inferred`` — a
   *  caveat on a verified profile is guidance, and colouring every
   *  profile that has one would leave no signal for the ones whose
   *  names are actually in doubt.  Built with textContent throughout —
   *  the strings come from profile YAML, which an operator can author. */
  function renderProfileNotice() {
    var el = document.getElementById('mig-rename-profile-notice');
    if (!el) return;
    var profileKey = currentRenameProfileKey();
    var profile = profileKey && _renameProfiles.find(function(p) {
      return (p.vendor + '/' + p.model) === profileKey;
    });
    var state = (profile && profile.deployment_state) || '';
    var grade = (profile && profile.evidence) || '';
    var caveat = (profile && profile.caveat) || '';
    // Ports-pane only: the notice is about port names, and this
    // function runs on every summary refresh, including ones fired
    // from the VLAN / user panes.
    var portsPane = document.getElementById('mig-rename-ports-pane');
    var portsActive = !portsPane || portsPane.classList.contains('active');
    // A profile that lists ports but declares no grade is UNGRADED,
    // and says so.  One with no ports at all (the bring-your-own-
    // hardware `opnsense/Generic`) has no port names to grade.
    var ungraded = !!profile && !grade
      && effectivePortsFor(profile).length > 0;
    el.textContent = '';
    if (!portsActive || !profile
        || (!state && !grade && !caveat && !ungraded)) {
      el.style.display = 'none';
      el.className = '';
      el.removeAttribute('data-evidence');
      return;
    }
    function addPart(testid, text, extraClass) {
      var span = document.createElement('span');
      span.className = 'mig-profile-notice-part'
        + (extraClass ? ' ' + extraClass : '');
      span.setAttribute('data-testid', testid);
      span.textContent = text;
      el.appendChild(span);
    }
    if (state) {
      addPart('migrate-rename-profile-notice-state',
        'Port names describe: ' + state);
    }
    if (grade) {
      addPart('migrate-rename-profile-notice-evidence',
        _PROFILE_EVIDENCE_LABEL[grade] || ('Evidence: ' + grade),
        'mig-profile-notice-grade');
      el.setAttribute('data-evidence', grade);
    } else if (ungraded) {
      addPart('migrate-rename-profile-notice-evidence',
        _PROFILE_UNGRADED_LABEL, 'mig-profile-notice-grade');
      el.setAttribute('data-evidence', 'ungraded');
    } else {
      el.removeAttribute('data-evidence');
    }
    if (caveat) {
      addPart('migrate-rename-profile-notice-caveat', caveat);
    }
    el.className = (grade === 'inferred') ? 'notice-warn' : '';
    el.style.display = '';
  }
