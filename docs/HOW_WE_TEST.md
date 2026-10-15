# How We Test — The matrix-honesty discipline

If you're a network engineer evaluating Netcanon, this page is the
substrate for the trust claim.  Every assertion the project makes
about translation accuracy has a verifiable test backing it.  The
table below describes how, layer by layer.

This is the operator-facing version of the discipline that
[`docs/METHODOLOGY.md`](METHODOLOGY.md) documents at the
contributor / methodology level.

---

## TL;DR

Netcanon ships with **four test layers**.  CI runs **all four on every PR** —
unit + integration across Python 3.11–3.14, plus **E2E** (Playwright) and
**desktop** (PySide6) on 3.13.  The only maintainer-run tool below is the
cross-mesh audit, which is NOT a CI gate:

| Layer | What it tests | Speed |
|---|---|---|
| **Unit** | Every codec parser + renderer in isolation against synthetic and real-capture inputs | ~30s for the full tier |
| **Integration** | The HTTP API + migration pipeline end-to-end via FastAPI TestClient | ~60s |
| **E2E** | The browser UI via Playwright against a live Uvicorn server | ~5min |
| **Desktop** | The PySide6 + pystray desktop shell with mocked Qt | ~30s |

Plus a **fifth layer that's the differentiator**:

| Layer | What it tests |
|---|---|
| **Cross-mesh audit** | Every supported vendor pair's translation through the canonical intermediate, parsed against vendor-doc-grounded expectations |

The cross-mesh audit is what catches **silent** translation errors —
the kind where the codec produces output that *looks* valid but
quietly drops or transforms a field in a way the operator wouldn't
spot until the device behaves wrong in production.

---

## The matrix

The cross-mesh audit runs locally / on demand — it is a maintainer tool
re-generated on every codec change (per the doc-sync checklist), NOT a CI
gate on every PR (the four pytest tiers gate; the cross-mesh audit does not).
Its results live in
[`tests/fixtures/real/PHASE4_RECONCILIATION.md`](../tests/fixtures/real/PHASE4_RECONCILIATION.md)
(machine-generated; not hand-edited).

Each cell of the matrix is one (source vendor × target vendor ×
field) translation, classified into one of **8 variance classes**:

| Class | Meaning |
|---|---|
| **ALIGNED** | Source field translates to target field exactly as the vendor docs predict.  Boring; we want most cells in this class. |
| **CODEC_BUG** *(high severity)* | The translation produced a result that contradicts the vendor docs.  Either parse misread the source or render emitted wrong syntax.  **Goal: zero.**  Live count lives in [`tests/fixtures/real/PHASE4_RECONCILIATION.md`](../tests/fixtures/real/PHASE4_RECONCILIATION.md) — that file is machine-generated, so it can't drift behind code. |
| **EXPECTED_LOSSY** | The capability matrix declares this field path as `lossy` for this pair, with a cited reason (e.g. per-VRF static-route VRF discriminator drops on round-trip).  Verified against the declaration. |
| **EXPECTED_UNSUPPORTED** | The capability matrix declares this field path as `unsupported` for this pair.  No render attempted; the migrate page surfaces it via the Tier-3 banner or the unsupported-paths panel. |
| **METHODOLOGY_ISSUE_under** | The expectation under-claims — the codec actually translates correctly, but the cross-vendor expectation YAML doesn't account for it.  Methodology bug; fixed by updating the expectation. |
| **METHODOLOGY_ISSUE_over** | The expectation over-claims — declares a field "should translate" when vendor docs disagree.  Methodology bug; fixed by softening the expectation. |
| **STRUCTURAL_ONLY** | Translation produced output but the comparison fails on structural details (dict ordering, list reordering) that don't carry semantic meaning.  Comparator bug; fixed by adding a normalization rule. |
| **TRIVIAL_EMPTY** | Both source and target are empty for this field.  Not a translation; a coverage gap to fill. |

The variance-class taxonomy is **complete** — every cell falls into
one of these eight.  Drift between "expected" and "actual" gets
classified honestly rather than smoothed over.

---

## The trust claim, quantified

> Across every vendor pair we ship a fixture + cross-vendor expectation
> for, the cross-mesh audit holds **5 CODEC_BUG cells** at last run —
> each triaged as a benign modelling/structural artifact in
> [`phase4_findings_residuals.md`](../tests/fixtures/real/phase4_findings_residuals.md),
> none a genuine translation error.

That's not "we think it works"; that's "every cell that should
translate, does, by automated test against vendor-doc-grounded
expectations."

The honest follow-up: **the audit only covers cells we have
fixtures for.**  Real-world configs exercise paths the synthetic
fixtures haven't reached.  See
[`../BUG_REPORTING.md`](../BUG_REPORTING.md) for how to submit a
fixture that surfaces a path we don't yet test — that's the
highest-impact contribution to the project.

---

## What the layers actually run

### Layer 1: Unit tests

`pytest tests/unit` — pure-function tests, no I/O.

Every codec parser is exercised against:
- **Synthetic kitchen-sink fixtures** — hand-crafted to exercise
  every grammar form the codec models.  Each one has a paired
  content-assertion module (`test_synthetic_<codec>_kitchen_sink.py`)
  alongside the shared round-trip sweep, because a round-trip proves
  canonical *stability* rather than *correctness*: a fixture that
  silently lost a surface would still round-trip on the smaller tree.
  The pairing is enforced — `test_kitchen_sink_module_parity.py` fails
  for any fixture without a module, and for any public codec without a
  fixture
- **Real-capture fixtures** — sanitized configs from public
  sources (Batfish, ntc-templates, vendor docs, community forum
  shares) and operator contributions, listed in
  [`tests/fixtures/real/NOTICE.md`](../tests/fixtures/real/NOTICE.md)

Every renderer is exercised against the symmetric round-trip:
parse → render → parse → assert structural equality.

Per-codec round-trip suites live under
`tests/unit/migration/codecs/<vendor>/`.

**Port names are checked against the hardware, not against the
code.**  A port name from a target profile or a device model is
written verbatim into a generated config, and a self-consistency
check cannot catch a wrong one — the data and the codec can be wrong
together.  So the model data has guards of its own
(`test_target_profile_evidence.py`, `test_device_models_shipped.py`):
every `capture` grade is re-proven against the committed real capture
it cites, which must identify itself as that exact model; the port
names and roles of every shipped model, in every deployment mode and
with every module, are pinned from hand-typed tables in the test
rather than regenerated from the code under test; and which part
number is which model is a table, not a comment.  Where a vendor has
a detector that reads the source device from a config, it must propose
for each such capture the deployment the capture claim states — two
readings of one file that have to agree — and it is handed text made
to be slow, which it must answer in time that fits the text's length
(`test_deployment_detect.py`).  A model-to-model
translation is additionally checked, on the jobs of
`test_run_plan_with_models.py`, in two ways: for a hardware port
sharing a target name with another name (the grouping recomputed in
the test), and — reading the rendered output back with the target
codec — for an interface that is not on the port the job reports, a
port in the output the job does not report, a name that moved and is
still there, an interface carrying the addresses of two, or — on a
target that finds a port by a factory name — a paired port that
carries no address going by a name the output uses and nothing
defines.  Between two AOS-S configs, whose ports carry no address,
every VLAN list and LAG member list is compared as well: between two
stacks nothing else can tell one member's config from another's.
Each of
those checks is also handed a defective job and required to fail: a
check nobody has seen fail is not known to check anything — and the
wrapper is handed one for each of its assertions, since a check that
is never called passes every test as well.  The
cross-mesh audit below does not exercise model-to-model mapping: it
runs without declared devices.

**A renamed port must take everything with it.**  The port
translator rewrites port names in a list of places.  A list cannot
show that it is complete, and a test that walks the same list agrees
with it — a place nobody listed stays invisible to both.  So
`test_port_name_universe.py` also runs an experiment that needs no
list.  On the committed captures it sends port names to one another
through the real translator and renderer, and compares the output,
parsed again, with the unmoved output in which the same names are
sent to one another.

What that reaches is narrower than "no list" suggests, and the
module tests it rather than asserting it.  It reaches a field only
where a committed capture puts a moved name in it *and* the codec's
own parser reads the field back from its own rendering; the captures
that have no two ports to exchange are pinned by name, so the
experiment cannot shrink unnoticed.  The translator is then broken at
each place in turn: which places a capture catches is pinned, and
each of the others has a small config in the module that does.  The
module's table of places, the rename pass and the collector are
compared on a tree built from the canonical schema — a name in every
`str` and `list[str]` field — so a new field cannot be in one and not
the others; a field that holds text in another shape fails the
builder until someone says what it is.  It
moves names the device already has, so what happens to a name that
is *new* — a RouterOS port an operator calls `WAN` — is pinned by
hand beside it.  And it runs twice: without devices declared, where
a port's hardware identity must stand still, and with the device
declared on both sides, where it must follow.

**A name nobody mapped is compared with an output the translator
had no hand in.**  Both experiments above compare one output of the
translator with another — a moved run with an unmoved one — so a
name the translator changes in BOTH cancels out, and the unmoved run
pins every port to its own name, which is an entry and keeps the
translator's own guess from running at all.  That is how a job from
a vendor to itself could rename and drop ports, and put a
sub-interface on its parent, past every guard.
`test_units_follow_their_port.py` reads the rendered output of jobs
run with an empty port map, as the page and `POST /plan` run them.
Between two configs of one codec — every committed capture and
kitchen sink — the output must be the bare pipeline's (parse and
render, no translator), as text and parsed again.  Across vendors —
each grammar that names a sub-interface `<port>.<unit>`, onto every
codec — each sub-interface is found in the output by its address,
and has to be on an interface of its own, named after what its port
became; where its 802.1Q tag cannot be read back, the job must not
say `completed`.  Where the unit is not in the output at all —
dropped with a port the target has no name for — the validation
report has nothing to list, and the job, run as `POST /plan` runs
it, must be `partial` and name the port and its units (the next
paragraph is about that status).  One thing is pinned as it is: a
tag the source parser does not read (AOS-CX, OS10) between two
configs of that vendor is lost there as on every path, with nothing
in the job to say so, and the pin keeps the documents which say so
true.  The same module keeps the list of the codecs whose own
names do not come back from their classifier and formatter, which
is the reason a same-vendor job no longer asks them.
**What a default can spell is read as text.**  Most checks of an
output read it back with the target's own parser.  That is blind to
one thing: a parser reads its own default.  A trunk with no allowed
line is every VLAN on some platforms and none on others, and for a
long time the tree had one value for both — so a trunk that allowed no
VLAN was written as a trunk with no allowed line, which the target's
parser read back as the same value the source had, and every wrong
output agreed with itself.  `test_a_trunk_says_none_nothing_or_all.py`
therefore reads the output twice: with the target's parser, and as
TEXT, with a reader written in the test for each target's grammar
(a trunk stanza with no allowed line is every VLAN on some targets
and none on another; the ids spelled out are not the platform's form
for every VLAN).  Every public codec is a target; the sources say
none, nothing and all in their own grammar; and what each statement
means is written out in the test by hand and compared with the table
the parsers read, so that a correction is made in both places on
purpose.  The gaps the code does not close are named sets in the
module, compared for equality with what is measured: the change that
closes one fails there until its pin is taken out.  The readers are
handed each form they must tell apart, and a new codec fails the
module until it says what a trunk with no list carries on its
platform.

**A port's VLANs are looked for in the output, not in the tree.**
The canonical tree states a port's VLAN membership twice — on the
VLAN and on the port — and two trees that agree with each other say
nothing about a line.  An AOS-S config names most of its ports only
in its VLANs' lists; the parser made no interface record for them,
most renderers write a port's VLANs from its record, and a switch's
access ports came out on NX-OS with no line at all, in a job that
said `completed`, while the validation report counted the
membership as supported and the cross-mesh audit held the drift as
an expected loss.  `test_vlan_members_reach_the_output.py` runs
every committed capture onto every codec as `POST /plan` runs it and
looks for each membership the source tree holds in the OUTPUT, three
ways: with the target's parser; as text, with a reader the test owns
for each grammar that puts a VLAN on a port, and the two readings
must agree; and by the port's name in a line, which asks no grammar
at all.  A membership may be missing only where the job lists the
port, where the port's own stanza says so in a `review:` line, or —
on a target that writes no port VLANs at all — where the validation
report lists a path that states that membership; anything else
fails, and so does a membership the output has and the source does
not.  What such a report accounts for is the membership and not the
port: on those targets too the port's name is looked for in a line,
or a renderer that wrote no stanza for a port with nothing it can
say of it would lose the port in a job whose report had not moved.
The parsers are held to the shape the renderers rely on: a
port that a VLAN's list or a LAG's member list names has a record,
on every capture, and on a config typed for each grammar that states
a LAG's members in a list.  What the module knows of and does not
mend is in named sets, compared for equality with what is measured.
It cannot see a membership the source parser never put in the tree:
that is missing from both sides.

**A convention of the tree is not checked by reading the tree that
way.**  A trunk states which VLAN it carries untagged and which VLANs
it carries, and the platforms differ on whether the second statement
names the first: a native line beside an allowed line that may leave
the VLAN out (IOS-XE, NX-OS, EOS, AOS-CX, Junos), an access VLAN
beside a list of tagged VLANs (OS10), `untagged` ports listed VLAN by
VLAN (AOS-S).  The tree kept each as its text had it, and every AOS-S
and OS10 trunk with an untagged VLAN was written for the first five
with a native line beside a list that left the VLAN out -- which on
AOS-CX, by HPE's own sentence, drops the port's untagged traffic --
in jobs that said `completed`.  The check above did not see it,
because it read a native VLAN as a membership whatever the list
said, on the source's tree and on the output parsed again: the two
always agreed.  `test_the_list_holds_the_native_vlan.py` reads what
a DEVICE carries untagged on a port, each side by its own platform's
grammar, from a table written in the test by hand and compared with
the one the codecs read; the output is read twice, parsed again and
as text.  It runs every committed capture of a switch onto every
switch, and small configs for each shape of trunk through every
pair, with what the source carries written beside each by hand.
Onto AOS-S, where a native VLAN the source's list leaves out has no
line to be written as, it also looks for the `; review:` line that
says so, in the stanza of that VLAN and for that port -- the line
WHOLE, typed out in the test, and in the form for what the output
makes of the name (a port, or a trunk group and a port on a `trunk`
line): a review line pinned by a few of its words can gain a claim
about a device that no page supports, and pass.  The VLAN pane's
map is held to the same question by a test with no list of cases
(`test_a_vlan_drop_and_a_trunks_list.py`): over every map of a few
ids, no port comes to carry untagged a VLAN it did not carry
untagged before.
A trunk that states no native VLAN is read by its platform's default
there: the guard holds every tree, the source's and the output's
parsed again, to having VLAN 1 as the native VLAN of such a trunk of
IOS-XE, NX-OS, EOS or AOS-CX whose list holds VLAN 1 -- and to NOT
having it on a port that does not say it is a trunk, which it reads
from the text and from no parser -- and its own readers add that
default to an output's text, which states less than the switch
does.  A port with no untagged VLAN is written each of those four
targets' form for that, and is read back by the same readers, which
know each platform's words for a native VLAN sent tagged.  Where an
IOS-XE or NX-OS output cannot say it of every trunk, the port is
left to the target's default under a review line: those cells are
pinned one by one and compared for equality, and the guard holds
each to having that line, whole, and no other port to having one.
What it cannot see is in its docstring and in the known limitations:
the default VLAN of an OS10 switch, which no trunk states, and what
an AOS-S port is in when no `untagged` line names it.

**A status is checked against the output, not against the warning
that should have moved it.**  With no devices declared, a job in
which two source names ended on one name, a name was dropped because
the target has none for it, or a name the translator could not read
was left as the source config has it, said so in a warning and said
`completed`.  It is `partial` now, and
`test_run_plan_checked_names.py` holds that three ways.  The
condition is tested branch by branch on small configs: two ports, a
port and a logical name, two logical names, a dropped port, a
dropped tunnel and a dropped hardware switch, a name left as it was
and each entry that decides one (a name, the name itself, `null`), a
name left that is the target's own (and each thing that makes it
not: another kind, a hardware port, another spelling, a platform of
free-text names on either side), a
Junos reference to unit 0 of an interface (one interface, not two)
beside a VyOS `vif 0` (two), a source whose names have letter case.
Every committed capture is then run onto every codec with no port
map, and the number of jobs that move from `completed` to `partial`
is pinned by source codec and by reason; no job may move any other
way, none between two configs of one codec may list a name, and
nothing of a job but its status, its sentence and the three fields
that carry the names may differ from what the pipeline returned
before.  And for every job that is still `completed`, the rendered
output is read back with the target's own parser and its interfaces
are found **by their addresses**, which the translator never
touches: none may carry the addresses of two source interfaces, and
no interface of the source that has an address — a port, a
loopback, a hardware switch — may be missing; and the translator's
own warnings may name no interface of the source left under a
foreign name.  Whether a name that was left is the target's own,
the read-back decides from the text of the output and a table
typed by hand — the line each target opens a VLAN's interface
with — and over every job, `completed` or not, a name the job does
not list has to pass that reading; how many do is pinned by pair
of codecs, so a name that leaves the list shows as a number that
moved.
That read-back asks nothing of the function it guards and does not
take its list of names — a guard that groups the names the engine
hands it shares the engine's blind spot, and one that asks the
source classifier which interfaces are ports shares the
classifier's.  It is itself handed a job with each defect, and has
to complain; and it counts how often it was asked, so that a loop
which reads no job back cannot pass.  What it can see is what an
address shows: two access ports on one name, with no address on
either, are outside it, and are the condition's own tests'.

**What it costs to read a config is searched for, not listed.**  A
config is whatever was pasted, and code can take time that grows with
the square of a run in it.  `test_untrusted_text_cost.py` keeps no list
of patterns to avoid.  For every regex the product holds — literals in
the source, compiled patterns and pattern-shaped strings a module
keeps, patterns in the shipped device definitions — it builds texts
from that pattern's own structure (what it needs before one of its
repeats, then a run that repeat accepts, then something the rest
refuses) and reads the time at growing sizes.  And it times every
public codec's `probe` and `parse` on a real capture with a run put
into it: of empty lines, of lines that go on, of white space inside
each of its own lines.  One shape none of those texts has is a config
with MANY stanzas, read by a handler that looks through everything the
earlier lines made: that search is `tools/stanza_cost_search.py`, which
writes every line and block of every capture many times over, takes
minutes and is run by hand; each handler it found is pinned in the
test module with a text of its own.  So is each record that was given
many lines (the addresses of one interface, looked through before each
was added) and each piece of work after the parse that was found doing
the same; and for the first of those the module reads the source
itself, with no clock, for a list one function both looks through and
adds to.  Each check is also handed
something slow, and has to say so.  It is a search and not a proof — its first version
timed only whole lines and short units, passed, and missed three of
the four shapes it now builds — so a slow path it does not reach is to
be expected, and the shape that reaches it is added when it is found.

**What a config may make is limited, and the limits are tested three
ways.**  A range is a few bytes that stand for thousands of entries, so
the product counts what a request makes and refuses past a limit
(`netcanon/migration/limits.py`).  `test_limits.py` first tests each
limit: a text under it is translated exactly as with no limit at all,
and a text over it is refused BEFORE what it asks for is made — the
refusal says whether the count came before or after, and the bytes
held on the way are counted.  Then completeness, by experiment: every
codec's parse is run past a deadline and has to stop (time there
passes only when the clock is looked at, so nothing depends on a
machine's speed); every line of every committed capture has to be
walked by a loop that looks at the clock; a tree whose entries nothing
counted is still refused.  Then by reading the source, each rule with
a table that a new case fails until it is in: every loop over a
config's lines, every `range(...)` in a module under `codecs/`, every
broad exception handler on the way.  A separate test holds every limit
a document prints to the code's (`test_limits_docs_truth.py`).
Requests at once -- under the demo's limits a server works on one at a
time -- are tested with an event the first request holds, never a
sleep: the second is seen in the line and then seen to run, and "busy"
is read on every surface, the pages included.  Clients that do not
behave are tested over a real socket and against a server the test
plays itself: one that sends its headers and no body, one that leaves,
one that never reads its answer.  A job's answer is
compared byte for byte with what the framework would have sent
(`test_job_answer.py`).  The memory itself is measured in a container
with an instance's limits, by hand, and recorded in
`docs/demo-plan/07-budget.md`: no test here can see a megabyte.  What
none of this shows: that the numbers are right for a device nobody
here has a capture of.

### Layer 2: Integration tests

`pytest tests/integration` — HTTP API surface via FastAPI
`TestClient`, no real device interaction.  The backup collector
is mocked at a single entry point (`get_collector`) so tests
exercise the full migration pipeline without touching real SSH /
NETCONF.

### Layer 3: E2E tests

`pytest -m e2e` — Playwright against a live Uvicorn server.
Exercises the migrate-page flows: paste source, pick target, run
plan, view diff, accept/decline review comments.

For the rename modal's device pickers the tier also holds what an
operator can **see and reach**, not only what the page's attributes
say: that the table and the Apply button are still inside the modal
and under the mouse on a laptop screen with a stack of ten on each
side; that a state's colour is the colour that was painted (read from
a screenshot — a class name is not a colour, and the theme's
translucent tints make a computed style something else again); that
the request Apply sends is what the screen showed, read off the wire;
and what the page does when the server does not answer, answers late,
or answers for a job that is no longer on the page.  These tests were
written after a review broke the page in a hundred small ways and
found that most of the breaks passed.

### Layer 4: Desktop tests

`pytest tests/desktop` — PySide6 + pystray mocked at a shared
conftest so the desktop shell logic gets exercised without a real
display.

### Layer 5: Cross-mesh audit

`python tools/run_full_mesh.py --matrix` — generates
`tests/fixtures/real/CROSS_MESH_RESULTS.md` (mechanical
parse-render drift across every (source × target × fixture)
permutation).

The source side of each comparison is a snapshot taken *before* the
render, not the tree the render was handed.  Rendering is not
guaranteed to leave its argument alone — the port-centric render paths
synthesise missing interfaces into the tree in place — and an audit
whose input can be edited by the code it measures is not measuring
anything.  Pinned by
`tests/unit/tools/test_run_full_mesh_source_snapshot.py`.

`python tools/run_phase4_reconciliation.py` — applies the 8-class
variance taxonomy and generates
`tests/fixtures/real/PHASE4_RECONCILIATION.md` (the matrix).

**What this layer structurally cannot see.**  The audit compares a
parsed source against a parsed round-trip, so it only measures what
`parse()` produced.  Anything discarded *inside* parse is absent from
both sides of the comparison, and the cell scores ALIGNED — the audit
reports perfect fidelity precisely because the data never reached it.

This is not hypothetical.  Until 2026-09 the port-centric codecs
dropped every VLAN that appeared only in a `switchport trunk allowed`
list; 45 real VLANs across the committed corpus vanished at parse
time, `/vlans/vlan/id` was declared `supported` on all six codecs, and
every affected cell scored ALIGNED.  A user found it by reading a
translation, which no gate here would have done.

The defence is not a bigger mesh — it is that a rule deciding what
parse keeps must carry its own guard measured against the corpus,
independently of the audit.  `test_trunk_allowed_specificity_bound.py`
is the worked example: it re-derives the threshold's evidence from the
committed captures on every run rather than trusting a constant.  When
you add a heuristic that discards input, assume the mesh will endorse
it and write that guard.

Both run locally / on demand — the cross-mesh audit is a maintainer tool,
NOT a CI gate (the four pytest tiers gate every PR; the cross-mesh audit
does not).  The
matrix gets regenerated on every codec change per the
[doc-sync checklist](../AGENTS.md#documentation-sync-checklist).

---

## Why this matters

Most config-translator tools in this space have one of two failure
modes:

1. **Over-claim accuracy + silently drop content.**  Operator runs
   the tool, gets output that looks right, deploys to a device,
   and discovers a missing field two weeks later in a production
   incident.
2. **Under-claim accuracy + over-warn.**  Operator runs the tool,
   gets warnings on every line, tunes them out, and back to (1).

The matrix-honesty discipline avoids both.  Every field is one of:

- **Supported** — translates correctly, audit-verified.
- **Lossy** — translates with a cited boundary; the boundary is
  visible to the operator via review comments.
- **Unsupported** — explicitly out of scope (Tier 3); the migrate
  page surfaces it via the dropped-Tier-3-sections banner.

There's no fourth state.  No "we think it might work."  No
"deprecated, but kept around."

---

## See also

- [`CAPABILITIES.md`](CAPABILITIES.md) — operator-facing capability
  matrix (the source of truth this page narrates)
- [`METHODOLOGY.md`](METHODOLOGY.md) — the contributor / engineering
  version of the same discipline (with worked-example citations
  into the live tree)
- [`vendors/README.md`](vendors/README.md) — per-vendor "what works
  for me?" pages
- [`../tests/fixtures/real/RESULTS.md`](../tests/fixtures/real/RESULTS.md)
  — live per-codec certification state
- [`../tests/fixtures/real/PHASE4_RECONCILIATION.md`](../tests/fixtures/real/PHASE4_RECONCILIATION.md)
  — live cross-mesh audit
- [`../tests/README.md`](../tests/README.md) — test-suite layout
  for contributors
- [`../BUG_REPORTING.md`](../BUG_REPORTING.md) — how to submit a
  fixture that surfaces a path we don't yet test
