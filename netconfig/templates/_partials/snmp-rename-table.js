  /* ── SNMP-community rename pane renderer ────────────────────────────
   * Fourth per-pane override category after ports + VLANs +
   * local_users.  Structural difference from the three sibling panes:
   *
   *   ports / vlans / local_users → LIST canonical surfaces, the
   *   pane renders a TABLE with one row per item.
   *
   *   snmp community → SCALAR canonical surface (CanonicalIntent.snmp
   *   holds a single CanonicalSNMP whose ``community`` is one string),
   *   the pane renders a SINGLE ROW.  Same input + drop-link widgets
   *   as the local-users pane row, just wrapped in a one-row table
   *   for visual consistency.
   *
   * Map shape: _renameSnmpCommunityMap = {source_community: target | null}
   *   — effectively single-entry (at most one key can match the
   *   current community), but we keep the dict shape for API
   *   symmetry with the server param snmp_community_rename_map.
   *
   * Extension point (future commit): trap_hosts is a list surface
   * and DOES fit the multi-row table pattern.  When adding it, drop
   * in a second sub-section below the community row, render one row
   * per trap host, use a separate state map
   * _renameSnmpTrapHostMap = {src_host: tgt_host | null}.  The
   * server-side orchestrator already has a naming convention
   * (snmp_trap_host_rename_map) reserved on run_plan_with_overrides.
   *
   * Depends on module-scope state declared in migrate.html:
   *
   *   _lastJob                  — most recent server job response
   *   _renameSnmpCommunityMap   — {source_community: target_community | null}
   *
   * And module-scope helpers:
   *
   *   escapeHtml(s)
   *   renderRenamePreview()
   *   renderRenameSummary()
   *   renderRenameRailCounts()
   * ────────────────────────────────────────────────────────────────── */

  /** Render the SNMP community-rename row.  No-op + shows empty
   *  state when the source config didn't declare an SNMP block. */
  function renderSnmpRenameTable() {
    var sectionsEl = document.getElementById('mig-rename-snmp-sections');
    var emptyEl = document.getElementById('mig-rename-snmp-empty');
    if (!sectionsEl) return;
    sectionsEl.innerHTML = '';

    var currentCommunity = (_lastJob && _lastJob.source_snmp_community) || '';
    // Empty-state: no SNMP block parsed OR bare SNMP block without
    // a community.  Either way the rename pane has nothing to
    // target — empty-state message, no table.
    if (!currentCommunity) {
      if (emptyEl) emptyEl.style.display = '';
      return;
    }
    if (emptyEl) emptyEl.style.display = 'none';

    var appliedRenames = (_lastJob && _lastJob.snmp_community_renames) || {};
    var autoDroppedSet = new Set(
      (_lastJob && _lastJob.snmp_community_drops) || []
    );

    // Build the single-row mini-table.  Style parity with the
    // local-users table keeps the visual shape uniform across
    // panes, even though this one always has exactly one row.
    var table = document.createElement('table');
    table.className = 'mig-rename-table';
    table.setAttribute('data-testid', 'migrate-rename-snmp-table');
    var thead = document.createElement('thead');
    thead.innerHTML = '<tr>'
      + '<th>Source community</th>'
      + '<th>Auto target</th>'
      + '<th>Override</th>'
      + '<th style="width:1.5rem"></th>'
      + '</tr>';
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    var src = currentCommunity;
    var userVal = _renameSnmpCommunityMap[src];
    var isUserDropped = userVal === null;
    var isAutoDropped = userVal === undefined && autoDroppedSet.has(src);
    var isDropped = isUserDropped || isAutoDropped;
    var appliedTarget = appliedRenames[src];
    var hasOverride = userVal !== undefined && !isUserDropped;

    var tr = document.createElement('tr');
    tr.setAttribute(
      'data-testid', 'migrate-rename-snmp-community-row',
    );
    if (hasOverride) tr.classList.add('has-override');
    if (isDropped) tr.classList.add('has-drop');
    if (isAutoDropped) tr.classList.add('has-auto-drop');

    var autoCell;
    if (isAutoDropped) {
      autoCell = '<td class="mig-rename-no-auto">'
        + '(auto-cleared — no SNMP block will render)</td>';
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
      : 'new community (leave blank to keep)';
    inp.value = isDropped
      ? ''
      : ((userVal !== undefined && userVal !== null) ? userVal : '');
    inp.disabled = isDropped;
    inp.setAttribute('data-testid',
      'migrate-rename-snmp-community-override');
    inp.addEventListener('input', function() {
      var raw = inp.value.trim();
      if (!raw) {
        delete _renameSnmpCommunityMap[src];
      } else {
        _renameSnmpCommunityMap[src] = raw;
      }
      renderSnmpRenameTable();
      renderRenamePreview();
      renderRenameSummary();
      renderRenameRailCounts();
    });
    overrideCell.appendChild(inp);

    // Drop / un-drop / keep-verbatim link — same three-state
    // machine as the ports + VLANs + local-users panes.  Clearing
    // the SNMP community tells the server to render no SNMP block
    // at all.
    var dropLink = document.createElement('span');
    dropLink.className = 'mig-rename-drop-link';
    if (isUserDropped) {
      dropLink.textContent = 'un-clear';
    } else if (isAutoDropped) {
      dropLink.textContent = 'keep verbatim';
    } else {
      dropLink.textContent = 'clear';
    }
    dropLink.setAttribute('data-testid',
      'migrate-rename-snmp-community-drop');
    dropLink.addEventListener('click', function() {
      if (isUserDropped) {
        delete _renameSnmpCommunityMap[src];
      } else if (isAutoDropped) {
        _renameSnmpCommunityMap[src] = src;
      } else {
        _renameSnmpCommunityMap[src] = null;
      }
      renderSnmpRenameTable();
      renderRenamePreview();
      renderRenameSummary();
      renderRenameRailCounts();
    });
    overrideCell.appendChild(dropLink);
    tr.appendChild(overrideCell);

    // Warning cell — kept structurally for table symmetry but
    // empty: SNMP community rename has no collision concept
    // (single-value target), so no collision warnings fire
    // client-side.
    var warnCell = document.createElement('td');
    tr.appendChild(warnCell);

    tbody.appendChild(tr);
    table.appendChild(tbody);
    sectionsEl.appendChild(table);
  }
