# Aruba AOS-S real captures — BLOCKED

**Status:** No permissively-licensed public captures of Aruba AOS-S
(formerly HP ProCurve) running-config have been located at the time
of the first real-capture validation pass.

## What was searched

* Aruba/HPE org repos on GitHub (aruba, HewlettPackard, HPENetworking)
* NTC-Templates `tests/hp_procurve/` — only has `show <cmd>` output
  fixtures, no full running-config captures
* Aruba's `central-sample-bulk-configurations` repo — has a 5-member
  stack template but it's a `%variable%`-interpolated template with
  `%if%/%endif%` directives, not directly parseable AOS-S config
* aruba/aos-switch-ansible-collection — no sample configs

## Why we're not synthesising one

Real-capture validation earns a codec the right to claim its parser
survives "the real world".  A fixture I write, even if it mimics
AOS-S structural markers faithfully, exercises only the grammar I
already had in mind when I wrote the parser — the whole point of
this harness is to surface grammar the author didn't anticipate.

## How to unblock

Drop any permissively-licensed AOS-S running-config snippet into this
directory (2+KB, must include `; J####A Configuration Editor` banner
or other AOS-S structural marker to confirm provenance).  The
parametrized harness in `tests/unit/migration/test_real_captures.py`
picks it up automatically — no code changes needed.  Update
`NOTICE.md` in the parent dir with origin URL + license, then
re-run `pytest tests/unit/migration/test_real_captures.py -v -s`.

Candidate sources to try:

* **Vendor-authored migration guides** — HPE / Aruba migration docs
  sometimes include sanitised customer config snippets.
* **Reverse-engineering AOS-S templates** — Aruba Central's
  `central-sample-bulk-configurations` has templates we could
  render with a placeholder-substitution script; commit the
  rendered output with provenance pointing at both the template and
  the substitution script.
* **Community-sanitised configs** — r/Networking, Network
  Engineering Stack Exchange, HP networking forums.
* **GNS3 / EVE-NG saved configs** — occasionally published on
  GitHub under permissive licenses.
