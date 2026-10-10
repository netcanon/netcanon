  /* ── Rename-modal apply flow + drag + selector wiring ────────────────
   * Re-posts the plan with the user's override map, repositions the
   * modal when the operator drags its header, and wires the three-
   * stage vendor/model/module selectors.  This is the last of the
   * rename-modal logic that was inline in migrate.html; extracting
   * it here completes the rename-modal's partial-ification.
   *
   * Depends on module-scope state in migrate.html:
   *   _lastJobBody, _lastJob, _renameUserMap, _renameDragState,
   *   _renameApplying, _devicePlanKey, _planReportOpen
   *
   * And module-scope helpers (some in other partials):
   *   renderResult, renderRenameTable, renderRenamePreview,
   *   renderRenameSummary                     (migrate.html / partials)
   *   applyDeviceDeclarations, devicesSettled, _devicesKey,
   *   currentPortPlan, deviceTargetPicked,
   *   forgetAcceptedDecisions                  (device-models.js)
   *   currentRenameProfileKey, currentRenameModuleSku,
   *   populateRenameModelDropdown,
   *   populateRenameModuleDropdown            (migrate.html inline)
   *   showToast                                (base.html global)
   * ────────────────────────────────────────────────────────────────── */

  /** POST to /plan again with the user's map, then swap in the new
   *  rendered output + refresh the modal table.
   *
   *  One Apply at a time (``_renameApplying``): the summary re-enables
   *  the button on every redraw, and a compile that answers while this
   *  waits redraws.  The answer is drawn only if the job it was asked
   *  for is still the one on the page: a translation submitted from
   *  the form behind the modal replaces it. */
  window.renameModalApply = async function() {
    if (!_lastJobBody || !_lastJob || _renameApplying) return;
    var applyBtn = document.getElementById('mig-rename-apply-btn');
    var status = document.getElementById('mig-rename-status');
    var origText = applyBtn.textContent;
    var baseBody = _lastJobBody;
    // True once a translation submitted behind the modal has replaced
    // the job this Apply was pressed for.  Asked after every wait.
    var gone = function() { return _lastJobBody !== baseBody; };
    _renameApplying = true;
    applyBtn.disabled = true;
    applyBtn.textContent = 'Applying…';
    if (status) status.textContent = '';
    try {
      // The devices first: a member number typed just before the click
      // is still being compiled, and the request is built from what is
      // on screen once that has answered -- the maps included, so an
      // entry made while this waits is in the request too.
      await devicesSettled();
      if (gone()) return;
      // Decisions "Accept as shown" recorded were a verdict on the
      // pairing on screen.  With other devices declared they are not
      // sent on: a port that had no place may have one now.
      if (_devicePlanKey !== _devicesKey() && forgetAcceptedDecisions()) {
        renderRenameTable();
      }
      var body = JSON.parse(JSON.stringify(baseBody));
      body.port_rename_map = Object.assign({}, _renameUserMap);
      // The body is a clone of the last request.  A per-pane map is
      // added below only when the operator touched that pane, so one
      // that was sent before and has since been cleared (Reset all)
      // must be taken out, or it would be applied again.
      delete body.vlan_rename_map;
      delete body.local_user_rename_map;
      delete body.snmp_community_rename_map;
      delete body.snmpv3_user_rename_map;
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
      // The devices: a target profile whenever one is chosen (with its
      // module only when the profile has modules), and the source and
      // target declarations when both are made -- whether or not their
      // previews compiled: the server refuses a declaration that is
      // wrong, in words, and the output is then left as it was.
      // Fields a previous Apply sent are removed first -- see
      // applyDeviceDeclarations.
      applyDeviceDeclarations(body);
      var devicesKey = _devicesKey();
      var resp = await fetch('/api/v1/migration/plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (gone()) return;
      if (!resp.ok) {
        var err = await resp.json().catch(function() { return {}; });
        var refusal = formatApiError(err, resp.statusText);
        showToast('Request rejected: ' + refusal, 'error');
        if (status) status.textContent = 'Not applied — the server refused the request.';
        return;
      }
      var newJob = await resp.json();
      if (gone()) return;
      _lastJob = newJob;
      _lastJobBody = body;
      _devicePlanKey = devicesKey;
      _planReportOpen = null;
      renderResult(newJob);
      // Re-render the modal from the refreshed job.
      renderRenameTable();
      if (typeof renderVlanRenameTable === 'function') renderVlanRenameTable();
      if (typeof renderLocalUserRenameTable === 'function') renderLocalUserRenameTable();
      if (typeof renderSnmpRenameTable === 'function') renderSnmpRenameTable();
      if (typeof renderSnmpV3UserRenameTable === 'function') renderSnmpV3UserRenameTable();
      if (typeof renderRenameRailCounts === 'function') renderRenameRailCounts();
      renderRenamePreview();
      renderRenameSummary();
      // What happened is said on the strip.  With a long member list
      // open above it, it is below the fold of the region that
      // scrolls: bring it into view.
      var strip = document.getElementById('mig-rename-plan');
      if (strip && strip.style.display !== 'none' && strip.scrollIntoView) {
        strip.scrollIntoView({ block: 'nearest' });
      }
      var applyPlan = currentPortPlan();
      var undecided = (applyPlan && applyPlan.applied)
        ? (applyPlan.unresolved_ports || []).length : 0;
      if (status) {
        if (applyPlan && !applyPlan.applied) {
          status.textContent = 'Applied. Ports were NOT paired by position — see above.';
        } else if (undecided) {
          status.textContent = 'Applied. ' + undecided + ' port name'
            + (undecided === 1 ? '' : 's') + ' still need'
            + (undecided === 1 ? 's' : '') + ' your decision.';
        } else {
          status.textContent = 'Applied. Rendered output refreshed.';
        }
      }
      showToast('Rename applied; output regenerated.', 'success');
    } catch (e) {
      showToast('Network error: ' + e.message, 'error');
    } finally {
      _renameApplying = false;
      applyBtn.textContent = origText;
      // Whether Apply is available is the summary's to say, not this
      // function's: enabling it here would undo a hold.
      renderRenameSummary();
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
        deviceTargetPicked();
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
        // A model from a model family brings its own controls (mode,
        // modules, stack members) and is compiled by the server.
        deviceTargetPicked();
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
        deviceTargetPicked();
      });
    }
  });
