  /* ── Keyboard shortcut cheatsheet ──
   * Global `?` keypress opens a modal documenting every other keyboard
   * shortcut the app exposes (config-viewer search nav, diff-page
   * collapsed-marker expand, configs-page compare-picker close).  The
   * goal is discoverability — operators who run multiple tabs and
   * Vim-style workflows expect a shortcuts panel; without one the
   * shortcuts are invisible to anyone who didn't read the source.
   *
   * Event-flow notes:
   *   - The `?` listener is bound at the document level but bails out
   *     when the active element is an <input> / <textarea> / <select>
   *     or anything contenteditable, so it doesn't hijack literal
   *     ``?`` typed into a form field.
   *   - The shortcut is registered as Shift+/ rather than `key === '?'`
   *     for layout compatibility — non-US layouts produce ``?`` via
   *     other key combinations and we don't want false positives.
   *   - Escape closes the cheatsheet AND any other open modal in the
   *     existing system (config viewer, compare-picker).  The
   *     config-viewer's own Esc handler runs first because its
   *     listener is registered earlier; this handler is additive.
   */

  /**
   * Open the cheatsheet modal.  Idempotent — calling twice is a no-op.
   * The modal's close button receives focus on open so screen readers
   * announce the dialog correctly and keyboard users can Tab through
   * + Esc out.
   */
  function openKbdCheatsheet() {
    var modal = document.getElementById('_kbd-cheatsheet');
    if (!modal) return;
    modal.style.display = 'flex';
    var closeBtn = modal.querySelector(
      '[data-testid="kbd-cheatsheet-close"]'
    );
    if (closeBtn) closeBtn.focus();
  }

  /**
   * Hide the cheatsheet modal.  Safe to call when it's already closed.
   */
  function closeKbdCheatsheet() {
    var modal = document.getElementById('_kbd-cheatsheet');
    if (modal) modal.style.display = 'none';
  }

  /**
   * Return true if *target* is a form field where ``?`` should be
   * treated as literal text input rather than a global shortcut.
   * Excludes inputs of types that can't take text (checkbox, radio,
   * button, submit, reset) so e.g. focusing a checkbox doesn't
   * disable the cheatsheet trigger.
   *
   * @param {EventTarget} target
   * @returns {boolean}
   */
  function _kbdIsTextEditableTarget(target) {
    if (!target || target.nodeType !== 1) return false;
    if (target.isContentEditable) return true;
    var tag = target.tagName;
    if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
    if (tag === 'INPUT') {
      var type = (target.type || '').toLowerCase();
      // Types that don't accept text input — global shortcut should
      // still fire when one of these is focused.
      var nonTextTypes = [
        'checkbox', 'radio', 'button', 'submit',
        'reset', 'file', 'range', 'color', 'image'
      ];
      return nonTextTypes.indexOf(type) === -1;
    }
    return false;
  }

  document.addEventListener('keydown', function(e) {
    // `?` (Shift+/ on US layouts; e.key === '?' covers other layouts
    // where Shift+something-else produces a question mark).  Bail
    // out if a text-editable field is focused or modifier keys are
    // pressed that would imply a browser/system shortcut.
    if (e.key !== '?') return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (_kbdIsTextEditableTarget(e.target)) return;
    e.preventDefault();
    // If the cheatsheet is already open, treat the second `?` as a
    // toggle (close).  This matches user expectation for "open with
    // ?, close with ?".
    var modal = document.getElementById('_kbd-cheatsheet');
    if (modal && modal.style.display === 'flex') {
      closeKbdCheatsheet();
    } else {
      openKbdCheatsheet();
    }
  });

  document.addEventListener('keydown', function(e) {
    if (e.key !== 'Escape') return;
    var modal = document.getElementById('_kbd-cheatsheet');
    if (modal && modal.style.display === 'flex') {
      closeKbdCheatsheet();
    }
  });
