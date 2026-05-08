/* ── Theme toggle ── */
/* Flips the document `data-theme` attribute between "light" and
   "dark", persists the choice to
   localStorage["netcanon.theme.v1"], and updates the toggle's
   aria-label so screen readers announce the correct next-action.
   The icon glyph itself swaps via CSS attribute-selector rules —
   no DOM mutation of the button contents.

   The initial theme was ALREADY set by the inline boot script in
   <head> (see base.html).  That boot script runs before CSS
   applies, preventing FOUC.  This function only handles
   user-initiated toggles thereafter. */
function toggleTheme() {
  var html = document.documentElement;
  var current = html.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
  var next = current === 'dark' ? 'light' : 'dark';
  html.setAttribute('data-theme', next);
  try {
    localStorage.setItem('netcanon.theme.v1', next);
  } catch (_) {
    /* Sandboxed iframes / privacy-mode browsers may deny
       localStorage; the toggle still works for the session, it
       just won't persist across reloads. */
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

/* Initialise aria-label on DOMContentLoaded.  The boot script
   set `data-theme` before the DOM existed, so we re-read it here
   and seed the button's aria state to match. */
document.addEventListener('DOMContentLoaded', function() {
  var current = document.documentElement.getAttribute('data-theme');
  _updateThemeToggleAriaLabel(current === 'dark' ? 'dark' : 'light');
});
