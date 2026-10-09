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
   *   _deviceDecl        — { source, target } declarations (family kind;
   *                        a target PROFILE lives in the three legacy
   *                        target selects, see currentDeviceDecl)
   *   _deviceInventory   — { source, target } compiled inventories
   *   _deviceError       — { source, target } why one did not compile
   *   _deviceProposal    — what the config says about its own hardware
   *   _deviceProposalFor — the source text that proposal was read from
   *   _deviceSourceKey   — the source text the source declaration is for
   *   _deviceSeq         — per-side counter; drops a stale response
   *   _deviceBusy        — per-side compile request in flight
   *   _devicePlanKey     — the declarations the last plan was made with
   *   _deviceTargetPick  — the last target vendor / model / module pick
   *   _lastJob, _lastJobBody, _renameUserMap, _renameProfiles, adapters
   *
   * Helpers used from elsewhere: currentRenameProfileKey,
   * currentRenameModuleSku, effectivePortsFor, formatApiError,
   * renderRenameTable, renderRenamePreview, renderRenameSummary.
   *
   * Every string that reaches the page here comes from the server --
   * family and profile YAML an operator can author, and lines of the
   * pasted config itself -- so everything is written with textContent.
   * ────────────────────────────────────────────────────────────────── */

  var _DEVICE_FAMILY_PREFIX = 'fam:';
  var _DEVICE_PROFILE_PREFIX = 'profile:';
  var _DEVICE_BAY_UNSTATED = '__unstated__';
  var _DEVICE_BAY_EMPTY = '__empty__';

  /** Wording for an inventory's evidence grade.  The grade is of the
   *  port NAMES of this one deployment. */
  var _DEVICE_EVIDENCE_LABEL = {
    'capture': 'Port names checked against a real capture of this deployment',
    'vendor-doc': 'Port names from published vendor sources (no capture of this deployment here)',
    'inferred': 'Port names NOT verified for this device',
  };
  var _DEVICE_UNGRADED_LABEL = 'Port names not yet graded';

  async function loadModelFamilies() {
    try {
      var resp = await fetch('/api/v1/migration/model-families');
      if (!resp.ok) return;
      var data = await resp.json();
      if (Array.isArray(data)) _modelFamilies = data;
    } catch (_) {
      // Model families are optional; without them the pickers offer
      // target profiles only.
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
      fromConfig: false,
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

  /** The body of a declaration as the API takes it. */
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

  /** Why the declared pair cannot be sent, or ''. */
  function _devicePairProblem() {
    var src = currentDeviceDecl('source');
    var tgt = currentDeviceDecl('target');
    if (!src && !tgt) return 'none';
    if (!src) return 'no-source';
    if (!tgt) return 'no-target';
    if (_deviceError.source) return 'source-error';
    if (_deviceError.target) return 'target-error';
    if (tgt.vendor !== _codecVendor(_deviceCodec('target'))) {
      return 'target-vendor';
    }
    return '';
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
   *  half a declaration. */
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

  /** Rebuild the mode select, the per-member controls and the
   *  add-member button of *side* from its declaration. */
  function renderDeviceControls(side) {
    var modeSel = document.getElementById('mig-device-' + side + '-mode');
    var membersEl = document.getElementById('mig-device-' + side + '-members');
    var addBtn = document.getElementById('mig-device-' + side + '-add');
    if (!modeSel || !membersEl || !addBtn) return;
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
    decl.members.forEach(function(member, rank) {
      membersEl.appendChild(_memberControls(side, decl, fam, member, rank, range));
    });
    var room = range ? (range[1] - range[0] + 1) : 1;
    addBtn.style.display = (range && decl.members.length < room) ? '' : 'none';
  }

  function _memberControls(side, decl, fam, member, rank, range) {
    var box = document.createElement('span');
    box.className = 'mig-device-member';
    var base = 'migrate-device-' + side + '-member-' + rank;
    box.setAttribute('data-testid', base);
    // The member's number comes first on its line, then what it is.
    var modelSel = null;
    if (rank > 0) {
      modelSel = document.createElement('select');
      modelSel.setAttribute('data-testid', base + '-model');
      modelSel.setAttribute('aria-label', 'Model of stack member ' + (rank + 1));
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
      idInput.value = (member.id === null || member.id === undefined)
        ? '' : String(member.id);
      idInput.setAttribute('data-testid', base + '-id');
      idInput.setAttribute('aria-label', 'Stack member number');
      idInput.title = 'Stack member number (' + range[0] + '–' + range[1] + ')';
      idInput.addEventListener('change', function() {
        var n = parseInt(idInput.value, 10);
        member.id = isNaN(n) ? null : n;
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
      baySel.setAttribute('aria-label', 'Module in bay ' + bay);
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
      removeBtn.setAttribute('aria-label', 'Remove stack member ' + (rank + 1));
      removeBtn.setAttribute('data-testid', base + '-remove');
      removeBtn.addEventListener('click', function() {
        decl.members.splice(rank, 1);
        deviceDeclChanged(side, true);
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
    deviceDeclChanged(side, true);
  }

  /** Called after any edit of a family declaration.  *rebuild* says
   *  the set of controls changed (a member added, a model swapped). */
  function deviceDeclChanged(side, rebuild) {
    var decl = _deviceDecl[side];
    if (decl) decl.fromConfig = false;
    if (rebuild) renderDeviceControls(side);
    refreshDeviceInventory(side);
  }

  /** The source select changed. */
  function deviceSourcePicked() {
    var sel = document.getElementById('mig-device-source-model');
    var value = sel ? sel.value : '';
    var vendor = _codecVendor(_deviceCodec('source'));
    var fam = _parseFamilyValue(value);
    if (fam) {
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
    _deviceTargetPick = {
      vendor: vendor, model: value,
      module: (modsel && modsel.style.display !== 'none') ? modsel.value : '',
    };
    var fam = _parseFamilyValue(value);
    var current = _deviceDecl.target;
    if (!fam) {
      _deviceDecl.target = null;
    } else if (!current || current.vendor !== vendor
               || current.family !== fam.family
               || current.members[0].model !== fam.model) {
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
   *  its verdict, not from the one it replaced. */
  function devicesSettled() {
    return Promise.all(
      [_deviceBusy.source, _deviceBusy.target].filter(Boolean)
    ).catch(function() { /* a failed compile is recorded as an error */ });
  }

  async function _compileDevice(side) {
    var decl = currentDeviceDecl(side);
    var seq = ++_deviceSeq[side];
    _deviceInventory[side] = null;
    _deviceError[side] = '';
    if (!decl || (side === 'target' && decl.kind === 'profile')) {
      _afterDeviceChange(side);
      return;
    }
    var request = { codec: _deviceCodec(side) };
    if (decl.kind === 'family') {
      request.deployment = _deploymentSpec(decl);
    } else {
      request.profile = decl.profile;
      if (decl.module) request.module = decl.module;
    }
    try {
      var resp = await fetch('/api/v1/migration/inventory', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      });
      var data = await resp.json().catch(function() { return {}; });
      if (seq !== _deviceSeq[side]) return;
      if (resp.ok) _deviceInventory[side] = data;
      else _deviceError[side] = formatApiError(data, resp.statusText);
    } catch (e) {
      if (seq !== _deviceSeq[side]) return;
      _deviceError[side] = 'Could not reach the server (' + e.message + ').';
    }
    _afterDeviceChange(side);
  }

  function _afterDeviceChange(side) {
    renderDeviceNote(side);
    renderRenameTable();
    renderRenamePreview();
    renderRenameSummary();
  }

  /* ── reading the source device from the config ── */

  function _sourceTextKey(body) {
    if (!body) return '';
    var text = body.raw_text || '';
    return (body.source || '') + '|' + (body.source_filename || '') + '|'
      + text.length + '|' + text.slice(0, 256);
  }

  /** A new translation: a different source text starts with no source
   *  device, a different target codec with no target family model. */
  function resetDevicesForJob(body) {
    var key = _sourceTextKey(body);
    if (key !== _deviceSourceKey) {
      _deviceSourceKey = key;
      _deviceDecl.source = null;
      _deviceInventory.source = null;
      _deviceError.source = '';
      _deviceProposal = null;
      _deviceProposalFor = '';
    }
    var target = _deviceDecl.target;
    if (target && target.vendor !== _codecVendor((body && body.target) || '')) {
      _deviceDecl.target = null;
      _deviceInventory.target = null;
      _deviceError.target = '';
      _deviceTargetPick = null;
    }
  }

  /** Ask the server what the config says about its own hardware --
   *  once per source text -- and pre-fill the source picker with it
   *  unless the operator has already chosen. */
  async function detectSourceDevice() {
    if (!_lastJobBody) return;
    var key = _sourceTextKey(_lastJobBody);
    if (_deviceProposalFor === key) return;
    _deviceProposalFor = key;
    _deviceProposal = null;
    var request = { source: _lastJobBody.source };
    if (typeof _lastJobBody.raw_text === 'string') {
      request.raw_text = _lastJobBody.raw_text;
    } else {
      request.source_filename = _lastJobBody.source_filename;
    }
    try {
      var resp = await fetch('/api/v1/migration/detect-deployment', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      });
      if (!resp.ok) return;
      var proposal = await resp.json();
      if (_deviceProposalFor !== key) return;
      _deviceProposal = proposal;
    } catch (_) {
      return;
    }
    if (!_deviceDecl.source && useDetectedSourceDevice()) return;
    renderDeviceNote('source');
  }

  /** Declare the source as the config states it.  False when the
   *  config states nothing a model family describes. */
  function useDetectedSourceDevice() {
    var p = _deviceProposal;
    if (!p || !p.deployment || !p.family) return false;
    var familyKey = String(p.family).split('/').slice(1).join('/');
    var fam = _familyOf(p.vendor, familyKey);
    var members = (p.deployment.members || []).filter(function(m) {
      return fam && (fam.models || {})[m.model];
    });
    if (!fam || !members.length
        || members.length !== (p.deployment.members || []).length) {
      return false;
    }
    _deviceDecl.source = {
      kind: 'family', vendor: p.vendor, family: familyKey,
      mode: p.deployment.mode || _defaultMode(fam, members[0].model),
      members: members.map(function(m) {
        return {
          model: m.model,
          id: (m.id === null || m.id === undefined) ? null : m.id,
          modules: Object.assign({}, m.modules || {}),
        };
      }),
      fromConfig: true,
    };
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

  /** What a declaration resolved to: the device in words, its port
   *  count and first and last port, how well the names are known,
   *  every caveat -- and, for the source, the config lines it was read
   *  from.  Amber when the names are in doubt or the config disagrees
   *  with the device; red when the declaration did not compile. */
  function renderDeviceNote(side) {
    var el = document.getElementById('mig-device-' + side + '-note');
    if (!el) return;
    el.textContent = '';
    el.className = 'mig-device-note';
    el.removeAttribute('data-evidence');
    var portsPane = document.getElementById('mig-rename-ports-pane');
    var portsActive = !portsPane || portsPane.classList.contains('active');
    var decl = currentDeviceDecl(side);
    var inv = _deviceInventory[side];
    var error = _deviceError[side];
    var proposal = (side === 'source') ? _deviceProposal : null;
    var base = 'migrate-device-' + side + '-note';
    var who = (side === 'source') ? 'Source' : 'Target';
    var warn = false;

    if (error) {
      _notePart(el, base + '-error', who + ' device: ' + error);
      el.classList.add('notice-block');
    } else if (inv) {
      _notePart(el, base + '-device', who + ': ' + (inv.description || ''),
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
      if (inv.mode_defaulted) {
        _notePart(el, base + '-mode-defaulted',
          'Mode not stated — the family default was used');
      }
      var unstated = [];
      (inv.members || []).forEach(function(m) {
        (m.unstated_bays || []).forEach(function(bay) {
          unstated.push((inv.members.length > 1
            ? 'member ' + (m.member_id || (m.rank + 1)) + ' ' : '') + 'bay ' + bay);
        });
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

    if (proposal) {
      var sameAsConfig = decl && decl.fromConfig;
      if (sameAsConfig) {
        _noteList(el, base + '-read-from',
          'Read from the config (' + (proposal.evidence || []).length + ' line'
            + ((proposal.evidence || []).length === 1 ? '' : 's') + ')',
          proposal.evidence || [], true);
        if (proposal.consistent === false) {
          var missing = proposal.missing_ports || [];
          _notePart(el, base + '-inconsistent',
            missing.length + ' port name' + (missing.length === 1 ? '' : 's')
            + ' the config uses ' + (missing.length === 1 ? 'is' : 'are')
            + ' not on this device: ' + missing.slice(0, 8).join(', ')
            + (missing.length > 8 ? ' …' : ''));
          warn = true;
        }
        (proposal.notes || []).forEach(function(note, i) {
          _notePart(el, base + '-detect-note-' + i, note);
        });
      } else if (proposal.deployment) {
        var said = (proposal.members || []).map(function(m) {
          return m.part;
        }).join(' + ');
        _notePart(el, base + '-config-says', 'The config states: ' + said);
        var use = document.createElement('button');
        use.type = 'button';
        use.className = 'mig-device-use-detected';
        use.textContent = 'use it';
        use.setAttribute('data-testid', 'migrate-device-source-use-detected');
        use.addEventListener('click', function() { useDetectedSourceDevice(); });
        el.appendChild(use);
      } else if (proposal.stated && (proposal.unknown_parts || []).length) {
        _notePart(el, base + '-unknown-parts',
          'The config states ' + proposal.unknown_parts.join(', ')
          + ', which no model family describes yet — choose the device yourself');
      } else if (!decl && (proposal.notes || []).length) {
        _notePart(el, base + '-detect-note-0', proposal.notes[0]);
      }
    }

    if (warn && !error) el.classList.add('notice-warn');
    el.style.display = (portsActive && el.childNodes.length) ? '' : 'none';
  }

  /* ── the port plan ── */

  /** The plan the job on screen was made with, or null. */
  function currentPortPlan() {
    var plan = _lastJob && _lastJob.port_mapping_plan;
    return (plan && typeof plan === 'object') ? plan : null;
  }

  var _PLAN_ROLE_KIND = { access: 'physical', uplink: 'physical', mgmt: 'mgmt' };

  /** Per source name: what the plan did with it, for the rename table.
   *
   *    state   paired | unplaced | off-inventory | displaced | follows
   *            | landed-off-target
   *    role    access | uplink | mgmt (a port of the declared source)
   *    kind    the table section the row belongs in, when known
   *    auto    the target the plan chose ('' when it chose none)
   *    text    what to show in place of a target when there is none
   *    why     the position that decided the pairing, and its flags
   *    order   position in the source inventory, for sorting          */
  function portPlanRowMeta(plan) {
    var meta = {};
    if (!plan || !plan.applied) return meta;
    var renames = (_lastJob && _lastJob.port_renames) || {};
    var dropped = new Set((_lastJob && _lastJob.port_drops) || []);
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
    // RouterOS finds a port by its factory name.  What the plan says
    // about that, for a row: the port of the model the config's own
    // name stands for; where the port's hardware is when the name in
    // the output is not it; and whether any line of the output finds
    // the port at all.
    function hardwareFlags(name) {
      var flags = [];
      if (labelled[name]) flags.push(labelled[name] + ' in the device model');
      if (hardware[name]) {
        flags.push('a name, not a place — the port is on ' + hardware[name]);
      }
      if (sourceHardware[name]) {
        flags.push('still looked up as ' + sourceHardware[name]
          + ', which the target does not have');
      }
      if (unbound[name]) {
        flags.push('no line of the output finds this port ('
          + unbound[name] + ') — give it another name');
      }
      return flags;
    }
    // Stack members pair in the order they are listed, so a member's
    // place and its number are two things.  A row names its member by
    // NUMBER, as the port's own name does, and says where that member
    // went when it is a member of another number, or no member at all.
    function memberOf(rank) {
      var from = sourceMembers[rank];
      var number = (from && from.member_id !== null && from.member_id !== undefined)
        ? from.member_id : rank + 1;
      var to = targetMembers[rank];
      if (!to) return ' · member ' + number + ' → no member';
      if (to.member_id !== null && to.member_id !== undefined
          && to.member_id !== number) {
        return ' · member ' + number + ' → member ' + to.member_id;
      }
      return ' · member ' + number;
    }
    function where(rank, role, position) {
      return role + ' ' + (position + 1)
        + (stacked && rank !== null && rank !== undefined ? memberOf(rank) : '');
    }
    (plan.pairings || []).forEach(function(p) {
      order += 1;
      if (!p.used) return;
      var flags = [];
      if (p.slower) {
        flags.push('slower: ' + (p.source_speed || '?') + ' → '
          + (p.target_speed || '?'));
      }
      if (p.poe_lost) flags.push('no PoE on the target port');
      flags = flags.concat(hardwareFlags(p.source));
      meta[p.source] = {
        state: 'paired', role: p.role, kind: _PLAN_ROLE_KIND[p.role],
        auto: p.target, text: '',
        why: where(p.member_rank, p.role, p.position), flags: flags,
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
        why: where(p.member_rank, p.role, p.position),
        flags: hardwareFlags(p.source),
        order: order,
      };
    });
    (plan.off_inventory || []).forEach(function(name) {
      order += 1;
      var outcome = dropped.has(name) ? 'dropped'
        : (renames[name] && renames[name] !== name
            ? 'translated by name to ' + renames[name] : 'left as it is');
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

  /** Source names the rename table draws a row for that are neither a
   *  key of ``port_renames`` nor quoted in a warning: the names a
   *  port plan reports, and ports the config uses under an unchanged
   *  name.  The rail count adds these to its own two. */
  function extraPortRowNames() {
    if (!_lastJob) return [];
    var seen = new Set(Object.keys(_lastJob.port_renames || {}));
    (_lastJob.warnings || []).forEach(function(w) {
      var m = String(w).match(/'([^']+)'/);
      if (m) seen.add(m[1]);
    });
    var extra = [];
    function note(name) {
      if (!name || seen.has(name)) return;
      seen.add(name);
      extra.push(name);
    }
    Object.keys(portPlanRowMeta(currentPortPlan())).forEach(note);
    (_lastJob.source_ports || []).forEach(note);
    return extra;
  }

  /** Names the plan could not settle and the operator has not decided
   *  in this modal either. */
  function pendingPlanDecisions(plan) {
    if (!plan || !plan.applied) return [];
    return (plan.unresolved_ports || []).filter(function(name) {
      return _renameUserMap[name] === undefined;
    });
  }

  /** Record, for every name still undecided, the outcome on screen as
   *  the operator's decision: a name that was dropped stays dropped,
   *  one that was kept stays where it landed.  Apply confirms it. */
  function acceptPortPlanAsShown() {
    var plan = currentPortPlan();
    var names = pendingPlanDecisions(plan);
    if (!names.length) return;
    var renames = (_lastJob && _lastJob.port_renames) || {};
    var dropped = new Set((_lastJob && _lastJob.port_drops) || []);
    names.forEach(function(name) {
      _renameUserMap[name] = dropped.has(name) ? null : (renames[name] || name);
    });
    renderRenameTable();
    renderRenamePreview();
    renderRenameSummary();
    var status = document.getElementById('mig-rename-status');
    if (status) {
      status.textContent = names.length + ' decision'
        + (names.length === 1 ? '' : 's') + ' recorded — Apply to confirm.';
    }
  }

  /** Members the pairing put on a member of another NUMBER.  Only a
   *  member the config uses is named, as in the plan's own line. */
  function renumberedMembers(plan) {
    var theirs = (plan.target && plan.target.members) || [];
    var used = {};
    (plan.pairings || []).forEach(function(p) {
      if (p.used) used[p.member_rank] = true;
    });
    return ((plan.source && plan.source.members) || []).filter(function(m) {
      var to = theirs[m.rank];
      return used[m.rank] && to
        && m.member_id !== null && m.member_id !== undefined
        && to.member_id !== null && to.member_id !== undefined
        && to.member_id !== m.member_id;
    }).map(function(m) {
      return 'member ' + m.member_id + ' → member ' + theirs[m.rank].member_id;
    });
  }

  function _planChip(el, testid, text, extraClass) {
    var chip = document.createElement('span');
    chip.className = 'mig-plan-chip' + (extraClass ? ' ' + extraClass : '');
    chip.setAttribute('data-testid', testid);
    chip.textContent = text;
    el.appendChild(chip);
  }

  /** The strip that says where the port mapping stands: what to do
   *  next while there is no plan, and what the plan did once there is
   *  one -- paired, unplaced, not on the source device, displaced, on
   *  a port the target lacks, fused, a route left naming a port that
   *  moved, and how many names still need the operator's decision. */
  function renderPortPlan() {
    var el = document.getElementById('mig-rename-plan');
    if (!el) return;
    el.textContent = '';
    el.className = '';
    el.removeAttribute('data-state');
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
      span.className = 'mig-plan-text';
      span.setAttribute('data-testid', testid);
      span.textContent = text;
      el.appendChild(span);
    }

    if (!plan || changed) {
      if (problem === 'none') {
        if (!plan) { el.style.display = 'none'; return; }
        say('migrate-rename-plan-hint',
          'The devices were cleared — Apply to go back to translating '
          + 'port names by their shape.');
      } else if (problem === 'no-source') {
        say('migrate-rename-plan-hint',
          'Choose the source device as well to pair ports by position. '
          + 'Until then the target’s port list only fills the choices below.');
      } else if (problem === 'no-target') {
        say('migrate-rename-plan-hint',
          'Choose the target device to pair ports by position.');
      } else if (problem === 'target-vendor') {
        say('migrate-rename-plan-hint',
          'The target device is not of the target codec’s vendor, so '
          + 'ports are not paired by position.');
      } else if (problem) {
        say('migrate-rename-plan-hint',
          'A device declaration is not valid yet — see the note above.');
      } else {
        say('migrate-rename-plan-hint', changed
          ? 'The devices changed since this mapping was made — Apply to pair again.'
          : 'Both devices are declared — Apply to pair their ports by position.');
      }
      el.className = 'plan-info';
      el.setAttribute('data-state', changed ? 'stale' : 'ready');
      el.style.display = '';
      return;
    }

    if (!plan.applied) {
      var reason = ((plan.warnings || [])[0] || '').replace(/^port mapping: /, '');
      say('migrate-rename-plan-unapplied',
        'Ports were NOT paired by position'
        + (reason ? ': ' + reason : '') + '. Every name was translated by its shape.');
      el.className = 'plan-block';
      el.setAttribute('data-state', 'unapplied');
      el.style.display = '';
      return;
    }

    var paired = (plan.pairings || []).filter(function(p) { return p.used; }).length;
    var unplaced = (plan.unplaced || []).filter(function(p) { return p.used; }).length;
    var offInv = (plan.off_inventory || []).length;
    var displaced = (plan.displaced || []).length;
    var fused = Object.keys(plan.fused || {}).length;
    var landed = Object.keys(plan.landed_off_target || {}).length;
    var stale = (plan.stale_next_hops || []).length;
    var unbound = Object.keys(plan.unbound_ports || {}).length;
    var pending = pendingPlanDecisions(plan);

    var title = document.createElement('strong');
    title.textContent = 'Ports paired by position';
    el.appendChild(title);
    _planChip(el, 'migrate-rename-plan-paired', paired + ' paired');
    var renumbered = renumberedMembers(plan);
    if (renumbered.length) {
      // Not a problem: stack members pair in the order they are
      // listed, and this is where that changed a member's number.
      _planChip(el, 'migrate-rename-plan-members', renumbered.join('; '), 'chip-info');
    }
    if (unplaced) {
      _planChip(el, 'migrate-rename-plan-unplaced',
        unplaced + ' with no place on the target', 'chip-warn');
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
    } else if ((plan.unresolved_ports || []).length) {
      _planChip(el, 'migrate-rename-plan-pending',
        'decisions recorded — Apply to confirm', 'chip-info');
    }
    var lines = (plan.warnings || []).map(function(w) {
      return String(w).replace(/^port mapping: /, '');
    });
    if (lines.length) {
      var details = document.createElement('details');
      details.className = 'mig-plan-report';
      details.setAttribute('data-testid', 'migrate-rename-plan-report');
      var summary = document.createElement('summary');
      summary.textContent = 'What the mapping reported (' + lines.length + ')';
      details.appendChild(summary);
      var list = document.createElement('ul');
      lines.forEach(function(line) {
        var item = document.createElement('li');
        item.textContent = line;
        list.appendChild(item);
      });
      details.appendChild(list);
      if (fused || unbound || pending.length || stale) details.open = true;
      el.appendChild(details);
    }
    var state = (fused || unbound) ? 'block'
      : ((pending.length || stale) ? 'warn' : 'ok');
    el.className = 'plan-' + state;
    el.setAttribute('data-state', state);
    el.style.display = '';
  }

  /** Called when the modal opens: fill the source select, put the
   *  target pick back, draw both sets of controls, and ask the config
   *  what device it came from. */
  function openDevicePickers() {
    populateDeviceSourceModels();
    restoreDeviceTargetPick();
    renderDeviceControls('source');
    renderDeviceControls('target');
    renderDeviceNote('source');
    renderDeviceNote('target');
    if (currentDeviceDecl('source') && !_deviceInventory.source
        && !_deviceError.source) {
      refreshDeviceInventory('source');
    }
    var target = currentDeviceDecl('target');
    if (target && target.kind === 'family' && !_deviceInventory.target
        && !_deviceError.target) {
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
          decl.mode = modeSel.value;
          var range = _memberIdRange(fam, decl.mode);
          if (!range) {
            // A device that stands alone: one member, no number.
            decl.members = [decl.members[0]];
            decl.members[0].id = null;
          } else {
            decl.members.forEach(function(m, rank) {
              if (m.id === null || m.id === undefined) m.id = range[0] + rank;
            });
          }
          deviceDeclChanged(side, true);
        });
      }
      var addBtn = document.getElementById('mig-device-' + side + '-add');
      if (addBtn) {
        addBtn.addEventListener('click', function() { addDeviceMember(side); });
      }
    });
  });
