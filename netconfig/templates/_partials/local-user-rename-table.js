  /* ── Local-user rename pane renderer ─────────────────────────────────
   * Third per-pane override category after ports + VLANs.  Builds a
   * per-user override table from _lastJob.source_local_users (every
   * local user the source config declared) plus already-applied
   * rewrites from _lastJob.local_user_renames and drops from
   * _lastJob.local_user_drops.  User edits land in _renameLocalUserMap:
   * { source_username: target_username | null }.
   *
   * Structural sibling of vlan-rename-table.js.  Differences:
   *   * String keys instead of integer IDs — no bounds validation,
   *     no number parsing; just non-empty string.
   *   * Free-text input (type="text") rather than type="number".
   *   * Collision detection is informational only — the server
   *     merges by best-effort (max privilege, first-wins role, first-
   *     wins hash) and the operator is advised via warnings, not
   *     blocked from applying.
   *
   * Depends on module-scope state declared in migrate.html:
   *
   *   _lastJob               — most recent server job response
   *   _renameLocalUserMap    — {source_username: target_username | null}
   *
   * And module-scope helpers (defined in migrate.html):
   *
   *   escapeHtml(s)
   *   renderRenamePreview()
   *   renderRenameSummary()
   *   renderRenameRailCounts()
   * ────────────────────────────────────────────────────────────────── */

  /** Build the local-user rewrite table from the server's
   *  source_local_users + already-applied local_user_renames + user
   *  overrides.  Every user in the source tree gets a row so the
   *  operator can see the full inventory and decide per-user whether
   *  to keep / rename / drop. */
  function renderLocalUserRenameTable() {
    var sectionsEl = document.getElementById('mig-rename-local-users-sections');
    var emptyEl = document.getElementById('mig-rename-local-users-empty');
    if (!sectionsEl) return;
    sectionsEl.innerHTML = '';

    var sourceUsers = (_lastJob && _lastJob.source_local_users) || [];
    if (!sourceUsers.length) {
      if (emptyEl) emptyEl.style.display = '';
      return;
    }
    if (emptyEl) emptyEl.style.display = 'none';

    var appliedRenames = (_lastJob && _lastJob.local_user_renames) || {};
    var autoDroppedSet = new Set((_lastJob && _lastJob.local_user_drops) || []);

    // Build informational collision set — same-target merges are
    // documented server-side as "merged on privilege level + role",
    // not blocked.  UI surfaces the advisory so operator sees it.
    var targetHits = {};
    sourceUsers.forEach(function(src) {
      var userVal = _renameLocalUserMap[src];
      if (userVal === null) return;
      if (userVal === undefined && autoDroppedSet.has(src)) return;
      var effective = (userVal !== undefined && userVal !== null)
        ? userVal
        : (appliedRenames[src] !== undefined
            ? appliedRenames[src] : src);
      if (!effective) return;
      if (!targetHits[effective]) targetHits[effective] = [];
      targetHits[effective].push(src);
    });

    var table = document.createElement('table');
    table.className = 'mig-rename-table';
    table.setAttribute('data-testid', 'migrate-rename-local-users-table');
    var thead = document.createElement('thead');
    thead.innerHTML = '<tr>'
      + '<th>Source username</th>'
      + '<th>Auto target</th>'
      + '<th>Override</th>'
      + '<th style="width:1.5rem">⚠</th>'
      + '</tr>';
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    // Stable display order — alphabetical so admin/operator/svc-*
    // land predictably rather than in parse order (which varies per
    // codec).
    var ordered = sourceUsers.slice().sort();
    ordered.forEach(function(src) {
      var tr = document.createElement('tr');
      // testid uses the raw username; CSS-escaping not required for
      // querySelector lookups the way forward-slash is for port names.
      tr.setAttribute('data-testid', 'migrate-rename-local-user-row-' + src);
      var userVal = _renameLocalUserMap[src];
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
      var hasCollision = !isDropped && effective
                         && targetHits[effective]
                         && targetHits[effective].length > 1;
      if (hasCollision) tr.classList.add('has-collision');
      if (hasOverride) tr.classList.add('has-override');
      if (isDropped) tr.classList.add('has-drop');
      if (isAutoDropped) tr.classList.add('has-auto-drop');

      var autoCell;
      if (isAutoDropped) {
        autoCell = '<td class="mig-rename-no-auto">'
          + '(auto-dropped — won\'t render)</td>';
      } else if (appliedTarget !== undefined && appliedTarget !== src) {
        autoCell = '<td>' + escapeHtml(appliedTarget) + '</td>';
      } else {
        autoCell = '<td class="mig-rename-no-auto">(no rewrite)</td>';
      }
      tr.innerHTML = '<td>' + escapeHtml(src) + '</td>' + autoCell;

      var overrideCell = document.createElement('td');
      overrideCell.className = 'mig-rename-target';
      var inp = document.createElement('input');
      inp.type = 'text';
      inp.placeholder = (appliedTarget !== undefined && appliedTarget !== src)
        ? ('auto: ' + appliedTarget)
        : 'target username (leave blank to keep)';
      inp.value = isDropped
        ? ''
        : ((userVal !== undefined && userVal !== null) ? userVal : '');
      inp.disabled = isDropped;
      inp.setAttribute('data-testid',
        'migrate-rename-local-user-override-' + src);
      inp.addEventListener('input', function() {
        var raw = inp.value.trim();
        if (!raw) {
          delete _renameLocalUserMap[src];
        } else {
          _renameLocalUserMap[src] = raw;
        }
        renderLocalUserRenameTable();
        renderRenamePreview();
        renderRenameSummary();
        renderRenameRailCounts();
      });
      overrideCell.appendChild(inp);

      // Drop / un-drop / keep-verbatim link — same three-state
      // machine as the ports + VLANs panes.
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
        'migrate-rename-local-user-drop-' + src);
      dropLink.addEventListener('click', function() {
        if (isUserDropped) {
          delete _renameLocalUserMap[src];
        } else if (isAutoDropped) {
          _renameLocalUserMap[src] = src;
        } else {
          _renameLocalUserMap[src] = null;
        }
        renderLocalUserRenameTable();
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
            'Collides with users: '
            + targetHits[effective].filter(function(s) {
              return s !== src;
            }).join(', ')
            + ' — server will merge on max privilege + first-wins role'
          ) + '">⛔</span>';
      }
      tr.appendChild(warnCell);

      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    sectionsEl.appendChild(table);
  }
