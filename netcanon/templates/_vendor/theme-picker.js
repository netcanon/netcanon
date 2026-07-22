/* theme-picker.js — GENERATED from tokens/themes.json by tools/build_css.py. DO NOT EDIT dist/ BY HAND.
 *
 * The netcanon-dev theme GUI setting. Zero dependencies, light DOM.
 *
 * Usage (the closing script tag is spelled <\/script> below so this comment cannot
 * terminate an inline <script> block if this file is ever pasted into a page):
 *   <script src="theme-picker.js"><\/script>         <!-- early in <head>: applies saved prefs, no FOUC -->
 *   <nc-theme-picker></nc-theme-picker>              <!-- the control, wherever you want it -->
 *   <nc-theme-picker compact></nc-theme-picker>      <!-- swatches only, no labels -->
 *
 * State lives on <html> as data-nc-theme / data-nc-mode (nc-namespaced: apps like netcanon and
 * Settlement Hunter already use a plain data-theme attribute for their own light/dark switching,
 * so ours must not collide). Persists in localStorage ("nc-theme", "nc-mode"). Omitted
 * data-nc-mode = follow the OS. Emits "nc-theme-change" on document when the user picks anything.
 */
(function () {
  "use strict";

  var THEMES = [{"id":"ocean","label":"Ocean","swatch":{"light":["#0969da","#1b7c83"],"dark":["#1f6feb","#39c5cf"]}},{"id":"indigo","label":"Indigo","swatch":{"light":["#4f46e5","#7c3aed"],"dark":["#6366f1","#a78bfa"]}},{"id":"lagoon","label":"Lagoon","swatch":{"light":["#1b7c83","#0969da"],"dark":["#39c5cf","#2f81f7"]}},{"id":"verdant","label":"Verdant","swatch":{"light":["#047857","#0369a1"],"dark":["#00e5a0","#0ea5e9"]}},{"id":"violet","label":"Violet","swatch":{"light":["#8250df","#bf3989"],"dark":["#a371f7","#f778ba"]}},{"id":"rose","label":"Rose","swatch":{"light":["#bf3989","#8250df"],"dark":["#f778ba","#a371f7"]}},{"id":"ember","label":"Ember","swatch":{"light":["#bc4c00","#bf3989"],"dark":["#f0883e","#f778ba"]}},{"id":"gold","label":"Gold","swatch":{"light":["#9a6700","#bc4c00"],"dark":["#e3b341","#f0883e"]}},{"id":"graphite","label":"Graphite","swatch":{"light":["#57606a","#768390"],"dark":["#768390","#9ea7b3"]}},{"id":"aurora","label":"Aurora","swatch":{"light":["#6741d9","#047857"],"dark":["#7c5cf0","#00e5a0"]}}];
  var MODES = [
    { id: "light", label: "Light" },
    { id: "auto", label: "Auto" },
    { id: "dark", label: "Dark" }
  ];

  var NcTheme = {
    themes: THEMES,
    get: function () {
      return {
        theme: document.documentElement.getAttribute("data-nc-theme") || "ocean",
        mode: document.documentElement.getAttribute("data-nc-mode") || "auto"
      };
    },
    set: function (theme, mode) {
      var root = document.documentElement;
      // Swap atomically: suppress transitions so fills and on-colors can't crossfade out of
      // step (e.g. a blue fill fading under an already-swapped dark label = illegible flash).
      root.setAttribute("data-nc-switching", "");
      clearTimeout(NcTheme._switchTimer);
      NcTheme._switchTimer = setTimeout(function () {
        root.removeAttribute("data-nc-switching");
      }, 80);
      if (theme) {
        root.setAttribute("data-nc-theme", theme);
        try { localStorage.setItem("nc-theme", theme); } catch (e) { /* storage may be unavailable */ }
      }
      if (mode) {
        if (mode === "auto") root.removeAttribute("data-nc-mode");
        else root.setAttribute("data-nc-mode", mode);
        try { localStorage.setItem("nc-mode", mode); } catch (e) { /* storage may be unavailable */ }
      }
      document.dispatchEvent(new CustomEvent("nc-theme-change", { detail: NcTheme.get() }));
    },
    boot: function () {
      var theme, mode;
      try {
        theme = localStorage.getItem("nc-theme");
        mode = localStorage.getItem("nc-mode");
      } catch (e) { /* storage may be unavailable */ }
      var root = document.documentElement;
      if (theme && THEMES.some(function (t) { return t.id === theme; })) root.setAttribute("data-nc-theme", theme);
      else if (!root.hasAttribute("data-nc-theme")) root.setAttribute("data-nc-theme", "ocean");
      if (mode === "light" || mode === "dark") root.setAttribute("data-nc-mode", mode);
      // A persisted "auto" must UNDO a markup-hardcoded data-nc-mode, or the user's Auto
      // choice is silently dropped on reload. Stored-null leaves the markup default alone.
      else if (mode === "auto") root.removeAttribute("data-nc-mode");
    }
  };
  window.NcTheme = NcTheme;
  NcTheme.boot();

  var CSS =
    ".nc-theme-picker{display:inline-flex;flex-direction:column;gap:8px;font-family:var(--nc-font,system-ui,sans-serif)}" +
    ".ncp-swatches{display:flex;flex-wrap:wrap;gap:6px}" +
    ".ncp-swatch{width:26px;height:26px;border-radius:50%;border:2px solid transparent;padding:0;cursor:pointer;" +
      "background-origin:border-box;box-shadow:inset 0 0 0 2px var(--nc-bg,#fff)}" +
    ".ncp-swatch[aria-checked=true]{border-color:var(--nc-text,#111)}" +
    ".ncp-swatch:focus-visible{outline:2px solid var(--nc-focus,#0969da);outline-offset:2px}" +
    ".ncp-modes{display:inline-flex;border:1px solid var(--nc-border-strong,#888);border-radius:6px;overflow:hidden;width:max-content}" +
    ".ncp-mode{font:500 12px/1 var(--nc-font,system-ui,sans-serif);color:var(--nc-text-muted,#666);" +
      "background:transparent;border:0;padding:6px 10px;cursor:pointer}" +
    ".ncp-mode[aria-checked=true]{background:var(--nc-accent-emphasis,#0969da);color:var(--nc-on-accent,#fff)}" +
    ".ncp-mode:focus-visible{outline:2px solid var(--nc-focus,#0969da);outline-offset:-2px}";

  function injectCss() {
    if (document.getElementById("nc-theme-picker-css")) return;
    var s = document.createElement("style");
    s.id = "nc-theme-picker-css";
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function swatchGradient(t) {
    var mode = document.documentElement.getAttribute("data-nc-mode");
    if (!mode) mode = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    var g = t.swatch[mode] || t.swatch.dark;
    return "linear-gradient(135deg," + g[0] + "," + g[1] + ")";
  }

  // APG radio-group keyboard model: arrows move AND select (wrapping); the checked
  // option is the only tab stop (roving tabindex).
  function wireArrowKeys(group, buttons, onPick) {
    group.addEventListener("keydown", function (e) {
      var delta = (e.key === "ArrowRight" || e.key === "ArrowDown") ? 1
                : (e.key === "ArrowLeft" || e.key === "ArrowUp") ? -1 : 0;
      if (!delta) return;
      var i = buttons.indexOf(document.activeElement);
      if (i === -1) return;
      e.preventDefault();
      var next = buttons[(i + delta + buttons.length) % buttons.length];
      onPick(next);          // set() dispatches nc-theme-change -> update() runs synchronously
      next.focus();          // in-place update keeps the node alive, so focus survives
    });
  }

  var NcThemePicker = /** @type {any} */ (function () {
    function P() { return Reflect.construct(HTMLElement, [], P); }
    P.prototype = Object.create(HTMLElement.prototype);

    P.prototype.connectedCallback = function () {
      injectCss();
      this.classList.add("nc-theme-picker");
      this.build();
      this.update();
      var self = this;
      this._onChange = function () { self.update(); };
      document.addEventListener("nc-theme-change", this._onChange);
      // in auto mode the swatch gradients depend on the OS scheme — re-sync on flips
      this._mq = matchMedia("(prefers-color-scheme: dark)");
      this._onScheme = function () { self.update(); };
      if (this._mq.addEventListener) this._mq.addEventListener("change", this._onScheme);
      else if (this._mq.addListener) this._mq.addListener(this._onScheme);
    };

    P.prototype.disconnectedCallback = function () {
      document.removeEventListener("nc-theme-change", this._onChange);
      if (this._mq) {
        if (this._mq.removeEventListener) this._mq.removeEventListener("change", this._onScheme);
        else if (this._mq.removeListener) this._mq.removeListener(this._onScheme);
      }
    };

    // Build the DOM once; update() mutates in place so keyboard focus is never destroyed.
    P.prototype.build = function () {
      this.textContent = "";
      var compact = this.hasAttribute("compact");

      var sw = document.createElement("div");
      sw.className = "ncp-swatches";
      sw.setAttribute("role", "radiogroup");
      sw.setAttribute("aria-label", "Color theme");
      this._swatchBtns = THEMES.map(function (t) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "ncp-swatch";
        b.setAttribute("role", "radio");
        b.setAttribute("aria-label", t.label);
        b.title = t.label;
        b._nc = t;
        b.addEventListener("click", function () { NcTheme.set(t.id, null); });
        sw.appendChild(b);
        return b;
      });
      wireArrowKeys(sw, this._swatchBtns, function (btn) { NcTheme.set(btn._nc.id, null); });
      this.appendChild(sw);

      this._modeBtns = [];
      if (!compact) {
        var md = document.createElement("div");
        md.className = "ncp-modes";
        md.setAttribute("role", "radiogroup");
        md.setAttribute("aria-label", "Color mode");
        this._modeBtns = MODES.map(function (m) {
          var b = document.createElement("button");
          b.type = "button";
          b.className = "ncp-mode";
          b.setAttribute("role", "radio");
          b.textContent = m.label;
          b._nc = m;
          b.addEventListener("click", function () { NcTheme.set(null, m.id); });
          md.appendChild(b);
          return b;
        });
        wireArrowKeys(md, this._modeBtns, function (btn) { NcTheme.set(null, btn._nc.id); });
        this.appendChild(md);
      }
    };

    P.prototype.update = function () {
      var state = NcTheme.get();
      function rove(buttons, checkedIdx) {
        buttons.forEach(function (b, i) {
          b.setAttribute("aria-checked", String(i === checkedIdx));
          b.tabIndex = (i === (checkedIdx === -1 ? 0 : checkedIdx)) ? 0 : -1;
        });
      }
      var themeIdx = THEMES.findIndex(function (t) { return t.id === state.theme; });
      this._swatchBtns.forEach(function (b) {
        b.style.background = swatchGradient(b._nc) + " border-box";
      });
      rove(this._swatchBtns, themeIdx);
      if (this._modeBtns.length) {
        rove(this._modeBtns, MODES.findIndex(function (m) { return m.id === state.mode; }));
      }
    };

    return P;
  })();

  if (!customElements.get("nc-theme-picker")) {
    customElements.define("nc-theme-picker", NcThemePicker);
  }
})();
