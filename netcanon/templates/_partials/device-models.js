  /* ── Device models: source + target device pickers, and the port plan ──
   * Lets the operator say which device the config came from and which
   * device it is going to, so the server pairs their ports by POSITION
   * instead of guessing a target name from the shape of a source name.
   *
   * A device is declared in one of two ways:
   *
   *   family   a model from a model family (GET /migration/model-families)
   *            plus its deployment mode, the module in each bay, and --
   *            in a stacking mode -- the stack members;
   *   profile  a flat target profile (GET /migration/target-profiles),
   *            for a device no family describes yet.
   *
   * The source picker is pre-filled from the config itself
   * (POST /migration/detect-deployment) and says which lines it was
   * read from.  Nothing is sent until Apply; `applyDeviceDeclarations`
   * then adds the declarations to the plan request, and the job comes
   * back with `port_mapping_plan`, which `renderPortPlan` and the
   * rename table show.
   *
   * Module-scope state (declared in migrate.html):
   *
   *   _modelFamilies     — families from the server
   *   _modelFamiliesFailed — the last attempt to fetch them failed
   *   _deviceDecl        — { source, target } declarations (family kind;
   *                        a target PROFILE lives in the three legacy
   *                        target selects, see currentDeviceDecl)
   *   _deviceInventory   — { source, target } compiled inventories
   *   _deviceError       — { source, target } why one did not compile
   *   _deviceUnchecked   — { source, target } the preview could not be
   *                        fetched at all (the error is not a verdict)
   *   _deviceChecking    — { source, target } a preview is in flight
   *   _deviceProposal    — what the config says about its own hardware
   *   _deviceProposalFor — the source text that proposal was read from
   *   _deviceDetecting   — the source text being asked about now
   *   _deviceDetectError — why the config could not be asked
   *   _deviceSourceKey   — the source text the source declaration is for
   *   _deviceSourceTouched — the operator chose in the source select
   *                        for this text ("(not declared)" included)
   *   _deviceTargetCodec — the target codec the target device is for
   *   _deviceSeq         — per-side counter; drops a stale response
   *   _deviceBusy        — per-side compile request in flight
   *   _devicePlanKey     — the declarations the last plan was made with
   *   _deviceTargetPick  — the last target vendor / model / module
   *                        pick, for the job's target codec
   *   _deviceMembersOpen — { source, target } a long member list, unfolded
   *   _planAccepted      — entries "Accept as shown" recorded, for the
   *                        plan on screen
   *   _planReportOpen    — the report under the strip, as the operator
   *                        left it (null: not touched)
   *   _lastJob, _lastJobBody, _renameUserMap, _renameProfiles, adapters
   *
   * Helpers used from elsewhere: currentRenameProfileKey,
   * currentRenameModuleSku, effectivePortsFor,
   * populateRenameModelDropdown, populateRenameModuleDropdown,
   * formatApiError, renderRenameTable, rebuildRenameTableSoon,
   * renderRenamePreview, renderRenameSummary, applyHeldBy.
   *
   * The browser holds no naming rule and no port list of its own for a
   * family model: what a declaration compiles to, whether it is valid,
   * and which member number a blank box stands for are the server's
   * answers.  A declaration the preview could not pass is still sent
   * on Apply, and the server refuses it in words.
   *
   * Every string that reaches the page here comes from the server --
   * family and profile YAML an operator can author, and lines of the
   * pasted config itself -- so everything is written with textContent.
   * ────────────────────────────────────────────────────────────────── */

  var _DEVICE_FAMILY_PREFIX = 'fam:';
  var _DEVICE_PROFILE_PREFIX = 'profile:';
  var _DEVICE_BAY_UNSTATED = '__unstated__';
  var _DEVICE_BAY_EMPTY = '__empty__';
  /** A stack of more members than this folds under its count. */
  var _DEVICE_FOLD_AT = 4;
  /** How long a preview may take before it is given up on.  Apply
   *  waits for a preview in flight; it must not wait for ever. */
  var _DEVICE_COMPILE_TIMEOUT_MS = 20000;

  /** Wording for an inventory's evidence grade.  The grade is of the
   *  port NAMES of this one deployment. */
  var _DEVICE_EVIDENCE_LABEL = {
    'capture': 'Port names checked against a real capture of this deployment',
    'vendor-doc': 'Port names from published vendor sources (no capture of this deployment here)',
    'inferred': 'Port names NOT verified for this device',
  };
  var _DEVICE_UNGRADED_LABEL = 'Port names not yet graded';

  var _modelFamiliesLoad = null;

  /** Fetch the model families.  Resolves true when they arrived.  One
   *  request at a time; a failed one is asked again the next time the
   *  modal opens. */
  function loadModelFamilies() {
    if (_modelFamiliesLoad) return _modelFamiliesLoad;
    _modelFamiliesLoad = (async function() {
      var arrived = false;
      try {
        var resp = await fetch('/api/v1/migration/model-families');
        if (resp.ok) {
          var data = await resp.json();
          if (Array.isArray(data)) {
            _modelFamilies = data;
            arrived = true;
          }
        }
      } catch (_) {
        // Model families are optional; without them the pickers offer
        // target profiles only -- and say so, see renderDeviceNote.
      }
      _modelFamiliesFailed = !arrived;
      _modelFamiliesLoad = null;
      if (arrived) _modelFamiliesArrived();
      return arrived;
    })();
    return _modelFamiliesLoad;
  }

  /** Families that arrive while the modal is open reach its lists. */
  function _modelFamiliesArrived() {
    var modal = document.getElementById('mig-rename-modal');
    if (!modal || !modal.classList.contains('open')) return;
    if (typeof populateRenameVendorDropdown === 'function') {
      var vsel = document.getElementById('mig-rename-target-vendor');
      var kept = vsel ? vsel.value : '';
      populateRenameVendorDropdown();
      if (vsel && kept) vsel.value = kept;
      populateRenameModelDropdown(vsel ? vsel.value : '');
    }
    openDevicePickers();
    // What the config states may be a device only these families
    // describe: it was read before they arrived, and is used now.
    if (!_deviceDecl.source && !_deviceSourceTouched && _deviceProposal) {
      useDetectedSourceDevice();
    }
  }

  /* ── lookups ── */

  function _deviceCodec(side) {
    if (!_lastJobBody) return '';
    return (side === 'source' ? _lastJobBody.source : _lastJobBody.target) || '';
  }

  function _codecVendor(codecName) {
    var a = adapters.find(function(x) { return x.name === codecName; });
    return (a && a.vendor_id) || '';
  }

  function _familiesOf(vendor) {
    return _modelFamilies.filter(function(f) { return f.vendor === vendor; });
  }

  function _familyOf(vendor, familyKey) {
    return _modelFamilies.find(function(f) {
      return f.vendor === vendor && f.family === familyKey;
    }) || null;
  }

  function _declFamily(decl) {
    return (decl && decl.kind === 'family')
      ? _familyOf(decl.vendor, decl.family) : null;
  }

  /** Mode names a model can be deployed in, in the family's order. */
  function _modeNames(fam, modelKey) {
    var model = (fam.models || {})[modelKey] || {};
    var all = Object.keys(fam.modes || {});
    if (Array.isArray(model.modes) && model.modes.length) {
      return all.filter(function(m) { return model.modes.indexOf(m) !== -1; });
    }
    return all;
  }

  function _defaultMode(fam, modelKey) {
    var names = _modeNames(fam, modelKey);
    if (names.indexOf(fam.default_mode) !== -1) return fam.default_mode;
    return names[0] || '';
  }

  /** ``[lowest, highest]`` member id of a stacking mode, or null for a
   *  mode in which a device stands alone. */
  function _memberIdRange(fam, modeName) {
    var mode = (fam && fam.modes || {})[modeName];
    return (mode && Array.isArray(mode.member_ids)) ? mode.member_ids : null;
  }

  function _newFamilyDecl(vendor, familyKey, modelKey) {
    var fam = _familyOf(vendor, familyKey);
    if (!fam || !(fam.models || {})[modelKey]) return null;
    var mode = _defaultMode(fam, modelKey);
    var range = _memberIdRange(fam, mode);
    return {
      kind: 'family', vendor: vendor, family: familyKey, mode: mode,
      members: [{ model: modelKey, id: range ? range[0] : null, modules: {} }],
      fromConfig: false, aside: null,
    };
  }

  /** The declaration for *side*, or null.  The target side has two
   *  homes: a profile is whatever the legacy vendor / model / module
   *  selects say, a family model is in ``_deviceDecl.target``. */
  function currentDeviceDecl(side) {
    if (side === 'source') return _deviceDecl.source;
    var key = currentRenameProfileKey();
    if (key) {
      return {
        kind: 'profile', vendor: key.split('/')[0], profile: key,
        module: currentRenameModuleSku(),
      };
    }
    return _deviceDecl.target;
  }

  /** What the rename table and the fit-check need to know about the
   *  target device: its ports as ``{id, kind}``, its LAG naming if
   *  known, and a label.  Null when no target device is chosen, or a
   *  family model has not compiled (yet). */
  function currentTargetDevice() {
    var key = currentRenameProfileKey();
    if (key) {
      var profile = _renameProfiles.find(function(p) {
        return (p.vendor + '/' + p.model) === key;
      });
      if (!profile) return null;
      return {
        ports: effectivePortsFor(profile),
        lags: profile.lags || null,
        label: profile.display_name || profile.model,
        profile: profile,
      };
    }
    var inv = _deviceInventory.target;
    if (!inv || !Array.isArray(inv.ports)) return null;
    return {
      ports: inv.ports.map(function(p) {
        return { id: p.name, kind: p.role === 'access' ? 'physical' : p.role };
      }),
      lags: null,
      label: inv.description || 'the target device',
      profile: null,
    };
  }

  /** The body of a declaration as the API takes it.  A member number
   *  is sent as the field holds it: the server says what is wrong with
   *  one, and picks one for a member that has none. */
  function _deploymentSpec(decl) {
    var range = _memberIdRange(_declFamily(decl), decl.mode);
    return {
      mode: decl.mode,
      members: decl.members.map(function(m) {
        var out = { model: m.model, modules: {} };
        if (range && m.id !== null && m.id !== undefined) out.id = m.id;
        Object.keys(m.modules || {}).forEach(function(bay) {
          out.modules[bay] = m.modules[bay];
        });
        return out;
      }),
    };
  }

  /** A stable text for "these two declarations" -- used to tell that
   *  the devices changed since the plan on screen was made. */
  function _declKey(decl) {
    if (!decl) return '';
    if (decl.kind === 'profile') {
      return 'profile|' + decl.profile + '|' + (decl.module || '');
    }
    return 'family|' + decl.vendor + '|' + decl.family + '|'
      + JSON.stringify(_deploymentSpec(decl));
  }

  function _devicesKey() {
    return _declKey(currentDeviceDecl('source')) + ' >> '
      + _declKey(currentDeviceDecl('target'));
  }

  /** True when the source select has a device to offer. */
  function _sourceModelsKnown() {
    var vendor = _codecVendor(_deviceCodec('source'));
    return _familiesOf(vendor).length > 0
      || _renameProfiles.some(function(p) { return p.vendor === vendor; });
  }

  /** Why no pair of devices goes out with the next Apply, or ''.
   *
   *    none              nothing is declared
   *    target-vendor     the target is not of the target codec's vendor
   *    no-source-models  no device is known for the source vendor
   *    no-source         only the target is declared
   *    no-target         only the source is declared
   *
   *  A declaration that did not compile is not among them.  It is
   *  sent, and the server refuses it in words: leaving the pair out
   *  would turn a mistyped member number into a translation by name
   *  shape that reports success.  See _devicePreviewState. */
  function _devicePairProblem() {
    var src = currentDeviceDecl('source');
    var tgt = currentDeviceDecl('target');
    if (!src && !tgt) return 'none';
    if (tgt && tgt.vendor !== _codecVendor(_deviceCodec('target'))) {
      return 'target-vendor';
    }
    if (!src) return _sourceModelsKnown() ? 'no-source' : 'no-source-models';
    if (!tgt) return 'no-target';
    return '';
  }

  /** How the previews of the two declarations stand:
   *
   *    checking    one is being compiled
   *    invalid     the server refused one (it will refuse it again)
   *    unchecked   one could not be previewed at all -- no answer, or
   *                an answer that is no verdict.  The server compiles
   *                the declaration itself on Apply.
   *    ''          both compiled (or need no preview)                */
  function _devicePreviewState() {
    if (_deviceChecking.source || _deviceChecking.target) return 'checking';
    var invalid = false;
    var unchecked = false;
    ['source', 'target'].forEach(function(side) {
      if (!_deviceError[side]) return;
      if (_deviceUnchecked[side]) unchecked = true;
      else invalid = true;
    });
    return invalid ? 'invalid' : (unchecked ? 'unchecked' : '');
  }

  /** True when the next Apply asks the server for a pairing that is
   *  not the one on screen. */
  function devicePairWaiting() {
    if (_devicePairProblem()) return false;
    var plan = currentPortPlan();
    return !plan || _devicePlanKey !== _devicesKey();
  }

  /** Put the device declarations on a plan request body.
   *
   *  The body is a clone of the previous request, so every field this
   *  function owns is removed first: a device that was cleared must
   *  not ride along from the last Apply.
   *
   *  A target PROFILE is sent whenever one is chosen (it has always
   *  been; on its own it is advice for the server).  A source, and a
   *  target family model, are sent only as a pair: the server refuses
   *  half a declaration.  A pair is sent whether or not its previews
   *  compiled. */
  function applyDeviceDeclarations(body) {
    ['source_deployment', 'source_profile', 'source_module',
     'target_deployment', 'target_profile', 'target_module',
    ].forEach(function(field) { delete body[field]; });
    var src = currentDeviceDecl('source');
    var tgt = currentDeviceDecl('target');
    if (tgt && tgt.kind === 'profile') {
      body.target_profile = tgt.profile;
      if (tgt.module) body.target_module = tgt.module;
    }
    if (_devicePairProblem()) return body;
    if (src.kind === 'family') {
      body.source_deployment = _deploymentSpec(src);
    } else {
      body.source_profile = src.profile;
      if (src.module) body.source_module = src.module;
    }
    if (tgt.kind === 'family') {
      body.target_deployment = _deploymentSpec(tgt);
    }
    return body;
  }

  /* ── building the controls ── */

  function _option(value, text) {
    var opt = document.createElement('option');
    opt.value = value;
    opt.textContent = text;
    return opt;
  }

  /** Append one ``<optgroup>`` per model family of *vendor*. */
  function appendDeviceFamilyOptions(select, vendor) {
    _familiesOf(vendor).forEach(function(fam) {
      var group = document.createElement('optgroup');
      group.label = (fam.display_name || fam.family)
        + ' — model family (mode, modules, stack members)';
      Object.keys(fam.models || {}).forEach(function(modelKey) {
        var model = fam.models[modelKey];
        group.appendChild(_option(
          _DEVICE_FAMILY_PREFIX + fam.family + ':' + modelKey,
          model.display_name || modelKey,
        ));
      });
      if (group.children.length) select.appendChild(group);
    });
  }

  /** ``fam:<family>:<model>`` -> ``{family, model}``, else null. */
  function _parseFamilyValue(value) {
    if (!value || value.indexOf(_DEVICE_FAMILY_PREFIX) !== 0) return null;
    var rest = value.slice(_DEVICE_FAMILY_PREFIX.length);
    var cut = rest.indexOf(':');
    if (cut < 0) return null;
    return { family: rest.slice(0, cut), model: rest.slice(cut + 1) };
  }

  function _selectValueOf(decl) {
    if (!decl) return '';
    if (decl.kind === 'family') {
      return _DEVICE_FAMILY_PREFIX + decl.family + ':' + decl.members[0].model;
    }
    return _DEVICE_PROFILE_PREFIX + decl.profile.split('/').slice(1).join('/');
  }

  /** Fill the source-device select: the families and the profiles of
   *  the SOURCE codec's vendor.  Disabled when there are none. */
  function populateDeviceSourceModels() {
    var sel = document.getElementById('mig-device-source-model');
    if (!sel) return;
    var vendor = _codecVendor(_deviceCodec('source'));
    sel.textContent = '';
    sel.appendChild(_option('', '(not declared)'));
    appendDeviceFamilyOptions(sel, vendor);
    var profiles = _renameProfiles.filter(function(p) {
      return p.vendor === vendor;
    }).sort(function(a, b) {
      return (a.display_name || a.model).localeCompare(b.display_name || b.model);
    });
    if (profiles.length) {
      var group = document.createElement('optgroup');
      group.label = 'Profiles — one fixed port list';
      profiles.forEach(function(p) {
        group.appendChild(_option(
          _DEVICE_PROFILE_PREFIX + p.model, p.display_name || p.model,
        ));
      });
      sel.appendChild(group);
    }
    sel.disabled = sel.options.length <= 1;
    sel.title = sel.disabled
      ? 'No device model is known for this source vendor yet'
      : 'The device this config came from';
    var want = _selectValueOf(_deviceDecl.source);
    sel.value = want;
    if (sel.value !== want) sel.value = '';
  }

  function _profileOf(decl) {
    if (!decl || decl.kind !== 'profile') return null;
    return _renameProfiles.find(function(p) {
      return (p.vendor + '/' + p.model) === decl.profile;
    }) || null;
  }

  /** The module of a source PROFILE.  Mirrors the target's module
   *  select: hidden when the profile has no modules. */
  function _renderSourceProfileModule() {
    var sel = document.getElementById('mig-device-source-module');
    if (!sel) return;
    var decl = _deviceDecl.source;
    var profile = _profileOf(decl);
    var skus = Object.keys((profile && profile.modules) || {});
    sel.textContent = '';
    if (!skus.length) {
      sel.style.display = 'none';
      sel.disabled = true;
      return;
    }
    if (!decl.module || skus.indexOf(decl.module) === -1) {
      decl.module = skus.indexOf('default') !== -1 ? 'default' : skus[0];
    }
    skus.forEach(function(sku) {
      var mod = profile.modules[sku] || {};
      sel.appendChild(_option(
        sku, mod.description ? sku + ' — ' + mod.description : sku,
      ));
    });
    sel.value = decl.module;
    sel.style.display = '';
    sel.disabled = false;
  }

  /** The row of *side*: what its controls live in. */
  function _deviceRow(side) {
    return document.getElementById(side === 'source'
      ? 'mig-device-source' : 'mig-rename-target-profile-group');
  }

  /** "Source device" / "Target device", for labels. */
  function _sideWords(side) {
    return side === 'source' ? 'Source device' : 'Target device';
  }

  /** Rebuild the mode select, the per-member controls and the
   *  add-member button of *side* from its declaration.  The control
   *  that had the focus has it again afterwards -- or, when it is
   *  gone (a member was removed), the control *fallback* names. */
  function renderDeviceControls(side, fallback) {
    var modeSel = document.getElementById('mig-device-' + side + '-mode');
    var membersEl = document.getElementById('mig-device-' + side + '-members');
    var addBtn = document.getElementById('mig-device-' + side + '-add');
    if (!modeSel || !membersEl || !addBtn) return;
    var row = _deviceRow(side);
    var active = document.activeElement;
    var focusId = (row && active && row.contains(active))
      ? active.getAttribute('data-testid') : null;
    if (side === 'source') _renderSourceProfileModule();
    var decl = _deviceDecl[side];
    var fam = _declFamily(decl);
    membersEl.textContent = '';
    // More than one switch: a line per member, so that a member's
    // number, model and modules read as one thing.
    membersEl.classList.toggle(
      'mig-device-members-stack', !!fam && decl.members.length > 1,
    );
    modeSel.textContent = '';
    if (!fam) {
      modeSel.style.display = 'none';
      addBtn.style.display = 'none';
      return;
    }
    var first = decl.members[0].model;
    _modeNames(fam, first).forEach(function(name) {
      modeSel.appendChild(_option(name, (fam.modes[name] || {}).label || name));
    });
    modeSel.value = decl.mode;
    modeSel.style.display = '';
    modeSel.title = 'How the device is deployed — it decides every port name';

    var range = _memberIdRange(fam, decl.mode);
    // A long stack folds under its count: ten members read from a
    // config are ten lines of controls nobody asked to see.  It stays
    // open once the operator has opened it, or has added a member.
    var holder = membersEl;
    if (decl.members.length > _DEVICE_FOLD_AT) {
      holder = document.createElement('details');
      holder.className = 'mig-device-members-fold';
      holder.setAttribute('data-testid', 'migrate-device-' + side + '-members-fold');
      holder.open = !!_deviceMembersOpen[side];
      var foldSummary = document.createElement('summary');
      foldSummary.setAttribute('data-testid',
        'migrate-device-' + side + '-members-fold-summary');
      foldSummary.textContent = decl.members.length + ' stack members'
        + _memberNumbersText(decl.members.map(function(m) { return m.id; }));
      foldSummary.addEventListener('click', function() {
        _deviceMembersOpen[side] = !holder.open;
      });
      holder.appendChild(foldSummary);
      membersEl.appendChild(holder);
    }
    decl.members.forEach(function(member, rank) {
      holder.appendChild(_memberControls(side, decl, fam, member, rank, range));
    });
    var room = range ? (range[1] - range[0] + 1) : 1;
    addBtn.style.display = (range && decl.members.length < room) ? '' : 'none';

    if (focusId && row) {
      var again = null;
      [focusId, fallback, 'migrate-device-' + side + '-add-member'].forEach(function(id) {
        if (again || !id) return;
        row.querySelectorAll('[data-testid]').forEach(function(el) {
          if (!again && el.getAttribute('data-testid') === id
              && el.offsetParent !== null) {
            again = el;
          }
        });
      });
      if (!again) {
        again = document.getElementById(side === 'source'
          ? 'mig-device-source-model' : 'mig-rename-target-model');
      }
      if (again && typeof again.focus === 'function') again.focus();
    }
  }

  /** Member numbers in words: " (1–6)" for a run, " (1, 3, 5)"
   *  otherwise, "" when none is numbered. */
  function _memberNumbersText(ids) {
    var known = ids.filter(function(id) { return typeof id === 'number'; });
    if (!known.length || known.length !== ids.length) return '';
    var run = known.every(function(id, i) { return i === 0 || id === known[i - 1] + 1; });
    if (run && known.length > 2) {
      return ' (' + known[0] + '–' + known[known.length - 1] + ')';
    }
    return ' (' + known.join(', ') + ')';
  }

  /** What a member is called in a label: by its number where it has
   *  one, as its port names do; by its place in the list where not. */
  function _memberWords(member, rank) {
    return (member.id !== null && member.id !== undefined)
      ? 'member ' + member.id : 'member in place ' + (rank + 1);
  }

  function _memberControls(side, decl, fam, member, rank, range) {
    var box = document.createElement('span');
    box.className = 'mig-device-member';
    var base = 'migrate-device-' + side + '-member-' + rank;
    box.setAttribute('data-testid', base);
    // Named by side and member, so that four "Module in bay A" on one
    // screen can be told apart without seeing where each one is.
    var named = _sideWords(side) + ', ' + _memberWords(member, rank);
    box.setAttribute('role', 'group');
    box.setAttribute('aria-label', named);
    // The member's number comes first on its line, then what it is.
    var modelSel = null;
    if (rank > 0) {
      modelSel = document.createElement('select');
      modelSel.setAttribute('data-testid', base + '-model');
      modelSel.setAttribute('aria-label', named + ': model');
      Object.keys(fam.models || {}).forEach(function(modelKey) {
        modelSel.appendChild(_option(
          modelKey, fam.models[modelKey].display_name || modelKey,
        ));
      });
      modelSel.value = member.model;
      modelSel.addEventListener('change', function() {
        member.model = modelSel.value;
        member.modules = {};
        deviceDeclChanged(side, true);
      });
    }
    if (range) {
      var idLabel = document.createElement('label');
      idLabel.textContent = 'member';
      var idInput = document.createElement('input');
      idInput.type = 'number';
      idInput.min = String(range[0]);
      idInput.max = String(range[1]);
      idInput.step = '1';
      idInput.value = (member.id === null || member.id === undefined)
        ? '' : String(member.id);
      idInput.setAttribute('data-testid', base + '-id');
      idInput.setAttribute('aria-label', _sideWords(side) + ', place '
        + (rank + 1) + ': stack member number');
      idInput.title = 'Stack member number (' + range[0] + '–' + range[1] + ')';
      idInput.addEventListener('change', function() {
        // What the field holds is what is sent.  The browser has no
        // rule for a member number: the server refuses 2.9 or 99 in
        // words, and picks a number for a field left blank -- which
        // is then written into the field (see _adoptMemberNumbers).
        var n = idInput.valueAsNumber;
        member.id = (idInput.value.trim() === '' || isNaN(n)) ? null : n;
        deviceDeclChanged(side, false);
      });
      idLabel.appendChild(idInput);
      box.appendChild(idLabel);
    }
    if (modelSel) box.appendChild(modelSel);
    var bays = ((fam.models || {})[member.model] || {}).bays || {};
    Object.keys(bays).forEach(function(bay) {
      var bayLabel = document.createElement('label');
      bayLabel.textContent = 'bay ' + bay;
      var baySel = document.createElement('select');
      baySel.setAttribute('data-testid', base + '-bay-' + bay);
      baySel.setAttribute('aria-label', named + ': module in bay ' + bay);
      baySel.appendChild(_option(_DEVICE_BAY_UNSTATED, '— not stated —'));
      baySel.appendChild(_option(_DEVICE_BAY_EMPTY, 'nothing fitted'));
      (bays[bay].accepts || []).forEach(function(sku) {
        var mod = (fam.modules || {})[sku] || {};
        baySel.appendChild(_option(
          sku, mod.description ? sku + ' — ' + mod.description : sku,
        ));
      });
      var fitted = (member.modules || {})[bay];
      baySel.value = (fitted === undefined) ? _DEVICE_BAY_UNSTATED
        : (fitted === null ? _DEVICE_BAY_EMPTY : fitted);
      baySel.addEventListener('change', function() {
        if (baySel.value === _DEVICE_BAY_UNSTATED) delete member.modules[bay];
        else if (baySel.value === _DEVICE_BAY_EMPTY) member.modules[bay] = null;
        else member.modules[bay] = baySel.value;
        deviceDeclChanged(side, false);
      });
      bayLabel.appendChild(baySel);
      box.appendChild(bayLabel);
    });
    if (rank > 0) {
      var removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'mig-device-remove';
      removeBtn.textContent = '×';
      removeBtn.title = 'Remove this stack member';
      removeBtn.setAttribute('aria-label', 'Remove ' + named);
      removeBtn.setAttribute('data-testid', base + '-remove');
      removeBtn.addEventListener('click', function() {
        decl.members.splice(rank, 1);
        // The button is gone with its member: the focus goes to the
        // member before it, or to "+ stack member".
        deviceDeclChanged(side, true,
          'migrate-device-' + side + '-member-' + (rank - 1) + '-remove');
      });
      box.appendChild(removeBtn);
    }
    return box;
  }

  /** A stack member is added as a copy of the first one, with the
   *  lowest member number not in use. */
  function addDeviceMember(side) {
    var decl = _deviceDecl[side];
    var fam = _declFamily(decl);
    var range = fam && _memberIdRange(fam, decl.mode);
    if (!range) return;
    var used = decl.members.map(function(m) { return m.id; });
    var id = range[0];
    while (used.indexOf(id) !== -1 && id <= range[1]) id += 1;
    if (id > range[1]) return;
    var first = decl.members[0];
    decl.members.push({
      model: first.model, id: id,
      modules: Object.assign({}, first.modules || {}),
    });
    // The operator is editing the list: it does not fold under them.
    _deviceMembersOpen[side] = true;
    deviceDeclChanged(side, true);
  }

  /** Called after any edit of a family declaration.  *rebuild* says
   *  the set of controls changed (a member added, a model swapped);
   *  *fallback* names the control to focus when the one that had the
   *  focus is gone. */
  function deviceDeclChanged(side, rebuild, fallback) {
    var decl = _deviceDecl[side];
    if (decl) decl.fromConfig = false;
    if (rebuild) {
      renderDeviceControls(side, fallback || 'migrate-device-' + side + '-add-member');
    }
    refreshDeviceInventory(side);
  }

  /** Put *decl* in *modeName*.  A mode in which a device stands alone
   *  has one member and no number; the others are set aside, not
   *  thrown away, and come back with a stacking mode. */
  function _setDeclMode(decl, fam, modeName) {
    decl.mode = modeName;
    var range = _memberIdRange(fam, modeName);
    if (!range) {
      if (decl.members.length > 1 || decl.members[0].id !== null) {
        decl.aside = {
          firstId: decl.members[0].id,
          rest: decl.members.slice(1),
        };
      }
      decl.members = [decl.members[0]];
      decl.members[0].id = null;
      return;
    }
    var aside = decl.aside;
    decl.aside = null;
    if (aside) {
      if (decl.members[0].id === null || decl.members[0].id === undefined) {
        decl.members[0].id = aside.firstId;
      }
      var room = range[1] - range[0] + 1;
      decl.members = decl.members.concat(aside.rest).slice(0, room);
    }
    // Every member has a number in this mode's range, each its own.
    var taken = {};
    decl.members.forEach(function(m) {
      var ok = typeof m.id === 'number' && m.id >= range[0] && m.id <= range[1]
        && !taken[m.id];
      if (!ok) m.id = null;
      else taken[m.id] = true;
    });
    decl.members.forEach(function(m) {
      if (m.id !== null) return;
      var id = range[0];
      while (taken[id] && id <= range[1]) id += 1;
      m.id = id;
      taken[id] = true;
    });
  }

  /** Give the first member of *decl* another model of the same family,
   *  keeping the stack: the other members, their numbers and modules
   *  are the operator's work.  A module stays where the new model has
   *  that bay and takes that module. */
  function _swapFirstModel(decl, fam, modelKey) {
    var first = decl.members[0];
    var bays = ((fam.models || {})[modelKey] || {}).bays || {};
    var kept = {};
    Object.keys(first.modules || {}).forEach(function(bay) {
      var sku = first.modules[bay];
      if (!bays[bay]) return;
      if (sku === null || (bays[bay].accepts || []).indexOf(sku) !== -1) kept[bay] = sku;
    });
    first.model = modelKey;
    first.modules = kept;
    if (_modeNames(fam, modelKey).indexOf(decl.mode) === -1) {
      _setDeclMode(decl, fam, _defaultMode(fam, modelKey));
    }
    decl.fromConfig = false;
  }

  /** The source select changed. */
  function deviceSourcePicked() {
    // The operator has chosen -- "(not declared)" included.  What the
    // config states is offered from here on, not applied.
    _deviceSourceTouched = true;
    var sel = document.getElementById('mig-device-source-model');
    var value = sel ? sel.value : '';
    var vendor = _codecVendor(_deviceCodec('source'));
    var fam = _parseFamilyValue(value);
    var current = _deviceDecl.source;
    if (fam && current && current.kind === 'family'
        && current.vendor === vendor && current.family === fam.family
        && _familyOf(vendor, fam.family)) {
      _swapFirstModel(current, _familyOf(vendor, fam.family), fam.model);
    } else if (fam) {
      _deviceDecl.source = _newFamilyDecl(vendor, fam.family, fam.model);
    } else if (value.indexOf(_DEVICE_PROFILE_PREFIX) === 0) {
      _deviceDecl.source = {
        kind: 'profile', vendor: vendor,
        profile: vendor + '/' + value.slice(_DEVICE_PROFILE_PREFIX.length),
        module: '',
      };
    } else {
      _deviceDecl.source = null;
    }
    renderDeviceControls('source');
    refreshDeviceInventory('source');
  }

  /** The target vendor, model or module select changed. */
  function deviceTargetPicked() {
    var vsel = document.getElementById('mig-rename-target-vendor');
    var msel = document.getElementById('mig-rename-target-model');
    var modsel = document.getElementById('mig-rename-target-module');
    var vendor = vsel ? vsel.value : '';
    var value = msel ? msel.value : '';
    // A pick is for the target codec of the job on the page: a
    // translation to another codec forgets it (resetDevicesForJob).
    _deviceTargetPick = {
      vendor: vendor, model: value,
      module: (modsel && modsel.style.display !== 'none') ? modsel.value : '',
    };
    var fam = _parseFamilyValue(value);
    var current = _deviceDecl.target;
    if (!fam) {
      _deviceDecl.target = null;
    } else if (current && current.vendor === vendor
               && current.family === fam.family
               && _familyOf(vendor, fam.family)) {
      if (current.members[0].model !== fam.model) {
        _swapFirstModel(current, _familyOf(vendor, fam.family), fam.model);
      }
    } else {
      _deviceDecl.target = _newFamilyDecl(vendor, fam.family, fam.model);
    }
    renderDeviceControls('target');
    refreshDeviceInventory('target');
  }

  /** Put the last target pick back after the model list was rebuilt
   *  (it is rebuilt every time the modal opens). */
  function restoreDeviceTargetPick() {
    var vsel = document.getElementById('mig-rename-target-vendor');
    var msel = document.getElementById('mig-rename-target-model');
    var modsel = document.getElementById('mig-rename-target-module');
    var pick = _deviceTargetPick;
    if (!pick || !vsel || !msel || !pick.model || vsel.value !== pick.vendor) {
      return;
    }
    msel.value = pick.model;
    if (msel.value !== pick.model) { msel.value = ''; return; }
    populateRenameModuleDropdown(pick.vendor, pick.model);
    if (pick.module && modsel && modsel.style.display !== 'none') {
      modsel.value = pick.module;
    }
  }

  /* ── compiling a declaration ── */

  /** Ask the server what *side*'s declaration compiles to.  A target
   *  profile needs no request: the profile already lists its ports.
   *  The request in flight is remembered, so Apply can wait for it. */
  function refreshDeviceInventory(side) {
    var run = _compileDevice(side);
    _deviceBusy[side] = run;
    return run;
  }

  /** Resolves once neither device is being compiled.  An edit made
   *  just before Apply (a member number typed, then the button
   *  clicked) starts a compile; the request has to be built from
   *  its verdict, not from the one it replaced.  An edit made while
   *  this waits starts another, and that one is waited for too. */
  async function devicesSettled() {
    for (;;) {
      var waiting = [_deviceBusy.source, _deviceBusy.target];
      await Promise.all(waiting.filter(Boolean)).catch(function() {
        /* a failed compile is recorded as an error */
      });
      if (waiting[0] === _deviceBusy.source && waiting[1] === _deviceBusy.target) {
        return;
      }
    }
  }

  /** A field left blank sends no member number, and the server picks
   *  one.  Write the number it picked into the declaration and the
   *  field, so that the screen says what was compiled. */
  function _adoptMemberNumbers(side, decl, inventory) {
    if (!decl || decl.kind !== 'family') return;
    if (!_memberIdRange(_declFamily(decl), decl.mode)) return;
    (inventory.members || []).forEach(function(m, rank) {
      var mine = decl.members[rank];
      if (!mine || (mine.id !== null && mine.id !== undefined)) return;
      if (typeof m.member_id !== 'number') return;
      mine.id = m.member_id;
      var input = null;
      var row = _deviceRow(side);
      if (row) {
        row.querySelectorAll('input[data-testid]').forEach(function(el) {
          if (el.getAttribute('data-testid')
              === 'migrate-device-' + side + '-member-' + rank + '-id') {
            input = el;
          }
        });
      }
      if (input) input.value = String(m.member_id);
    });
  }

  async function _compileDevice(side) {
    var decl = currentDeviceDecl(side);
    var seq = ++_deviceSeq[side];
    _deviceInventory[side] = null;
    _deviceError[side] = '';
    _deviceUnchecked[side] = false;
    if (!decl || (side === 'target' && decl.kind === 'profile')) {
      _deviceChecking[side] = false;
      _afterDeviceChange(side);
      return;
    }
    // Until the answer is in, the screen says it is waiting for one:
    // the note and the strip do not go on describing the last device.
    _deviceChecking[side] = true;
    renderDeviceNote(side);
    renderPortPlan();
    var request = { codec: _deviceCodec(side) };
    if (decl.kind === 'family') {
      request.deployment = _deploymentSpec(decl);
    } else {
      request.profile = decl.profile;
      if (decl.module) request.module = decl.module;
    }
    var abort = (typeof AbortController === 'function') ? new AbortController() : null;
    var timer = abort ? setTimeout(function() { abort.abort(); },
                                   _DEVICE_COMPILE_TIMEOUT_MS) : null;
    var verdict = { inventory: null, error: '', unchecked: false };
    try {
      var options = {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      };
      if (abort) options.signal = abort.signal;
      var resp = await fetch('/api/v1/migration/inventory', options);
      var data = await resp.json().catch(function() { return null; });
      if (resp.ok && data && Array.isArray(data.ports)) {
        verdict.inventory = data;
      } else if (resp.status === 422 || resp.status === 400) {
        // The server read the declaration and refused it.
        verdict.error = formatApiError(data || {}, resp.statusText);
      } else {
        // No verdict: a failure of the request, not of the device.
        verdict.error = resp.ok
          ? 'The server’s answer could not be read.'
          : 'The server answered ' + resp.status
            + (resp.statusText ? ' ' + resp.statusText : '') + '.';
        verdict.unchecked = true;
      }
    } catch (e) {
      verdict.error = (e && e.name === 'AbortError')
        ? 'No answer from the server in '
          + Math.round(_DEVICE_COMPILE_TIMEOUT_MS / 1000) + ' seconds.'
        : 'Could not reach the server (' + e.message + ').';
      verdict.unchecked = true;
    }
    if (timer) clearTimeout(timer);
    if (seq !== _deviceSeq[side]) return;
    _deviceChecking[side] = false;
    _deviceInventory[side] = verdict.inventory;
    _deviceError[side] = verdict.error;
    _deviceUnchecked[side] = verdict.unchecked;
    if (verdict.inventory) _adoptMemberNumbers(side, decl, verdict.inventory);
    _afterDeviceChange(side);
  }

  function _afterDeviceChange(side) {
    renderDeviceNote(side);
    renderPortPlan();
    // A preview answers when it answers -- possibly while a row of the
    // table is being pressed.  The table is redrawn when that cannot
    // take the row away (rebuildRenameTableSoon, rename-table.js).
    rebuildRenameTableSoon();
  }

  /* ── reading the source device from the config ── */

  /** What tells one source text from another: the whole text.  A
   *  length and the first lines do not -- a member number or a part
   *  number corrected in place changes neither.  A stored config is
   *  told apart by its file name, which carries the time it was
   *  collected. */
  function _sourceTextKey(body) {
    if (!body) return '';
    if (typeof body.raw_text === 'string') {
      return (body.source || '') + '\n\ntext\n\n' + body.raw_text;
    }
    return (body.source || '') + '\n\nfile\n\n' + (body.source_filename || '');
  }

  /** A new translation: a different source text starts with no source
   *  device, a different target codec with no target device.  A
   *  preview or a detection still in flight for the old job is
   *  disowned, so its answer is not drawn for the new one. */
  function resetDevicesForJob(body) {
    var key = _sourceTextKey(body);
    if (key !== _deviceSourceKey) {
      _deviceSourceKey = key;
      _deviceSeq.source += 1;
      _deviceChecking.source = false;
      _deviceDecl.source = null;
      _deviceInventory.source = null;
      _deviceError.source = '';
      _deviceUnchecked.source = false;
      _deviceProposal = null;
      _deviceProposalFor = '';
      _deviceDetecting = '';
      _deviceDetectError = '';
      _deviceMembersOpen.source = false;
      _deviceSourceTouched = false;
    }
    var targetCodec = (body && body.target) || '';
    if (targetCodec !== _deviceTargetCodec) {
      // A pick is put back when the modal opens.  One made for another
      // target codec -- a family model or a flat profile -- is not
      // this job's, and neither is the vendor it was made under.
      _deviceTargetCodec = targetCodec;
      _deviceSeq.target += 1;
      _deviceChecking.target = false;
      _deviceDecl.target = null;
      _deviceInventory.target = null;
      _deviceError.target = '';
      _deviceUnchecked.target = false;
      _deviceTargetPick = null;
      _deviceMembersOpen.target = false;
      var vsel = document.getElementById('mig-rename-target-vendor');
      if (vsel) vsel.value = '';
      if (typeof populateRenameModelDropdown === 'function') {
        populateRenameModelDropdown('');
      }
    }
  }

  /** Ask the server what the config says about its own hardware --
   *  once per source text -- and pre-fill the source picker with it
   *  unless the operator has already chosen.  A request that fails is
   *  said, and asked again the next time the modal opens. */
  async function detectSourceDevice() {
    if (!_lastJobBody) return;
    var key = _sourceTextKey(_lastJobBody);
    if (_deviceProposalFor === key || _deviceDetecting === key) return;
    _deviceDetecting = key;
    _deviceProposal = null;
    _deviceDetectError = '';
    var request = { source: _lastJobBody.source };
    if (typeof _lastJobBody.raw_text === 'string') {
      request.raw_text = _lastJobBody.raw_text;
    } else {
      request.source_filename = _lastJobBody.source_filename;
    }
    var proposal = null;
    var failed = '';
    try {
      var resp = await fetch('/api/v1/migration/detect-deployment', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      });
      if (!resp.ok) {
        failed = 'the server answered ' + resp.status
          + (resp.statusText ? ' ' + resp.statusText : '');
      } else {
        proposal = await resp.json();
        if (!proposal || typeof proposal !== 'object') {
          proposal = null;
          failed = 'the server’s answer could not be read';
        }
      }
    } catch (e) {
      failed = (e && e.message) ? e.message : 'no answer';
    }
    // Another text is on the page by now: this answer is not for it.
    if (_deviceDetecting !== key) return;
    _deviceDetecting = '';
    if (!proposal) {
      _deviceDetectError = failed;
      renderDeviceNote('source');
      return;
    }
    _deviceProposal = proposal;
    _deviceProposalFor = key;
    if (!_deviceDecl.source && !_deviceSourceTouched
        && useDetectedSourceDevice()) {
      return;
    }
    renderDeviceNote('source');
  }

  /** The members of a proposal as a declaration would hold them, or
   *  null when a model family does not describe every one of them. */
  function _proposalMembers(p) {
    if (!p || !p.deployment || !p.family) return null;
    var familyKey = String(p.family).split('/').slice(1).join('/');
    var fam = _familyOf(p.vendor, familyKey);
    var stated = p.deployment.members || [];
    var members = stated.filter(function(m) {
      return fam && (fam.models || {})[m.model];
    });
    if (!fam || !members.length || members.length !== stated.length) return null;
    return { familyKey: familyKey, fam: fam, members: members };
  }

  /** Declare the source as the config states it.  False when the
   *  config states nothing a model family describes. */
  function useDetectedSourceDevice() {
    var p = _deviceProposal;
    var found = _proposalMembers(p);
    if (!found) return false;
    _deviceDecl.source = {
      kind: 'family', vendor: p.vendor, family: found.familyKey,
      mode: p.deployment.mode || _defaultMode(found.fam, found.members[0].model),
      members: found.members.map(function(m) {
        return {
          model: m.model,
          id: (m.id === null || m.id === undefined) ? null : m.id,
          modules: Object.assign({}, m.modules || {}),
        };
      }),
      fromConfig: true, aside: null,
    };
    _deviceMembersOpen.source = false;
    populateDeviceSourceModels();
    renderDeviceControls('source');
    refreshDeviceInventory('source');
    return true;
  }

  /* ── the note under each device ── */

  function _notePart(el, testid, text, extraClass) {
    var span = document.createElement('span');
    span.className = 'mig-device-note-part' + (extraClass ? ' ' + extraClass : '');
    span.setAttribute('data-testid', testid);
    span.textContent = text;
    el.appendChild(span);
    return span;
  }

  function _noteList(el, testid, summaryText, lines, asCode) {
    if (!lines.length) return;
    var details = document.createElement('details');
    details.className = 'mig-device-note-list';
    details.setAttribute('data-testid', testid);
    var summary = document.createElement('summary');
    summary.setAttribute('data-testid', testid + '-summary');
    summary.textContent = summaryText;
    details.appendChild(summary);
    var list = document.createElement('ul');
    lines.forEach(function(line) {
      var item = document.createElement('li');
      if (asCode) {
        var code = document.createElement('code');
        code.textContent = line;
        item.appendChild(code);
      } else {
        item.textContent = line;
      }
      list.appendChild(item);
    });
    details.appendChild(list);
    el.appendChild(details);
  }

  /** The device in one line.  A stack is said by runs of like
   *  members -- "6 × <model> + <module> as members 1–6" -- and not
   *  once per member, which for ten members is ten times the same
   *  words.  One device is said as the server says it. */
  function _describeInventory(inv) {
    var members = inv.members || [];
    if (members.length < 2) return inv.description || '';
    var runs = [];
    members.forEach(function(m) {
      var modules = Object.keys(m.modules || {}).map(function(bay) {
        return m.modules[bay];
      });
      var what = (m.display_name || m.model || '')
        + (modules.length ? ' + ' + modules.join(' + ') : '');
      var last = runs[runs.length - 1];
      if (last && last.what === what) last.ids.push(m.member_id);
      else runs.push({ what: what, ids: [m.member_id] });
    });
    var parts = runs.map(function(run) {
      var numbers = _memberNumbersText(run.ids);
      return (run.ids.length > 1 ? run.ids.length + ' × ' : '') + run.what
        + (numbers
          ? ' as member' + (run.ids.length > 1 ? 's' : '') + numbers.replace(/[()]/g, '')
          : '');
    });
    return parts.join('; ') + (inv.mode_label ? ' — ' + inv.mode_label : '');
  }

  /** What a declaration resolved to: the device in words, its port
   *  count and first and last port, how well the names are known,
   *  every caveat -- and, for the source, the config lines it was read
   *  from.  Amber when the names are in doubt, the config disagrees
   *  with the device, or the device could not be checked; red when
   *  the server refused the declaration. */
  function renderDeviceNote(side) {
    var el = document.getElementById('mig-device-' + side + '-note');
    if (!el) return;
    el.textContent = '';
    el.className = 'mig-device-note';
    el.removeAttribute('data-evidence');
    el.removeAttribute('data-state');
    var portsPane = document.getElementById('mig-rename-ports-pane');
    var portsActive = !portsPane || portsPane.classList.contains('active');
    var decl = currentDeviceDecl(side);
    var inv = _deviceInventory[side];
    var error = _deviceError[side];
    var proposal = (side === 'source') ? _deviceProposal : null;
    var base = 'migrate-device-' + side + '-note';
    var who = (side === 'source') ? 'Source' : 'Target';
    var warn = false;

    if (_deviceChecking[side]) {
      _notePart(el, base + '-checking', who + ' device: checking …');
      el.setAttribute('data-state', 'checking');
    } else if (error && _deviceUnchecked[side]) {
      // Not a verdict on the device: the preview did not arrive.
      _notePart(el, base + '-unchecked', who + ' device could not be checked here: '
        + error + ' Apply sends it as declared, and the server decides.');
      el.setAttribute('data-state', 'unchecked');
      warn = true;
    } else if (error) {
      _notePart(el, base + '-error', who + ' device: ' + error);
      el.classList.add('notice-block');
      el.setAttribute('data-state', 'invalid');
    } else if (inv) {
      _notePart(el, base + '-device', who + ': ' + _describeInventory(inv),
                'mig-device-note-device');
      var names = (inv.ports || []).map(function(p) { return p.name; });
      var count = names.length || inv.port_count || 0;
      _notePart(el, base + '-ports', count + ' port' + (count === 1 ? '' : 's')
        + (names.length ? ': ' + names[0]
            + (names.length > 1 ? ' … ' + names[names.length - 1] : '') : ''));
      var grade = inv.evidence || '';
      _notePart(el, base + '-evidence',
        _DEVICE_EVIDENCE_LABEL[grade] || _DEVICE_UNGRADED_LABEL,
        'mig-device-note-grade');
      el.setAttribute('data-evidence', grade || 'ungraded');
      if (grade === 'inferred') warn = true;
      if (inv.origin === 'legacy-profile') {
        _notePart(el, base + '-order',
          'Port order is the profile’s list order, not checked against the faceplate');
      }
      // Said by bay, with the members that have it unstated: ten
      // members with one unstated bay each are one phrase, not ten.
      // A member is named by its NUMBER, as its port names are.
      var unstatedIn = {};
      (inv.members || []).forEach(function(m) {
        (m.unstated_bays || []).forEach(function(bay) {
          var numbered = m.member_id !== null && m.member_id !== undefined;
          (unstatedIn[bay] = unstatedIn[bay] || []).push(
            numbered ? m.member_id : (m.rank + 1));
        });
      });
      var unstated = Object.keys(unstatedIn).map(function(bay) {
        var of = unstatedIn[bay];
        if ((inv.members || []).length < 2) return 'bay ' + bay;
        return 'bay ' + bay + ' of member' + (of.length > 1 ? 's' : '')
          + _memberNumbersText(of).replace(/[()]/g, '');
      });
      if (unstated.length) {
        _notePart(el, base + '-unstated',
          'Not stated, counted as empty: ' + unstated.join(', '));
        warn = true;
      }
      _noteList(el, base + '-caveats',
        (inv.caveats || []).length + ' note'
          + ((inv.caveats || []).length === 1 ? '' : 's') + ' on this device',
        inv.caveats || [], false);
    }

    if (side === 'source' && !_deviceChecking.source) {
      var readFromConfig = !!(proposal && decl && decl.fromConfig);
      if (readFromConfig) {
        _noteList(el, base + '-read-from',
          'Read from the config (' + (proposal.evidence || []).length + ' line'
            + ((proposal.evidence || []).length === 1 ? '' : 's') + ')',
          proposal.evidence || [], true);
        if (proposal.consistent === false) {
          // The list is capped by the server; the count is not.
          var missing = proposal.missing_ports || [];
          var howMany = proposal.missing_port_count || missing.length;
          _notePart(el, base + '-inconsistent',
            howMany + ' port name' + (howMany === 1 ? '' : 's')
            + ' the config uses ' + (howMany === 1 ? 'is' : 'are')
            + ' not on this device: ' + missing.slice(0, 8).join(', ')
            + (howMany > 8 ? ' …' : ''));
          warn = true;
        } else if (proposal.consistent !== true) {
          // null: nothing was checked (the text names no port, or
          // could not be parsed).  The note below says which; it is
          // not a pass, so it is not shown as one.
          warn = true;
        }
        (proposal.notes || []).forEach(function(note, i) {
          _notePart(el, base + '-detect-note-' + i, note);
        });
      } else {
        // Chosen or edited by hand, or not declared at all.
        if (decl && inv) {
          // Only a device read from the config was checked against
          // the port names the config uses; saying nothing here would
          // read as a check that passed.
          _notePart(el, base + '-not-checked',
            'Not checked against the port names the config uses — Apply '
            + 'lists any the device does not have');
        }
        if (proposal && proposal.deployment) {
          // The config states a device.  Say which, and offer it --
          // unless the page cannot declare it: the model families did
          // not load, or do not hold its model.
          var said = (proposal.members || []).map(function(m) {
            return m.part;
          }).join(' + ');
          _notePart(el, base + '-config-says', 'The config states: ' + said);
          if (_proposalMembers(proposal)) {
            var use = document.createElement('button');
            use.type = 'button';
            use.className = 'mig-device-use-detected';
            use.textContent = 'use it';
            use.setAttribute('data-testid', 'migrate-device-source-use-detected');
            use.addEventListener('click', function() {
              if (useDetectedSourceDevice()) {
                var model = document.getElementById('mig-device-source-model');
                if (model) model.focus();
              }
            });
            el.appendChild(use);
          } else {
            _notePart(el, base + '-families-missing', _modelFamiliesFailed
              ? 'The model families could not be loaded, so it cannot be '
                + 'declared here — close and reopen this window to try again'
              : 'No model family loaded here describes it — choose the device yourself');
            warn = true;
          }
        } else if (decl) {
          if (proposal && proposal.stated && (proposal.unknown_parts || []).length) {
            _notePart(el, base + '-unknown-parts',
              'The config states ' + proposal.unknown_parts.join(', ')
              + ', which no model family describes yet');
          }
        } else if (!_sourceModelsKnown()) {
          // Nothing to choose from: do not tell the operator to choose.
          _notePart(el, base + '-no-models',
            'No device model is known for this source vendor yet; its '
            + 'ports are translated by the shape of their names');
        } else if (_deviceDetectError) {
          _notePart(el, base + '-detect-failed',
            'Could not read the device from the config (' + _deviceDetectError
            + ') — declare it yourself, or close and reopen this window to try again');
          warn = true;
        } else if (proposal && (proposal.notes || []).length) {
          // Nothing was proposed.  The server puts the reason first;
          // what its detector said about the lines it read follows.
          proposal.notes.forEach(function(note, i) {
            _notePart(el, base + '-detect-note-' + i, note);
          });
        } else if (proposal && proposal.stated
                   && (proposal.unknown_parts || []).length) {
          _notePart(el, base + '-unknown-parts',
            'The config states ' + proposal.unknown_parts.join(', ')
            + ', which no model family describes yet — choose the device yourself');
        }
      }
    }

    if (warn && !el.classList.contains('notice-block')) {
      el.classList.add('notice-warn');
    }
    el.style.display = (portsActive && el.childNodes.length) ? '' : 'none';
  }

  /* ── the port plan ── */

  /** The plan the job on screen was made with, or null. */
  function currentPortPlan() {
    var plan = _lastJob && _lastJob.port_mapping_plan;
    return (plan && typeof plan === 'object') ? plan : null;
  }

  var _PLAN_ROLE_KIND = { access: 'physical', uplink: 'physical', mgmt: 'mgmt' };

  /** Where every source name ended, read from the job and not from
   *  the pairing: the plan's pairings are the mapping AS MADE, before
   *  the operator's own entries.  Returns a function: source name ->
   *  null when it was dropped, else the target port its hardware is
   *  on (RouterOS can keep a name on other hardware), else the name it
   *  has in the output. */
  function _planOutcomes(plan) {
    var drops = new Set((_lastJob && _lastJob.port_drops) || []);
    var renames = (_lastJob && _lastJob.port_renames) || {};
    var hardware = plan.target_hardware || {};
    return function(source) {
      if (drops.has(source)) return null;
      var at = Object.prototype.hasOwnProperty.call(hardware, source)
        ? hardware[source] : '';
      if (typeof at === 'string' && at) return at;
      var to = Object.prototype.hasOwnProperty.call(renames, source)
        ? renames[source] : '';
      return (typeof to === 'string' && to) ? to : source;
    };
  }

  /** Source names the operator's own map decided in the job on
   *  screen: the entries that were sent with it, and those the plan
   *  says replaced one of its own. */
  function _planDecided(plan) {
    var names = new Set(plan.overridden || []);
    var sent = (_lastJobBody && _lastJobBody.port_rename_map) || {};
    Object.keys(sent).forEach(function(name) { names.add(name); });
    return names;
  }

  /** A function: does this used pairing stand as the plan made it?
   *  It does unless the operator's own entry decided the port and it
   *  ended somewhere else (or nowhere). */
  function _planStanding(plan) {
    var decided = _planDecided(plan);
    var ended = _planOutcomes(plan);
    return function(p) {
      return !decided.has(p.source) || ended(p.source) === p.target;
    };
  }

  /** Per source name: what the plan did with it, for the rename table.
   *
   *    state   paired | unplaced | off-inventory | displaced | follows
   *            | landed-off-target
   *    role    access | uplink | mgmt (a port of the declared source)
   *    kind    the table section the row belongs in, when known
   *    auto    the target the plan chose ('' when it chose none)
   *    text    what to show in place of a target when there is none
   *    why     the position that decided the pairing
   *    flags   [{text, level}] -- level is info | warn | block
   *    order   position in the source inventory, for sorting          */
  function portPlanRowMeta(plan) {
    // Keyed by interface names: no prototype, so that no name finds
    // anything inherited.
    var meta = Object.create(null);
    if (!plan || !plan.applied) return meta;
    var renames = (_lastJob && _lastJob.port_renames) || {};
    var dropped = new Set((_lastJob && _lastJob.port_drops) || []);
    var ended = _planOutcomes(plan);
    var stands = _planStanding(plan);
    var sourceMembers = (plan.source && plan.source.members) || [];
    var targetMembers = (plan.target && plan.target.members) || [];
    var stacked = sourceMembers.length > 1;
    var undecided = new Set(plan.unresolved_ports || []);
    var labelled = plan.labelled_ports || {};
    var hardware = plan.target_hardware || {};
    var sourceHardware = plan.source_hardware || {};
    var unbound = plan.unbound_ports || {};
    var landed = plan.landed_off_target || {};
    var order = 0;
    function own(map, name) {
      return Object.prototype.hasOwnProperty.call(map, name) ? map[name] : undefined;
    }
    function flag(text, level) { return { text: text, level: level }; }
    // RouterOS finds a port by its factory name.  What the plan says
    // about that, for a row: the port of the model the config's own
    // name stands for; where the port's hardware is when the name in
    // the output is not it; and whether any line of the output finds
    // the port at all.  Only the last holds the job.
    function hardwareFlags(name) {
      var flags = [];
      if (own(labelled, name)) {
        flags.push(flag(own(labelled, name) + ' in the device model', 'info'));
      }
      if (own(hardware, name)) {
        flags.push(flag('a name, not a place — the port is on '
          + own(hardware, name), 'info'));
      }
      if (own(sourceHardware, name)) {
        flags.push(flag('still looked up as ' + own(sourceHardware, name)
          + ', which the target does not have', 'warn'));
      }
      if (own(unbound, name)) {
        flags.push(flag('no line of the output finds this port ('
          + own(unbound, name) + ') — give it another name', 'block'));
      }
      return flags;
    }
    // Stack members pair in the order they are listed, so a member's
    // place and its number are two things.  A row names its member by
    // NUMBER, as the port's own name does, and says where that member
    // went when it is a member of another number, or no member at all
    // -- unless the operator's own entry sent this port elsewhere.
    function memberOf(rank, withArrow) {
      var from = sourceMembers[rank];
      var number = (from && from.member_id !== null && from.member_id !== undefined)
        ? from.member_id : rank + 1;
      var to = targetMembers[rank];
      if (!withArrow) return ' · member ' + number;
      if (!to) return ' · member ' + number + ' → no member';
      if (to.member_id !== null && to.member_id !== undefined
          && to.member_id !== number) {
        return ' · member ' + number + ' → member ' + to.member_id;
      }
      return ' · member ' + number;
    }
    function where(rank, role, position, withArrow) {
      return role + ' ' + (position + 1)
        + (stacked && rank !== null && rank !== undefined
          ? memberOf(rank, withArrow) : '');
    }
    (plan.pairings || []).forEach(function(p) {
      order += 1;
      if (!p.used) return;
      var standing = stands(p);
      var flags = [];
      if (standing) {
        // The flags describe the target port of the pairing; they are
        // said only for a port that is on it.
        if (p.slower) {
          flags.push(flag('slower: ' + (p.source_speed || '?') + ' → '
            + (p.target_speed || '?'), 'warn'));
        }
        if (p.poe_lost) flags.push(flag('no PoE on the target port', 'warn'));
      } else {
        var at = ended(p.source);
        flags.push(at === null
          ? flag('dropped by your own entry', 'warn')
          : flag('sent to ' + at + ' by your own entry', 'info'));
      }
      flags = flags.concat(hardwareFlags(p.source));
      meta[p.source] = {
        state: 'paired', role: p.role, kind: _PLAN_ROLE_KIND[p.role],
        auto: p.target, text: '',
        why: where(p.member_rank, p.role, p.position, standing), flags: flags,
        order: order,
      };
    });
    (plan.unplaced || []).forEach(function(p) {
      order += 1;
      if (!p.used) return;
      var text = '';
      var auto = '';
      if (!p.dropped && undecided.has(p.source)) {
        // Kept by the ordinary translation, which knows what the
        // target vendor does with a management port -- but not
        // whether THIS target device has one.
        text = 'kept as ' + (p.landed || p.source)
          + ' — confirm the target has a management port';
      } else if (!p.dropped) {
        // The operator gave it a place: where it landed is its target.
        auto = p.landed || '';
      } else if (p.reason === 'no-member') {
        text = 'the target has no stack member in this position — dropped';
      } else {
        text = 'no ' + p.role + ' port left on the target — dropped';
      }
      meta[p.source] = {
        state: 'unplaced', role: p.role, kind: _PLAN_ROLE_KIND[p.role],
        auto: auto, text: text,
        why: where(p.member_rank, p.role, p.position, true),
        flags: hardwareFlags(p.source),
        order: order,
      };
    });
    (plan.off_inventory || []).forEach(function(name) {
      order += 1;
      var to = own(renames, name);
      var outcome = dropped.has(name) ? 'dropped'
        : ((typeof to === 'string' && to && to !== name)
            ? 'translated by name to ' + to : 'left as it is');
      meta[name] = {
        state: 'off-inventory', role: '', kind: '', auto: '',
        text: 'not a port of the declared source device — ' + outcome,
        why: '', flags: [], order: order,
      };
    });
    Object.keys(plan.sub_interfaces || {}).forEach(function(name) {
      order += 1;
      var target = plan.sub_interfaces[name];
      meta[name] = {
        state: 'follows', role: '', kind: '', auto: target || '',
        text: target ? '' : 'dropped with the port it belongs to',
        why: 'follows its port', flags: [], order: order,
      };
    });
    (plan.displaced || []).forEach(function(name) {
      order += 1;
      meta[name] = {
        state: 'displaced', role: (meta[name] || {}).role || '',
        kind: (meta[name] || {}).kind || '', auto: '',
        text: 'dropped — by name it would have taken a name another '
          + 'interface holds',
        why: (meta[name] || {}).why || '', flags: [], order: order,
      };
    });
    // A logical name the ordinary translation gave a port-shaped name
    // the target device does not have.  Nothing shares the name, so it
    // was kept -- on a port that is not there.
    Object.keys(landed).forEach(function(name) {
      order += 1;
      meta[name] = {
        state: 'landed-off-target', role: '', kind: '', auto: '',
        text: 'given the port name ' + landed[name]
          + ', which the target device does not have',
        why: '', flags: [], order: order,
      };
    });
    return meta;
  }

  /** Names the plan could not settle and the operator has not decided
   *  in this modal either. */
  function pendingPlanDecisions(plan) {
    if (!plan || !plan.applied) return [];
    return (plan.unresolved_ports || []).filter(function(name) {
      return _renameUserMap[name] === undefined;
    });
  }

  /** True when the operator's map is not the one the job on screen
   *  was made with: entries added, changed or cleared since. */
  function renameMapUnsent() {
    var sent = (_lastJobBody && _lastJobBody.port_rename_map) || {};
    var mine = Object.keys(_renameUserMap);
    if (mine.length !== Object.keys(sent).length) return true;
    return mine.some(function(name) {
      return !Object.prototype.hasOwnProperty.call(sent, name)
        || sent[name] !== _renameUserMap[name];
    });
  }

  /** Record, for every name still undecided, the outcome on screen as
   *  the operator's decision: a name that was dropped stays dropped,
   *  one that was kept stays where it landed.  Apply confirms it.
   *
   *  What is recorded is a verdict on THIS pairing.  It is kept apart
   *  (``_planAccepted``) so that it is forgotten when the devices are
   *  no longer the ones it was shown for, and is not remembered
   *  across a page reload -- see forgetAcceptedDecisions. */
  function acceptPortPlanAsShown() {
    var plan = currentPortPlan();
    var names = pendingPlanDecisions(plan);
    if (!names.length) return;
    var renames = (_lastJob && _lastJob.port_renames) || {};
    var dropped = new Set((_lastJob && _lastJob.port_drops) || []);
    names.forEach(function(name) {
      var to = Object.prototype.hasOwnProperty.call(renames, name) ? renames[name] : '';
      var value = dropped.has(name) ? null
        : ((typeof to === 'string' && to) ? to : name);
      _renameUserMap[name] = value;
      _planAccepted[name] = value;
    });
    renderRenameTable();
    renderRenamePreview();
    renderRenameSummary();
    setRenameStatus(names.length + ' decision'
      + (names.length === 1 ? '' : 's') + ' recorded — Apply to confirm.');
    // The button is gone with the strip that was redrawn; what comes
    // next is Apply.
    var applyBtn = document.getElementById('mig-rename-apply-btn');
    if (applyBtn && !applyBtn.disabled) applyBtn.focus();
  }

  /** Decisions "Accept as shown" recorded are a verdict on one
   *  pairing.  Forget them -- unless a row was changed by hand since,
   *  which makes it the operator's own.  Called by Apply when the
   *  devices are no longer those of the plan on screen. */
  function forgetAcceptedDecisions() {
    var forgot = 0;
    Object.keys(_planAccepted).forEach(function(name) {
      if (_renameUserMap[name] === _planAccepted[name]) {
        delete _renameUserMap[name];
        forgot += 1;
      }
    });
    _planAccepted = Object.create(null);
    return forgot;
  }

  /** Members the pairing put on a member of another NUMBER, in two
   *  lists, as the plan's own two lines have them: a RENUMBERING,
   *  where neither number is declared on the other side (1, 3 onto
   *  1, 2), and a CROSSING, where one is -- the same members listed
   *  in another order, every port of each on another switch.  Only a
   *  member the config uses is named: a used port of it stands on the
   *  member it was paired with, or lost its place there, and the
   *  operator did not decide that port themselves. */
  function renumberedMembers(plan) {
    var ours = (plan.source && plan.source.members) || [];
    var theirs = (plan.target && plan.target.members) || [];
    function numbers(members) {
      var seen = {};
      members.forEach(function(m) {
        if (m.member_id !== null && m.member_id !== undefined) seen[m.member_id] = true;
      });
      return seen;
    }
    var onSource = numbers(ours);
    var onTarget = numbers(theirs);
    var stands = _planStanding(plan);
    var decided = _planDecided(plan);
    var used = {};
    (plan.pairings || []).forEach(function(p) {
      if (p.used && stands(p)) used[p.member_rank] = true;
    });
    (plan.unplaced || []).forEach(function(p) {
      if (p.used && !decided.has(p.source)) used[p.member_rank] = true;
    });
    var out = { renumbered: [], crossed: [] };
    ours.forEach(function(m) {
      var to = theirs[m.rank];
      if (!used[m.rank] || !to
          || m.member_id === null || m.member_id === undefined
          || to.member_id === null || to.member_id === undefined
          || to.member_id === m.member_id) {
        return;
      }
      var pair = 'member ' + m.member_id + ' → member ' + to.member_id;
      var both = onTarget[m.member_id] || onSource[to.member_id];
      (both ? out.crossed : out.renumbered).push(pair);
    });
    return out;
  }

  function _planChip(el, testid, text, extraClass) {
    var chip = document.createElement('span');
    chip.className = 'mig-plan-chip' + (extraClass ? ' ' + extraClass : '');
    chip.setAttribute('data-testid', testid);
    chip.textContent = text;
    el.appendChild(chip);
  }

  function _plural(count, one, many) {
    return count + ' ' + (count === 1 ? one : many);
  }

  /** The strip that says where the port mapping stands: what to do
   *  next while there is no plan, and what the plan did once there is
   *  one.  Every count is of what HAPPENED in the job on screen --
   *  read from where each name ended, not from the pairing as it was
   *  made -- and the colour is the job's: amber while a name needs a
   *  decision the server has not been sent, whatever is recorded in
   *  the modal meanwhile. */
  function renderPortPlan() {
    var el = document.getElementById('mig-rename-plan');
    if (!el) return;
    el.textContent = '';
    el.className = '';
    el.removeAttribute('data-state');
    el.removeAttribute('data-stale');
    var portsPane = document.getElementById('mig-rename-ports-pane');
    if (portsPane && !portsPane.classList.contains('active')) {
      el.style.display = 'none';
      return;
    }
    var plan = currentPortPlan();
    var problem = _devicePairProblem();
    var changed = !!plan && _devicePlanKey !== _devicesKey();

    function say(testid, text) {
      var span = document.createElement('span');
      span.setAttribute('data-testid', testid);
      span.textContent = text;
      el.appendChild(span);
    }

    if (!plan || changed) {
      if (problem === 'none' && !plan) { el.style.display = 'none'; return; }
      // With a plan on screen, the table below is still that plan's.
      var lead = plan
        ? 'The table below is still the mapping made with the devices as they were. '
        : '';
      var hint = '';
      var state = 'incomplete';
      var look = 'plan-info';
      var preview = problem ? '' : _devicePreviewState();
      var held = (!problem && typeof applyHeldBy === 'function') ? applyHeldBy() : '';
      if (problem === 'none') {
        hint = 'The devices were cleared — Apply to go back to translating '
          + 'port names by their shape.';
        state = 'cleared';
      } else if (problem === 'no-source') {
        hint = 'Choose the source device as well to pair ports by position. '
          + 'Until then the target’s port list only fills the choices below.';
      } else if (problem === 'no-source-models') {
        hint = 'No device model is known for the source vendor yet, so ports '
          + 'cannot be paired by position. The target’s port list only fills '
          + 'the choices below.';
      } else if (problem === 'no-target') {
        hint = 'Choose the target device to pair ports by position.';
      } else if (problem === 'target-vendor') {
        hint = 'The target device is not of the target codec’s vendor, so '
          + 'ports are not paired by position.';
      } else if (preview === 'checking') {
        hint = 'Checking the device …';
        state = 'checking';
      } else if (preview === 'invalid') {
        hint = 'A device declaration is not valid — see the note above. '
          + 'Apply sends it as it stands, and the server will refuse it.';
        state = 'invalid';
        look = 'plan-block';
      } else if (preview === 'unchecked') {
        hint = 'A device could not be checked here — see the note above. '
          + 'Apply sends both devices, and the server decides.';
        state = 'unchecked';
        look = 'plan-warn';
      } else if (held) {
        hint = 'Both devices are declared, but ' + held
          + '. Change one of them, then Apply.';
        state = 'held';
        look = 'plan-warn';
      } else {
        hint = changed
          ? 'The devices changed since this mapping was made — Apply to pair again.'
          : 'Both devices are declared — Apply to pair their ports by position.';
        state = 'ready';
      }
      // Two facts.  ``data-state`` is what the next Apply will do with
      // the devices as they are declared now; ``data-stale`` is that
      // the table below was made with other devices.
      say('migrate-rename-plan-hint',
        (plan && state !== 'cleared' && state !== 'ready') ? lead + hint : hint);
      el.className = look;
      el.setAttribute('data-state', state);
      if (plan) el.setAttribute('data-stale', 'true');
      el.style.display = '';
      return;
    }

    if (!plan.applied) {
      var reason = ((plan.warnings || [])[0] || '').replace(/^port mapping: /, '');
      say('migrate-rename-plan-unapplied',
        'Ports were NOT paired by position'
        + (reason ? ': ' + reason : '; every name was translated by its shape.'));
      el.className = 'plan-block';
      el.setAttribute('data-state', 'unapplied');
      el.style.display = '';
      return;
    }

    // What happened, from the job.
    var stands = _planStanding(plan);
    var jobDrops = new Set((_lastJob && _lastJob.port_drops) || []);
    var unresolved = plan.unresolved_ports || [];
    var unresolvedSet = new Set(unresolved);
    var usedPairs = (plan.pairings || []).filter(function(p) { return p.used; });
    var standing = usedPairs.filter(stands);
    var paired = standing.length;
    var yourDrops = usedPairs.filter(function(p) {
      return !stands(p) && jobDrops.has(p.source);
    }).length;
    var yourMoves = usedPairs.length - paired - yourDrops;
    var usedUnplaced = (plan.unplaced || []).filter(function(p) { return p.used; });
    var unplaced = usedUnplaced.filter(function(p) { return p.dropped; }).length;
    var yourPlaces = usedUnplaced.filter(function(p) {
      return !p.dropped && !unresolvedSet.has(p.source);
    }).length;
    var slower = standing.filter(function(p) { return p.slower; }).length;
    var unpowered = standing.filter(function(p) { return p.poe_lost; }).length;
    var offInv = (plan.off_inventory || []).length;
    var displaced = (plan.displaced || []).length;
    var fused = Object.keys(plan.fused || {}).length;
    var landed = Object.keys(plan.landed_off_target || {}).length;
    var offTarget = (plan.off_target || []).length;
    var stale = (plan.stale_next_hops || []).length;
    var unbound = Object.keys(plan.unbound_ports || {}).length;
    var pending = pendingPlanDecisions(plan);

    var title = document.createElement('strong');
    title.textContent = 'Ports paired by position';
    el.appendChild(title);
    _planChip(el, 'migrate-rename-plan-paired', paired + ' paired');
    if (yourMoves) {
      _planChip(el, 'migrate-rename-plan-your-moves',
        _plural(yourMoves, 'paired port', 'paired ports')
        + ' sent elsewhere by your own entries', 'chip-info');
    }
    if (yourDrops) {
      _planChip(el, 'migrate-rename-plan-your-drops',
        _plural(yourDrops, 'paired port', 'paired ports')
        + ' dropped by your own entries', 'chip-warn');
    }
    var moved = renumberedMembers(plan);
    if (moved.renumbered.length) {
      // Not a problem: stack members pair in the order they are
      // listed, and this is where that changed a member's number.
      _planChip(el, 'migrate-rename-plan-members',
        moved.renumbered.join('; '), 'chip-info');
    }
    if (moved.crossed.length) {
      // The same members listed in another order: every port of each
      // is on another switch.  The operator may mean it, so it holds
      // nothing -- but it is what a list typed out of order looks
      // like, and it is said in amber.
      _planChip(el, 'migrate-rename-plan-crossed',
        'crossed: ' + moved.crossed.join('; '), 'chip-warn');
    }
    if (unplaced) {
      _planChip(el, 'migrate-rename-plan-unplaced',
        unplaced + ' with no place on the target', 'chip-warn');
    }
    if (yourPlaces) {
      _planChip(el, 'migrate-rename-plan-your-places',
        yourPlaces + ' given a place by your own entries', 'chip-info');
    }
    if (offInv) {
      _planChip(el, 'migrate-rename-plan-off-inventory',
        offInv + ' not on the source device', 'chip-warn');
    }
    if (displaced) {
      _planChip(el, 'migrate-rename-plan-displaced',
        displaced + ' displaced', 'chip-warn');
    }
    if (landed) {
      _planChip(el, 'migrate-rename-plan-landed',
        landed + ' on a port the target does not have', 'chip-warn');
    }
    if (offTarget) {
      // An entry of the operator's own put a port on a name the
      // declared target does not list.  They may mean it; it is said.
      _planChip(el, 'migrate-rename-plan-off-target',
        offTarget + ' on a name the target does not list, by your own entries',
        'chip-warn');
    }
    if (slower) {
      _planChip(el, 'migrate-rename-plan-slower',
        slower + ' on a slower port', 'chip-warn');
    }
    if (unpowered) {
      _planChip(el, 'migrate-rename-plan-poe-lost',
        _plural(unpowered, 'PoE port', 'PoE ports') + ' on a port without PoE',
        'chip-warn');
    }
    if (fused) {
      _planChip(el, 'migrate-rename-plan-fused',
        fused + ' target port' + (fused === 1 ? '' : 's')
        + ' given more than one source', 'chip-block');
    }
    if (unbound) {
      // RouterOS output has no Ethernet line for a port whose name
      // reads as a VLAN, a bridge or a LAG.  Only another name for
      // the port clears it.
      _planChip(el, 'migrate-rename-plan-unbound',
        unbound + ' not found by ' + (unbound === 1 ? 'its' : 'their')
        + ' hardware in the output', 'chip-block');
    }
    if (stale) {
      // The route has to name interfaces the output has: corrected in
      // the output, or by entries that keep the names it uses.
      _planChip(el, 'migrate-rename-plan-stale-routes',
        stale + ' route' + (stale === 1 ? '' : 's')
        + ' still name' + (stale === 1 ? 's' : '') + ' a port that moved',
        'chip-warn');
    }
    if (pending.length) {
      _planChip(el, 'migrate-rename-plan-pending',
        pending.length + ' need' + (pending.length === 1 ? 's' : '')
        + ' your decision', 'chip-warn');
      var accept = document.createElement('button');
      accept.type = 'button';
      accept.className = 'mig-plan-accept';
      accept.textContent = 'Accept as shown';
      accept.title = 'Record what is on screen as your decision for each: '
        + 'a dropped port stays dropped, a kept one stays where it landed';
      accept.setAttribute('data-testid', 'migrate-rename-plan-accept');
      accept.addEventListener('click', acceptPortPlanAsShown);
      el.appendChild(accept);
    } else if (unresolved.length) {
      // Recorded in the modal, not yet sent: the job on screen is
      // still the one that needs them.
      _planChip(el, 'migrate-rename-plan-pending',
        _plural(unresolved.length, 'decision', 'decisions')
        + ' recorded — Apply to confirm', 'chip-warn');
    } else if (renameMapUnsent()) {
      _planChip(el, 'migrate-rename-plan-unsent',
        'your entries changed since this mapping was made — Apply to see the result',
        'chip-info');
    }
    var state = (fused || unbound) ? 'block'
      : ((unresolved.length || stale) ? 'warn' : 'ok');
    var lines = (plan.warnings || []).map(function(w) {
      return String(w).replace(/^port mapping: /, '');
    });
    if (lines.length) {
      var details = document.createElement('details');
      details.className = 'mig-plan-report';
      details.setAttribute('data-testid', 'migrate-rename-plan-report');
      var summary = document.createElement('summary');
      summary.setAttribute('data-testid', 'migrate-rename-plan-report-summary');
      summary.textContent = 'What the mapping reported (' + lines.length + ')';
      summary.addEventListener('click', function() {
        // The click comes before the toggle: this is what it will be.
        _planReportOpen = !details.open;
      });
      details.appendChild(summary);
      var list = document.createElement('ul');
      lines.forEach(function(line) {
        var item = document.createElement('li');
        item.textContent = line;
        list.appendChild(item);
      });
      details.appendChild(list);
      // Open while the job needs the operator; as they left it, once
      // they have opened or closed it themselves.
      details.open = (_planReportOpen === true || _planReportOpen === false)
        ? _planReportOpen : state !== 'ok';
      el.appendChild(details);
    }
    el.className = 'plan-' + state;
    el.setAttribute('data-state', state);
    el.style.display = '';
  }

  /** Called when the modal opens (and when a new job replaces the one
   *  it was opened on): fill the source select, put the target pick
   *  back, draw both sets of controls, and ask the config what device
   *  it came from. */
  function openDevicePickers() {
    // Families that did not load are asked for again; when they come
    // the lists are rebuilt (see _modelFamiliesArrived).
    if (!_modelFamilies.length && _modelFamiliesFailed) loadModelFamilies();
    populateDeviceSourceModels();
    restoreDeviceTargetPick();
    renderDeviceControls('source');
    renderDeviceControls('target');
    renderDeviceNote('source');
    renderDeviceNote('target');
    if (currentDeviceDecl('source') && !_deviceInventory.source
        && !_deviceError.source && !_deviceChecking.source) {
      refreshDeviceInventory('source');
    }
    var target = currentDeviceDecl('target');
    if (target && target.kind === 'family' && !_deviceInventory.target
        && !_deviceError.target && !_deviceChecking.target) {
      refreshDeviceInventory('target');
    }
    detectSourceDevice();
  }

  /** Show or hide everything here that belongs to the ports pane. */
  function showDevicePickers(portsOnly) {
    var row = document.getElementById('mig-device-source');
    if (row) row.style.display = portsOnly ? '' : 'none';
    renderDeviceNote('source');
    renderDeviceNote('target');
    renderPortPlan();
  }

  document.addEventListener('DOMContentLoaded', function() {
    var sourceModel = document.getElementById('mig-device-source-model');
    if (sourceModel) sourceModel.addEventListener('change', deviceSourcePicked);
    var sourceModule = document.getElementById('mig-device-source-module');
    if (sourceModule) {
      sourceModule.addEventListener('change', function() {
        if (_deviceDecl.source && _deviceDecl.source.kind === 'profile') {
          _deviceDecl.source.module = sourceModule.value;
          refreshDeviceInventory('source');
        }
      });
    }
    ['source', 'target'].forEach(function(side) {
      var modeSel = document.getElementById('mig-device-' + side + '-mode');
      if (modeSel) {
        modeSel.addEventListener('change', function() {
          var decl = _deviceDecl[side];
          var fam = _declFamily(decl);
          if (!fam) return;
          _setDeclMode(decl, fam, modeSel.value);
          deviceDeclChanged(side, true);
        });
      }
      var addBtn = document.getElementById('mig-device-' + side + '-add');
      if (addBtn) {
        addBtn.addEventListener('click', function() { addDeviceMember(side); });
      }
    });
  });
