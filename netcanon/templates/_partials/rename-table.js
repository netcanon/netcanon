  /* ── Rename-modal mapping table renderer ─────────────────────────────
   * Builds the per-kind expandable sections from _lastJob.port_renames
   * + _lastJob.warnings, with user overrides layered on top (via
   * _renameUserMap).  Renders dropdowns or free-text inputs depending
   * on whether a target profile is selected.  Depends on module-scope
   * state declared in migrate.html:
   *
   *   _lastJob               — most recent server job response
   *   _renameUserMap         — {source_name: target_name | null}
   *   _renameProfiles        — array of target profiles
   *   _RENAME_KIND_ORDER     — stable display order of kind sections
   *   _RENAME_KIND_LABEL     — kind → human label
   *
   * And module-scope helpers (defined elsewhere in migrate.html or
   * in _partials/classify.js):
   *
   *   _guessKind(name)       — classify.js
   *   _looksLikeUplink(name) — classify.js
   *   currentRenameProfileKey()
   *   effectivePortsFor(profile)
   *   escapeHtml(s)
   *   renderRenamePreview()
   *   renderRenameSummary()
   * ────────────────────────────────────────────────────────────────── */

  /** Build the mapping table from _lastJob.port_renames + warnings.
   *
   *  Row shape: each row has a source name, the codec's auto-computed
   *  target, and a user-editable target that wins when set. */
  function renderRenameTable() {
    var sectionsEl = document.getElementById('mig-rename-sections');
    var emptyEl = document.getElementById('mig-rename-table-empty');
    if (!sectionsEl) return;
    sectionsEl.innerHTML = '';

    // Collect per-kind rows.  The server-side
    // translate_port_names returned only what CHANGED (applied map)
    // + warnings for what fell through.  For a complete table we
    // need to merge: every name mentioned in applied + every name
    // mentioned in warnings gets a row.
    var rowsByKind = {};
    function addRow(sourceName, kind, autoTarget, warning) {
      if (!rowsByKind[kind]) rowsByKind[kind] = [];
      // Deduplicate by source name within a kind.
      var existing = rowsByKind[kind].find(function(r) {
        return r.source === sourceName;
      });
      if (existing) {
        if (warning && !existing.warning) existing.warning = warning;
        if (autoTarget && !existing.auto) existing.auto = autoTarget;
        return;
      }
      rowsByKind[kind].push({
        source: sourceName,
        kind: kind,
        auto: autoTarget || sourceName,
        warning: warning || '',
      });
    }

    var applied = (_lastJob && _lastJob.port_renames) || {};
    Object.keys(applied).forEach(function(src) {
      addRow(src, _guessKind(src), applied[src], '');
    });

    var warnings = (_lastJob && _lastJob.warnings) || [];
    warnings.forEach(function(w) {
      // Warning text shape:
      //  "<codec>: <verb> ... <'port-name'> ... <details>"
      // Extract the 'port-name' between single quotes and a kind keyword.
      var nameMatch = w.match(/'([^']+)'/);
      if (!nameMatch) return;
      var src = nameMatch[1];
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

    var totalRows = 0;
    _RENAME_KIND_ORDER.forEach(function(kind) { totalRows += (rowsByKind[kind] || []).length; });
    if (totalRows === 0) {
      emptyEl.style.display = '';
      return;
    }
    emptyEl.style.display = 'none';

    // Build collision set from user map: target_name -> [source_name, ...].
    // Dropped sources don't count — they won't reach the target so
    // they can't collide with anything.
    var targetHits = {};
    _RENAME_KIND_ORDER.forEach(function(kind) {
      (rowsByKind[kind] || []).forEach(function(row) {
        // Drop is encoded as null in the user map.
        if (_renameUserMap[row.source] === null) return;
        var effective = _renameUserMap[row.source] || row.auto;
        if (!effective) return;
        if (!targetHits[effective]) targetHits[effective] = [];
        targetHits[effective].push(row.source);
      });
    });

    // Profile-driven dropdown options.  If a profile is selected,
    // dropdown lists the profile's known port ids, filtered by kind.
    var profileKey = currentRenameProfileKey();
    var selectedProfile = _renameProfiles.find(function(p) {
      return (p.vendor + '/' + p.model) === profileKey;
    });
    function profileOptionsFor(kind, sourceName) {
      if (!selectedProfile) return null;
      // Effective port set = chassis-fixed + selected-module ports.
      // For legacy profiles (no modules) this is identical to
      // ``selectedProfile.ports``; for module-variant profiles it
      // adds the currently-selected module's uplinks.
      var effectivePorts = effectivePortsFor(selectedProfile);
      if (kind === 'physical') {
        // Split physical rows by uplink heuristic: source names that
        // look like uplinks get uplink-port options, access-looking
        // names get access-port options.  Prevents a Cat 9300 NM-slot
        // FortyGig being offered 48 access ports on a 2930F-48G.
        var targetKind = (sourceName && _looksLikeUplink(sourceName))
          ? 'uplink' : 'physical';
        return effectivePorts
          .filter(function(p) { return p.kind === targetKind; })
          .map(function(p) { return p.id; });
      }
      if (kind === 'uplink' || kind === 'breakout') {
        return effectivePorts
          .filter(function(p) { return p.kind === 'uplink'; })
          .map(function(p) { return p.id; });
      }
      if (kind === 'mgmt') {
        return effectivePorts
          .filter(function(p) { return p.kind === 'mgmt'; })
          .map(function(p) { return p.id; });
      }
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

      var section = document.createElement('details');
      section.className = 'mig-rename-kind-section';
      section.setAttribute('data-testid', 'migrate-rename-section-' + kind);
      // Auto-open: first non-empty section, OR any section with
      // warnings/collisions (needs attention).
      if (kind === firstNonEmptyKind || warnCount || collisionCount) {
        section.open = true;
      }

      var summary = document.createElement('summary');
      summary.innerHTML = _RENAME_KIND_LABEL[kind]
        + '<span class="count">' + rows.length + '</span>'
        + (warnCount ? '<span class="count warn-count">'
             + warnCount + ' ⚠</span>' : '')
        + (collisionCount ? '<span class="count" style="color:var(--badge-failed-fg)">'
             + collisionCount + ' collisions</span>' : '');
      section.appendChild(summary);

      var table = document.createElement('table');
      table.className = 'mig-rename-table';
      var thead = document.createElement('thead');
      thead.innerHTML = '<tr>'
        + '<th>Source</th>'
        + '<th>Auto target</th>'
        + '<th>Override</th>'
        + '<th style="width:1.5rem">⚠</th>'
        + '</tr>';
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

        // Auto-target column:
        //   * Auto-dropped by the backend (unmappable by default) →
        //     "(auto-dropped — won't render)" in dim italic.  Operator
        //     can click "keep" to re-include verbatim.
        //   * Auto target differs from source → show the target name.
        //   * Auto target equals source (no translation, but server
        //     didn't auto-drop either — shouldn't happen in normal
        //     flow but handle defensively) → "(no mapping — needs
        //     override)".
        var autoCell;
        if (isAutoDropped) {
          autoCell = '<td class="mig-rename-no-auto">(auto-dropped — won\'t render)</td>';
        } else if (row.auto === row.source) {
          autoCell = '<td class="mig-rename-no-auto">(no mapping — needs override)</td>';
        } else {
          autoCell = '<td>' + escapeHtml(row.auto) + '</td>';
        }
        tr.innerHTML = '<td>' + escapeHtml(row.source) + '</td>' + autoCell;

        var overrideCell = document.createElement('td');
        overrideCell.className = 'mig-rename-target';
        // Drop sentinel used in the dropdown's special "don't render" option.
        var DROP_VALUE = '__DROP__';
        var opts = profileOptionsFor(row.kind, row.source);
        if (opts && opts.length) {
          var sel = document.createElement('select');
          sel.setAttribute('data-testid',
            'migrate-rename-override-' + row.source);
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
          // under a PREVIOUS target profile and then changed the
          // profile, their chosen value might not be in the new
          // profile's port list.  Surface it as a "(custom: X)"
          // option at the top so the operator can see and correct
          // it; selecting anything else from the dropdown replaces
          // the override.
          if (typeof userVal === 'string'
              && userVal !== row.source  // not a keep-verbatim no-op
              && opts.indexOf(userVal) === -1) {
            var customOpt = document.createElement('option');
            customOpt.value = userVal;
            customOpt.textContent = '(custom: ' + userVal
              + ' — not in profile)';
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
          opts.forEach(function(opt) {
            var o = document.createElement('option');
            o.value = opt; o.textContent = opt;
            if (_renameUserMap[row.source] === opt) o.selected = true;
            sel.appendChild(o);
          });
          sel.addEventListener('change', function() {
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
            ? 'Type target name (required)'
            : 'auto: ' + row.auto;
          inp.value = isDropped ? '' : (_renameUserMap[row.source] || '');
          inp.disabled = isDropped;
          inp.setAttribute('data-testid',
            'migrate-rename-override-' + row.source);
          inp.addEventListener('input', function() {
            if (inp.value.trim()) _renameUserMap[row.source] = inp.value.trim();
            else delete _renameUserMap[row.source];
            renderRenameTable();
            renderRenamePreview();
            renderRenameSummary();
          });
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

        var warnCell = document.createElement('td');
        if (hasCollision) {
          warnCell.innerHTML = '<span class="mig-rename-collision-icon" '
            + 'title="' + escapeHtml(
              'Collides with: '
              + targetHits[effective].filter(function(s) {
                return s !== row.source;
              }).join(', ')
            ) + '">⛔</span>';
        } else if (row.warning) {
          warnCell.innerHTML = '<span class="mig-rename-warn-icon" '
            + 'title="' + escapeHtml(row.warning) + '">⚠</span>';
        }
        tr.appendChild(warnCell);

        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      section.appendChild(table);
      sectionsEl.appendChild(section);
    });
  }
