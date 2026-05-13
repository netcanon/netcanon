  /* ── Rename-modal apply flow + drag + selector wiring ────────────────
   * Re-posts the plan with the user's override map, repositions the
   * modal when the operator drags its header, and wires the three-
   * stage vendor/model/module selectors.  This is the last of the
   * rename-modal logic that was inline in migrate.html; extracting
   * it here completes the rename-modal's partial-ification.
   *
   * Depends on module-scope state in migrate.html:
   *   _lastJobBody, _lastJob, _renameUserMap, _renameDragState
   *
   * And module-scope helpers (some in other partials):
   *   renderResult, renderRenameTable, renderRenamePreview,
   *   renderRenameSummary                     (migrate.html / partials)
   *   currentRenameProfileKey, currentRenameModuleSku,
   *   populateRenameModelDropdown,
   *   populateRenameModuleDropdown            (migrate.html inline)
   *   showToast                                (base.html global)
   * ────────────────────────────────────────────────────────────────── */

  /** POST to /plan again with the user's map, then swap in the new
   *  rendered output + refresh the modal table. */
  window.renameModalApply = async function() {
    if (!_lastJobBody || !_lastJob) return;
    var applyBtn = document.getElementById('mig-rename-apply-btn');
    var status = document.getElementById('mig-rename-status');
    var origText = applyBtn.textContent;
    applyBtn.disabled = true;
    applyBtn.textContent = 'Applying…';
    if (status) status.textContent = '';
    var body = JSON.parse(JSON.stringify(_lastJobBody));
    body.port_rename_map = Object.assign({}, _renameUserMap);
    // VLAN category — send the map ONLY when the operator has
    // actually touched a VLAN row.  Empty-map sends are harmless
    // (server normalises to no-op) but surface as "VLAN pane
    // engaged" in the job response even when nothing changed,
    // which is confusing telemetry.  Gating on non-empty keeps
    // the response shape aligned with operator intent.
    if (typeof _renameVlanUserMap === 'object'
        && _renameVlanUserMap
        && Object.keys(_renameVlanUserMap).length > 0) {
      body.vlan_rename_map = Object.assign({}, _renameVlanUserMap);
    }
    // Local-users category — same gate-on-non-empty pattern.
    if (typeof _renameLocalUserMap === 'object'
        && _renameLocalUserMap
        && Object.keys(_renameLocalUserMap).length > 0) {
      body.local_user_rename_map = Object.assign({}, _renameLocalUserMap);
    }
    // SNMP-community category — scalar but the wire contract uses
    // the same dict shape.  Only send when the operator actually
    // touched the community row; otherwise the pipeline stays on
    // the auto path (no override, no drop).
    if (typeof _renameSnmpCommunityMap === 'object'
        && _renameSnmpCommunityMap
        && Object.keys(_renameSnmpCommunityMap).length > 0) {
      body.snmp_community_rename_map = Object.assign(
        {}, _renameSnmpCommunityMap,
      );
    }
    // SNMPv3 USM user-rename category — fifth per-pane surface.
    // Same gate-on-non-empty pattern; auth / priv / group / engine_id
    // fields travel with the renamed user record server-side (no
    // separate wire surface).
    if (typeof _renameSnmpV3UserMap === 'object'
        && _renameSnmpV3UserMap
        && Object.keys(_renameSnmpV3UserMap).length > 0) {
      body.snmpv3_user_rename_map = Object.assign(
        {}, _renameSnmpV3UserMap,
      );
    }
    var profileKey = currentRenameProfileKey();
    if (profileKey) body.target_profile = profileKey;
    // Only send target_module when the profile actually has
    // modules — prevents noise in the request for legacy profiles.
    var moduleSku = currentRenameModuleSku();
    if (moduleSku) body.target_module = moduleSku;
    try {
      var resp = await fetch('/api/v1/migration/plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        var err = await resp.json().catch(function() { return {}; });
        showToast('Request rejected: ' + formatApiError(err, resp.statusText), 'error');
        return;
      }
      var newJob = await resp.json();
      _lastJob = newJob;
      _lastJobBody = body;
      renderResult(newJob);
      // Re-render the modal from the refreshed job.
      renderRenameTable();
      if (typeof renderVlanRenameTable === 'function') renderVlanRenameTable();
      if (typeof renderLocalUserRenameTable === 'function') renderLocalUserRenameTable();
      if (typeof renderSnmpRenameTable === 'function') renderSnmpRenameTable();
      if (typeof renderRenameRailCounts === 'function') renderRenameRailCounts();
      renderRenamePreview();
      renderRenameSummary();
      if (status) status.textContent = 'Applied. Rendered output refreshed.';
      showToast('Rename applied; output regenerated.', 'success');
    } catch (e) {
      showToast('Network error: ' + e.message, 'error');
    } finally {
      applyBtn.disabled = false;
      applyBtn.textContent = origText;
    }
  };

  /* ── Drag behaviour on the modal header ── */
  function onRenameDragStart(e) {
    var modal = document.getElementById('mig-rename-modal');
    if (!modal.classList.contains('open')) return;
    // Only drag when the mousedown originated on the header itself
    // (not one of its buttons).
    if (e.target.closest('button')) return;
    var rect = modal.getBoundingClientRect();
    _renameDragState = {
      offsetX: e.clientX - rect.left,
      offsetY: e.clientY - rect.top,
    };
    // Switch to absolute positioning so translateX(-50%) no longer
    // affects drag math.
    modal.style.transform = 'none';
    modal.style.left = rect.left + 'px';
    modal.style.top  = rect.top + 'px';
    e.preventDefault();
  }
  function onRenameDragMove(e) {
    if (!_renameDragState) return;
    var modal = document.getElementById('mig-rename-modal');
    modal.style.left = (e.clientX - _renameDragState.offsetX) + 'px';
    modal.style.top  = (e.clientY - _renameDragState.offsetY) + 'px';
  }
  function onRenameDragEnd() { _renameDragState = null; }

  /* ── DOMContentLoaded wiring for modal-specific listeners ── */
  document.addEventListener('DOMContentLoaded', function() {
    var header = document.getElementById('mig-rename-modal-header');
    if (header) header.addEventListener('mousedown', onRenameDragStart);
    document.addEventListener('mousemove', onRenameDragMove);
    document.addEventListener('mouseup', onRenameDragEnd);

    var vsel = document.getElementById('mig-rename-target-vendor');
    var msel = document.getElementById('mig-rename-target-model');
    var modsel = document.getElementById('mig-rename-target-module');

    if (vsel) {
      vsel.addEventListener('change', function() {
        // Re-populate the model dropdown whenever the vendor changes.
        // Model resets to "(pick model)" — user must explicitly commit
        // to hardware; we don't guess.  populateRenameModelDropdown
        // cascades into populateRenameModuleDropdown, so the module
        // dropdown gets reset in the same step.
        populateRenameModelDropdown(vsel.value);
        renderRenameTable();
        renderRenamePreview();
        renderRenameSummary();
      });
    }
    if (msel) {
      msel.addEventListener('change', function() {
        // Re-populate the module dropdown when the model changes —
        // different chassis have different NM-slot inventories (or
        // none at all for legacy profiles).  User overrides that
        // pointed at a port in the PREVIOUS profile's namespace are
        // preserved but surfaced as "(custom: X — not in profile)"
        // rows in the dropdown — operator can then see what's
        // orphaned and decide to keep or re-pick.  See
        // renderRenameTable().
        populateRenameModuleDropdown(vsel ? vsel.value : '', msel.value);
        renderRenameTable();
        renderRenamePreview();
        renderRenameSummary();
      });
    }
    if (modsel) {
      modsel.addEventListener('change', function() {
        // Module swap (e.g. Cat 9300 NM-8X → NM-2Q).  Existing user
        // overrides persist; if they referenced a port that only
        // existed under the previous module, the orphaned-override
        // dropdown logic in renderRenameTable() surfaces them as
        // "(custom: X — not in profile)" so the operator can re-pick
        // or keep.  No state reset — operator intent survives module
        // churn, consistent with profile-change behaviour.
        renderRenameTable();
        renderRenamePreview();
        renderRenameSummary();
      });
    }
  });
