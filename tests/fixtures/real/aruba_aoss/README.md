# Aruba AOS-S real captures — rendered from Aruba Central template

**Status:** *partially unblocked* via upstream-template rendering.
One fixture committed; a real deployed AOS-S capture is still the
preferred long-term answer.

## What's here

`aruba_central_5memberstack_rendered.cfg` — the output of
`scripts/render_aruba_central_template.py` applied to Aruba Central's
`5MemberStack` bulk-configuration template
([aruba/central-sample-bulk-configurations](https://github.com/aruba/central-sample-bulk-configurations)
`ArubaOS-Switch Templates/5MemberStack - Template/5memberStack - Template.txt`).

Provenance chain:

    Aruba Central template (BSD)
        -> scripts/render_aruba_central_template.py (in-tree)
        -> aruba_central_5memberstack_rendered.cfg

The script substitutes defensible defaults for every `%variable%`
(hostname, IPs, VLAN IDs, etc.), takes sensible branches through
`%if% / %else% / %endif%` directives, and post-processes to dedent
top-level stanzas that the template's nested conditionals indented.

## Do-better note

A rendered template still only exercises grammar Aruba's template
author anticipated — strictly less valuable than a sanitised capture
from a deployed switch (which could surface corner-case grammar even
Aruba's template authors didn't expect to see).

Swap this fixture for a real capture when one becomes available.
Candidate sources:

* **Vendor-authored migration guides** — HPE / Aruba migration docs
  sometimes include sanitised customer config snippets.
* **Community-sanitised configs** — r/Networking, Network Engineering
  Stack Exchange, HP networking forums.
* **GNS3 / EVE-NG saved configs** — occasionally published on GitHub
  under permissive licenses.

The parametrized harness at `tests/unit/migration/test_real_captures.py`
picks up every `*.txt` / `*.cfg` / `*.xml` / `*.conf` / `*.rsc` under
this directory automatically — no code changes needed to add more.

## Re-rendering

If the upstream template changes and you want to regenerate:

```
curl -o /tmp/tpl.txt \\
    'https://raw.githubusercontent.com/aruba/central-sample-bulk-configurations/master/ArubaOS-Switch%20Templates/5MemberStack%20-%20Template/5memberStack%20-%20Template.txt'
python scripts/render_aruba_central_template.py \\
    --template /tmp/tpl.txt \\
    --output tests/fixtures/real/aruba_aoss/aruba_central_5memberstack_rendered.cfg
```

The upstream template currently has an off-by-one (1462 `%if%` vs.
1461 `%endif%` as of this writing) — the script auto-closes the
unclosed block with a stderr warning and renders the best-effort
result.
