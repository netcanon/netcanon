/* ── Theme toggle ── */
/* Flips the unified UI mode between "light" and "dark" via
   NcTheme.set(null, mode) — NcTheme is defined by the vendored
   _vendor/theme-picker.js include in base.html's <head>.  NcTheme
   owns persistence (localStorage["nc-mode"]) and the
   <html data-nc-mode> attribute; the icon glyph swaps via CSS
   keyed on that attribute (absent attribute = follow the OS —
   see base.html).

   The initial theme/mode was ALREADY applied by NcTheme.boot()
   inside the vendored include.  It runs synchronously in <head>
   before CSS applies, preventing FOUC.  This function only
   handles user-initiated toggles thereafter.

   The legacy localStorage["netcanon.theme.v1"] key is still
   WRITTEN (one-way mirror) so the self-contained /docs page —
   which keeps its own pre-unification theme copy — follows the
   mode chosen here.  This page no longer READS the legacy key
   (a one-time snippet in <head> migrated it into "nc-mode"). */

/* Effective mode: the forced <html data-nc-mode> when present,
   otherwise the OS preference — mirrors how the vendored CSS
   resolves the "auto" state. */
function _effectiveMode() {
  var forced = document.documentElement.getAttribute('data-nc-mode');
  if (forced === 'dark' || forced === 'light') return forced;
  return (window.matchMedia &&
          window.matchMedia('(prefers-color-scheme: dark)').matches)
    ? 'dark' : 'light';
}

function toggleTheme() {
  var next = _effectiveMode() === 'dark' ? 'light' : 'dark';
  NcTheme.set(null, next);
  try {
    localStorage.setItem('netcanon.theme.v1', next);
  } catch (_) {
    /* Sandboxed iframes / privacy-mode browsers may deny
       localStorage; NcTheme.set already applied the mode for this
       session, the mirror just won't reach the /docs page. */
  }
  _updateThemeToggleAriaLabel(next);
}

/* Mirror the glyph swap in the button's aria-label so screen
   readers announce the ACTION (what clicking does) rather than
   the current state.  "Switch to dark theme" / "Switch to light
   theme" is clearer than "Dark mode on" / "Dark mode off". */
function _updateThemeToggleAriaLabel(activeTheme) {
  var btn = document.getElementById('nav-theme-toggle');
  if (!btn) return;
  btn.setAttribute(
    'aria-label',
    activeTheme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'
  );
  btn.setAttribute(
    'aria-pressed',
    activeTheme === 'dark' ? 'true' : 'false'
  );
}

/* Initialise aria-label on DOMContentLoaded.  NcTheme.boot() set
   the mode attributes before the DOM existed, so we resolve the
   effective mode here and seed the button's aria state to match. */
document.addEventListener('DOMContentLoaded', function() {
  _updateThemeToggleAriaLabel(_effectiveMode());
});
