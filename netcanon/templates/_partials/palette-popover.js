/* Palette popover — the right-rail <nc-theme-picker> lives inside a native
   <details> disclosure (#nav-palette in base.html).  <details> toggles on its
   summary, but does not dismiss on an outside click or Escape the way a
   menu-like popover should — wire that here.  The only state is the element's
   own `.open`; nothing else is tracked. */
(function () {
  "use strict";
  var d = document.getElementById("nav-palette");
  if (!d) return;

  // Outside click closes it (a click inside the summary/panel is ignored).
  document.addEventListener("click", function (e) {
    if (d.open && !d.contains(e.target)) d.open = false;
  });

  // Escape closes it and returns focus to the trigger (APG menu-button model).
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && d.open) {
      d.open = false;
      var s = document.getElementById("nav-palette-summary");
      if (s) s.focus();
    }
  });
})();
