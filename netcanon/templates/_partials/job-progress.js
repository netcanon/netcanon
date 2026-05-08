  /* ── Job progress panel ────────────────────────────────────────────────
   * Global floating widget anchored in base.html so it survives page
   * navigation AND full page reloads (active job ID is persisted to
   * localStorage; on DOMContentLoaded we resume polling if the stored
   * job is still non-terminal).
   *
   * Per-device status levels (SOP):
   *    queued  — in the job but collector not yet called
   *    running — collector active on this device
   *    success — config saved
   *    failed  — error caught
   *
   * Events dispatched on document (listen from page-level scripts):
   *    netcanon:job-started   { detail: {jobId} }
   *    netcanon:job-progress  { detail: {job}   }   (each poll)
   *    netcanon:job-complete  { detail: {job}   }   (terminal state)
   *    netcanon:job-dismissed { detail: {jobId} }
   * ────────────────────────────────────────────────────────────────── */
  (function() {
    var STORAGE_KEY = 'netcanon.activeJob';
    var POLL_MS = 1500;
    var MAX_ERRORS = 3;
    var pollTimer = null;
    var pollErrors = 0;
    var currentJobId = null;

    /** Return true for any terminal job status. */
    function isTerminal(status) {
      return status === 'completed' || status === 'partial' || status === 'failed';
    }

    /** Icon glyph per device status. */
    function deviceIcon(status) {
      switch (status) {
        case 'success':  return '\u2713';  // ✓
        case 'failed':   return '\u2717';  // ✗
        case 'running':  return '\u27F3';  // ⟳
        case 'queued':   return '\u25CB';  // ○
        default:         return '\u2022';  // •
      }
    }

    /** Human-readable counts for the header summary. */
    function buildSummary(job) {
      var counts = { queued:0, running:0, success:0, failed:0 };
      (job.results || []).forEach(function(r) {
        if (counts[r.status] !== undefined) counts[r.status] += 1;
      });
      var done = counts.success + counts.failed;
      if (isTerminal(job.status)) {
        if (job.status === 'completed') return done + '/' + job.total_devices + ' succeeded';
        if (job.status === 'partial')   return counts.success + '/' + job.total_devices + ' succeeded (partial)';
        return counts.success + '/' + job.total_devices + ' succeeded';  // failed
      }
      return done + '/' + job.total_devices + ' complete'
           + (counts.running ? ' \u2014 running: ' + counts.running : '')
           + (counts.queued  ? ' \u2014 queued: '  + counts.queued  : '');
    }

    /** Render a single device row. */
    function renderDeviceRow(result) {
      var row = document.createElement('div');
      row.className = 'jp-row';
      row.setAttribute('data-testid', 'job-progress-device-row');
      row.setAttribute('data-host', result.host);
      row.setAttribute('data-status', result.status);
      var secs = result.duration_seconds;
      var dur = (secs && secs > 0) ? secs.toFixed(1) + 's' : '';
      row.innerHTML =
        '<span class="jp-icon jp-icon-' + result.status + '"'
          + ' data-testid="job-progress-device-status">'
          + deviceIcon(result.status) + '</span>'
        + '<span class="jp-host" data-testid="job-progress-device-host">'
          + _jpEscape(result.device_type) + ' '
          + _jpEscape(result.host) + '</span>'
        + '<span class="jp-state">' + result.status + '</span>'
        + '<span class="jp-duration" data-testid="job-progress-device-duration">'
          + dur + '</span>';
      if (result.status === 'failed' && result.error) {
        var err = document.createElement('div');
        err.className = 'jp-error';
        err.setAttribute('data-testid', 'job-progress-device-error');
        err.setAttribute('title', result.error);
        err.textContent = result.error.length > 120
          ? result.error.slice(0, 120) + '\u2026' : result.error;
        row.appendChild(err);
      }
      return row;
    }

    /** Minimal HTML escape for safe concatenation. */
    function _jpEscape(s) {
      return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    /** Replace the panel's contents with a fresh render of *job*. */
    function renderPanel(job) {
      var panel   = document.getElementById('_job-progress');
      var idEl    = document.getElementById('_job-progress-job-id');
      var sumEl   = document.getElementById('_job-progress-summary');
      var statEl  = document.getElementById('_job-progress-status');
      var bodyEl  = document.getElementById('_job-progress-body');
      var footEl  = document.getElementById('_job-progress-footer');
      var viewEl  = document.getElementById('_job-progress-view-link');
      if (!panel) return;

      idEl.textContent   = job.id.substring(0, 8) + '\u2026';
      sumEl.textContent  = buildSummary(job);
      statEl.textContent = job.status;  // back-compat: existing E2E tests read this
      panel.setAttribute('data-job-status', job.status);
      panel.style.display = '';

      bodyEl.innerHTML = '';
      (job.results || []).forEach(function(r) {
        bodyEl.appendChild(renderDeviceRow(r));
      });

      if (isTerminal(job.status)) {
        footEl.style.display = 'flex';
        viewEl.href = '/jobs#' + job.id.substring(0, 8);
      } else {
        footEl.style.display = 'none';
      }
    }

    /** Expand/collapse the body section. */
    window.toggleJobProgress = function() {
      var body    = document.getElementById('_job-progress-body');
      var foot    = document.getElementById('_job-progress-footer');
      var chevron = document.getElementById('_job-progress-chevron');
      var open = body.style.display === 'none';
      body.style.display = open ? '' : 'none';
      // Footer visibility is status-driven; don't show if body is collapsed
      // AND job is mid-flight (just hide both).
      if (!open) foot.style.display = 'none';
      else if (foot.getAttribute('data-should-show') === '1') foot.style.display = 'flex';
      chevron.classList.toggle('open', open);
    };

    /** Dismiss the panel; clears persisted state. */
    window.dismissJobProgress = function() {
      var panel = document.getElementById('_job-progress');
      panel.style.display = 'none';
      try { localStorage.removeItem(STORAGE_KEY); } catch (_) {}
      document.dispatchEvent(new CustomEvent('netcanon:job-dismissed',
        { detail: { jobId: currentJobId } }));
      currentJobId = null;
      _stopPoll();
    };

    function _stopPoll() {
      if (pollTimer !== null) { clearInterval(pollTimer); pollTimer = null; }
      pollErrors = 0;
    }

    async function _tick() {
      if (!currentJobId) { _stopPoll(); return; }
      try {
        var r = await fetch('/api/v1/backups/' + currentJobId);
        if (r.status === 404) {
          // Job no longer exists (purged/restart before persist). Stop quietly.
          dismissJobProgress();
          return;
        }
        if (!r.ok) throw new Error('HTTP ' + r.status);
        var job = await r.json();
        pollErrors = 0;
        renderPanel(job);
        document.dispatchEvent(new CustomEvent('netcanon:job-progress',
          { detail: { job: job } }));
        if (isTerminal(job.status)) {
          _stopPoll();
          // Footer gets a sticky "should-show" flag so collapse-then-expand
          // restores it without re-polling.
          document.getElementById('_job-progress-footer')
            .setAttribute('data-should-show', '1');
          document.dispatchEvent(new CustomEvent('netcanon:job-complete',
            { detail: { job: job } }));
        }
      } catch (err) {
        if (++pollErrors >= MAX_ERRORS) {
          _stopPoll();
          var sumEl = document.getElementById('_job-progress-summary');
          if (sumEl) sumEl.textContent = 'Lost contact with server';
        }
      }
    }

    /** Public entry point: start tracking a new job in the panel. */
    window.startJobProgress = function(jobId) {
      _stopPoll();
      currentJobId = jobId;
      try { localStorage.setItem(STORAGE_KEY, jobId); } catch (_) {}
      // Seed minimal render so the panel appears immediately; poll fills it in.
      renderPanel({ id: jobId, status: 'pending', total_devices: 0, results: [] });
      document.dispatchEvent(new CustomEvent('netcanon:job-started',
        { detail: { jobId: jobId } }));
      _tick();  // immediate first poll
      pollTimer = setInterval(_tick, POLL_MS);
    };

    /** Resume the panel on page load if localStorage holds a non-terminal job. */
    function _resume() {
      var jobId = null;
      try { jobId = localStorage.getItem(STORAGE_KEY); } catch (_) {}
      if (!jobId) return;
      currentJobId = jobId;
      // Do a synchronous-ish probe before showing: if the job is already
      // terminal we still render (so the user sees the result once), and
      // if it 404s we clear silently.
      fetch('/api/v1/backups/' + jobId).then(function(r) {
        if (r.status === 404) {
          try { localStorage.removeItem(STORAGE_KEY); } catch (_) {}
          currentJobId = null;
          return;
        }
        return r.json().then(function(job) {
          renderPanel(job);
          if (isTerminal(job.status)) {
            document.getElementById('_job-progress-footer')
              .setAttribute('data-should-show', '1');
          } else {
            _tick();
            pollTimer = setInterval(_tick, POLL_MS);
          }
        });
      }).catch(function() { /* network glitch on reload — just stay hidden */ });
    }

    document.addEventListener('DOMContentLoaded', _resume);
  })();
