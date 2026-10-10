  /* ── Rename-modal mapping table renderer ─────────────────────────────
   * Builds the per-kind expandable sections from _lastJob.port_renames
   * + _lastJob.warnings + _lastJob.source_ports, with user overrides
   * layered on top (via _renameUserMap).  When the job carries a port
   * plan (both devices were declared), the plan's rows come first:
   * every pairing with the position that decided it, and every name
   * the plan could not place, with what happened to it.  Renders
   * dropdowns or free-text inputs depending on whether a target
   * device is selected.  Depends on module-scope state declared in
   * migrate.html:
   *
   *   _lastJob               — most recent server job response
   *   _deviceInventory       — the compiled source device: before a
   *                            plan, its port order is the rows' order
   *   _renameUserMap         — {source_name: target_name | null}
   *   _planAccepted          — entries "Accept as shown" recorded; a
   *                            row edited by hand leaves it
   *   _renameSectionOpen     — sections the operator opened or closed
   *   _renameProfiles        — array of target profiles
   *   _RENAME_KIND_ORDER     — stable display order of kind sections
   *   _RENAME_KIND_LABEL     — kind → human label
   *
   * And module-scope helpers (defined elsewhere in migrate.html or
   * in _partials/classify.js):
   *
   *   _guessKind(name)       — classify.js
   *   _looksLikeUplink(name) — classify.js
   *   currentTargetDevice()  — device-models.js: the target's ports,
   *                            from a profile or a family model
   *   currentPortPlan(), portPlanRowMeta(plan) — device-models.js
   *   renderRenamePreview()
   *   renderRenameSummary()
   *
   * Every string a row shows -- an interface name from the pasted
   * config, a port name or a label from profile and family YAML an
   * operator can author, the server's warning text -- is written with
   * textContent or as an attribute value.  Nothing here assigns
   * markup (tests/unit/test_device_picker_partial.py holds that), so
   * no such string can be read as HTML and none needs escaping.
   *
   * The table is rebuilt whole on every change.  Four things make
   * that bearable: the element that had the focus has it again
   * afterwards (found by its test id, with its caret); a section the
   * operator opened stays open; a row's list of target ports is
   * filled when the list is first used, not for every row on every
   * rebuild -- two stacks of eight are four hundred rows of four
   * hundred choices each; and a rebuild nobody asked for by acting on
   * the table -- a text field left, a device that finished compiling
   * -- waits until no mouse button is down (rebuildRenameTableSoon).
   * ────────────────────────────────────────────────────────────────── */

  var _renameTableDue = false;
  var _renamePointerDown = false;

  /** Rebuild the table at a moment when doing so cannot take an
   *  element out from under the operator.
   *
   *  A click is a press and a release on ONE element.  The press that
   *  leaves a text field is the press on whatever is being clicked
   *  next; a rebuild between that press and its release replaces the
   *  element, and the click is lost.  So the rebuild waits until no
   *  button is down -- and, by then, the focus has reached where it
   *  was going, and is given back to it. */
  function rebuildRenameTableSoon() {
    _renameTableDue = true;
    setTimeout(_rebuildRenameTableIfDue, 0);
  }

  function _rebuildRenameTableIfDue() {
    if (!_renameTableDue || _renamePointerDown) return;
    renderRenameTable();
    renderRenamePreview();
    renderRenameSummary();
  }

  document.addEventListener('pointerdown', function() {
    _renamePointerDown = true;
  }, true);
  ['pointerup', 'pointercancel'].forEach(function(type) {
    document.addEventListener(type, function() {
      _renamePointerDown = false;
      // After the click this release completes has been delivered.
      if (_renameTableDue) setTimeout(_rebuildRenameTableIfDue, 0);
    }, true);
  });
  window.addEventListener('blur', function() { _renamePointerDown = false; });

  /** The element with *testid* under *root*, or null.  Test ids hold
   *  interface names, which may hold anything; compared as text, not
   *  spliced into a selector. */
  function _byTestId(root, testid) {
    var found = null;
    root.querySelectorAll('[data-testid]').forEach(function(el) {
      if (!found && el.getAttribute('data-testid') === testid) found = el;
    });
    return found;
  }

  /** Build the mapping table from _lastJob.port_renames + warnings.
   *
   *  Row shape: each row has a source name, the codec's auto-computed
   *  target, and a user-editable target that wins when set. */
  function renderRenameTable() {
    var sectionsEl = document.getElementById('mig-rename-sections');
    var emptyEl = document.getElementById('mig-rename-table-empty');
    if (!sectionsEl) return;
    _renameTableDue = false;
    // What had the focus, so that it has it again after the rebuild.
    var active = document.activeElement;
    var focusId = (active && sectionsEl.contains(active))
      ? active.getAttribute('data-testid') : null;
    var caret = null;
    if (focusId && active.tagName === 'INPUT') {
      try { caret = [active.selectionStart, active.selectionEnd]; } catch (_) { caret = null; }
    }
    sectionsEl.textContent = '';

    /** A <span> with a class, text, and optionally a title and a test id. */
    function mark(className, text, title, testid) {
      var el = document.createElement('span');
      el.className = className;
      el.textContent = text;
      if (title) el.title = title;
      if (testid) el.setAttribute('data-testid', testid);
      return el;
    }
    /** A cell with text, and optionally a class and a test id. */
    function cell(text, className, testid) {
      var td = document.createElement('td');
      if (className) td.className = className;
      if (testid) td.setAttribute('data-testid', testid);
      td.textContent = text;
      return td;
    }

    // Collect per-kind rows.  The server-side
    // translate_port_names returned only what CHANGED (applied map)
    // + warnings for what fell through.  For a complete table we
    // need to merge: every name mentioned in applied + every name
    // mentioned in warnings gets a row.
    var rowsByKind = {};
    // A port plan, when both devices were declared for this job.
    var plan = (typeof currentPortPlan === 'function')
      ? currentPortPlan() : null;
    var planActive = !!plan && !!plan.applied;
    var planMeta = (planActive && typeof portPlanRowMeta === 'function')
      ? portPlanRowMeta(plan) : {};
    // Keyed by interface names, which an operator chooses on some
    // platforms: no prototype, so no name finds anything inherited.
    var rowOf = Object.create(null);
    function addRow(sourceName, kind, autoTarget, warning) {
      // Deduplicate by source name within a kind -- or, under a port
      // plan, across kinds: the plan knows what a port IS (its role),
      // so its row is the row for that name wherever a later source
      // would have filed it.
      var existing = planActive ? rowOf[sourceName] : null;
      if (!existing) {
        if (!rowsByKind[kind]) rowsByKind[kind] = [];
        existing = rowsByKind[kind].find(function(r) {
          return r.source === sourceName;
        });
      }
      if (existing) {
        if (warning && !existing.warning) existing.warning = warning;
        if (autoTarget
            && (!existing.auto || existing.auto === existing.source)) {
          existing.auto = autoTarget;
        }
        return existing;
      }
      var row = {
        source: sourceName,
        kind: kind,
        auto: autoTarget || sourceName,
        warning: warning || '',
        meta: null,
        plain: false,
      };
      rowsByKind[kind].push(row);
      if (!rowOf[sourceName]) rowOf[sourceName] = row;
      return row;
    }

    // Plan rows first, in the order of the source device's ports.
    Object.keys(planMeta).sort(function(a, b) {
      return planMeta[a].order - planMeta[b].order;
    }).forEach(function(src) {
      var meta = planMeta[src];
      addRow(src, meta.kind || _guessKind(src), meta.auto, '').meta = meta;
    });

    var applied = (_lastJob && _lastJob.port_renames) || {};
    Object.keys(applied).forEach(function(src) {
      addRow(src, _guessKind(src), applied[src], '');
    });

    // A quoted name in a job warning can be a name of the TARGET
    // ("multiple source ports map to '1/1'").  It is not a source
    // name and gets no row.  A name is a target name if a rename ends
    // on it; it is a source name if the job says so anywhere else.
    var knownSources = new Set(Object.keys(applied));
    ((_lastJob && _lastJob.port_drops) || []).forEach(function(n) { knownSources.add(n); });
    ((_lastJob && _lastJob.source_ports) || []).forEach(function(n) { knownSources.add(n); });
    Object.keys(planMeta).forEach(function(n) { knownSources.add(n); });
    var targetNames = new Set();
    Object.keys(applied).forEach(function(src) {
      if (typeof applied[src] === 'string') targetNames.add(applied[src]);
    });

    var warnings = (_lastJob && _lastJob.warnings) || [];
    warnings.forEach(function(w) {
      // Warning text shape:
      //  "<codec>: <verb> ... <'port-name'> ... <details>"
      // Extract the 'port-name' between single quotes and a kind keyword.
      var nameMatch = w.match(/'([^']+)'/);
      if (!nameMatch) return;
      var src = nameMatch[1];
      if (targetNames.has(src) && !knownSources.has(src)) return;
      // Kind hints in warning text (from port_names.py orchestrator).
      // Order matters — check specific kinds before the generic
      // "physical" catch-all so e.g. a "breakout" warning doesn't
      // get reclassified as "physical" (the identity kind IS physical
      // in some orchestrator paths).
      var kind = 'unknown';
      if (/\bloopback\b/i.test(w)) kind = 'loopback';
      else if (/\bbreakout\b/i.test(w)) kind = 'breakout';
      else if (/\bhw_aggregate\b|\baggregate\b/i.test(w)) kind = 'hw_aggregate';
      else if (/\btunnel\b/i.test(w)) kind = 'tunnel';
      else if (/\bmgmt\b/i.test(w)) kind = 'mgmt';
      else if (/\bsvi\b/i.test(w)) kind = 'svi';
      else if (/\blag\b/i.test(w)) kind = 'lag';
      else if (/\bphysical\b/i.test(w)) kind = 'physical';
      else if (/could not classify/i.test(w)) kind = 'unknown';
      // Fall back to the source-name classifier if the warning text
      // didn't contain a kind keyword — ensures rows still land in a
      // meaningful section (Cat 9300 uplink-module ports, etc.).
      if (kind === 'unknown') kind = _guessKind(src);
      addRow(src, kind, '', w);
    });

    // Every hardware port the config uses that nothing above gave a
    // row: its name goes through unchanged.  A same-vendor
    // translation usually renames nothing, and the table then listed
    // only the names a warning quoted -- or none at all.
    ((_lastJob && _lastJob.source_ports) || []).forEach(function(src) {
      if (rowOf[src]) return;
      addRow(src, _guessKind(src), '', '').plain = true;
    });

    // Without a plan the rows are in the order the job named them,
    // which is the order the config first mentions its ports in.  A
    // config that lists its ports VLAN by VLAN (AOS-S) mentions them
    // as 1, 48-52, 35-47, 2...: no order to look a port up in.  Where
    // the source device is declared, the rows go in its own port
    // order, as they will after Apply; a name the device does not
    // have keeps its place, after them.  Under a plan the order is
    // already the plan's, and is left alone.
    var sourceInv = (typeof _deviceInventory === 'object' && _deviceInventory)
      ? _deviceInventory.source : null;
    if (!planActive && sourceInv && Array.isArray(sourceInv.ports)) {
      var portRank = Object.create(null);
      sourceInv.ports.forEach(function(p, i) { portRank[p.name] = i; });
      var placeOf = function(row) {
        return (row.source in portRank) ? portRank[row.source] : Infinity;
      };
      _RENAME_KIND_ORDER.forEach(function(kind) {
        if (!rowsByKind[kind]) return;
        // A stable sort: rows with no place keep the order they had.
        rowsByKind[kind].sort(function(a, b) {
          var first = placeOf(a), second = placeOf(b);
          return first === second ? 0 : (first < second ? -1 : 1);
        });
      });
    }

    var totalRows = 0;
    _RENAME_KIND_ORDER.forEach(function(kind) { totalRows += (rowsByKind[kind] || []).length; });
    // The rail's count is the rows drawn: counted here, where they
    // are made, so the two cannot differ.
    var railCount = document.getElementById('mig-rename-rail-ports-count');
    if (railCount) railCount.textContent = String(totalRows);
    if (totalRows === 0) {
      emptyEl.style.display = '';
      return;
    }
    emptyEl.style.display = 'none';

    // Build collision set from user map: target_name -> [source_name, ...].
    // Dropped sources don't count — they won't reach the target so
    // they can't collide with anything.
    var targetHits = Object.create(null);
    var serverDropped = new Set((_lastJob && _lastJob.port_drops) || []);
    _RENAME_KIND_ORDER.forEach(function(kind) {
      (rowsByKind[kind] || []).forEach(function(row) {
        // Drop is encoded as null in the user map.
        if (_renameUserMap[row.source] === null) return;
        // A port the server dropped and the operator has not
        // touched reaches no target either.
        if (_renameUserMap[row.source] === undefined
            && serverDropped.has(row.source)) return;
        var effective = _renameUserMap[row.source] || row.auto;
        if (!effective) return;
        if (!targetHits[effective]) targetHits[effective] = [];
        targetHits[effective].push(row.source);
      });
    });

    // Profile-driven dropdown options.  If a profile is selected,
    // dropdown lists the profile's known port ids, filtered by kind.
    var selectedProfile = (typeof currentTargetDevice === 'function')
      ? currentTargetDevice() : null;
    var freeTargets = new Set(planActive ? (plan.unused_target || []) : []);
    // Names an operator's entry put a port on that the declared
    // target does not list.  Reported by the plan; marked on the row.
    var offTarget = new Set(planActive ? (plan.off_target || []) : []);
    // The target's ports by kind, made once: every row of a kind is
    // offered the same list.
    var portsOfKind = Object.create(null);
    var portsNotOfKind = Object.create(null);
    var allPortIds = new Set();
    if (selectedProfile) {
      selectedProfile.ports.forEach(function(p) { allPortIds.add(p.id); });
    }
    function idsOfKind(kind) {
      if (!portsOfKind[kind]) {
        portsOfKind[kind] = selectedProfile.ports
          .filter(function(p) { return p.kind === kind; })
          .map(function(p) { return p.id; });
      }
      return portsOfKind[kind];
    }
    function idsNotOfKind(kind) {
      if (!portsNotOfKind[kind]) {
        portsNotOfKind[kind] = selectedProfile.ports
          .filter(function(p) { return p.kind !== kind; })
          .map(function(p) { return p.id; });
      }
      return portsNotOfKind[kind];
    }
    function profileOptionsFor(kind, sourceName, meta) {
      if (!selectedProfile) return null;
      // The target device's ports: a profile's chassis-fixed ports
      // plus the selected module's, or a family model's compiled
      // inventory.
      if (meta && meta.role) {
        // A port of the declared source device: its role is known,
        // not guessed from its name.  Ports of the same role first;
        // a port with no place among them may take any other.
        var wanted = meta.role === 'access' ? 'physical' : meta.role;
        if (meta.state === 'paired') return idsOfKind(wanted);
        return idsOfKind(wanted).concat(idsNotOfKind(wanted));
      }
      if (kind === 'physical') {
        // Split physical rows by uplink heuristic: source names that
        // look like uplinks get uplink-port options, access-looking
        // names get access-port options.  Prevents a Cat 9300 NM-slot
        // FortyGig being offered 48 access ports on a 2930F-48G.
        return idsOfKind((sourceName && _looksLikeUplink(sourceName))
          ? 'uplink' : 'physical');
      }
      if (kind === 'uplink' || kind === 'breakout') return idsOfKind('uplink');
      if (kind === 'mgmt') return idsOfKind('mgmt');
      if (kind === 'lag') {
        if (!selectedProfile.lags || !selectedProfile.lags.prefix) return null;
        var opts = [];
        for (var i = 1; i <= selectedProfile.lags.max; i++) {
          opts.push(selectedProfile.lags.prefix + i);
        }
        return opts;
      }
      return null;
    }

    /** True when *name* is a name the selected profile has, for a row
     *  of *kind*.  LAG rows are judged against the LAG option list;
     *  every other kind against ALL the profile's port ids, not just
     *  the kind-filtered dropdown -- an access-looking source that
     *  auto-maps onto a real uplink id is on the profile, and calling
     *  it "not a port" would be false. */
    function profileKnowsName(kind, name, opts) {
      if (!selectedProfile) return true;
      if (kind === 'lag') return opts.indexOf(name) !== -1;
      return allPortIds.has(name);
    }

    // Auto-expand the first non-empty section so the user sees
    // content immediately on modal open; remaining sections default
    // collapsed per operator preference ("Default Collapsed is good
    // if it works right").  Sections with warnings or collisions
    // always open regardless of order.
    var firstNonEmptyKind = null;
    _RENAME_KIND_ORDER.forEach(function(kind) {
      if (firstNonEmptyKind === null && (rowsByKind[kind] || []).length) {
        firstNonEmptyKind = kind;
      }
    });

    _RENAME_KIND_ORDER.forEach(function(kind) {
      var rows = rowsByKind[kind] || [];
      if (!rows.length) return;

      var warnCount = rows.filter(function(r) { return r.warning; }).length;
      var collisionCount = rows.filter(function(r) {
        var effective = _renameUserMap[r.source] || r.auto;
        return effective && targetHits[effective] && targetHits[effective].length > 1;
      }).length;

      // Names the port plan left for the operator to decide.
      var undecided = planActive ? (plan.unresolved_ports || []) : [];
      var decisionCount = rows.filter(function(r) {
        return undecided.indexOf(r.source) !== -1
          && _renameUserMap[r.source] === undefined;
      }).length;

      var section = document.createElement('details');
      section.className = 'mig-rename-kind-section';
      section.setAttribute('data-testid', 'migrate-rename-section-' + kind);
      // Open: the first non-empty section, and any section with
      // warnings, collisions or undecided names.  A section the
      // operator opened stays open across a rebuild, and one they
      // closed stays closed unless a row in it needs them.
      var wanted = _renameSectionOpen[kind];
      if (collisionCount || decisionCount) {
        section.open = true;
      } else if (wanted === true || wanted === false) {
        section.open = wanted;
      } else if (kind === firstNonEmptyKind || warnCount) {
        section.open = true;
      }

      var summary = document.createElement('summary');
      summary.setAttribute('data-testid', 'migrate-rename-section-summary-' + kind);
      summary.appendChild(document.createTextNode(_RENAME_KIND_LABEL[kind]));
      summary.appendChild(mark('count', String(rows.length)));
      if (warnCount) {
        summary.appendChild(mark('count warn-count', warnCount + ' ⚠'));
      }
      if (collisionCount) {
        summary.appendChild(mark('count collision-count',
          collisionCount + ' collisions'));
      }
      summary.addEventListener('click', function() {
        // The click comes before the toggle: this is what it will be.
        _renameSectionOpen[kind] = !section.open;
      });
      if (decisionCount) {
        var decisionChip = document.createElement('span');
        decisionChip.className = 'count warn-count';
        decisionChip.setAttribute('data-testid',
          'migrate-rename-decision-count-' + kind);
        decisionChip.textContent = decisionCount + ' need'
          + (decisionCount === 1 ? 's' : '') + ' a decision';
        summary.appendChild(decisionChip);
      }
      section.appendChild(summary);

      var table = document.createElement('table');
      table.className = 'mig-rename-table';
      var thead = document.createElement('thead');
      var headRow = document.createElement('tr');
      ['Source', 'Auto target', 'Override']
        .concat(planActive ? ['Position'] : [])
        .concat(['⚠'])
        .forEach(function(label) {
          var th = document.createElement('th');
          th.scope = 'col';
          th.textContent = label;
          if (label === '⚠') th.className = 'mig-rename-mark-col';
          headRow.appendChild(th);
        });
      thead.appendChild(headRow);
      table.appendChild(thead);

      var tbody = document.createElement('tbody');
      // Auto-dropped set (from server port_drops) — these are rows
      // the backend stripped because the target codec couldn't
      // translate them.  User can override with a rename or
      // "keep verbatim" to re-include them.
      var autoDroppedSet = new Set((_lastJob && _lastJob.port_drops) || []);
      rows.forEach(function(row) {
        var tr = document.createElement('tr');
        tr.setAttribute('data-testid', 'migrate-rename-row-' + row.source);
        var userVal = _renameUserMap[row.source];
        var isUserDropped = userVal === null;
        var isAutoDropped = userVal === undefined && autoDroppedSet.has(row.source);
        var isDropped = isUserDropped || isAutoDropped;
        var effective = isDropped ? null : (userVal || row.auto);
        var hasOverride = userVal !== undefined && !isUserDropped;
        var hasCollision = !isDropped && effective && targetHits[effective]
                           && targetHits[effective].length > 1;
        if (row.warning) tr.classList.add('has-warning');
        if (hasCollision) tr.classList.add('has-collision');
        if (hasOverride) tr.classList.add('has-override');
        if (isDropped) tr.classList.add('has-drop');
        if (isAutoDropped) tr.classList.add('has-auto-drop');
        var meta = row.meta;
        var needsDecision = undecided.indexOf(row.source) !== -1
          && userVal === undefined;
        if (needsDecision) tr.classList.add('needs-decision');
        if (meta) tr.setAttribute('data-plan-state', meta.state);
        // A flag that blocks the job: the row says so on its edge,
        // not only in the words of the flag.
        var blocking = ((meta && meta.flags) || []).filter(function(f) {
          return f.level === 'block';
        });
        if (blocking.length) tr.classList.add('has-block');
        // An entry of the operator's that put the port on a name the
        // declared target does not list.
        var isOffTarget = hasOverride && typeof userVal === 'string'
          && offTarget.has(userVal);
        if (isOffTarget) tr.classList.add('has-offtarget');

        // Auto-target column:
        //   * Auto-dropped by the backend (unmappable by default) →
        //     "(auto-dropped — won't render)" in dim italic.  Operator
        //     can click "keep" to re-include verbatim.
        //   * Auto target differs from source → show the target name.
        //   * Auto target equals source (no translation, but server
        //     didn't auto-drop either — shouldn't happen in normal
        //     flow but handle defensively) → "(no mapping — needs
        //     override)".
        var autoId = 'migrate-rename-auto-' + row.source;
        var autoCell;
        if (meta && meta.text) {
          // What the port plan did with a name it could not pair.
          autoCell = cell(meta.text, 'mig-rename-no-auto',
            'migrate-rename-plan-state-' + row.source);
        } else if (meta && meta.state === 'paired' && !isAutoDropped) {
          // The port plan gave this port a place.  Where that place
          // has the port's own name -- an access port between two
          // stacks, any port between two switches of one model -- it
          // is still a pairing, and the name is shown as one.
          autoCell = cell(row.auto, '', autoId);
        } else if (row.plain && row.auto === row.source && !isAutoDropped) {
          autoCell = cell('(unchanged)', 'mig-rename-no-auto', autoId);
        } else if (isAutoDropped) {
          autoCell = cell('(auto-dropped — won\'t render)', 'mig-rename-no-auto', autoId);
        } else if (row.auto === row.source) {
          autoCell = cell('(no mapping — needs override)', 'mig-rename-no-auto', autoId);
        } else {
          autoCell = cell(row.auto, '', autoId);
        }
        tr.appendChild(cell(row.source, 'mig-rename-source',
          'migrate-rename-source-' + row.source));
        tr.appendChild(autoCell);

        var overrideCell = document.createElement('td');
        overrideCell.className = 'mig-rename-target';
        // Drop sentinel used in the dropdown's special "don't render" option.
        var DROP_VALUE = '__DROP__';
        var opts = profileOptionsFor(row.kind, row.source, meta);
        // Off-profile auto target.  Selecting a profile does NOT change
        // auto-translation: the translator derives a name from the shape
        // of the source name (Cisco Gi1/0/1 -> AOS-S 1/1) whatever model
        // is chosen.  When the profile lists ports of this kind and the
        // auto name is not one of the profile's names at all, say so on
        // the row -- otherwise the default the operator leaves in place
        // is a port the selected device does not have, with no signal.
        var offProfile = !isDropped && !hasOverride
          && !!opts && opts.length > 0
          && !!row.auto && row.auto !== row.source
          && !profileKnowsName(row.kind, row.auto, opts);
        if (offProfile) tr.classList.add('has-offprofile');
        if (opts && opts.length) {
          var sel = document.createElement('select');
          sel.setAttribute('data-testid',
            'migrate-rename-override-' + row.source);
          sel.setAttribute('aria-label', 'Target for ' + row.source);
          var blank = document.createElement('option');
          blank.value = '';
          // If server auto-dropped this row, reflect the default
          // action in the dropdown label so the operator sees the
          // ambient state without having to cross-reference the
          // dim-italic cell.
          blank.textContent = isAutoDropped
            ? '(auto-dropped)'
            : '(auto: ' + row.auto + ')';
          sel.appendChild(blank);
          // Orphaned user-override: if the user set an override
          // under a PREVIOUS target device and then changed the
          // device, their chosen value might not be in the new
          // device's port list.  Surface it as a "(custom: X)"
          // option at the top so the operator can see and correct
          // it; selecting anything else from the dropdown replaces
          // the override.
          if (typeof userVal === 'string'
              && userVal !== row.source  // not a keep-verbatim no-op
              && opts.indexOf(userVal) === -1) {
            var customOpt = document.createElement('option');
            customOpt.value = userVal;
            customOpt.textContent = '(custom: ' + userVal
              + (selectedProfile.profile
                ? ' — not in profile)' : ' — not a port of the target)');
            customOpt.selected = true;
            sel.appendChild(customOpt);
          }
          // "Keep verbatim" — only shown when the row is auto-dropped;
          // a no-op rename that beats the server's auto-drop.
          if (isAutoDropped) {
            var keepOpt = document.createElement('option');
            keepOpt.value = '__KEEP__';
            keepOpt.textContent = 'Keep verbatim (' + row.source + ')';
            if (userVal === row.source) keepOpt.selected = true;
            sel.appendChild(keepOpt);
          }
          // "Don't render" — first option after auto so it's easy to find.
          var dropOpt = document.createElement('option');
          dropOpt.value = DROP_VALUE;
          dropOpt.textContent = '— Drop (don\'t render) —';
          if (isUserDropped) dropOpt.selected = true;
          sel.appendChild(dropOpt);
          // The target's ports.  Only the one chosen is made now; the
          // rest are added when the list is first used (focus, or the
          // press that opens it), which comes before the browser
          // draws the list.
          var portOption = function(opt) {
            var o = document.createElement('option');
            o.value = opt;
            // Under a port plan, say which target ports nothing holds.
            o.textContent = freeTargets.has(opt) ? opt + '  (free)' : opt;
            o.setAttribute('data-port', '1');
            return o;
          };
          if (typeof userVal === 'string' && opts.indexOf(userVal) !== -1) {
            var chosenOpt = portOption(userVal);
            chosenOpt.selected = true;
            sel.appendChild(chosenOpt);
          }
          var fillPorts = function() {
            if (sel.getAttribute('data-filled')) return;
            sel.setAttribute('data-filled', '1');
            var keep = sel.value;
            sel.querySelectorAll('option[data-port]').forEach(function(o) {
              sel.removeChild(o);
            });
            var all = document.createDocumentFragment();
            opts.forEach(function(opt) { all.appendChild(portOption(opt)); });
            sel.appendChild(all);
            sel.value = keep;
          };
          sel.addEventListener('focus', fillPorts);
          sel.addEventListener('pointerdown', fillPorts);
          sel.addEventListener('mousedown', fillPorts);
          sel.addEventListener('change', function() {
            // A row changed by hand is the operator's own decision.
            delete _planAccepted[row.source];
            if (sel.value === DROP_VALUE) {
              _renameUserMap[row.source] = null;
            } else if (sel.value === '__KEEP__') {
              // Verbatim override — beats auto-drop without renaming.
              _renameUserMap[row.source] = row.source;
            } else if (sel.value) {
              _renameUserMap[row.source] = sel.value;
            } else {
              delete _renameUserMap[row.source];
            }
            renderRenameTable();
            renderRenamePreview();
            renderRenameSummary();
          });
          overrideCell.appendChild(sel);
        } else {
          var inp = document.createElement('input');
          inp.type = 'text';
          // Placeholder conveys whether there's an auto default (which
          // the user could keep by leaving the field blank) or whether
          // an override is effectively required (no auto was produced).
          inp.placeholder = row.auto === row.source
            ? ((row.plain || meta) ? 'Type a target name'
                                   : 'Type target name (required)')
            : 'auto: ' + row.auto;
          inp.value = isDropped ? '' : (_renameUserMap[row.source] || '');
          inp.disabled = isDropped;
          inp.setAttribute('data-testid',
            'migrate-rename-override-' + row.source);
          inp.setAttribute('aria-label', 'Target for ' + row.source);
          // Typing changes the map, the preview and the summary.  The
          // table is rebuilt when the field is left (or Enter is
          // pressed), not on every key: a rebuild replaces the field
          // being typed in, and the field then held one character.
          // Leaving the field is often a press on something else in
          // the table, so that rebuild waits for the release.
          inp.addEventListener('input', function() {
            delete _planAccepted[row.source];
            if (inp.value.trim()) _renameUserMap[row.source] = inp.value.trim();
            else delete _renameUserMap[row.source];
            renderRenamePreview();
            renderRenameSummary();
          });
          inp.addEventListener('change', rebuildRenameTableSoon);
          overrideCell.appendChild(inp);
          // Drop / keep link beside the input.  State machine:
          //   * Not dropped → "drop" (click sets user_map[src] = null)
          //   * User-dropped (explicit) → "un-drop" (click deletes entry)
          //   * Auto-dropped by server → "keep verbatim" (click sets
          //     user_map[src] = src, a no-op rename that beats the
          //     auto-drop so the interface is rendered with its
          //     original name).
          var dropLink = document.createElement('span');
          dropLink.className = 'mig-rename-drop-link';
          if (isUserDropped) {
            dropLink.textContent = 'un-drop';
          } else if (isAutoDropped) {
            dropLink.textContent = 'keep verbatim';
          } else {
            dropLink.textContent = 'drop';
          }
          dropLink.setAttribute('data-testid',
            'migrate-rename-drop-' + row.source);
          dropLink.addEventListener('click', function() {
            delete _planAccepted[row.source];
            if (isUserDropped) {
              delete _renameUserMap[row.source];
            } else if (isAutoDropped) {
              // "keep verbatim" — verbatim override beats auto-drop.
              _renameUserMap[row.source] = row.source;
            } else {
              _renameUserMap[row.source] = null;
            }
            renderRenameTable();
            renderRenamePreview();
            renderRenameSummary();
          });
          overrideCell.appendChild(dropLink);
        }
        tr.appendChild(overrideCell);

        if (planActive) {
          // The position that decided the pairing, and what the
          // target port lacks.  textContent: the strings are built
          // from device data an operator can author.
          var whyCell = document.createElement('td');
          whyCell.className = 'mig-rename-why';
          if (meta) {
            whyCell.setAttribute('data-testid',
              'migrate-rename-why-' + row.source);
            whyCell.appendChild(document.createTextNode(meta.why || ''));
            (meta.flags || []).forEach(function(flag, index) {
              var flagEl = document.createElement('span');
              flagEl.className = 'flag flag-' + flag.level;
              flagEl.setAttribute('data-level', flag.level);
              flagEl.setAttribute('data-testid',
                'migrate-rename-flag-' + row.source + '-' + index);
              flagEl.textContent = flag.text;
              whyCell.appendChild(flagEl);
            });
          }
          tr.appendChild(whyCell);
        }

        var warnCell = document.createElement('td');
        if (needsDecision && !hasCollision) {
          warnCell.appendChild(mark('mig-rename-decision-icon', '?',
            'Needs your decision: give it a target port, or drop it',
            'migrate-rename-decision-' + row.source));
        } else if (hasCollision) {
          warnCell.appendChild(mark('mig-rename-collision-icon', '⛔',
            'Collides with: ' + targetHits[effective].filter(function(s) {
              return s !== row.source;
            }).join(', '),
            'migrate-rename-collision-' + row.source));
        } else if (blocking.length) {
          warnCell.appendChild(mark('mig-rename-collision-icon', '⛔',
            blocking[0].text, 'migrate-rename-block-' + row.source));
        } else if (row.warning) {
          warnCell.appendChild(mark('mig-rename-warn-icon', '⚠', row.warning));
        } else if (offProfile) {
          warnCell.appendChild(mark('mig-rename-warn-icon', '⚠',
            'Auto name ' + row.auto + ' is not a port on '
              + selectedProfile.label + ' — pick one from the list',
            'migrate-rename-offprofile-' + row.source));
        } else if (isOffTarget) {
          warnCell.appendChild(mark('mig-rename-warn-icon', '⚠',
            userVal + ' is not a port the declared target device lists',
            'migrate-rename-offtarget-' + row.source));
        }
        tr.appendChild(warnCell);

        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      // Off-profile auto targets: count them on the section header and
      // open the section, so a profile whose names the translator did
      // not produce cannot sit unnoticed in a collapsed list.
      var offCount = tbody.querySelectorAll('tr.has-offprofile').length;
      if (offCount) {
        var offChip = document.createElement('span');
        offChip.className = 'count warn-count';
        offChip.setAttribute('data-testid',
          'migrate-rename-offprofile-count-' + kind);
        offChip.textContent = offCount + ' not on profile';
        summary.appendChild(offChip);
        section.open = true;
      }
      section.appendChild(table);
      sectionsEl.appendChild(section);
    });

    // Give the focus back to what had it.
    if (focusId) {
      var again = _byTestId(sectionsEl, focusId);
      if (again && typeof again.focus === 'function') {
        again.focus();
        if (caret && again.tagName === 'INPUT') {
          try { again.setSelectionRange(caret[0], caret[1]); } catch (_) { /* not a text field */ }
        }
      }
    }
  }
