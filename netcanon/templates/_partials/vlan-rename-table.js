  /* ── VLAN-rename pane renderer ───────────────────────────────────────
   * Builds a per-VLAN override table from _lastJob.source_vlans (every
   * VLAN the source config declared) and _lastJob.vlan_renames /
   * vlan_drops (rewrites already applied by the server).  User edits
   * land in _renameVlanUserMap: { source_vlan_id: target_vlan_id | null }.
   *
   * Mirrors the structural shape of rename-table.js but stays deliberately
   * lighter:
   *   * No kind-sections — VLANs don't have a physical/logical taxonomy
   *     the way ports do; every row is an int → int rewrite.
   *   * No profile-driven dropdowns — VLAN IDs are universal 1-4094,
   *     no target device to filter against.
   *   * Free-text integer input.  Empty string means "keep as-is";
   *     user types the desired target ID, or clicks Drop.
   *
   * Depends on module-scope state declared in migrate.html:
   *
   *   _lastJob               — most recent server job response
   *   _renameVlanUserMap     — {source_vlan_id: target_vlan_id | null}
   *
   * And module-scope helpers (defined in migrate.html):
   *
   *   escapeHtml(s)
   *   renderRenamePreview()
   *   renderRenameSummary()
   *   renderRenameRailCounts()
   * ────────────────────────────────────────────────────────────────── */

  /** Build the VLAN rewrite table from the server's source_vlans +
   *  already-applied vlan_renames + user overrides.  Every VLAN in
   *  the source tree gets a row so the operator can see the full
   *  inventory and decide per-VLAN whether to keep / rewrite / drop. */
  function renderVlanRenameTable() {
    var sectionsEl = document.getElementById('mig-rename-vlans-sections');
    var emptyEl = document.getElementById('mig-rename-vlans-empty');
    if (!sectionsEl) return;
    sectionsEl.innerHTML = '';

    var sourceVlans = (_lastJob && _lastJob.source_vlans) || [];
    if (!sourceVlans.length) {
      if (emptyEl) emptyEl.style.display = '';
      return;
    }
    if (emptyEl) emptyEl.style.display = 'none';

    var appliedRenames = (_lastJob && _lastJob.vlan_renames) || {};
    var autoDroppedSet = new Set((_lastJob && _lastJob.vlan_drops) || []);

    // Build collision set from the combined "auto renames + user
    // overrides" state.  An operator collapsing VLAN 10 + 20 → 30
    // is probably intentional (the orchestrator merges on the
    // server), but the UI still surfaces the collision so the
    // operator knows it's happening.
    var targetHits = {};
    sourceVlans.forEach(function(src) {
      var userVal = _renameVlanUserMap[src];
      if (userVal === null) return;                // dropped
      if (userVal === undefined
          && autoDroppedSet.has(src)) return;      // auto-dropped, no override
      var effective = (userVal !== undefined && userVal !== null)
        ? userVal
        : (appliedRenames[src] !== undefined
            ? appliedRenames[src] : src);
      if (!targetHits[effective]) targetHits[effective] = [];
      targetHits[effective].push(src);
    });

    var table = document.createElement('table');
    table.className = 'mig-rename-table';
    table.setAttribute('data-testid', 'migrate-rename-vlans-table');
    var thead = document.createElement('thead');
    thead.innerHTML = '<tr>'
      + '<th>Source VLAN</th>'
      + '<th>Auto target</th>'
      + '<th>Override</th>'
      + '<th style="width:1.5rem">⚠</th>'
      + '</tr>';
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    // Stable display order — ascending VLAN ID, so the operator
    // reads the table in the same order they'd read `show vlan`.
    var ordered = sourceVlans.slice().sort(function(a, b) { return a - b; });
    ordered.forEach(function(src) {
      var tr = document.createElement('tr');
      tr.setAttribute('data-testid', 'migrate-rename-vlan-row-' + src);
      var userVal = _renameVlanUserMap[src];
      var isUserDropped = userVal === null;
      var isAutoDropped = userVal === undefined && autoDroppedSet.has(src);
      var isDropped = isUserDropped || isAutoDropped;
      var appliedTarget = appliedRenames[src];
      var effective = isDropped
        ? null
        : ((userVal !== undefined && userVal !== null)
            ? userVal
            : (appliedTarget !== undefined ? appliedTarget : src));
      var hasOverride = userVal !== undefined && !isUserDropped;
      var hasCollision = !isDropped && effective != null
                         && targetHits[effective]
                         && targetHits[effective].length > 1;
      if (hasCollision) tr.classList.add('has-collision');
      if (hasOverride) tr.classList.add('has-override');
      if (isDropped) tr.classList.add('has-drop');
      if (isAutoDropped) tr.classList.add('has-auto-drop');

      // Auto-target column: shows the server-applied rewrite if
      // one exists, or "(no rewrite)" when the VLAN passes through
      // unchanged.  Dropped rows show a distinct "(dropped)" label.
      var autoCell;
      if (isAutoDropped) {
        autoCell = '<td class="mig-rename-no-auto">'
          + '(auto-dropped — won\'t render)</td>';
      } else if (appliedTarget !== undefined && appliedTarget !== src) {
        autoCell = '<td>' + escapeHtml(String(appliedTarget)) + '</td>';
      } else {
        autoCell = '<td class="mig-rename-no-auto">(no rewrite)</td>';
      }
      tr.innerHTML = '<td>' + escapeHtml(String(src)) + '</td>' + autoCell;

      var overrideCell = document.createElement('td');
      overrideCell.className = 'mig-rename-target';
      var inp = document.createElement('input');
      inp.type = 'number';
      inp.min = '1';
      inp.max = '4094';
      inp.step = '1';
      inp.placeholder = (appliedTarget !== undefined && appliedTarget !== src)
        ? ('auto: ' + appliedTarget)
        : 'target VLAN id (1-4094)';
      // Display value: show the user override if set; otherwise leave
      // blank so the placeholder carries the auto-target hint.  Never
      // pre-fill with the auto target — an empty field means
      // "accept the auto default".
      inp.value = isDropped
        ? ''
        : ((userVal !== undefined && userVal !== null)
            ? String(userVal) : '');
      inp.disabled = isDropped;
      inp.setAttribute('data-testid',
        'migrate-rename-vlan-override-' + src);
      inp.addEventListener('input', function() {
        var raw = inp.value.trim();
        if (!raw) {
          delete _renameVlanUserMap[src];
        } else {
          var n = parseInt(raw, 10);
          if (isNaN(n) || n < 1 || n > 4094) {
            // Invalid input — leave the previous state in place
            // rather than store a bad value.  UI hints at the valid
            // range via min/max attributes on the input.
            return;
          }
          _renameVlanUserMap[src] = n;
        }
        renderVlanRenameTable();
        renderRenamePreview();
        renderRenameSummary();
        renderRenameRailCounts();
      });
      overrideCell.appendChild(inp);

      // Drop / un-drop link.  Same three-state logic as the port
      // table (drop / un-drop / keep-verbatim beats auto-drop).
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
        'migrate-rename-vlan-drop-' + src);
      dropLink.addEventListener('click', function() {
        if (isUserDropped) {
          delete _renameVlanUserMap[src];
        } else if (isAutoDropped) {
          _renameVlanUserMap[src] = src;
        } else {
          _renameVlanUserMap[src] = null;
        }
        renderVlanRenameTable();
        renderRenamePreview();
        renderRenameSummary();
        renderRenameRailCounts();
      });
      overrideCell.appendChild(dropLink);
      tr.appendChild(overrideCell);

      var warnCell = document.createElement('td');
      if (hasCollision) {
        warnCell.innerHTML = '<span class="mig-rename-collision-icon" '
          + 'title="' + escapeHtml(
            'Collides with VLANs: '
            + targetHits[effective].filter(function(s) {
              return s !== src;
            }).join(', ')
          ) + '">⛔</span>';
      }
      tr.appendChild(warnCell);

      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    sectionsEl.appendChild(table);
  }
