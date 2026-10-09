# Adding a device model — families, modes and port inventories

Use this when you want netcanon to know what ports a device actually
has, by name, in each way it can be deployed — so a migration can pair
the ports of two devices by position instead of guessing from the shape
of their names.

See also: [`adding-a-target-profile.md`](adding-a-target-profile.md)
(the older, flat per-model registry, and where the rule about port
names comes from), [`../ARCHITECTURE.md`](../ARCHITECTURE.md) ("Device
models and inventories"), and
[`../netcanon/migration/device_models.py`](../netcanon/migration/device_models.py)
(the schema, with a worked YAML example in its module docstring).

---

## What you are describing

A port's name is not a property of the port alone.  It depends on:

* the **model** — how many ports, in what order;
* the **modules fitted** — an uplink bay may be empty, or hold a
  four-port module, or a one-port one;
* the **deployment mode** — an Aruba 2930F port is `24` standalone and
  `1/24` as a VSF member; a 2930M's first uplink is `A1` with stacking
  disabled and `1/A1` with it enabled.

So the registry does not list names.  It lists **facts**, and a naming
rule turns them into names for one stated deployment:

| You write, in YAML | It means |
|---|---|
| a **family** file | models that share a naming rule, a set of modes and a set of modules |
| a **model** | one part number's fixed panel — port groups in port-number order — and its module bays |
| a **mode** | a deployment state that changes names (`standalone`, `vsf`, `stacked`) |
| a **module** | what a bay can hold, and the ports it contributes |
| a **capture claim** | a committed real capture, and the exact deployment it is of |

and in code, beside the vendor's codec, there is one small **naming
rule** per naming grammar — not per product line.  Every AOS-S
fixed-port switch is the single `aoss` rule
(`physical_port_name` in
[`codecs/aruba_aoss/port_names.py`](../netcanon/migration/codecs/aruba_aoss/port_names.py)).

A **deployment** — a mode plus an ordered list of members, each a model
with its modules — compiles to an **inventory**: every port that
exists, with its real name, its role, its position and how well its
name is established.

Family files live in
[`netcanon/definitions/library/model_families/`](../netcanon/definitions/library/model_families/),
one per family, named `<vendor>_<family in lower case>.yaml`.  Read the
ones that ship before writing another; they are commented for exactly
that purpose.

---

## The rule that matters most

**Every value comes from the hardware, never from the formatter, a
sibling model, or recall.**  This is the Hard Rule in
[`../AGENTS.md`](../AGENTS.md) on where a port id may come from, and it
applies to this data exactly as it does to target profiles.  A name an
inventory produces is written verbatim into a generated config.

In practice:

1. **Find the vendor's own enumeration first** — the list of part
   numbers the vendor says exist.  A model missing from your file is a
   gap; a model in your file that the vendor never shipped is a defect.
2. **Take counts from a per-part-number table, and check the pairing.**
   Text extracted from a PDF table drifts: a part number ends up beside
   the wrong row.  Read the table in a second rendering, or against a
   second document, before you trust a row.  A capacity figure the
   vendor prints (switching capacity, say) is an independent check on
   the uplink class.
3. **Port groups go in port-NUMBER order, not left-to-right on the
   panel.**  On every pictured Aruba 2930F the SFP cages are the
   leftmost ports and are numbered last.  An author who follows the
   faceplate writes
   the uplink group first, and the naming rule then hands `1`..`4` to
   the uplinks — with every name still a real port.
4. **A vendor document can be wrong.**  The 2930F QuickSpecs prints
   "4 SFP+" under a model whose capacity figure, data sheet and product
   name all say 1G SFP.  When you find one, say so in a comment in the
   family file, so the next reader does not "correct" your value into
   the error.
5. **If something is not established, leave it unstated or flag it.**
   An empty `cage` means "not stated", and is the right value wherever
   the position of a cage type on the panel is not known.  Do not swap
   one plausible value for another.

---

## Evidence: graded per fact, and `capture` is granted, not inherited

A port's name is the product of separately evidenced facts.  Each is
graded where it is stated:

| Field | The claim |
|---|---|
| a mode's `naming` | "in this state a fixed port is `M/N`" |
| a mode's `bay_naming` | the same for a port in a module bay, when that is established less well |
| a model's `panel` | "this part number has these ports, numbered in this order" |
| a module's `inventory` | "this module has four ports" |

Each takes `vendor-doc` or `inferred` (with a `caveat` saying what is
unverified), and a `ref` naming what backs it.  A port's grade is the
weakest of the facts that produced it — so a standalone switch with an
**empty** bay is not dragged down by a doubt about bay-port names it
does not have.

**Write each `ref` so it stands on its own.**  It is served to API
clients exactly as written, and they see neither the YAML comments nor
the other family files.  Name the document in full, with its number
and the page or table — `HPE QuickSpecs c05052929 V33 p.23`, not `QS
p.23` with a legend in the header.  For public device output give the
thread's title or slug and its post date; no poster names, and no host
names or addresses from the paste.  "Real configs" with nothing to
find them by is not a reference.  The shipped-data test refuses the
tags it has seen used this way.

A model's `panel` grade covers the count and the roles.  Where a port
*type* sits within the numbering — which positions are the combo
ports, or the multi-gigabit ones — decides `speed` and `cage`, never a
name; if that rests on weaker evidence than the count does, say so in
the model's `caveat`.

**None of those four may be `capture`.**  A capture is a checked claim
about ONE deployment — this part number, in this mode, as this member,
with these modules.  It is declared under `captures:`:

```yaml
captures:
  - fixture: tests/fixtures/real/aruba_aoss/user_contrib_2930m_wc1611.cfg
    marker: 'member 1 type "jl323a"'      # a line only THIS model's capture has
    mode: stacked
    members:
      - {model: 2930M-40G-8SR-PoEP, id: 1, modules: {A: JL083A}}
```

and a port is graded `capture` only where a claim matches exactly: the
same model, the same mode, the same member id — and, for a bay port,
the same module in that bay.  A sibling model with identical port
names, a TAA twin, the same model as member 2, or the same model with a
different module stays at the grade of its parts.  That is why a TAA
twin gets its own model entry rather than a second line in its
sibling's `skus:`.

Every claim is re-proven on every test run: the fixture must contain
the marker, the marker must carry a part number of the claimed model,
the fixture must belong to the family's vendor, and the hardware ports
it names must **equal** the compiled inventory.  A capture that names
only some of the device's ports cannot be claimed — the claim would
grant the grade to ports it never shows.  In a mode whose names carry
a member id, every member of the claim states the `id` the capture
shows.

`capture` means exactly that re-proof, so a claim grants the grade
only when it is one the test re-proves: it is listed in
`PROVEN_CAPTURE_CLAIMS` in `device_models.py`, and the test requires
that list to equal the claims it checks.  A claim in an operator's own
family file is read, logged and grants nothing.

A capture proves **names**.  It retires the caveat of the naming fact
and keeps the caveat of the panel or module fact, because which ports
are uplinks, and what speed each is, is not something a config shows.

---

## Steps

1. **Establish the facts** as above.  If your sources include public
   device output that is not committed here, say where it can be found
   again — in the `ref` it supports, and listed in the family file's
   header comment (thread title or slug, and post date).
2. **Write or extend the family file.**  Give each model the key the
   device itself prints (its stock host name is a good source) so twins
   that differ only in uplink class cannot be confused; list the part
   number(s) under `skus:`; put the first part number in
   `display_name`.  A family name, model key and module SKU is a plain
   token — letters, digits, `.`, `_`, `+`, `-` — and YAML aliases
   (`&name` / `*name`) are not allowed in a family file.
3. **Pin the inventory by hand** in
   [`tests/unit/migration/test_device_models_shipped.py`](../tests/unit/migration/test_device_models_shipped.py):
   the access names and the uplink names, in order, for every mode and
   every module choice.  Type them from your sources.  A capture can
   only prove names — it cannot prove which ports are uplinks, since
   many grammars carry no role in the name — so this table is the only
   thing that catches two port groups written in the wrong order.  The
   test fails if any shipped combination is not pinned.  In the same
   file add each part number to `EXPECTED_PART_NUMBERS` (which part
   number is which model is data there, not a comment), and a part
   you graded `inferred` to `KNOWN_INFERRED_PARTS`.
4. **Add the capture claim**, if a committed capture of that exact
   model exists and names every port of it: in the family file, in
   `EXPECTED_CLAIMS` in the same test file (fixture, marker, mode and
   each member), and in `PROVEN_CAPTURE_CLAIMS` in `device_models.py`.
   A new fixture needs its rows in
   [`tests/fixtures/real/NOTICE.md`](../tests/fixtures/real/NOTICE.md)
   and `RESULTS.md` there, as for any real capture.
5. **If a flat target profile describes the same device**, add the pair
   to `PROFILE_AGREES_WITH` (addressed by part number, never by key —
   legacy keys are not consistent with each other).  The test finds
   such profiles by the part number in their display name and fails
   until the pair is listed.  Where both exist the family is
   authoritative for port mapping.
6. **Run** `pytest tests/unit/migration/test_device_models.py
   tests/unit/migration/test_device_models_shipped.py`.

### A new naming grammar

A family for a vendor whose grammar no rule covers needs a rule first:
a pure function beside that vendor's codec, registered in
`_naming_rules()` in `device_models.py` as a `NamingRuleSpec` — the
render function, and the set of **roles it can name**.  That set
matters: a port group whose role the rule cannot name is refused when
the family loads.  AOS-S out-of-band management is the `oobm` context,
not a numbered port, so the `aoss` rule names `access` and `uplink`
only; a `mgmt` group counted into the panel would have been handed the
next free number and become port 25 of a 24-port switch.

Test the rule against the vendor's own printed examples, including one
whose member number is not 1.

---

## What the loader enforces

A family file is validated when it is registered, and everything it
allows is compiled then — every model, in every mode, with each bay
empty and with each module it accepts, and every capture claim.  So
these are load errors, not surprises later:

* an unknown or misspelt field (unknown keys are rejected), a missing
  `role`, a `speed` or `cage` outside the vocabulary, a `count` that
  is not an integer, a missing `schema: 1`;
* a mapping key written twice (plain YAML would keep the last), a YAML
  alias, or a model or module key that is not a plain name (a bare
  `yes` or `0755` is read by YAML as something else — quote it);
* a `capture` grade on a part, or an `inferred` grade with no caveat;
* a capture claim that leaves out a member id in a mode whose names
  carry one;
* a bay that accepts a module the family does not define; a bay name
  the naming rule refuses; a port named twice;
* a model key or part number another model already uses;
* more port groups, ports in a group, or bay-and-module combinations
  than the loader will build (the limits are constants at the top of
  `device_models.py`; no fixed-port device comes near them).

At runtime a file that fails any of these — or that cannot be read at
all: not UTF-8, a folder with a `.yaml` name — is logged and skipped
so one bad file cannot stop the application; the shipped files are
loaded strictly by the test suite, so a typo there fails the build.

An operator's own `model_families/` directory, under a relocated
definitions directory, is laid over the shipped families.  It can add
new families, each with its own models.  A file that re-declares a
shipped family — even to add one model to it — is refused and logged,
and a capture claim in an operator's file grants no `capture` grade.

---

## What is not modelled yet

Modular chassis (line cards in lettered or numbered slots — every
bay-and-module combination of a model is compiled at load, which a
many-bay chassis would make too many), breakout
lanes, ports a stack consumes as links, ports that belong to a stack
rather than to one member (a Catalyst's single management interface),
and literal non-systematic names (a FortiGate's `wan1`, `dmz`).  The
schema has room for each as an additive field; none has data or a
consumer today.  A device of one of those kinds can still be declared
through its flat target profile, as one device in the one state that
profile documents.
