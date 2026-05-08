  /* ── SNMPv3-user rename pane renderer ────────────────────────────────
   * Fifth per-pane override category after ports + VLANs +
   * local_users + snmp_community.  Structural sibling of
   * local-user-rename-table.js — list-oriented canonical surface
   * (CanonicalSNMP.v3_users is a list of CanonicalSNMPv3User records),
   * one row per source user.
   *
   * Map shape: _renameSnmpV3UserMap = {source_name: target_name | null}
   *
   * Differences from the local-users pane:
   *   * Collisions are server-handled via first-wins merge (auth /
   *     priv keys are NEVER combined across users — the crypto
   *     would be incoherent).  Client-side collision UI marks the
   *     advisory but doesn't block Apply.
   *   * Auth / priv / group are metadata, not identity.  The rename
   *     operation only rewrites ``name``; everything else follows
   *     the renamed record.
   *
   * Depends on module-scope state declared in migrate.html:
   *
   *   _lastJob              — most recent server job response
   *   _renameSnmpV3UserMap  — {source_name: target_name | null}
   *
   * And module-scope helpers (defined in migrate.html):
   *
   *   escapeHtml(s)
   *   renderRenamePreview()
   *   renderRenameSummary()
   *   renderRenameRailCounts()
   * ────────────────────────────────────────────────────────────────── */

  /** Build the SNMPv3-user rewrite table from the server's
   *  source_snmpv3_users + already-applied snmpv3_user_renames +
   *  drops + user overrides.  Every v3 user in the source tree gets
   *  a row; empty list → empty-state message. */
  function renderSnmpV3UserRenameTable() {
    var sectionsEl = document.getElementById('mig-rename-snmpv3-sections');
    var emptyEl = document.getElementById('mig-rename-snmpv3-empty');
    if (!sectionsEl) return;
    sectionsEl.innerHTML = '';

    var sourceUsers = (_lastJob && _lastJob.source_snmpv3_users) || [];
    if (!sourceUsers.length) {
      if (emptyEl) emptyEl.style.display = '';
      return;
    }
    if (emptyEl) emptyEl.style.display = 'none';

    var appliedRenames = (_lastJob && _lastJob.snmpv3_user_renames) || {};
    var autoDroppedSet = new Set(
      (_lastJob && _lastJob.snmpv3_user_drops) || []
    );

    // Target-collision set — informational only (server does
    // first-wins merge, auth/priv keys never combined).  Surface
    // advisory in the warn column.
    var targetHits = {};
    sourceUsers.forEach(function(src) {
      var userVal = _renameSnmpV3UserMap[src];
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
    table.setAttribute('data-testid', 'migrate-rename-snmpv3-table');
    var thead = document.createElement('thead');
    thead.innerHTML = '<tr>'
      + '<th>Source v3 username</th>'
      + '<th>Auto target</th>'
      + '<th>Override</th>'
      + '<th style="width:1.5rem">⚠</th>'
      + '</tr>';
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    var ordered = sourceUsers.slice().sort();
    ordered.forEach(function(src) {
      var tr = document.createElement('tr');
      tr.setAttribute(
        'data-testid', 'migrate-rename-snmpv3-user-row-' + src,
      );
      var userVal = _renameSnmpV3UserMap[src];
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
        : 'target securityName (leave blank to keep)';
      inp.value = isDropped
        ? ''
        : ((userVal !== undefined && userVal !== null) ? userVal : '');
      inp.disabled = isDropped;
      inp.setAttribute('data-testid',
        'migrate-rename-snmpv3-user-override-' + src);
      inp.addEventListener('input', function() {
        var raw = inp.value.trim();
        if (!raw) {
          delete _renameSnmpV3UserMap[src];
        } else {
          _renameSnmpV3UserMap[src] = raw;
        }
        renderSnmpV3UserRenameTable();
        renderRenamePreview();
        renderRenameSummary();
        renderRenameRailCounts();
      });
      overrideCell.appendChild(inp);

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
        'migrate-rename-snmpv3-user-drop-' + src);
      dropLink.addEventListener('click', function() {
        if (isUserDropped) {
          delete _renameSnmpV3UserMap[src];
        } else if (isAutoDropped) {
          _renameSnmpV3UserMap[src] = src;
        } else {
          _renameSnmpV3UserMap[src] = null;
        }
        renderSnmpV3UserRenameTable();
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
            'Collides with v3 users: '
            + targetHits[effective].filter(function(s) {
              return s !== src;
            }).join(', ')
            + ' — server applies first-wins; other records dropped'
          ) + '">⛔</span>';
      }
      tr.appendChild(warnCell);

      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    sectionsEl.appendChild(table);
  }
