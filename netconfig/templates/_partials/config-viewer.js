  /* ── Config viewer modal ──
   * Features:
   *   - Syntax highlighting (Cisco / Fortigate / Mikrotik / OPNsense XML)
   *     inferred from the file extension; unknown extensions fall back to
   *     escaped plain text.
   *   - In-modal incremental search with match counter and prev/next
   *     navigation (Enter / Shift+Enter, or the ▲ / ▼ buttons).
   *   - The raw config text is preserved between renders so the search can
   *     be re-applied without another network round trip.
   */
  var _cvRawText = '';           // raw (unescaped) content of the current config
  var _cvExt = '';               // lowercased file extension for highlighting
  // One entry per LOGICAL match; each is a group of <mark> elements
  // because a single match may span syntax-highlight boundaries and thus
  // produce multiple adjacent <mark> nodes in the DOM.
  //   [{ marks: [HTMLMarkElement, ...], first: HTMLMarkElement }, ...]
  var _cvMatches = [];
  var _cvIdx = -1;               // index of the currently highlighted match

  /**
   * Open the viewer modal, fetch the named config, apply syntax highlighting,
   * and focus the search input so the keyboard is immediately useful.
   *
   * @param {string} filename - Bare filename returned by GET /api/v1/configs/.
   */
  async function viewConfig(filename) {
    var modal  = document.getElementById('_config-viewer');
    var pre    = document.getElementById('_config-viewer-pre');
    var title  = document.getElementById('_config-viewer-title');
    var search = document.getElementById('_config-viewer-search');
    title.textContent = filename;
    pre.textContent   = 'Loading\u2026';
    _cvRawText = '';
    _cvMatches = [];
    _cvIdx = -1;
    search.value = '';
    _cvUpdateCount();
    modal.style.display = 'flex';
    try {
      var res = await fetch('/api/v1/configs/' + encodeURIComponent(filename));
      if (!res.ok) { pre.textContent = 'Error ' + res.status + ': ' + res.statusText; return; }
      _cvRawText = await res.text();
      _cvExt = (filename.split('.').pop() || '').toLowerCase();
      pre.innerHTML = _cvRenderHighlighted(_cvRawText, _cvExt);
      search.focus();
    } catch(e) { pre.textContent = 'Network error: ' + e.message; }
  }

  /**
   * Hide the modal and release any cached state.  Safe to call twice.
   */
  function closeConfigViewer() {
    document.getElementById('_config-viewer').style.display = 'none';
    _cvRawText = '';
    _cvMatches = [];
    _cvIdx = -1;
  }

  /**
   * Escape characters that are significant in HTML so user data can be
   * safely concatenated into innerHTML.
   *
   * @param {string} s
   * @returns {string}
   */
  function _cvEscape(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  /**
   * Syntax-highlight *text* based on *ext* and return an HTML string.
   * Dispatches to a language-specific tokenizer; unknown extensions are
   * returned as escaped plain text with no colouring.
   *
   * @param {string} text - Raw config content.
   * @param {string} ext  - Lowercased file extension (e.g. "cfg", "xml").
   * @returns {string} HTML with <span class="tok-*"> markup.
   */
  function _cvRenderHighlighted(text, ext) {
    if (ext === 'xml') return _cvHighlightXml(text);
    if (ext === 'cfg' || ext === 'conf' || ext === 'txt' || ext === 'log') {
      return _cvHighlightConfig(text);
    }
    return _cvEscape(text);
  }

  /* ── Token regexes ────────────────────────────────────────────────────
   * Each language uses one combined regex with alternation so the scan is
   * a single pass — this avoids nested-span bugs you get when you chain
   * multiple .replace() calls.
   * ──────────────────────────────────────────────────────────────────── */

  /* Cfg/conf/txt (Cisco, Fortigate, Mikrotik superset) */
  var _CV_CONFIG_TOKEN = new RegExp([
    '("[^"\\n]*")',                                       // 1: string
    '\\b(\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}(?:/\\d+)?)\\b',  // 2: IPv4 / CIDR
    '\\b(interface|hostname|ip|ipv6|router|vlan|version|enable|no|' +
      'config|set|edit|end|next|unset|crypto|access-list|access-group|' +
      'permit|deny|line|username|password|service|boot|route|' +
      'bgp|ospf|eigrp|rip|description|shutdown|duplex|speed|mtu)\\b',  // 3: keyword
    '\\b(\\d+)\\b'                                        // 4: bare number
  ].join('|'), 'g');

  /* XML */
  var _CV_XML_TOKEN = new RegExp([
    '(<!--[\\s\\S]*?-->)',                                // 1: comment
    '(</?[\\w\\-:]+)',                                    // 2: tag open/close
    '(\\b[\\w\\-:]+)(?==")',                              // 3: attribute name (lookahead)
    '("[^"\\n]*")'                                        // 4: attribute value
  ].join('|'), 'g');

  /**
   * Tokenize a config-style file (Cisco / Fortigate / Mikrotik).  Comment
   * lines (``!`` or ``#``) are handled line-by-line so keywords inside
   * them don't get re-coloured.
   */
  function _cvHighlightConfig(text) {
    return text.split('\n').map(function(line) {
      if (/^\s*[!#]/.test(line)) {
        return '<span class="tok-comment">' + _cvEscape(line) + '</span>';
      }
      return _cvTokenize(line, _CV_CONFIG_TOKEN, _cvConfigWrap);
    }).join('\n');
  }

  /** Wrap a config-line regex match group into the right span. */
  function _cvConfigWrap(m) {
    if (m[1]) return '<span class="tok-string">'  + _cvEscape(m[1]) + '</span>';
    if (m[2]) return '<span class="tok-ip">'      + _cvEscape(m[2]) + '</span>';
    if (m[3]) return '<span class="tok-keyword">' + _cvEscape(m[3]) + '</span>';
    if (m[4]) return '<span class="tok-number">'  + _cvEscape(m[4]) + '</span>';
    return _cvEscape(m[0]);
  }

  /** Tokenize XML. */
  function _cvHighlightXml(text) {
    return _cvTokenize(text, _CV_XML_TOKEN, function(m) {
      if (m[1]) return '<span class="tok-comment">' + _cvEscape(m[1]) + '</span>';
      if (m[2]) return '<span class="tok-tag">'     + _cvEscape(m[2]) + '</span>';
      if (m[3]) return '<span class="tok-attr">'    + _cvEscape(m[3]) + '</span>';
      if (m[4]) return '<span class="tok-string">'  + _cvEscape(m[4]) + '</span>';
      return _cvEscape(m[0]);
    });
  }

  /**
   * Shared single-pass tokenizer.  Walks *text* with *re* and lets *wrap*
   * decide how to render each match; content between matches is HTML-escaped.
   */
  function _cvTokenize(text, re, wrap) {
    re.lastIndex = 0;
    var out = '', last = 0, m;
    while ((m = re.exec(text)) !== null) {
      if (m.index > last) out += _cvEscape(text.slice(last, m.index));
      out += wrap(m);
      last = m.index + m[0].length;
    }
    if (last < text.length) out += _cvEscape(text.slice(last));
    return out;
  }

  /* ── Search ─────────────────────────────────────────────────────────── */

  /**
   * Scan the rendered <pre> for *query* (case-insensitive) and wrap every
   * occurrence in one or more ``<mark>`` elements.
   *
   * CROSS-NODE MATCHING: the syntax highlighter fragments the original
   * text into many text nodes interleaved with ``<span class="tok-*">``
   * elements, so a query like ``64:ff9b`` or ``hostname Router`` spans
   * DOM boundaries and a naive per-text-node search misses it.  This
   * implementation flattens the entire <pre> into a single string (with
   * a segment map back to the original text nodes), finds matches in the
   * flat string, and wraps each match across whatever boundaries it
   * crosses — producing one ``<mark>`` element per affected text-node
   * slice, grouped as a single logical match for navigation.
   *
   * Matches are processed in REVERSE document order so the splits of
   * later matches don't invalidate the segment offsets for earlier ones.
   *
   * Previously-inserted marks are unwrapped first so the function is
   * idempotent.  The first match becomes the "current" match and is
   * scrolled into view.
   *
   * @param {string} query - User-entered search term; empty clears marks.
   */
  function _cvSearch(query) {
    var pre = document.getElementById('_config-viewer-pre');
    _cvClearMarks(pre);
    _cvMatches = [];
    _cvIdx = -1;
    if (!query) { _cvUpdateCount(); return; }

    // Flatten all text nodes into one string; remember each node + its
    // absolute start offset so we can map matches back to the DOM.
    var walker = document.createTreeWalker(pre, NodeFilter.SHOW_TEXT, null);
    var segs = [];  // [{ node, start }]
    var flat = '';
    while (walker.nextNode()) {
      var n = walker.currentNode;
      segs.push({ node: n, start: flat.length });
      flat += n.nodeValue;
    }

    // Collect absolute [start, end) spans for every occurrence of query.
    var qLower = query.toLowerCase();
    var flatLower = flat.toLowerCase();
    var hits = [];
    var idx = flatLower.indexOf(qLower);
    while (idx >= 0) {
      hits.push({ start: idx, end: idx + qLower.length });
      idx = flatLower.indexOf(qLower, idx + qLower.length);
    }

    // Wrap in reverse so earlier offsets stay valid after splitText calls
    // on later-in-document matches.  After wrapping, prepend to
    // _cvMatches so the final list is in document order.
    for (var hi = hits.length - 1; hi >= 0; hi--) {
      var marks = _cvWrapSpan(segs, hits[hi].start, hits[hi].end);
      if (marks.length) {
        _cvMatches.unshift({ marks: marks, first: marks[0] });
      }
    }

    if (_cvMatches.length > 0) configViewerNav(1);
    _cvUpdateCount();
  }

  /**
   * Wrap every text-node slice intersecting [*absStart*, *absEnd*) in a
   * ``<mark>`` element and return the list of mark elements (in document
   * order).  Handles single-node matches, matches starting mid-node,
   * ending mid-node, and spans that cover multiple whole nodes.
   *
   * @param {Array} segs   - Segment map from _cvSearch.
   * @param {number} absStart - Absolute offset in the flat text (inclusive).
   * @param {number} absEnd   - Absolute offset in the flat text (exclusive).
   * @returns {HTMLMarkElement[]} All wraps produced for this one match.
   */
  function _cvWrapSpan(segs, absStart, absEnd) {
    var marks = [];
    for (var si = 0; si < segs.length; si++) {
      var seg = segs[si];
      var segStart = seg.start;
      var nodeLen = seg.node.nodeValue.length;
      var segEnd = segStart + nodeLen;
      if (segEnd <= absStart) continue;       // segment is entirely before the match
      if (segStart >= absEnd) break;          // segment (and all later ones) are after
      var localStart = Math.max(absStart, segStart) - segStart;
      var localEnd   = Math.min(absEnd,   segEnd)   - segStart;
      var node = seg.node;
      // Chop the tail (characters after the match) into a new sibling first
      // so the subsequent splitText index still makes sense on the retained
      // prefix+match portion.
      if (localEnd < node.nodeValue.length) {
        node.splitText(localEnd);
      }
      var middle;
      if (localStart > 0) {
        middle = node.splitText(localStart);
      } else {
        middle = node;
      }
      var mark = document.createElement('mark');
      middle.parentNode.replaceChild(mark, middle);
      mark.appendChild(middle);
      marks.push(mark);
    }
    return marks;
  }

  /**
   * Remove every ``<mark>`` under *root*, merging the split text nodes back
   * together so the DOM ends up in the same shape it had before the search.
   */
  function _cvClearMarks(root) {
    var marks = root.querySelectorAll('mark');
    for (var i = 0; i < marks.length; i++) {
      var m = marks[i], p = m.parentNode;
      while (m.firstChild) p.insertBefore(m.firstChild, m);
      p.removeChild(m);
      p.normalize();
    }
  }

  /**
   * Move to the next / previous search match.  Wraps around at either end.
   * A logical match may be multiple ``<mark>`` elements (cross-span
   * matches), so the ``current`` class is toggled on every element in the
   * group and scrollIntoView targets the first.
   *
   * @param {number} dir - ``+1`` for next, ``-1`` for previous.
   */
  function configViewerNav(dir) {
    if (_cvMatches.length === 0) return;
    var prev = _cvMatches[_cvIdx];
    if (prev) prev.marks.forEach(function(m) { m.classList.remove('current'); });
    _cvIdx = (_cvIdx + dir + _cvMatches.length) % _cvMatches.length;
    var curr = _cvMatches[_cvIdx];
    curr.marks.forEach(function(m) { m.classList.add('current'); });
    curr.first.scrollIntoView({ block: 'center' });
    _cvUpdateCount();
  }

  /** Refresh the "N / M" match counter and enable/disable nav buttons. */
  function _cvUpdateCount() {
    var el     = document.getElementById('_config-viewer-search-count');
    var search = document.getElementById('_config-viewer-search');
    var prev   = document.querySelector('[data-testid="config-viewer-search-prev"]');
    var next   = document.querySelector('[data-testid="config-viewer-search-next"]');
    var total  = _cvMatches.length;
    if (!search.value) {
      el.textContent = '';
    } else if (total === 0) {
      el.textContent = 'No matches';
    } else {
      el.textContent = (_cvIdx + 1) + ' / ' + total;
    }
    prev.disabled = total === 0;
    next.disabled = total === 0;
  }

  document.addEventListener('DOMContentLoaded', function() {
    var search = document.getElementById('_config-viewer-search');
    if (!search) return;
    search.addEventListener('input', function(e) { _cvSearch(e.target.value); });
    search.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        configViewerNav(e.shiftKey ? -1 : 1);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        if (e.target.value) { e.target.value = ''; _cvSearch(''); }
        else closeConfigViewer();
      }
    });
  });

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      // Don't double-close if the search input already handled it.
      var active = document.activeElement;
      if (active && active.id === '_config-viewer-search') return;
      closeConfigViewer();
    }
  });
