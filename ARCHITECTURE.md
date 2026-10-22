# Netcanon — Architecture

This is the conceptual map.  For day-to-day contributor rules see
[`AGENTS.md`](AGENTS.md); for the active roadmap and backlog see
[`translator-plans.txt`](translator-plans.txt).

---

## Two concerns, one app

Netcanon is a FastAPI application that co-hosts two independent jobs:

```
            ┌────────────────────────────────────────────────────┐
            │                  FastAPI app                        │
            │  (netcanon/main.py, shared by web + desktop)      │
            └──────────────┬─────────────────────────┬────────────┘
                           │                         │
                  ┌────────▼────────┐       ┌────────▼────────┐
                  │    BACKUP       │       │   MIGRATION     │
                  │                 │       │                 │
                  │  devices → SSH  │       │  raw config →   │
                  │   → configs/    │       │  CanonicalIntent│
                  │                 │       │  → raw config   │
                  │                 │       │   (other vendor)│
                  └─────────────────┘       └─────────────────┘
```

**Backup** (`netcanon/collectors/`, `netcanon/api/routes/backups.py`):
fetches the current running configuration from devices over a
pluggable transport (SSH via Netmiko / NETCONF / REST), validates
against a device-class schema, stores in `configs/<host>.<ext>`.
Scheduled or on-demand.  Mocked in tests at a single factory
(`get_collector`).

**Migration** (`netcanon/migration/`): the subject of most of this
document.  Takes a stored backup, parses it into a shared intent tree,
and renders that tree in another vendor's native format.

The rest of this document is about the migration layer.  The backup
layer is architecturally simpler — see
[`netcanon/collectors/README.md`](netcanon/collectors/README.md).
Backup definitions ship for Cisco IOS-XE, Fortigate FortiOS, MikroTik
RouterOS, OPNsense, Aruba AOS-S, Juniper Junos, Arista EOS, and VyOS
(the last live-validated 2026-06-17, #113), plus provisional definitions
for Cisco NX-OS, Cisco IOS-XR, and Aruba AOS-CX — see
[`netcanon/definitions/library/README.md`](netcanon/definitions/library/README.md) for the
per-vendor authoring notes and validation status.

---

## Credential security (encryption at rest)

Device credentials (passwords, enable passwords) used by the backup
collectors are encrypted at rest under
[`netcanon/security/`](netcanon/security/):

- **`credentials.py`** — Fernet symmetric encryption.  The key is
  resolved first-hit-wins across three tiers: (1) the
  `NETCANON_FERNET_KEY` environment variable (operator-explicit;
  recommended for container / production), (2) the OS keyring (Windows
  Credential Manager / macOS Keychain / Linux SecretService; best fit
  for desktop installs), (3) a file fallback at
  `$NETCANON_DATA_DIR/.fernet_key` (zero-config bootstrap for headless
  deployments, auto-generated on first use).  In-memory model objects
  always hold **plaintext** — encryption is a storage-layer concern
  applied on write and reversed on read.
- **`migration.py`** — `migrate_credential_fields(data, fields)`, the
  shared legacy-plaintext upgrade helper.  Both `FileDeviceProfileStore`
  and `FileScheduleStore` call it on first load: a field that fails to
  decrypt (`InvalidToken`) is treated as a pre-encryption plaintext
  value, returned as-is, and flagged for re-save with encryption.

Operator-facing key-management guidance lives in
[`SECURITY.md`](SECURITY.md); this section is the architectural pointer.

---

## Migration — four-layer model

The migration pipeline decouples four concerns that tend to get
conflated in vendor-specific tooling:

```
┌─────────────────────────┐  ┌──────────────────────────┐
│  Vendor Definition      │  │  Canonical Intent Model  │
│  (what device is this?) │  │  (what is the tree?)     │
└──────────┬──────────────┘  └─────────────┬────────────┘
           │                                │
           ▼                                ▼
┌─────────────────────────┐  ┌──────────────────────────┐
│  Format Codec           │─▶│  Schema Validator        │
│  (CLI/XML/JSON ↔ tree)  │  │  (strictness policy)     │
└──────────┬──────────────┘  └──────────────────────────┘
           │
           ▼
┌─────────────────────────┐
│  Transport              │
│  (how to get bytes      │
│   in/out of device)     │
└─────────────────────────┘
```

### Layer 1 — Vendor Definition

**Where:** `netcanon/definitions/library/*.yaml`
**What:** A small declarative struct per vendor/device family:
`{name, device_classes, cli_prompt_hints, default_timeout}`.  No code.

**Purpose:**
- UX grouping in the migration picker ("Show me all FortiGate codecs")
- Default `device_class` declaration
- Shared taxonomy anchor with the backup layer's `type_key` field

**Layered definitions (backup side).**  The `DeviceDefinition` schema
in `netcanon/definitions/schema.py` supports two-level lookup:

* **Family-base** entries (`os_version` and `model` both unset) form
  the default `dict[type_key, DeviceDefinition]` returned by
  `DefinitionLoader.load_all()`.  Existing callers that don't know
  about variants hit exactly these entries.
* **Overlays** (entries with `os_version` or `model` set) live in a
  parallel variant registry reachable via `DefinitionLoader.resolve(
  type_key, os_version=None, model=None)`.  The resolver does
  longest-match: exact triple → version-pin → model-pin → family base.

Operators pin the axes they know by setting `os_version` and/or
`model` on their `DeviceProfile`.  The backup pipeline passes the
pins through `DeviceTarget`; unpinned targets fall back to the
family base automatically.  Probe-driven auto-detection (future
commit) writes back to `DeviceProfile.detected_facts`, which operators
see read-only in the device edit panel so they can reconcile their
pins against what the device actually reports.

See [`netcanon/definitions/library/README.md`](netcanon/definitions/library/README.md) for the full
authoring guide; [`netcanon/definitions/README.md`](netcanon/definitions/README.md)
for the loader implementation and Pydantic schema reference.

### Layer 2 — Format Codec

**Where:** `netcanon/migration/codecs/<vendor>/codec.py`
**What:** Translates between a **wire format** and the **canonical
intent tree**.  Every codec declares:

```python
vendor:           str      # points at a Vendor YAML
format:           str      # machine-readable format tag
direction:        enum     # parse_only | render_only | bidirectional
canonical_model:  str      # which CIM it speaks
capability_matrix: ...     # what xpaths it can round-trip
certainty:        enum     # certified | best_effort | experimental
```

**Key design choices:**

* **Direction is independent of the vendor.** Many CLI parsers are
  `parse_only` because rendering clean CLI is harder than parsing it.
  The migration UI shows `parse_only` codecs only as source options,
  `render_only` codecs only as target options.
* **Multiple codecs can share a vendor.** `cisco_iosxe` (NETCONF
  OpenConfig) and `cisco_iosxe_cli` (`show running-config` parser) are
  both `vendor_id="cisco_iosxe"` but speak different wire formats.
* **Auto-registration.** Drop a subpackage under
  `netcanon/migration/codecs/`, decorate the class with `@register`,
  and `pkgutil` auto-discovery at app startup picks it up — no manual
  wiring.
* **Codec-contract types live in `models/migration.py`, not in
  `codecs/`.** `CapabilityMatrix`, `LossyPath`, and `UnsupportedPath`
  are defined in `netcanon/models/migration.py` alongside the other
  platform DTOs (`ValidationReport`, `MigrationJob`, `CodecInfo`).
  This is intentional: `CapabilityMatrix` is returned verbatim over
  HTTP (`GET /api/v1/migration/adapters/{name}/capabilities`), so it
  belongs in the shared models layer that the API routes, the validate
  service, and the codecs all import from a common leaf.  The
  dependency direction is strictly downward — `codecs/` imports
  `models/`; `models/` imports nothing from `codecs/`.  The four-dot
  relative import each codec uses (`from ....models.migration import
  CapabilityMatrix`) is a function of directory nesting, not of an
  incorrect layering.

For authoring instructions see
[`netcanon/migration/codecs/README.md`](netcanon/migration/codecs/README.md).

#### Where a stanza, and a block of text, ends (parse side)

A parser reads a config as its DEVICE places the lines, not as the
printer happens to lay them out, and what it cannot place it refuses in
words rather than guesses.  Three rules of one idea, each grounded in
what the vendor documents (or said to be inferred where it does not),
and each in `AGENTS.md`'s Hard Rules:

* **A stanza ends where the device ends it.**  AOS-S ends a context at
  its `exit`, an `end`, or a line in column 0 that enters another
  context or that the top level reads (`_ends_the_stanza`), never at
  indentation.  IOS XR places a line by its indentation, and a
  submode's `!` does not end the stanza it is in; EOS reads `router
  bgp`, whose blocks are real, by depth.
* **A text the device would place otherwise than the parser reads it
  is refused.**  A text with no indentation, by the IOS XR, EOS,
  AOS-CX, IOS-XE CLI, NX-OS and OS10 parsers
  (`_scanner.first_flat_stanza`, which counts as indentation what each
  parser's readers count: a space or a tab for IOS XR and EOS, any
  white space for the other four), and IOS XR's `show running-config
  formal` form: the sentence names a line and quotes nothing of the
  text.
* **A block of text is text, never lines of the config.**  A banner, a
  macro, a scheduler job or an EOS `EOF` body is emptied before any
  reader of the parse runs -- the Tier-3 rows included -- each line
  keeping its number, so every later refusal names the right line
  (`_scanner.without_text_bodies`, with each parser's `opens` /
  `Body` from its vendor's rule; EOS keeps its own loop).  A body with
  no end, a line of one that ends where the device does not end a
  line, and a line where two readings of the grammar end the body
  differently are refused.

The blind spot all three shared: every check read the captures as
printed, and pinned the shapes the printers write; the shapes that
broke each parser (a text without its indentation, a banner whose text
holds an account line) were in no test.  The guards build those shapes
by hand and read each target's OUTPUT
(`tests/unit/migration/codecs/aruba_aoss/test_where_a_stanza_ends.py`,
`tests/unit/migration/test_cisco_iosxr_indentation.py`,
`tests/unit/migration/test_arista_eos_indentation.py`,
`tests/unit/migration/test_a_flat_text_is_refused.py`,
`tests/unit/migration/test_a_banner_is_text.py`).  Which parsers still
read a flat text, or a free-text value of another grammar, is in the
CHANGELOG's known limitations.

### Layer 3 — Canonical Intent Model (CIM)

**Where:** `netcanon/migration/canonical/intent.py`
**What:** The shared tree shape codecs parse into and render out of.

The current CIM is a lightweight OpenConfig-inspired pydantic model
with fields tiered by semantic stability:

| Tier | Meaning | Examples |
|---|---|---|
| **Tier 1** | Every vendor models it, stable cross-vendor semantics | `hostname`, `dns_servers`, `ntp_servers`, `interfaces[]` with ipv4_addresses, `vlans[]` with tagged/untagged port lists, `static_routes[]` |
| **Tier 2** | Common enough to model, vendor mappings are lossy | `snmp`, `lags[]`, `local_users[]`, `dhcp_servers[]`, `radius_servers[]`, per-port `mtu` |
| **Tier 2 (ship-before-wire)** | Schema shipped ahead of any codec populating it; DC codecs declare the xpath under `unsupported` so the UI banner surfaces the gap | `vxlan_vnis[]` (VLAN↔VNI mappings), `evpn_type5_routes[]` (BGP-EVPN IP-prefix advertisements), `routing_instances[]` + per-interface `vrf` (VRF / routing-instance declarations) |
| **Tier 3** | Opaque carry-through, never auto-rendered | `raw_sections[]` — firewall rules, PKI chains, QoS policies, vendor-specific |

**The design bet:** most cross-vendor translation value lives in
Tiers 1 + 2.  Tier 3 features get preserved as opaque blobs so they
survive the round-trip but don't have to be modelled end-to-end.

**Ship-before-wire** is the pattern for features whose canonical
shape we're confident about but whose codec implementations will
land incrementally.  The schema ships with `Unsupported` capability-
matrix entries on every relevant codec; each codec-wiring commit
demotes the entry (to `supported` or `lossy`) as parse+render land.
EVPN-VXLAN is the reference case: `CanonicalVxlan` + `CanonicalEvpnType5Route`
landed in a single commit ahead of any Arista / Junos / NX-OS
wire-up, letting the UI report "VXLAN detected but not translated"
instead of silently dropping it.

**Shared transforms:** `netcanon/migration/canonical/transforms.py`
holds post-parse passes that bridge representation differences (e.g.
`project_switchport_to_vlan` converts Cisco's per-port VLAN
membership to Aruba's VLAN-centric membership lists).  These run
after the codec's `parse()` so the canonical tree is complete
regardless of which vendor originated it.

### Layer 4 — Transport

**Where:** `netcanon/collectors/` (currently only the backup side
exercises transport layer; migration is file-input for now)
**What:** How bytes get in and out of a device.  SSH via Netmiko,
NETCONF, REST APIs — pluggable per vendor.

Migration's Phase 2+ deploy story will push rendered configs back to
devices via this layer; for now the flow is file → codec → file.

---

## Certification model

Every codec declares `certainty` — a promise about how battle-tested
it is:

| Level | Criterion | UI signal |
|---|---|---|
| `experimental` | Synthetic fixtures only | Red banner |
| `best_effort` | ≥1 real fixture round-trips clean | Yellow banner |
| `certified` | ≥3 real captures from ≥2 OS versions, all round-trip stable | Green chip |

**Certainty rates round-trip fidelity, not deploy automation.**  A
`certified` chip means the translation is trustworthy enough to hand to
an operator — *not* that Netcanon will push it to a device.  There is no
deploy path today; rendered output is for manual review and apply (the
deploy endpoints remain on the roadmap — see
[`netcanon/api/routes/migration.py`](netcanon/api/routes/migration.py)).

The bar is intentionally strict.  Per-codec status is tracked in
[`tests/fixtures/real/RESULTS.md`](tests/fixtures/real/RESULTS.md) —
consult it as the source of truth, not this doc (this paragraph goes
stale as codecs promote).

---

## Pipeline orchestration

**Where:** `netcanon/services/migration_pipeline.py`
**What:** A single public function `run_plan(source_codec, target_codec,
raw, transforms=...)` that drives:

```
raw_text
  → source_codec.parse(raw_text)         # returns CanonicalIntent
  → apply transforms (zero or more)
  → validate against schema + capability matrix
  → target_codec.render(tree)            # returns raw_text
```

**Critical invariant:** the signatures of pipeline-stage functions in
`migration_pipeline.py` **must never change**.  Dozens of tests and
API routes depend on the exact shape.  Later phases add NEW public
functions (e.g. `plan_with_deploy`, `plan_with_diff`); existing
stages stay frozen.  See the module docstring.

`run_plan_with_models` is one such addition: it takes the port
inventory of the source device and of the target device, pairs the
ports the config uses by position, and forwards the resulting rename
map to the frozen `run_plan_with_overrides`.  See "Device models and
inventories" below.  `run_plan_with_checked_names` is another, for a
request that declares no devices: `run_plan_with_overrides`, and then
a look at what the port translator made of the names in the finished
run.

**What decides a job's status.**  A job that rendered is `completed`
unless one of three things makes it `partial`; each adds its sentence
to `job.error` after any the job already has.

1. *The validation report* (`run_plan`): a block-level unsupported or
   lossy path.
2. *An input that parsed to nothing* (`run_plan`): non-trivial text
   that yields an empty tree is a wrong source vendor, not a clean
   result.
3. *The port names.*  A warning is not a status.  The port translator
   says in a warning line that two source names ended on one name of
   the output, that it dropped a name the target has none for, or
   that it could not read a name and left it as the source config
   has it; none of those is a loss the capability matrix has a path
   for.  With both devices declared `run_plan_with_models` checks its
   own finished run, for the hardware ports, and records the outcome
   on `port_mapping_plan`.  With none declared
   `run_plan_with_checked_names` asks what became of every name in a
   run made by name shape — logical ones included, since there is
   no pairing whose ports alone need protecting — and puts the names
   on the job (`fused_ports`, `unresolved_ports`,
   `untranslated_ports`).  The third list starts from the
   translator's own: it says as data which names it left
   (`PortRenameResult.untranslated`), and keeps apart a name the
   config only refers to — a route to `Null0`, a VXLAN source
   address — which holds no job.  Of the names it left, the job
   lists those that are a FOREIGN name on the target.  A name is
   not one between two codecs of one platform (one `vendor_id`:
   IOS-XE as CLI text and over NETCONF), nor where the target
   itself writes that very name for the kind of thing the source
   parser read it to be — a VLAN's interface, a loopback, an
   aggregate, a tunnel; never a hardware port, and never to or
   from a platform whose names are free text.  The AOS-S parser
   names the interface of a VLAN's address `Vlan20`, its
   classifier does not read that name, and `interface Vlan20` is
   what EOS, IOS-XE and NX-OS call it: nothing is listed there.
   What shares a name is not always two interfaces: Junos refers to
   `lo0` as `lo0.0`.  Unit 0 beside its interface is told from a
   second interface of that name by the tree that was rendered (how
   many interfaces it holds under the name), not by the shape of the
   two names.

On either path an entry of `port_rename_map` is the operator deciding
a name, so `run_translation` hands the body's own port map to
whichever entry it dispatches to, on every plan endpoint: a status an
entry cannot clear from the URL it was posted to is a trap.  An entry
is a name or `null`; a blank target is neither — nor is one that
draws nothing, such as a zero-width space — and the request model
refuses it.  The job's sentence offers a pair of declared devices
only where a hardware port is among what it lists: for logical names
the path with devices holds nothing, and would call the same output
`completed`.

---

## Config limits (what one request may make, and for how long)

**Where:** `netcanon/migration/limits.py`
**What:** counts of what a request makes, a deadline for the request,
and the refusal when either is passed.

**The idea.**  A config is whatever was pasted, and a few bytes of it
can stand for a great deal: `2-4000` is thousands of VLAN ids, `all` is
every one (and so, on four platforms, is a trunk that states no list),
every trunk that allows every VLAN is a member of every VLAN, and an
interface stanza is one line.  So the size of a text bounds neither the
memory a request takes nor its time, and a cap on the text is not a cap
on the work.  The limits are therefore on what is MADE.

**Why counts and not bytes.**  An operator can check "1,000 trunk ports
x 1,000 VLANs" against a device; nobody can check a megabyte, and a
megabyte is a different number on Linux, on Windows and after the next
pydantic release.  And several counts, because one entry is not one
price: a VLAN id on a port costs a pointer, a membership hundreds of
bytes by the time a target has reported on it, an interface
thousands.  The kinds are in `limits.KINDS`; the numbers, in four named
sets (`small`, `standard`, `large`, `unlimited`), are in
[`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) § H.

**Three objects, and no signature that carries them.**

* a *scope* (`limits_scope`) says which set applies and holds the
  request's deadline.  An entry point opens it: the command line, a
  tool, a test.  A handler of the server opens `server_scope`, which is
  the same and takes the request's turn as well (below): the request
  path in `_migration_helpers.run_translation`, the sanitiser's route
  on its worker thread, detection.  Work that opens none runs under
  `standard`, so a caller nobody thought about is still bounded.
* a *meter* (`metered`) holds the running counts of ONE stage.
  `CodecBase.__init_subclass__` already wrapped every codec's `parse`
  (to turn a model's validation error into a `ParseError`); the same
  wrapper opens a meter round every `parse` and every `render`.  No
  codec is handed anything, and no frozen pipeline signature changes.
* `LimitExceeded` is what a count or the clock raises.  Every entry
  point turns it into an answer in words (below).

Both are context variables: a request's handler runs on a worker
thread, and its counts and its limits are that thread's.

**Requests at once.**  Counts and a deadline are for one request, and
requests at once add up.  A set of limits can therefore also say how
many requests a server WORKS on at once (`Limits.at_once`: one under
`small`, no limit under the others).  It is taken where the server's
scope is opened, so every handler that reads config text is covered by
opening its scope and by nothing else:

* A request holds memory before any handler runs: its body.  So the
  outermost middleware (`_migration_helpers.AnswerSent`) COUNTS a
  request that would read config text when its headers arrive
  (`Answer.arrived`; which requests those are is decided from the
  method and the path, `READS_CONFIG_TEXT`).  There are as many places
  as may work and wait.  One more request is answered there, 503 with
  `Retry-After`, and its body is never asked for.  The request's one
  deadline is set then too, and runs from its arrival.
* `server_scope` takes that deadline (or sets one, for a request
  nobody counted) and THEN waits for a turn
  (`limits._Turns`: one for the process, a `threading.Condition`, in
  order of arrival).  The wait is inside the deadline and on the
  handler's worker thread; the event loop never waits, so `/health`
  and the pages are not behind it.  At most `MOST_WAITING` wait: a
  waiter holds a thread of the pool and its body.
* A request still in the line at its deadline raises `LimitExceeded`
  with the kind `at_once`, before its block is entered.  The pipeline
  never sees it, so each handler answers it where it opened the scope:
  `run_translation` makes the same `failed` job a refusal inside a
  stage gets, the sanitiser and `detect` answer 503 with `Retry-After`
  (`refusal_as_http`), `detect-deployment` a proposal with one note.
* A request that stood in the line and THEN runs out of time is busy
  too, and not slow: the scope remembers how long it waited, and the
  clock raises `at_once` with that in its words where it would have
  raised `seconds` (`limits._out_of_time`).  This one is raised inside
  a stage, so it comes back the way any refusal does.
* A scope inside a scope is the same request: the turn is carried in
  the context, like the scope, and is not taken twice or waited for.
* The turn outlasts the handler.  An answer is memory too, so the
  application keeps an `Answer` for every request (the outermost
  middleware, `AnswerSent`), the scope lends its turn to it, and the
  turn comes back when the answer has gone out -- or at the request's
  deadline, from a client that does not read.
* At that deadline the answer goes too.  The application inside waits
  for the client in two places -- for the body (`receive`) and for the
  client to read (`send`) -- and for a request that holds a place the
  middleware ends both waits at the deadline (`_InItsTime`): it tells
  the application what it is told when a client leaves, so a streamed
  answer runs to its end and lets go of its pieces; then it answers a
  request whose body never came (408), or leaves an answer unfinished,
  which makes the server close the connection.  Only waiting is
  bounded: a refusal made at the deadline is still sent.  An answer is
  handed to the server 64 KiB at a time, so that "gone out" does not
  mean "in the server's buffer".
* A server closes a connection once what it wrote has been taken, so
  the connection of a client that takes nothing outlives all of the
  above, with what the system holds for it.  Nothing inside the
  application can end it; the system can.  Both launchers -- `netcanon
  serve` and the desktop's embedded server -- therefore start the
  server on what `_migration_helpers.listening_sockets` gives them:
  under limits that say how many requests work at once, on a system
  that has the option (Linux), a socket on which the system ends a
  connection whose client has taken nothing for the seconds a request
  may take (`TCP_USER_TIMEOUT`, which every accepted connection gets
  from the listening socket); everywhere else `None`, and the server
  binds its own.
* A request that has taken its turn first hands freed memory back to
  the system (`malloc_trim`, glibc): a server runs its requests on
  whichever thread is idle, and the C library keeps what a thread
  freed for that thread.

**The answer to a job is written a piece at a time**
(`_migration_helpers.job_answer`, `json_pieces`).  A handler that
returns a model leaves the framework to make the answer in five passes
over it, and a job's validation report has a path for every
membership: the largest answer `small` admits cost more memory to make
than the translation did.  The seven job handlers return the job
written straight to JSON, a field or a run of a long list at a time --
the same bytes and the same `Content-Length`, which a test compares
with the framework's own job by job.  `response_model` stays declared,
for the schema.

**Where the counts are charged.**  Before the entries are made, at each
place a token expands (`charge`): the VLAN id-list readers
(`_helpers._parse_vlan_list`, `merge_trunk_allowed`, the Arista and
Junos readers of their own); the list of a trunk that states none,
where its platform's trunk carries every VLAN -- no token stands for
those 4,094 ids, so they are charged where the list is made
(`_helpers.unstated_trunk_list`), and so are the copy a first `add` or
`remove` starts from and the list each record of a stanza met again
is given (`TrunksByName`); the AOS-S port range (memberships, then
the different ports ranges have named); the switchport projection,
which knows the whole product after its first pass and before its
first stamp; the Junos `interface-range` fold; block-form Junos, in
words, since the path is written again for every statement; VyOS set
lines, in the characters of the nested blocks they become; the
renderers that write every id of a list (IOS-XE and EOS add up the
lengths of the lists before they write a character; Junos counts each
port's lines).  An interface is counted where it is made -- in the
model, the one place every parser and every renderer passes.  Then,
with no list of places at all: the finished tree of every parse is
counted at the boundary (`census`), and so is the length of every
output.  The early counts refuse before the memory is spent; the late
ones need nobody to have found the place.

Counts belong to one stage, because they are a property of the config:
the same text is refused or accepted whichever endpoint it is posted
to and however often that endpoint parses it.

**The deadline** belongs to the request.  It is looked at in every
loop over the lines of a config (`ticked`, `tick`), in the
projection's passes, at every charge, and when a stage starts.
A thread cannot be stopped from outside, so only work that looks stops:
a renderer does not, and a request whose time runs out in one is not
interrupted ([`SECURITY.md`](SECURITY.md) has what follows from that).

**A refusal is a result.**  `run_plan` has one clause for it: the job
is `failed`, `error` begins `refused:`, `refusal` (a `Refusal` model)
says the same as data, and the validation report is dropped -- the
answer to "too large" is small.  The sanitiser answers 413,
`detect-deployment` adds a note to a proposal it still makes, the
command line exits 2.  The sentence names what was large, how large
and the limit, and then what allows more for whoever reads it
(`how_to_raise`): the environment variable and the Preferences dialog
on a server, the option on the command line, and under `small` --
which is the public demo's -- no setting at all on a server (the
command line, which has no server and whose user did choose, names its
option there too).  A request that did not get a turn is refused in
the same shapes, in words that say the server was busy and to send it
again; so is one that got its turn too late to finish.  Two answers
are the middleware's own, because no handler ran: 503 for a request
that found every place taken, and 408 for one whose body did not
arrive in its time -- the same on every endpoint that reads config
text.

**Guards** (`tests/unit/migration/test_limits.py`): each limit has a
text under it and a text over it; every codec's parse is stopped at a
deadline it has passed; and three rules are read from the source, each
with a table a new case fails until it is in -- every loop over a
config's lines looks at the deadline, every `range(...)` under
`codecs/` has an answer, and no broad handler stands between an
expander and its caller without naming the refusal.  Requests at once
are tested with an event the first request holds and no sleep; every
handler that takes config text is found by what it takes
(`tests/integration/test_config_limits_api.py`) and has to take its
turn, for the answer the application keeps for it -- and to have been
counted before that, when it arrived.  The middleware is also tested
alone, against a server the test plays: what it hands on, what it
waits for, and until when.

---

## Per-pane overrides (Tier-3 rename modal)

**Where:** `run_plan_with_overrides` in
`netcanon/services/migration_pipeline.py` +
`netcanon/migration/canonical/{port_names,vlan_names,local_user_names,snmp_names,snmpv3_user_names}.py`
+ `netcanon/api/routes/migration.py` (per-pane POST endpoints) +
the left-rail category nav in `netcanon/templates/migrate.html`
with per-category partials under `_partials/`.

**What:** The Tier-3 rename modal lets operators override the
auto-heuristic for individual canonical categories without
leaving the translate workflow.  Each category (Ports, VLANs,
Local Users, SNMP community, SNMPv3 users today; future SNMP trap-hosts /
RADIUS) has:

1. **An orchestrator** under `netcanon/migration/canonical/`
   that walks the canonical tree and applies a caller-supplied
   override map.  Returns a result struct with `applied`,
   `dropped`, and `warnings` lists so the UI can show exactly
   what happened.
2. **A per-pane API endpoint** — `POST /api/v1/migration/plan/ports`,
   `POST /api/v1/migration/plan/vlans`,
   `POST /api/v1/migration/plan/local_users`,
   `POST /api/v1/migration/plan/snmp`,
   `POST /api/v1/migration/plan/snmpv3` — that applies its
   category's override map and delegates to
   `run_plan_with_overrides` with the other categories' maps
   defaulted to `None`.  The port map is the exception: every
   plan endpoint applies the one the body carries, because a
   job's status depends on what was decided about its ports
   (see "What decides a job's status" above).
3. **A rail button + category pane** in the modal UI.  Panes are
   mutually exclusive (one visible at a time); the preview on
   the right stays cross-category.

**Growth-safe engine:** `run_plan_with_overrides` is the one
function new per-pane categories extend.  New parameters go there
as optional maps defaulting to `None`; `run_plan` and
`run_plan_with_rename` signatures stay frozen.  Adding a new
category follows the established three-step recipe (proven five
times over: ports → vlans → local_users → snmp_community →
snmpv3_users): orchestrator module → wire into
`run_plan_with_overrides` under a None-vs-dict sentinel guard →
add endpoint + rail button + pane partial.  Each new category
also extends the capture transform if the UI pane needs to
enumerate source-tree entities (VLAN IDs, usernames, SNMP
community, SNMPv3 user names, etc.).

**Scalar vs list canonical surfaces:** ports / VLANs / local_users
are list-like (many rows per pane, collision detection, merge
semantics).  SNMP community is scalar — one string per canonical
tree — so its pane renders a single-row table for visual parity
with the list-oriented siblings and collision detection
definitionally returns zero.  Future categories in either shape
class fit the same recipe; the map shape is uniformly
`dict[T, T | None] | None` even when T is effectively singleton.

**Sentinel semantics (all override maps):**

* `None` — don't engage the category's transform at all (legacy
  behaviour).
* `{}` — engage with auto-heuristic only.  The UI sends this on
  first translate to turn the rename pipeline on without yet
  specifying overrides.
* `{src: tgt, ...}` — engage with explicit per-entry overrides.
  Values may include `None` to drop.

**Two kinds of name the port heuristic never reads.**  The port
orchestrator's auto-heuristic is `source.classify_port_name` →
`target.format_port_identity`, and `translate_port_names` keeps two
kinds of name away from it:

* *Between two configs of one codec a name nobody mapped stands.*
  It is a name of that platform by construction, and the round trip
  is not the identity on several codecs' own names — Junos reads
  `fxp0` and writes `em0`, FortiOS reads `dmz` and writes `dmz1`, the
  OS10 formatter has no form for its own breakout lanes; AOS-S,
  IOS-XE CLI and VyOS are the others on the committed inputs, and on
  the rest it is the identity there — so a job from a
  codec to itself renamed and dropped ports nobody had named, and
  said `completed`.  With an empty port map the output of such a job
  is the bare pipeline's.
* *A sub-interface goes where its port goes, with its unit*
  (`<port>.<unit>` becomes `<what the port became>.<unit>`), and is
  dropped with a port that is dropped.  `PortIdentity` has no place
  for a unit, so a classifier either reads the name as the port
  (Junos, VyOS: two interfaces on one name) or does not know it (IOS,
  EOS, NX-OS, IOS-XR: the name stays in the other vendor's config).
  The rule names no vendor.  A name is a unit of `<port>` when the
  source classifier does not read it as a thing of its own (it calls
  it `unknown`, or gives it the port's own kind), the parser did not
  type it as a VLAN interface, and — across vendors — it is an
  interface of the tree, not numbered 0, whose port is a physical
  port, a breakout lane or a LAG.  A unit is read as text and never
  converted, and across vendors it is a number of at most ten
  digits: a name that ends in a longer run is left to the
  classifier, so that no renderer which makes a number of the unit
  (FortiOS, VyOS) is handed one.  What the port IS decides that,
  not only its name: a port its parser marked as the management
  port from context (the IOS-XE `Mgmt-vrf` port,
  `CanonicalInterface.kind`) carries no sub-interface another
  platform has.  Between two configs of one codec a unit stands
  like any other name, and moves only when an entry moves or drops
  its port.  Where the source platform's names have no letter case
  the port of a unit is found as the config — else a key of the map
  — spells it, so `gigabitethernet0/0/1.54` is a unit of
  `GigabitEthernet0/0/1`.  What the target makes of
  `<its port>.<unit>` is its renderer's: where it has no tagged
  sub-interface its capability matrix says so, and the job is
  `partial` when the tree holds a tag for the validation report to
  list.  The tag is a field (`dot1q_vlan`), not part of the name: a
  unit that went with its port across vendors and has none in the
  tree — the AOS-CX and OS10 parsers read none — is written without
  one, and the translator says so in a warning of its own.  Between
  two configs of one codec it says nothing, and such a tag is lost
  there as on every path: a job from AOS-CX to AOS-CX writes the
  sub-interface without it, as parse and render alone do, and
  nothing reports it.

`tests/unit/migration/test_units_follow_their_port.py` holds both by
reading the rendered output against something the translator had no
hand in: the bare pipeline's output for every committed capture and
kitchen sink, and — from each source grammar that names a
sub-interface, onto every codec — each sub-interface found in the
output by its address.

**Cross-category ordering:** port rename runs BEFORE VLAN rename
in `run_plan_with_overrides` so port-name rewrites don't race
with VLAN-ID references changing underneath them.  Current order
is ports → vlans → local_users → snmp_community → snmpv3_users;
the last four are independent of each other (VLANs don't
reference users, users don't reference SNMP, SNMP doesn't
reference ports/VLANs, SNMPv3 users are orthogonal to v1/v2c
community) so only the ports-first constraint is load-bearing.
Adding a future category requires deciding its order relative to
the existing transforms; document the choice in both
`run_plan_with_overrides` and the orchestrator module.

**localStorage ack persistence (UI):** operator overrides are
persisted under
`netcanon.rename-ack.v1:<source_codec>:<target_codec>:<hostname>`.
Moving to a different device (different hostname), different
codec pair, or pressing Reset-all clears or scopes away saved
state.  Version segments for source/target are omitted from the
key today: all 12 parsers populate `CanonicalIntent.source_version`
now, but the ack key is not yet version-scoped (it would only matter
once version-targeted rendering grows an operator-facing surface).

**Source-shape capture:** `run_plan_with_overrides` injects a
capture-first transform that populates `MigrationJob.source_vlans`,
`source_local_users`, `source_snmp_community`, `source_ports`,
`source_other_names` and
`source_hostname` from the post-parse, pre-transform tree.  This
is load-bearing for the VLAN / local-users / SNMP panes (they
have no "auto-rewritten" rows to fall back on if the operator
hasn't already sent overrides) and for the localStorage key
(hostname).  The ports pane needs it for the same reason since a
name nobody mapped stands: between two configs of one codec no
rename and no warning names a LAG or a loopback, so the two lists
— the hardware ports, and every other name the translator
rewrites — are where their rows come from.

**Target-codec compatibility banners:** each codec exposes
`unsupported_rename_categories: frozenset[str]` listing per-pane
categories it can't round-trip.  The rename modal surfaces an
amber warning on the affected pane when the operator's active
target is in the declaring set — prevents the ghost-success bug
where rename overrides apply to the canonical tree but vanish
from rendered output.

**Current state:** every shipped bidirectional codec has the
attribute empty EXCEPT `OpnSenseCodec` and `CiscoIOSXECodec` (the
NETCONF Phase-0.5 stub), which each declare `frozenset({"snmpv3"})`
because their parse + render paths don't yet round-trip that category
(operators renaming SNMPv3 users on either of those codecs as the
target see the surfaced banner immediately).

`CiscoIOSXECodec` also declared `"ports"` until #482, on the grounds
that its `classify_port_name` / `format_port_identity` were inherited
`CodecBase` no-ops.  That entry is a cautionary example of this
mechanism's limit: a banner is a *UI hint*, and this one was
advertising a cosmetic warning-collapse while the underlying no-op
silently DELETED every port name (`strip_unmappable` defaults to True,
so "no native representation" removes rather than preserves — contrary
to what the `CodecBase.format_port_identity` docstring claimed).
Measured before the fix: 96% of 441 interfaces lost across five source
codecs.  The entry is gone because IOS-XE NETCONF now shares the IOS-XE
CLI port-name bridge — same platform, two wire formats.  **Declaring a
category here is not a substitute for failing loudly when data is being
dropped.**  Earlier `OPNsenseCodec`
and `FortiGateCLICodec` also declared `{"local_users"}` under an
incorrect assumption that those codecs kept user blocks in
`raw_sections`; verified otherwise (both round-trip
`CanonicalLocalUser` end-to-end and always did — see
`test_local_users_wire_through.py`) and that entry was removed.
The attribute remains wired as an extension point — the next codec
that ships without a Tier-2 round-trip for a category declares it
and gets the banner for free.  Adding an entry triggers an
[`AGENTS.md`](AGENTS.md) doc-sync row obligation to update this
section + the codec's own docstring.

**Per-pane capacity fit-checks:** each pane renders its own
fit-check banner (separate from the ports fit-check in
`_partials/fit-check.js`).  Banner state is a pure function of
the active target profile's capacity fields
(`TargetProfile.max_vlans`, `TargetProfile.max_local_users`) and
the corresponding source count — no cross-pane coupling.  Hidden
when the profile doesn't declare the limit, same discipline as
the ports fit-check's "no profile = no banner" rule.

See [`netcanon/migration/codecs/README.md`](netcanon/migration/codecs/README.md)
for the codec-authorship side of this (every codec must expose
`classify_port_name` / `format_port_identity` to participate in
the port-rename mesh; VLAN orchestrator is codec-agnostic).

---

## Auto-detection

**Where:** `netcanon/services/migration_detect.py` + per-codec `probe()`

The migration UI can auto-propose the right source codec when given
raw config text.  Each codec's `probe(raw_prefix)` returns
`(confidence, reason)` or `None`; the detector walks the registry and
returns a ranked list.  Structural markers that discriminate vendors:
`! J####A Configuration Editor` (Aruba), `# ... by RouterOS` (MikroTik),
`<opnsense>` root element, `config system global` (FortiOS), etc.

---

## Cross-cutting render-time policies

Some concerns are vendor-agnostic and live in shared sibling modules
at the migration-package root rather than per-codec.  Each policy is
called by multiple codecs to keep cross-vendor behaviour consistent:

**Hash-portability policy** (`netcanon/migration/_user_secrets.py`).
When a render path consumes `CanonicalLocalUser.hashed_password`, it
calls `is_migratable(hashed, target_vendor)` to decide whether the
target's CLI accepts that hash form.  Cross-vendor mismatches (e.g.
Cisco type-9 scrypt → Junos, OPNsense bcrypt → Arista) emit a
`format_review_comment(...)` line in the appropriate per-codec
syntax instead of leaking the hash literal as plaintext.  Per-target
accepted-algorithm sets live in `_TARGET_ACCEPTS[<vendor>]`.

**RADIUS shared-secret portability policy**
(`netcanon/migration/_radius_secrets.py`).  The third credential
surface, sibling to `_user_secrets.py` (password hashes) and
`_usm_keys.py` (SNMPv3 USM keys).  A render path consuming
`CanonicalRADIUSServer.key` calls
`radius_secret_is_migratable(value, source_vendor, target_vendor)`.
Only a **plaintext** secret crosses a vendor boundary.  A secret the
source platform stored in a form of its own is carried behind the
envelope its parser puts on it -- `fortios:` (FortiGate `set secret
ENC <blob>`, encrypted under that device's own key), `iosxe:` (IOS-XE
`key 6|7 <blob>`), `eos:` (EOS `key 7 <blob>`), `aoss:` (AOS-S
`encrypted-key`) -- and is refused on every other platform, with a
`format_review_comment(...)` line that names the form so the operator
knows to re-enter it.  The envelope is the parser's to put on: what a
value is is said by the grammar it was read from, and a stored form
that reaches the tree bare is a "plaintext" secret to the gate.  Same-vendor re-render always passes — that is the
reference path.  Unlike the SNMPv3 rule, a refusal does **not** drop
the server record: a keyless `radius-server host <ip>` is a
half-configured server the operator can see and finish, whereas a
vanished one is an invisible hole in their AAA config.

Classification is by envelope and **provenance**, never by the value's
shape.  Note the deliberate asymmetry with a colon: when
`source_vendor` is known the full envelope set is known too, so
`my:secret` is a legal literal secret; only an unregistered
envelope-shaped prefix from an *unvouched* source classifies as
`unknown` and is refused.  Refusing every value containing a colon
would be a false-positive blast rather than a fix.

**One value where one value goes** (`netcanon/migration/_one_value.py`).
A renderer puts a value into its line as it stands, and most CLIs read
a line a word at a time: a credential that holds white space is two
words there, and the second is read as whatever that place takes next
(NX-OS `snmp-server community public rw` is a read-write community
`public`).  No word-at-a-time CLI documents a quoted form for a
credential, so a secret -- a local user's password, an SNMP community,
an SNMPv3 passphrase, a VRRP/HSRP key -- or an account's name that does
not stand as one word (`splits`) is not written, and is never altered to
fit.  It is left out with the granularity the credential rules set (a
local user whole; an SNMPv3 user whole; a community with every trap host
that would carry it, never an invented `public`; an FHRP key alone, the
group kept) and said in a `left_out(...)` review line that names the
place and never the value.  Where the target quotes, the value is
quoted with the target's own escape (FortiOS, Junos, VyOS leaves);
where it quotes with no escape (AOS-S), a value holding a `"`
(`breaks_its_quotes`) is left out the same way.  RADIUS keys are not yet
under the rule.  Guarded by
`tests/unit/migration/test_a_secret_is_one_value.py`, which reads the
output as text.

What is not a secret goes through `one_value_tree(tree, ...)`, which
each line renderer runs before its first line and which returns the
tree to write (a copy, when anything changes) and the review lines to
put at the top of the output.  Each renderer names the fields it writes
as one word, by kind: a NAME that labels (host name, VLAN name, VRF
name, route name) is written as `one_word()` makes it -- `_` for each
run of white space, `'` for a `"` -- on the tree, so that every place
it goes agrees (a VRF with every interface, route and EVPN prefix in
it, and a name that would then be another VRF's told apart); an
ADDRESS (a server, a domain, a gateway, a DHCP pool's options) is
never altered and is left out, a static route whose gateway it is
whole; a TEXT in a place no vendor page says reads to the end of the
line is written and said, and one between quotes with no escape
(AOS-S, VyOS, OS10) has each `"` written `'`.  Guarded by
`tests/unit/migration/test_a_name_is_one_word.py`.

**Naming-value sanitisation** (`netcanon/migration/_naming.py`).
Arista EOS and Cisco IOS-XE wrote the host name through
`sanitise_hostname()` before `one_value_tree` did it for every line
renderer, with a review line; the calls are kept and change nothing
now.  Source state preserved on canonical, sanitised only at the wire
boundary.

**A value is written on one line** (`netcanon/migration/_one_line.py`).
Every renderer puts a value into its line as it stands, so a value that
held a line break was written as lines of its own, and the text after
the break was a command: a description that held `username ...
nopassword` after a break was that account on every line-based target.
The XML parsers keep a break that an element's text holds, and FortiOS
prints a value of several lines between its quotes, so the tree can
hold one.  No target is given a value of more than one line, whatever
the field: the pipeline (`run_plan`, and the sanitiser before it
renders) writes each run of breaks -- any character `str.splitlines`
ends a line at -- as one space, after the transforms, and says each
place in the job's warnings; `CodecBase.render` refuses a tree that
still holds one, so a caller that renders without the pipeline cannot
write one either.  It is one rule for every target, not a list of
which field of which target may hold a break, because a value in the
wrong place on such a list is an account; what a target that could
have held the break loses (an XML target, FortiOS between its quotes)
is the layout of the text.  `raw_sections`, the one field built to
carry lines, is filled by no parser: one that fills it has to settle
what its lines become, since the IOS-XE CLI renderer writes each as a
command.

**Switchport ↔ VLAN projection**
(`netcanon/migration/canonical/transforms.py`).  The
canonical model carries L2 membership both ways: per-iface
`switchport_mode`/`access_vlan`/`trunk_allowed_vlans` AND per-vlan
`tagged_ports`/`untagged_ports`.  Codecs whose parse populates only
one direction call `project_switchport_to_vlan(intent)` (or the
inverse `project_vlan_to_switchport`) as a post-pass for round-trip
stability.  The forward helper guards the list of every id
(`range(1,4095)`: Junos `vlan members all`, AOS-CX `vlan trunk allowed
all`, a Cisco or Arista trunk that states no list) to avoid
synthesising 4094 phantom VLANs: such a trunk goes onto the VLANs
already declared.  The two directions are not equally read: most
render paths write a port — its VLANs and its LAG — from the port's
own record and never look at the lists.  So a parser whose config
states membership per VLAN (AOS-S, where the device prints an
`interface` stanza only for a port with a setting of its own) gives
every port one of its lists names an interface record before it
mirrors, and
[`tests/unit/migration/test_vlan_members_reach_the_output.py`](tests/unit/migration/test_vlan_members_reach_the_output.py)
looks for each port's VLANs in the output of every target.

**What a trunk's allowed list says**
(`TRUNK_THAT_STATES_NO_LIST` in `netcanon/migration/codecs/_helpers.py`;
`is_every_vlan` in `netcanon/migration/canonical/transforms.py`).  The
tree has no value for "not stated".  On a trunk
`trunk_allowed_vlans == []` is NO VLAN, a list of every id (1-4094) is
EVERY VLAN, and any other list is the list.  What a trunk carries when
its config has no allowed line is a fact about the source platform —
every VLAN on IOS-XE, NX-OS, EOS and AOS-CX; none on OS10 and Junos —
so the parser, which knows its platform, puts it in the list, from
the one table.  It does so for an INTERFACE, when the whole config
has been read (`TrunksByName` in the same module): a stanza met twice
is one interface whose allowed lines are applied to one list, and
the platform's list is given only to a port that says it is a trunk,
not to one the parser took for a trunk from a trunk line alone.  A
renderer writes its target's form for each of the
three statements, and no allowed line where the list is the target's
own default (what the device prints, and what makes a default trunk
come back as it went).  Where a target has no form, the output carries
a review line and the cell is a documented limitation: AOS-CX cannot
be told "no VLAN", OS10 cannot be told "every VLAN".  (AOS-S cannot be
told "and any VLAN made later", and has no line to carry a note: its
vendor page says so.)  The readers of
the list follow the same rule: the VLAN rename pass leaves "every
VLAN" as it is and warns when a drop empties a trunk, and the
renderers that hang a VLAN on one parent (OPNsense, RouterOS,
FortiOS) look for a trunk that names it before a trunk of every
VLAN.

**A trunk's list holds its native VLAN**
(`NATIVE_VLAN_AND_THE_LIST` in `netcanon/migration/codecs/_helpers.py`;
`trunk_untagged_vlan` in `netcanon/migration/canonical/transforms.py`).
`trunk_allowed_vlans` is what a trunk CARRIES, its native VLAN among
them, and `trunk_native_vlan` says which of them goes without a tag.
A native VLAN the list does not hold is stated and not carried.  The
platforms' texts do not all say it that way, so each is brought to
the convention at its own edge, by the one table.  Where the native
VLAN is a line of its own that the allowed line may name or leave out
(IOS-XE, NX-OS, EOS, AOS-CX, the Junos ELS grammar) the parser puts
the list the text states and the renderer writes the list as it
stands.  Where the untagged VLAN is stated BESIDE a list of tagged
VLANs (OS10's access VLAN of a trunk) the parser adds it to the list
and the renderer takes it out, so no VLAN is on both lines.  AOS-S,
which is told VLAN by VLAN, gets there through the projections: a
port tagged in some VLANs and untagged in one is a trunk whose list
holds all of them, and a trunk is an untagged member of its native
VLAN only where its list holds it (`trunk_untagged_vlan`, which is
also what a renderer asks), so the two halves of the tree do not
answer differently.  A pass that rewrites the two fields keeps them
so, by asking what the port carried untagged before and after: where
a VLAN map would bring a native VLAN outside its port's list into
the list, the VLAN rename pass clears the native VLAN if the map has
merged it with a VLAN of the config that the list names, and takes
the new id out of the list if the list only covered that number with
a range -- each with a warning, and whatever the port's mode.
What a switch does with a native VLAN its list leaves out is
established for some of these platforms and not for others; the
vendors' sentences are in
[`docs/vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md`](docs/vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md#a-trunks-untagged-vlan-and-its-allowed-list-platform-by-platform).
A trunk that states NO native VLAN has its platform's default, and
the parser puts it, as it puts the list of a trunk that states none
(`TRUNK_THAT_STATES_NO_NATIVE` in the same module; `TrunksByName`
gives it to an interface when the whole config has been read, after
its list): VLAN 1 on IOS-XE, NX-OS, EOS and AOS-CX, for a port that
says it is a trunk and whose list holds VLAN 1; nothing on Junos,
and nothing on OS10, whose default is a setting of the switch.  A
port that keeps trunk lines without saying it is a trunk is given
none, as it is given nothing of the platform's list.  So an unset
`trunk_native_vlan`
in a tree a parser made is no untagged VLAN, and the tree has no
value for "not stated" here either.  The `switchport` renderers
write no native line for the VLAN that is their platform's default.
The other direction: a trunk with no native VLAN whose list holds
the default is written its target's form for "this trunk carries no
VLAN untagged" (`wants_no_untagged_vlan`) -- AOS-CX `vlan trunk
native 1 tag`, EOS `switchport trunk native vlan tag`, and on IOS-XE
and NX-OS `vlan dot1q tag native`, a line for every trunk of the
switch, written only where no port the check reads blocks it
(`every_native_vlan_tagged`: the ports in trunk mode, the ports with
trunk lines and no mode, and the ports in a mode no mode line is
written for -- dynamic, private-vlan, dot1q-tunnel, fex-fabric and
the like; a port with no mode and no trunk line is not counted);
otherwise such a port has a `! review:` line and the target's
default.  OS10 and AOS-S have a default for such a port too, and are
asked another question.  OS10's is the switch's default VLAN, which
has no id the list can be asked about: a trunk with no native VLAN
is written `no switchport access vlan`, under a `! review:` line
(Dell's pages disagree on what it leaves), unless another record of
the interface states its untagged VLAN -- a native VLAN, or an access
VLAN -- which the line would take back.  AOS-S is asked of the
output's member lists, VLAN by VLAN: a name some VLAN tags, none
lists untagged and no line of VLAN 1 names is taken out of VLAN 1
with `no untagged` in VLAN 1's stanza, written for a tree that has no
VLAN 1 record as well.  What
remains -- a trunk that carries nothing, which AOS-S has no form for
-- is in the CHANGELOG's known limitations.
[`tests/unit/migration/test_the_list_holds_the_native_vlan.py`](tests/unit/migration/test_the_list_holds_the_native_vlan.py)
reads what a device carries untagged on each side of every job by
its own platform's grammar, and does not read the tree by the
convention it guards.

**What makes a switchport VLAN real** (the phantom-VLAN prune,
`transforms.switchport_declared_vlan_ids`).  Left to itself the
projection synthesises a `CanonicalVlan` for every VID a switchport
line mentions, so the six port-centric codecs (`cisco_iosxe_cli`,
`arista_eos`, `cisco_nxos`, `juniper_junos`, `aruba_aoscx`,
`dell_os10`) snapshot a "legitimate" VID set before projecting, hand it
to the projection (`keep=`) so that no record outside it is made at
all, and prune to it after.  That set is every
declared `vlan <N>` stanza, every `access_vlan` / `trunk_native_vlan`,
and — provided the expanded list is no wider than
`TRUNK_ALLOWED_SPECIFICITY_BOUND` — every member of a
`trunk_allowed_vlans` list.  The bound exists because a trunk-allowed
list is a *filter*, not a VLAN database: a narrow one enumerates
exactly the VLANs on that link, while a wide one (`1-4094`) says
"don't filter" and names no VLAN at all.  Breadth is the only signal
that separates them — literal form does not, since real narrow
declarations are written as ranges too (`701-710`).  Trunk-allowed
members were excluded outright until 2026-09; that dropped 45 real
VLANs across the committed corpus at parse time, *before* the
cross-mesh comparison could see them, so every affected cell scored
ALIGNED.  A constant this load-bearing would rot silently, so
`tests/unit/migration/test_trunk_allowed_specificity_bound.py`
re-measures the corpus each CI run and fails if a genuine trunk list
ever lands near the bound.

**`kind=mgmt` cascade**.  Source-side codecs promote
`CanonicalInterface.kind` from `physical` to `mgmt` when context
indicates an out-of-band management interface (e.g. cisco_iosxe_cli
parser detects `Mgmt-vrf` binding on a `GigabitEthernet0/0`).
Target codecs route `kind=mgmt` interfaces through dedicated emit
paths: Aruba `oobm` block, FortiGate `mgmt1` port, OPNsense
`opt_mgmt` zone, Junos routing-instance binding.  Honours the
canonical `kind` field; never emit a regular physical port for
mgmt-classified interfaces.

**Tier-3 drop detection** (`netcanon/migration/_tier3_detection.py`).
Tier-3 stanzas (firewall / NAT / VPN / routing-protocols) have no
canonical surface, so codec parsers silently skip them.  Each parser
calls its per-vendor `detect_tier3_sections_<vendor>(raw)` before
returning, populating `CanonicalIntent.dropped_tier3_sections` with
human-readable labels that the migrate page surfaces as a "Detected in
source but not translated" banner.  (The Junos codec hands its
detector the set-form the parser read, since the patterns begin
`set `, and puts ahead of the sections a bounded list of rows for
the statements the parser read and left out — `inactive: ...` for
one the source had deactivated.  The IOS XR codec lists an
`interface preconfigure` stanza, which the router holds for an
interface it does not have, with a row of the same kind:
`preconfigure: ...`.)  Output-only — a notification
surface, never fed to the renderer or any transform — so the
deliberate drop is surfaced honestly (the silent-drop-honesty
discipline `docs/METHODOLOGY.md` treats as flagship).

When adding a new codec, audit each policy and decide whether to
opt in.  Most cases: opt in.  Re-implementing the policy locally is
the wrong call — see `netcanon/migration/codecs/README.md`
"Cross-codec shared utilities" section.

---

## Target profiles (hardware-aware rename-modal metadata)

**Where:** `netcanon/definitions/library/target_profiles/*.yaml` +
`netcanon/migration/target_profiles.py`
**What:** Declarative descriptions of a target device's port
inventory — vendor, model, device class, stacking mode,
chassis-fixed ports + optional swappable-module variants, LAG
capacity.  Loaded from YAML at startup; never modified at runtime.

**Purpose:** drive the Tier-3 **rename modal** in `/migrate`:

* Populate the per-row target-name dropdown with the profile's
  valid port ids (so a Cat 9300-48P offers `GigabitEthernet1/0/1`
  … `1/0/48` + the selected uplink module, not free-form text).
* Drive the hardware fit-check banner (source vs. target per-kind
  capacity comparison).
* Drive the three-stage `vendor → model → module` selector cascade.

Profiles are **optional** — leaving the target-profile dropdown
empty falls back to Tier-2 free-form input (the codec still runs,
no dropdown validation).  The `opnsense/Generic` profile with
``ports: []`` is an explicit opt-out for bring-your-own-hardware
cases.

### Two shapes: legacy vs. module-variant

**Legacy** (fixed hardware — 2930F, C9500, fixed-port firewalls):

```yaml
vendor: aruba_aoss
model: 2930F-48G
deployment_state: "standalone (VSF disabled)"
evidence: capture
evidence_ref: "tests/fixtures/real/aruba_aoss/hpe_community_2930f_wc1607_intervlan.cfg"
ports:
  - {range: "1-48", kind: physical, speed: gig}
  - {range: "49-52", kind: uplink, speed: gig, sfp: true}
lags: {max: 60, prefix: Trk}
```

**Module-variant** (chassis + swappable uplink module — Cat 9300
NM slot, Aruba 3810M expansion slot):

```yaml
vendor: cisco_iosxe
model: C9300-48P
ports:                              # chassis-fixed
  - {range: "GigabitEthernet1/0/1-48", kind: physical, speed: gig, poe: true}
  - {id: "GigabitEthernet0/0", kind: mgmt, speed: gig}
modules:
  NM-8X:
    description: "8x 10G SFP+"
    ports:
      - {range: "TenGigabitEthernet1/1/1-8", kind: uplink, speed: 10gig, sfp: true}
  NM-2Q:
    description: "2x 40G QSFP+"
    ports:
      - {range: "FortyGigabitEthernet1/1/1-2", kind: uplink, speed: 40gig, sfp: true}
```

Modules are **additive**: `effective_ports(sku) = chassis_ports +
modules[sku].ports`.  The UI's third-stage dropdown enumerates
declared SKUs; operator picks the module they have installed and
the dropdown options reconfigure.  `MODULE_VARIANT_PROFILES`
allowlists in
[`tests/unit/migration/test_target_profile_shipped.py`](tests/unit/migration/test_target_profile_shipped.py)
and [`tests/integration/test_migration_target_profiles_api.py`](tests/integration/test_migration_target_profiles_api.py)
guard against silent drift — a profile listed there must actually
declare `modules:`, and a legacy profile must keep `modules: {}`.

### Provenance: a profile describes hardware, in one stated state

A port id an operator picks from a profile is written **verbatim**
into the generated config, so a wrong id is a config naming a port
the device does not have.  A registry audit found exactly that in a
third of the shipped profiles.  Most had one written cause — the
authoring guide told contributors to derive ids from
`format_port_identity`, so profiles described the formatter rather
than the device; the remainder were vendor documents misread or a
sibling model's facts transplanted.  Optional provenance fields now
carry what is actually known:

* `deployment_state` — a port's name is a function of the model
  **and** how it is deployed (an Aruba 2930F port is `24` standalone
  and `1/24` as a VSF member).  A flat port list describes one state;
  every stack-capable profile must say which.
* `evidence` — `capture` | `vendor-doc` | `inferred`, grading the
  port names and counts.  `capture` is a checked claim, not a label:
  `evidence_ref` names a committed real fixture and
  [`tests/unit/migration/test_target_profile_evidence.py`](tests/unit/migration/test_target_profile_evidence.py)
  parses it on every run, failing if the fixture does not identify
  itself as that model or any profile port id is not a hardware port
  in it.  The graded sets are pinned, so a grade cannot appear or
  vanish unreviewed.  Unset means *not yet graded* — not a clean bill
  of health, and the UI says "not yet graded" rather than nothing.
* `caveat` — operator-visible text, mandatory when the grade is
  `inferred`.

The rename modal shows all three under the fit-check banner
(`migrate-rename-profile-notice`, amber when the grade is
`inferred`), and `/definitions` lists them per profile.  A profile
that is known wrong but whose correct names are not established for
the exact model is **flagged, not renamed** — replacing one
plausible name with another is how the registry got here.  A profile
for hardware its target OS does not run on is neither: it is deleted,
since no device exists for the names to be right on.

Selecting a profile still has **no effect on auto-translated names**:
the codec formatter derives a target name from the shape of the
source name (Cisco `GigabitEthernet1/0/1` becomes AOS-S `1/1`)
whatever model is selected, so the auto column can disagree with a
profile that describes a standalone switch.  The rename table marks
each row whose auto name is not a port the selected profile lists
(`has-offprofile`, "N not on profile" on the section header), so the
disagreement is visible per port.  Closing it needs the pipeline to
be told the source and target models: a request that declares both
devices is paired by position (see "Device models and inventories"
below), and the modal's source-device and target-device pickers
send exactly that.  With a target chosen and no source device, the
paragraph above still holds.

### Per-category capacity limits

Profiles may declare `max_vlans` and/or `max_local_users` to
drive per-pane fit-check banners in the rename modal (VLAN pane +
local-users pane each render their own banner when the active
profile declares the corresponding limit).  Both fields are
optional — `None` means "no limit known / declared" and hides the
banner for that pane.  Same discipline as the existing ports
fit-check: no profile selected = no banner; no limit on a profile
= no banner for that category.

Values should come from vendor datasheets and be hedged
conservatively — silently-wrong limits are worse than missing
ones because they let bad migrations look safe.  Every shipped
profile currently declares `max_vlans`; per-vendor rationale:

* Aruba 2930F family — 2048 (the `max-vlans` ceiling, AOS-S 16.11
  Advanced Traffic Management Guide; the factory default is 256).
* Aruba 3810M / 6300M + Cisco C9300 / C9500 — 4094 (enforced
  protocol ceiling).
* MikroTik RouterOS + OPNsense — 4094 (protocol ceiling;
  software-VLAN stacks have no hardware cap).
* Juniper — the figure each model's datasheet prints (4093 / 4091 /
  4093), which is one or three short of the VLAN-id range.
* Arista — 4094, the usable VLAN-id range (the datasheets print
  "4096 VLANs").
* FortiGate 40F / 60F — 512; 100E — 1024 (FortiOS 7.x
  "Maximum Values Table").

`max_local_users` is declared only where the datasheet number is
small enough to matter and the codec actually round-trips users
(Aruba CX 6300M = 64, vendor-documented).  The Aruba AOS-S profiles
leave it unset: the 16 they once carried was not a vendor figure, and
an unsourced cap drives a banner that is confidently wrong.  OPNsense
leaves it unset
because its user count is software-unbounded in practice and so
carries no useful fit-check signal; FortiGate leaves it unset
because the admin-account cap varies materially by FortiOS version
and isn't a reliable datasheet number.  **Both codecs round-trip
`CanonicalLocalUser` end-to-end** — see the
`unsupported_rename_categories` discussion above, where the
incorrect `{"local_users"}` entry and its compat-banner rationale
were removed.  MikroTik leaves it unset because RouterOS's
user count is software-unbounded.  Shipped-profile lock-in tests
in
[`tests/unit/migration/test_target_profile_shipped.py`](tests/unit/migration/test_target_profile_shipped.py)
guard against drift on both fields.

### Relationship to backup-side device definitions

The two subsystems share a vendor slug (`cisco_iosxe`,
`aruba_aoss`, etc.) but not a schema.  Backup definitions describe
**how to fetch bytes** (`prompts.trailing`, paging, netmiko
device_type); target profiles describe **what port ids exist on
the target**.  No automatic cross-link today; a future `PlatformKey`
shared type may unify on `(vendor, os_family)` — see
[`translator-plans.txt`](translator-plans.txt).

See [`netcanon/definitions/library/README.md`](netcanon/definitions/library/README.md) for full
schema + authoring guide;
[`netcanon/migration/target_profiles.py`](netcanon/migration/target_profiles.py)
for the loader + accessor implementation.

### The `/definitions` browsing page

`/definitions` is the single browsing view for everything
Netcanon knows about — four sections in one page:

1. **Backup-side device definitions** (`section-device-definitions`):
   the legacy table — what vendor YAMLs the backup layer
   recognises (`Cisco`, `Fortigate`, etc.).  Excludes overlays so
   each `type_key` appears exactly once.
2. **Version / model overlays** (`section-overlays`, conditional):
   the extra variants (`Cisco 17.12`) that the loader keeps in
   its `_variants` registry but filters out of `load_all()`.
   Explains "loaded N but showed N-M" on the startup log.
3. **Migration target profiles** (`section-target-profiles`):
   dozens of hardware models with per-model port layouts, module
   variants (NM-8X, NM-2Q, JL083A, …), stacking caps, VLAN/user
   limits, and each profile's provenance (deployment state,
   evidence grade, caveat).  Previously only reachable through the Tier-3
   rename-modal dropdown — now browsable with vendor grouping +
   live filter.
4. **Migration vendors + codec capabilities** (`section-vendors`):
   every shipped migration vendor with its registered codecs,
   direction (`parse_only` / `bidirectional`), certainty tier
   (`certified` / `best_effort` / `experimental`), and per-codec
   capability-matrix counts (supported / lossy / unsupported xpaths).

Template: [`netcanon/templates/definitions.html`](netcanon/templates/definitions.html).
Route: [`netcanon/api/routes/ui.py::definitions_page`](netcanon/api/routes/ui.py).
Collapsible panels use native `<details>` / `<summary>` — zero
JS, browser-built-in keyboard + screen-reader behaviour.
The profile filter is a pure DOM hide/show on a pre-lowercased
`data-haystack` attribute set server-side (vendor + model +
display_name concatenated).  See
[`tests/testid_reference.md`](tests/testid_reference.md) for
the full testid inventory (one `section-*` testid per
container, plus per-row, per-module, per-codec testids).

---

## Device models and inventories (model-to-model port mapping)

**Where:** `netcanon/migration/device_models.py` (schema, compiler,
loader), `netcanon/migration/port_mapping.py` (the mapper),
`netcanon/migration/deployment_detect.py` (reading the source device
from the config), `netcanon/models/port_inventory.py` (the data
shapes), `netcanon/definitions/library/model_families/*.yaml` (the
data), and one naming rule per grammar — and, where there is one, one
detector — beside each vendor's codec.

**The problem.**  A port name cannot be translated from its shape.
The same string means different ports on different models, and the
same port has different names depending on how the device is
deployed: an Aruba 2930F port is `24` standalone and `1/24` as a VSF
member; a 2930M's first uplink is `A1` with stacking disabled, `1/A1`
with it enabled, and does not exist with the bay empty.  The
name-shape translator (`canonical/port_names.py`) is not told the
model, so on a same-vendor pair it is the identity — a name nobody
mapped stands as written — and it
could never know that port `49` of one switch is `1/A1` of another.

**The approach: translate positions, not names.**  Each end of a
migration is declared as a *deployment* — a mode, and an ordered list
of members, each a model with its fitted modules.  A deployment
compiles to an *inventory*: the ordered list of the ports that exist,
each with its real name.  Two inventories are paired by position, and
the pairing is an ordinary `port_rename_map`, which the translator
already applies ahead of its own guess.  The translator is shared with
every translation, so what this feature needs from it is kept small
and applies to all of them: a name the target cannot express is
stripped before anything is renamed, a route's next hop that is
the name of an interface follows that interface, and a sub-interface
goes where its port goes.  Everything that
depends on knowing the target device is done by the caller that knows
it.

```
   declared source device                    declared target device
   (deployment, or a profile key)            (deployment, or a profile key)
              │ compile                                  │ compile
              ▼                                          ▼
          Inventory ──────── plan_port_mapping ──────── Inventory
                                   │   (only the ports the config uses)
                                   ▼
                MappingPlan { rename_map, pairings, unplaced,
                              off_inventory, evidence, ... }
                                   │
       operator port_rename_map ───┤   always wins
                                   ▼
                     run_plan_with_overrides   (unchanged)
                                   │
                                   ▼
        check the finished run, over EVERY name the config
        references: did two names end on one target name, or a
        logical name on a port of the target?  A name nobody
        decided that caused it is dropped and the translation run
        once more; then settle_plan records what happened.
```

**Families, models, modes.**  The registry does not list names; it
lists facts.  A *family* file holds models that share a naming rule, a
set of deployment modes and a set of modules.  A *model* is one part
number's fixed panel (port groups in port-number order) plus its
module bays.  A *mode* is a deployment state that changes names.  A
*naming rule* is a small pure function beside the codec — one per
naming grammar, not per product line — that renders one port's name
from its coordinates, and declares which roles it can name at all (a
group in a role the rule cannot name is refused at load: AOS-S
out-of-band management is the `oobm` context, not a numbered port).

**Pairing policy** (`port_mapping.py`):

* Members pair by rank, never by vendor member id — ids are sticky and
  sparse, so a lone ex-member can be `3/N`.  A member's rank is its
  place in the declaration's list, so two stacks pair in the order
  their members are listed, and that order is how an operator chooses
  which member goes where.  Where it puts a member the config uses
  on a member of another number, the plan says which went to which
  (`_member_lines`): in one line for a RENUMBERING, where neither
  number is declared on the other side, and in another for a
  CROSSING, where one is — for instance the same members listed in
  another order — with what to do about it.  Neither holds a job.  A
  side read from a
  flat profile states no member number, and gets neither line.
* Within a member, ports pair role to role, in order.  A port never
  changes member to find a place.
* A used port with no position on the target is **dropped,
  explicitly**, and reported.  It is never spilled onto a port of
  another role, and never left out of the map: left to the name-shape
  translator it would keep its old name on a same-vendor pair, which
  can be the very name another port was just mapped to.
* A sub-interface (`ge-0/0/0.54`) follows its parent port, and is
  dropped with it.  Between two configs of the **same codec** the
  pipeline writes the entry beforehand: the unit suffix means the
  same thing on both sides.  Across codecs the translator's own rule
  for a unit sends it after the port it was PAIRED with
  (`Ethernet1.54`), and the pipeline reads what followed from the
  finished run.  Both are recorded in `sub_interfaces`, and neither
  asks for a decision — with one exception, across codecs: a unit
  the parsed source holds no 802.1Q tag for.  It went with its port
  like the rest, the output has an interface of that name with no
  VLAN, and nothing else in the job would say so (there is no tag
  for the validation report to list).  It is recorded in
  `untagged_units` instead, stays off-inventory and unresolved,
  and has a line of its own.  A second exception, on either path: a
  unit the plan does not take for a unit of its port — typed in
  another letter case than the port, or a unit of a unit.  The
  finished run shows it went where its port went; the plan records
  that (`unvouched_units`) so that its line and the page's row say
  what happened, and leaves it off-inventory and unresolved.  An
  operator's entry that names a sub-interface onto a unit of a port
  the target lists is where the plan itself would put one, and is
  not reported as off-target.  A target with no sub-interfaces still
  gets an interface of that name (`1.54` on AOS-S), which is not a
  name of the device; where the source holds a tag the validation
  report lists it as one the target cannot carry.
* Some names are left to the name-shape translator — the ordinary
  port translation, which derives a target name from the shape of
  the source name without knowing either model (and, between two
  configs of one codec, derives nothing: the name stands).  An unplaced
  *management* port, because the translator knows what each target
  does with out-of-band management (AOS-S has an `oobm` block, not a
  management interface).  A name the config uses that is not a port
  of the declared source — **off-inventory**, the tripwire for a
  source model declared wrongly.  And every *logical* name (a LAG, an
  SVI, a loopback), which was never the mapper's to decide.
* **What the translator makes of those names is checked — all of
  them.**  Its answer can be a port the pairing gave to something
  else: a management port whose role comes from a profile rather
  than from its name is, by shape, just port 1; a FortiGate aggregate
  whose codec classifies its name as a physical port becomes the
  first port of every target.  The mapper cannot know that in advance
  without re-deriving the translator, so the pipeline asks the
  finished run instead (`fused_targets`), over every name the config
  references and not only the hardware ports the plan was made for.
  Where a hardware port and another name ended on one target, or a
  logical name ended on a port of the target, every name that
  neither the pairing nor the operator decided is dropped —
  **displaced** — and the translation is run once more.  Where no
  name in a clash was decided, one keeps the name — a port of the
  declared source if there is one, else a hardware port, else the
  first: its place was good.  A fusion that is left is the
  operator's own override; it is recorded (`fused`) and the job is
  not a clean success, whatever was acknowledged.  (Two *logical*
  names the ordinary translation puts on one name — two loopbacks on
  a target with one loopback form — are outside this check and are
  warned about by the translator, as they always were.)
* **Whether another letter case can be another interface is a fact
  about the platform**, and each codec states it
  (`CodecBase.port_names_case_sensitive`).  On AOS-S or IOS `1/a1` is
  the port `1/A1`, and an override that hides behind its spelling
  would put two ports on one.  On FortiOS and RouterOS, where an
  operator chooses interface names as free text, `DMZ` and `dmz` are
  two interfaces, and folding them together turned an operator's own
  name for a VLAN interface into the physical port beside it.  Junos,
  VyOS and OPNsense names are case-sensitive too, and that is the
  wrong question there: every interface name is the system's, in
  lower case, so `GE-0/0/2` is `ge-0/0/2` misspelt and is compared as
  that port.  Source names are compared by the source platform's rule
  and target names by the target's.  There is no safe default — the
  wrong value either merges two interfaces in silence or lets a
  misspelling pass beside the port — so every codec states its own,
  and a test fails for one that does not.
* **The plan's flags and warnings describe the outcome, not the
  intention.**  `settle_plan` reconciles the plan with the run: an
  unplaced port the operator gave a target was kept; a management
  port the target cannot express was dropped by the translator and
  is reported as dropped; a route, a DHCP pool, a VRRP track entry or
  a VTEP source that named a dropped port went with it and is
  listed.  `unresolved_ports`, `displaced`, `fused`, `off_target`,
  `target_hardware`, `source_hardware`, `unbound_ports`,
  `landed_off_target`, `stale_next_hops`,
  `sub_interfaces`, `untagged_units`, `unvouched_units`,
  `emptied_lags`, `shrunk_lags`,
  `lost_routes`,
  `lost_dhcp_pools`, `lost_tracking` and `lost_vtep_sources` are
  stored fields, so a client reads the outcome as data.  `pairings` and
  `rename_map` stay the pairing as it was made, before the
  operator's map: `overridden` names the pairings a client must not
  read as final.
* A run with an unresolved name — dropped for want of a place, a
  management port kept although the target lists none,
  off-inventory, displaced, or a logical name given a port-shaped
  name the target does not list, and not named in the operator's own
  map — or with a fused target, or with a route left naming a port
  that moved, or with a port the output does not look up by
  its hardware, or for which no pairing could be made at all, is
  `partial`, not `completed`.
* An operator's target is read as the declared target spells its
  ports (`1/a1` is `1/A1`) where another letter case cannot be
  another interface on the target platform — it has no case, or it
  names every interface itself in lower case; on FortiOS and RouterOS
  it is stripped and taken as typed.  An entry with a blank target is
  set aside: it decides
  nothing.  Only case and surrounding space are understood: an
  abbreviation the device accepts (`Gi1/0/1`) is not recognised as
  the port it names, and is reported as a target the model does not
  list.

**Which names a mapping is made for.**  `collect_port_names` is the
list of the port names a canonical tree holds: every place the
translator's rename pass rewrites.  They are the names the CONFIG
uses.  A route's next hop can name an interface too (RouterOS
`gateway=ether1`, Junos `next-hop et-0/0/24.0`): where it is exactly
an interface's name — or, between two configs of one codec, such a
name with a unit — the route follows its interface and goes with a
dropped one.  Any other form (a list of gateways, a routing-table
suffix, a unit across vendors) is left as written, and
`run_plan_with_models` lists the route (`stale_next_hops`) — as it
does a next hop naming a port of the declared source that the config
has no interface record for.  A list whose members only changed
places among themselves still says what it said, and is not listed.

**A port's hardware identity is not a reference to it.**  RouterOS
keeps a port's *factory name* (`ether2`) beside the name an operator
may have given it (`core-a`).  The rest of the config uses the
second; the renderer finds the port on the device by the first
(`set [ find default-name=ether2 ] name=core-a`).  An entry of a
rename map can therefore mean two things, and nothing in the entry
says which: MOVE this port's config onto other hardware, or NAME this
port.  `sfp1` is a port of one RouterOS model and a short name for
`sfp-sfpplus1` on another, so the shape of the name cannot decide it.
A declared target device can.  So:

* the translator — shared with every translation — never touches the
  factory name.  Without devices declared an entry names a port, and
  the output finds it by the factory name it had, as it always did;
* `run_plan_with_models` finds such a port in the source model by its
  factory name, and speaks of it everywhere else — the plan, the
  job's lists, the key of an operator's entry — by the name the
  config uses (`labelled_ports` says which port of the model that
  is);
* onto a target that finds a port by a factory name — the codec
  says so (`ports_keep_a_factory_name`; RouterOS) — it sets the
  factory name itself, after the translator has run, on every port
  the mapping can account for, whatever vendor the config came from.
  Which port of the SOURCE an interface of the translated tree is:
  the one whose factory name it still carries, where the source
  config recorded one; else the port of the declared source whose
  name the rename map sent to this interface's name.  (A RouterOS
  config states a factory name only on a port it has an
  `/interface ethernet` line for, and another vendor's config states
  none.)  Where that port then is: a port whose name in the output is
  a port of the declared target IS that port; a port under any other
  name — one an operator gave it, in the source config or in their
  map — is on the hardware its pairing gave it.  Where each port's
  hardware ended is read back from the tree that is rendered
  (`target_hardware`; `source_hardware` where that hardware is not a
  port of the target), and two ports on one piece of hardware are a
  clash although they share no name;
* the tree is not the output.  The RouterOS renderer writes no
  Ethernet line for an interface whose name reads as a VLAN, a
  bridge, a LAG or a loopback, whatever factory name the interface
  carries.  None of that rule is re-derived: the rendered output is
  parsed again with the target's own parser, and a port that no line
  OF ITS OWN looks up by its hardware is listed (`unbound_ports`) and
  leaves the job `partial`.  That another interface is looked up by
  the same hardware says nothing for the port;
* and the binder's reach is not the pairing's.  The binder walks
  interfaces; the pairing is over every port the config uses, and a
  port named only as a LAG member or in a route has no interface.
  Under the target port's name it needs no line.  Under a name an
  operator gave it nothing defines it, so the read-back is handed the
  pairing's list as well as the binder's and reports such a port
  where the output uses its name;
* onto any other vendor a port has one name, so a port an operator
  named takes the name of the port it was paired with.

The field was first missing from the check altogether, while every
moved RouterOS port was rendered as "find the port with the old
name"; it was then rewritten in the translator, which was right for
two declared devices and broke the commonest entry of a rename map
for everyone else; and the handling that replaced that acted only
between two RouterOS configs, on a port whose factory name the config
happened to state — so a port named from any other vendor, or an SFP
port with no line of its own, was still rendered as "find the port
with this name".  All three are the same mistake: a rule made total
over the case in view, in code that serves a wider one.

That list of places was written by reading the tree, and a list
written that way cannot show that it is complete.  So it is also
checked by an experiment that needs no list
([`tests/unit/migration/test_port_name_universe.py`](tests/unit/migration/test_port_name_universe.py)):
send port names to one another through the translator on the
committed captures, and compare the output, parsed again, with the
unmoved output in which the same names are sent to one another.
What it reaches is limited and is itself tested: a field only where
a capture puts a moved name in it and the codec's parser reads the
field back; names the device already has; two configs of one codec.
The module breaks the translator at each place in turn and pins
which places a capture catches; each of the others has a small
config there that does.  Its table of places, the rename pass and
the collector are compared on a tree built from the canonical schema
— a name of its own in every `str` and `list[str]` field — so a field
added to one of the three and not the others fails without anyone
keeping a fixture.  A field that holds text in another shape (a dict,
a set, a union) fails the builder itself until it is taught the shape
or listed as holding no port name: left empty, it would be missing
from all three alike.

The places are of two kinds.  An interface stanza, a VLAN's
membership list and a LAG's member list are *evidence* that the
device has a port of that name.
A static route's or DHCP pool's interface, a VRRP track entry and a
VTEP source are *references*: a real port named only there must be
part of the mapping, but what those fields hold is not always an
interface — a route to `Null0`, an EOS pool's own name, a VTEP
source address — so a reference counts only when the declared
inventory lists it or the source codec's classifier positively calls
it a hardware port.  From the evidence is taken what is not
hardware: an interface whose canonical type says SVI, LAG, loopback,
bridge or tunnel; a LAG's name; and a name the classifier
*positively* calls logical.  `unknown` is never grounds for leaving
evidence out (on AOS-S it is what a real uplink named `A1`
classifies as), and a port of the declared source always counts,
whatever the classifier says.  This set is what the mapping is made
FOR; the check on the finished run reads every name.

**Evidence is per port, and `capture` is granted.**  A name is the
product of separately evidenced facts — the mode's naming, the
model's panel, the module's port count — each graded `vendor-doc` or
`inferred` where it is stated; a port takes the weakest of the facts
that produced it.  None of them may be `capture`: a capture proves one
deployment, so it is declared as a *capture claim* (fixture, a line
only that model's capture contains, mode, members) and granted only
where a deployment matches exactly — same model, same mode, same
member id, and for a bay port the same module.  A sibling model, a TAA
twin, another member id or another module does not inherit it.

`capture` means a test re-proves the claim on every run, so only the
claims that test re-proves grant it: the engine holds their list
(`PROVEN_CAPTURE_CLAIMS`) and the shipped-data test requires that
list to equal the claims it re-proves.  An entry is the whole claim —
fixture, mode, each member's model, id and modules — so a proven
fixture cited for another model grants nothing either.  A claim in
an operator's own family file names a fixture nothing reads; it is
logged and grants nothing.  And a capture proves *names*: it retires the caveat of the
naming fact and keeps the caveat of the panel or module fact, because
which ports are uplinks is not something a config shows.  For the
same reason the grade on a pairing or a plan says how well the two
port names are established, not that the pairing was observed.

**Guards**
([`tests/unit/migration/test_device_models_shipped.py`](tests/unit/migration/test_device_models_shipped.py)):
every shipped file loads strictly; every capture claim is pinned
whole and re-proven against its fixture, whose ports must equal the
compiled inventory (a capture that names only some ports cannot be
claimed); the `(name, role)` sequence of every shipped model in every
mode with every module is pinned from hand-typed tables in the test,
not regenerated from the code under test (a capture cannot prove
which ports are uplinks), as are which part number is
which model and which facts are graded `inferred`; every compiled
name the vendor's classifier recognises round-trips to the member,
slot and port that produced it — the bare-letter module port of a
switch that is not stacked (`A1`) is not recognised by the AOS-S
classifier yet and is pinned as a known gap, which the mapping does
not depend on because an explicit rename entry is applied before
classification; and where a flat target profile describes the same
device, the two must list the same ports with the same roles.
The pipeline's central promise — no hardware port on a target name
another name ends on, unless the operator asked for it — is asserted
on the jobs of
[`tests/unit/migration/test_run_plan_with_models.py`](tests/unit/migration/test_run_plan_with_models.py),
whose wrapper also reads each job's RENDERED OUTPUT back: an
interface that can be recognised by its address must be on the port
the job reports, the output must name no port the job does not
report, no name that moved may still be in it, and no interface may
carry the addresses of two source interfaces; and, on a target that
finds a port by a factory name, for a port that carries no address at
all (a LAG member, a route's interface), the name it has in the
output must be a port of the target or an interface the output looks
up by a factory name.  An AOS-S port carries no address either, so
between two stacks — where the names of one member are names of the
other — none of those can tell one member's config from another's:
between two AOS-S configs the wrapper also compares every VLAN list
and LAG member list of the output with the source's, each name moved
as the job says.  The address checks
and the old-name check take nothing from the engine's list of places;
the port-list check reads both sides with the engine's collectors.
Each is handed a job with the defect it is for, in the same module,
and has to fail — and the wrapper is handed such a job for each of
its assertions, and has to refuse it in that assertion's own words,
so that none can be taken out of the wrapper unnoticed.  (Where a
test expects two ports on one name, the checks that read a port's
place off its address and the list comparison are not run: a parser
gives back one interface per name.)

**Relationship to target profiles.**  A target profile is one model in
one stated state, as a flat list.  `inventory_from_profile` reads one
into the same `Inventory` shape, so a device no family describes yet
can still be declared — as one device, with its ports in the
profile's list order, which the mapping plan flags as unvouched.
Where a family and a profile describe the same device, the family is
authoritative for port mapping and the profile keeps feeding the
rename modal's dropdowns until it is retired.

**Loading.**  The shipped families always load.  An operator's own
`model_families/` directory under a relocated definitions directory is
laid over them: it can add new families, each with its own models.  A
file that re-declares a shipped family — even to add one model to it
— is refused and logged, so a shipped family is never replaced.  A
file that cannot be loaded for any reason (not UTF-8, not YAML, a
YAML alias, a key that is not a plain name, the wrong schema) is
logged and skipped; none of them can stop the application starting.
Both `target_profiles/` and `model_families/` are reserved as
immediate children of the definitions root, so the backup-side
definition loader does not try to read them.

**API.**  `GET /api/v1/migration/model-families` lists families;
`POST /api/v1/migration/inventory` compiles one declaration to its
ports; `POST /api/v1/migration/detect-deployment` proposes the source
declaration from the config; a plan request that declares both devices
(`source_deployment` or `source_profile`, with `target_deployment` or
`target_profile`) is paired by position on every plan endpoint and
returns the pairing on `MigrationJob.port_mapping_plan`; the body's
own `port_rename_map` is the operator's edits to that pairing on
every one of them, the per-pane endpoints included.
`target_profile` on its own stays advisory; a `target_deployment` on
its own is refused.

**Not modelled yet:** modular chassis (every bay-and-module
combination of a model is compiled when its family loads, and that
product is capped), breakout lanes, ports a stack consumes as links,
ports that belong to a stack rather than a member, literal
non-systematic names, the form a tagged routed sub-interface takes
on a target that has none (it is written `<port>.<unit>` and its tag
is reported), and whether a model has an out-of-band management
port at all (a kept management port therefore always needs the
operator's decision).

**In the rename modal** (`_partials/device-models.js`).  The ports
pane has a source-device row and a target-device row.  A device is a
model from a model family — with its mode, the module in each bay
and, in a stacking mode, its members — or a flat profile where no
family describes it.  The source row is pre-filled from the config
(`/detect-deployment`) and shows the lines it was read from.  The
source declaration, and a target family model, are compiled by the
server (`/inventory`) as they are edited, and the note under each
says what it resolved to, how well its port names are established,
and every caveat; a target flat profile is not compiled — the
browser already holds its port list, and shows the profile notice.
The browser holds no naming rule and no port list of its own for a
family model: it shows what the server compiled.  Apply sends the two
declarations with the operator's overrides; the table then draws
the plan — each pairing with the position that decided it, and
each name the plan could not place, with what happened to it and a
marker while it still needs a decision.  Five rules keep the screen
and the request honest:

* every device field is removed from the cloned request body before
  the current declarations are added, so a device that was cleared
  cannot ride along from the last Apply;
* a source device, or a target family model, is sent only as one of
  a pair — a target alone stays advice for the choices in the table,
  as it always was;
* a pair is sent **whether or not its preview compiled**.  The
  browser does not judge a declaration: one the server would refuse
  is refused by the server, in words, and nothing is applied.
  Leaving it out instead turned a mistyped member number into a
  translation by name shape that reported success.  Those words are
  the footer's status line (`setRenameStatus`, its one writer), not
  only a toast: a toast is gone in four seconds;
* the strip is drawn from what **happened** — `port_renames`,
  `port_drops` and the plan's outcome fields — not from `pairings`,
  which is the pairing as made, before the operator's entries; and
  its colour is the state of the job on the page, not of edits that
  have not been sent;
* what **Accept as shown** records is kept apart from the operator's
  own override map (`_planAccepted`): it is a verdict on one pairing,
  so it is dropped when Apply is pressed with other devices declared,
  and it is not written to `localStorage`.

The modal does not block the page, so the job under it can be
replaced; `captureJobForRename` then redraws the modal from the new
job, and an answer that arrives for the old one — a preview, a
detection, an Apply — is dropped.

**Reading the source device from the config**
(`netcanon/migration/deployment_detect.py`).  An AOS-S `show
running-config` usually states its own hardware; no other vendor has a
detector yet.  Detection is split the way naming is: a small *detector*
beside the vendor's codec reads the lines that state the device and
returns the part numbers, member numbers and bays they state — it has
no table of models — and `propose_deployment` resolves what was read
against the model registry, picks the family mode from whether the
config is in a stacking mode, compiles the result, and **checks it
against the config**: every port name the config uses should be a port
of the device the config says it is.  That check is the collection a
translation makes of the same config, with the same folding, so a
proposal's missing ports are, up to the cap on that list, the ports a
translation would report as off the inventory (a vendor whose ports
keep a factory name gets no detector until that holds for it too).
The result is a *proposal* with the hardware lines
it was read from, each as far as its part number; it is never applied
by itself, because a member or module line states what a device is
provisioned for, not what is fitted.  A detector reads what a config
states and must not infer a model from the shape or number of its port
names — that is the guess this whole section exists to replace.  It
also reads text nobody vouches for: its patterns are anchored to a
line and bounded, what a proposal carries is capped (members,
evidence, missing ports, notes), and every way of not arriving at a
deployment is an answer whose first note is the reason rather than an
error.  Guards: the detector must agree with
every proven capture claim of a vendor that has a detector, since both
describe the same committed capture; and every registered detector is
handed text made to be slow.

Authoring guide:
[`docs/adding-a-device-model.md`](docs/adding-a-device-model.md).

---

## Template organisation

Jinja2 templates live in `netcanon/templates/`.  The base layout is
`base.html`; each page is an extending template.

**Large page templates split into partials.**  `migrate.html` and
`base.html` both use the `{% include "_partials/<name>.js" %}` pattern
to factor long `<script>` blocks out into reusable partial files:

```
netcanon/templates/
├── migrate.html              # outer HTML + script — the largest
│                             # page template, hosts the Tier-3
│                             # rename modal that depends on the
│                             # partials below
├── base.html                 # outer chrome + global JS
└── _partials/                # see the directory for the current set;
                              # included via Jinja `{% include %}`
```

Current partials (at time of writing — contents of `_partials/` is
the source of truth):

* **classify.js** — shared `_guessKind` / `_looksLikeUplink`
  client-side port classifiers, used by both rename-table.js and
  fit-check.js.
* **config-viewer.js** — modal viewer with syntax highlighting +
  search, mounted globally from base.html.
* **fit-check.js** — hardware-capacity banner on the rename modal
  (access/uplink/mgmt per-kind overage indicators).
  — and the target-profile provenance notice (`renderProfileNotice`).
* **job-progress.js** — floating job-status widget, mounted
  globally from base.html; survives page navigation via
  localStorage.
* **kbd-cheatsheet.js** — global keyboard-shortcut modal mounted
  from base.html; opens on `?` keypress (or via the nav button).
  Lists the application-wide shortcuts in a single overlay; no
  per-page wiring needed.
* **device-models.js** — rename-modal source-device and
  target-device pickers (model family or profile, mode, modules,
  stack members), source detection, the per-device notes, and the
  port-plan strip and row data.
* **rename-apply.js** — rename-modal Apply-button flow + drag
  handlers + vendor/model/module selector wiring.
* **rename-panel.js** — rename-modal preview + summary renderer.
* **rename-table.js** — rename-modal per-kind expandable sections
  with per-row override dropdowns, collision detection, drop links.
* **vlan-rename-table.js** — rename-modal VLAN-category pane
  renderer; structurally parallels rename-table.js but simpler
  (integer IDs, no per-kind sections, no target-profile dropdown).
* **local-user-rename-table.js** — rename-modal local-users
  category pane renderer (P2C4); third per-pane category after
  ports + VLANs.  Free-text rewrite, collision warning is
  informational (server merges on max privilege + first-wins role).
* **snmp-rename-table.js** — rename-modal SNMP-community pane
  renderer (P2C5); fourth per-pane category.  Scalar canonical
  surface (one community string) so the pane renders a single-row
  table for visual parity with the list-oriented panes.
  "Clear" replaces "drop" semantically — clearing the community
  causes the render path to omit the entire SNMP block.
* **snmpv3-user-rename-table.js** — rename-modal SNMPv3 USM user
  pane renderer (P2C6); fifth per-pane category.  List-oriented
  sibling of the local-users pane — one row per source USM user.
  Rename is identity-only: auth / priv / group / engine_id
  follow the renamed record.  Collisions merge on first-wins
  (auth/priv keys are NEVER combined across users).
* **theme-toggle.js** — global light/dark mode toggle wired to
  the `nav-theme-toggle` button.  Calls `NcTheme.set(null, mode)`
  (from the vendored `_vendor/theme-picker.js`), which flips
  `<html data-nc-mode>` between `light`/`dark` and persists to
  `localStorage["nc-mode"]`; also mirrors the value one-way into
  the legacy `localStorage["netcanon.theme.v1"]` key so the
  self-contained `/docs` theme copy follows.  Updates `aria-label`
  + `aria-pressed` to reflect the next-action.  The vendored
  theme-picker include in `base.html`'s `<head>` (NOT this
  partial) applies the persisted theme synchronously before CSS
  parses — required for FOUC prevention.

**Why include-splice rather than ES-modules?** The templates embed
inline `<script>` blocks that share lexical scope with the rest of the
page's client JS (state vars like `_lastJob`, `_renameUserMap`, and
cross-function references).  Jinja `{% include %}` splices the partial
verbatim into that scope at render time — no module boundary to cross,
no export/import plumbing, no build step.  Downside: the partials
aren't unit-testable in isolation; e2e tests via `data-testid`
selectors are the safety net.

**Selector discipline** (AGENTS.md hard rule): every interactive
element in every template — including content generated inside
partials — carries a `data-testid` attribute.  The full inventory
lives in [`tests/testid_reference.md`](tests/testid_reference.md).

**Theming (unified design language).**  The app's palette + mode
ship from the vendored netcanon-dev/ui-design-spec deliverable
(pinned tag + checksums in `netcanon/templates/_vendor/README.md`).
Three layers, all Jinja-inlined by `base.html`:

1. `_vendor/netcanon-ui.css` — the unified `--nc-*` tokens: ten
   palettes selected by `<html data-nc-theme>` (netcanon defaults
   to `indigo`), light/dark forced by `<html data-nc-mode>`, and
   an absent `data-nc-mode` = follow the OS via
   `prefers-color-scheme`.
2. `_vendor/compat-netcanon.css` — the compat shim: remaps the
   legacy `--page-bg`/`--surface`/… var names onto `--nc-*` under
   `:root[data-nc-theme]`, which outranks the legacy `:root` and
   `[data-theme="dark"]` blocks still present (inert) in
   `base.html`.  Every themed declaration keeps using
   `var(--token)` — never raw hex — and re-themes through the
   shim without a rewrite.
3. `_vendor/theme-picker.js` — the `NcTheme` runtime.  Its boot
   applies persisted `localStorage["nc-theme"]`/`["nc-mode"]`
   prefs to `<html>` synchronously in `<head>` before CSS parses
   (FOUC prevention — do NOT move it to an external
   `<script src=>`; it must block).  A tiny inline snippet just
   before it migrates a pre-unification
   `localStorage["netcanon.theme.v1"]` value into `nc-mode` once.

Rules that keep the pattern robust:

1. **Never edit `_vendor/` files by hand** — they are byte-pinned
   to a spec-repo tag by sha256 (`_vendor/README.md`); re-vendor
   at a newer tag to change them.
2. **New CSS uses `var(--token)`** — legacy names still resolve
   through the shim; new code may reference `--nc-*` directly.
3. **Theme-aware toast/alert colour pairs via CSS class, never
   inline style.**  `showToast()` assigns a CSS class
   (`.toast-info` / `.toast-error` / `.toast-success`) instead
   of writing `element.style.background = '#...'` — the class
   resolves to `var(--badge-*-bg)` / `var(--badge-*-fg)` so
   dark mode inherits the semantic pair automatically.
4. **The `<pre>` code wells stay fixed-dark in both modes** — the
   `tok-*` syntax-highlight palette is hardcoded for a dark well;
   var-izing it is a follow-up (see the shim's header comment).

The global toggle is a single icon button
(`data-testid="nav-theme-toggle"`) right-aligned on the nav; sun
glyph in dark mode, moon glyph in light mode, swap via CSS keyed
on `data-nc-mode` (plus a `prefers-color-scheme` fallback pair
for the no-attribute "auto" state) so JS never mutates the button
content.  See `_partials/theme-toggle.js` for the toggle function
+ `aria-label` updater.

---

## Test architecture

Four layers, each with specific isolation guarantees:

| Layer | Path | Mocking | Runtime |
|---|---|---|---|
| Unit | `tests/unit/` | None — pure functions | <1s per file |
| Integration | `tests/integration/` | `get_collector` patched in TestClient fixture | <1s per file |
| E2E | `tests/e2e/` | `get_collector` patched for session's live Uvicorn | ~30s full sweep |
| Desktop | `tests/desktop/` | PySide6 + pystray fully mocked via sys.modules | <1s per file |

**Real-capture validation** lives at `tests/unit/migration/test_real_captures.py`.
It auto-discovers fixtures under `tests/fixtures/real/<vendor>/`,
runs parse + round-trip + determinism assertions, and prints
per-fixture coverage metrics.  The harness is what gated codec
promotion to `certified` during the real-capture-pass sessions —
all shipped codecs except the NETCONF/OpenConfig stub have promoted
to `certified` (see `tests/fixtures/real/RESULTS.md` for the per-vendor
matrix and cert decisions).  The harness now drives *hardening* rather than
promotion: new fixtures surface latent bugs and cover grammar
surfaces the current corpus doesn't touch.

Mocking single entry point: **SSH collection is mocked at
`netcanon.api.routes.backups.get_collector`, never at `ConnectHandler`
or `paramiko.SSHClient` directly** (see AGENTS.md hard rule).

### Cross-mesh fidelity audit harness

Beyond the test layers above, a separate audit harness lives at
[`tools/run_full_mesh.py`](tools/run_full_mesh.py) (Phase 1: mechanical drift) +
[`tools/run_phase4_reconciliation.py`](tools/run_phase4_reconciliation.py) (Phase 4: classify drift
against per-pair Phase-3 expectation YAMLs in
`tests/fixtures/cross_vendor_expectations/`).  Output committed as
`tests/fixtures/real/CROSS_MESH_RESULTS.md` and
`tests/fixtures/real/PHASE4_RECONCILIATION.md`.
See [`tools/README.md`](tools/README.md) for full usage notes and cell-status legend.

Phase 4 classifies every `(source_codec, target_codec, fixture,
field)` cell into one of eight variance classes:

* **ALIGNED** — drift matches expectation; no action.
* **CODEC_BUG** — drifted where YAML says `disposition: good`.
  This is the high-severity signal — real cross-vendor drift the
  codec author should fix.
* **EXPECTED_LOSSY** — drifted, YAML says `disposition: lossy`
  (acknowledged loss).
* **EXPECTED_UNSUPPORTED** — drifted, YAML says
  `disposition: unsupported` (target vendor has no equivalent).
* **METHODOLOGY_ISSUE_under** — YAML says `lossy`/`unsupported` but
  the cell actually aligns (over-claiming loss).
* **METHODOLOGY_ISSUE_over** — YAML says `good` but cell is
  `not_applicable` (over-claiming applicability).
* **STRUCTURAL_ONLY** — list-row count drift (e.g. 17 source
  interfaces → 2 target interfaces) collapsed to a single signal
  per cell-parent rather than amplified across N per-field keys.
  Added to prevent a single `count drift: 17 → 2 (interfaces)`
  signal from inflating CODEC_BUG by 6× across `interfaces[].mtu`,
  `interfaces[].description`, etc.  Per-record drift on surviving
  rows still fires CODEC_BUG normally.
* **TRIVIAL_EMPTY** — both sides empty/zero on this field; the
  cell trivially aligns by absence of data.  Surfaces cases where
  the test fixture doesn't exercise the field (e.g.
  `evpn_type5_routes` on a fixture with no EVPN data,
  `apply_groups` on non-Junos source fixtures, `timezone` /
  `ntp_servers` when the source declares neither).  Distinct from
  ALIGNED (which means real preservation of populated data) and
  from METHODOLOGY_ISSUE_under (which now means real preservation
  where YAML claimed lossy — actionable over-claim signal).
  Added Wave 10α to peel ~4169-of-7382 noise cells out of the
  methodology-issue bucket so the remaining signal is actionable.
  Wave 10γ extended the classification to list-sub-fields: when a
  parent list HAS rows on both sides but a particular sub-field is
  empty on every record (e.g. `interfaces` populated but every
  row's `switchport_mode` / `voice_vlan` / `vrf` is None), the
  sub-field also routes here rather than masquerading as
  METHODOLOGY_under.  Phase 1 records the union of sub-fields with
  data per parent list (`subfields_with_data`) so the cascade can
  distinguish the trivial case from real preservation.  Severity
  `ok`.  Phase 1's `compute_field_disposition` flags the upstream
  `trivially_preserved` boolean for parent lists; the reconciler
  routes both parent and sub-field cases here regardless of the
  YAML's expectation.

**Vendor-correct rename equivalences.** Some canonical-field values
legitimately differ in spelling across vendors without representing
drift — Junos `ae<N>`, Cisco `Port-channel<N>` (and the `Po<N>`
abbreviation), and Aruba `trk<N>` are the same LAG bundle expressed
in vendor-native names.  The reconciler accepts an `equivalence`
callable on `_subfield_drift_in_list` / `_slice_list_subfield`;
today it plugs in `_lag_name_equivalence` for the field-keys in
`_LAG_NAME_FIELDS = {"lags[].name", "interfaces[].lag_member_of"}`.
Names not matching a documented LAG shape (loopback / VLAN /
physical-port / free-form interface names) fall through to raw
equality, so non-LAG drift on the same fields still surfaces
normally.  Added in commit `faf925f` (Wave 9β); the variance-class
set was 7 at that time — TRIVIAL_EMPTY landed later in Wave 10α
(commit `35c7bf0`).  The LAG equivalence callable just shifts where
individual cells land between ALIGNED and CODEC_BUG; it doesn't add
or remove a class.

Per-source-vendor investigation reports under
`tests/fixtures/real/phase4_findings_<vendor>.md` carry per-cell
triage: real bug (codec fix), stale expectation (YAML refresh), or
acceptable lossy (reclassify).  This audit is what gates
"is-the-cross-vendor-translation-honest?" — failing CODEC_BUG cells
become backlog items for codec waves; failing METHODOLOGY cells
flag expectation drift.

---

## Evolution roadmap

For the active backlog see [`translator-plans.txt`](translator-plans.txt)
(dense, grep-friendly, opens with a TL;DR).  Big structural pieces
that have shipped:

- **Phase 0** — codec scaffold + mock adapter (`run_plan`, capability matrix)
- **Phase 0.5** — canonical intent model + pluggable CIMs
- **Phase 1** — real codecs across the major switching/firewall
  vendors, all bidirectional: Cisco IOS-XE CLI (originally
  Cisco-as-source, since certified `direction = bidirectional`),
  Cisco IOS-XE NETCONF stub, Aruba AOS-S, OPNsense, MikroTik
  RouterOS, FortiGate CLI, Arista EOS, and Juniper Junos.  See
  `netcanon/migration/codecs/` for the live registry.
- **Phase 1.5 (v0.1.5–v0.1.8)** — four more bidirectional,
  round-trip-certified codecs: Cisco NX-OS, Cisco IOS-XR, Aruba
  AOS-CX, and VyOS — bringing the live registry to 12 codecs.
- **R5** — auto-detection probe
- **R6/7** — real-capture validation harness + fixture corpus
- **Tier 2 wire-throughs** — SNMP + SNMPv3, LAGs, local_users, DHCP pools,
  RADIUS, MTU, IPv6 addresses, VRFs, VXLAN/EVPN
- **v0.1.1 (v0.2.0 Wave A+B+C)** — `CanonicalVRRPGroup` canonical
  primitive shipped as a ship-before-wire schema (every codec declares
  the new xpaths as `unsupported` first), then Waves B + C wired the
  VRRP / HSRP / CARP grammar across all 7 bidirectional codecs.
  Anycast-gateway wired on 3 codecs (Junos `virtual-gateway-address`,
  Arista EOS VARP, Cisco IOS-XE SD-Access).  See
  [`docs/v0.2.0-planning/01-vrrp-canonical/IMPLEMENTED.md`](docs/v0.2.0-planning/01-vrrp-canonical/IMPLEMENTED.md)
  + [`docs/v0.2.0-planning/02-anycast-gateway/IMPLEMENTED.md`](docs/v0.2.0-planning/02-anycast-gateway/IMPLEMENTED.md).
- **v0.1.2 — Security-hardening release** — defusedxml swap on the
  two operator-XML parse sites (OPNsense + Cisco IOS-XE NETCONF);
  workflow-level supply-chain hardening (zizmor + Trivy + SHA-pinned
  third-party actions + workflow permissions + Dependabot cooldowns).
  Translation behaviour unchanged.  See [`SECURITY.md`](SECURITY.md)
  § "Supply-Chain Integrity" → "v0.1.2 supply-chain hardening".
- **2026-05 — fixture-research catalogue** — 14-OS fixture-source
  catalogue + overlay-priority synthesis for v0.2.0+ overlay
  authoring backlog.  See
  [`docs/fixture-research-2015/`](docs/fixture-research-2015/).

What's queued:
- Opportunistic grammar-diversity fixtures (FortiGate multi-VDOM,
  FortiOS 7.4, RouterOS 7.19+, OPNsense 25.x, AOS-S 16.11 late
  patches — all hardening, no longer cert-promotion — see
  `tests/fixtures/real/RESULTS.md`)
- Fidelity polish bucket (VRFs, STP globals, PKI chains → Tier 3)
- Deploy phase (transport layer wiring for migration output push)
- Additional canonical models (firewall-specific, wireless-specific CIMs)
- Per-pane overrides for **NTP servers**, **DNS servers**,
  **syslog servers**, **SNMP trap-hosts**, and **RADIUS** — all
  list-oriented cross-vendor-stable management-plane surfaces with
  per-codec parse+render already in place **on the codecs that wire
  them** (e.g. syslog on 5 of 12; RADIUS and trap-hosts are declared
  unsupported on some, such as vyos RADIUS and aoscx trap-hosts).
  Following the same
  three-step recipe (orchestrator → pipeline → pane) as ports /
  VLANs / local_users / SNMP-community / SNMPv3-users.  See
  [`translator-plans.txt`](translator-plans.txt) for viability
  audit + ordering decisions.

---

## See also

- [`netcanon/definitions/library/README.md`](netcanon/definitions/library/README.md) — device-definition + target-profile YAML schema
- [`netcanon/migration/codecs/README.md`](netcanon/migration/codecs/README.md) — codec authorship guide
- [`netcanon/migration/canonical/README.md`](netcanon/migration/canonical/README.md) — canonical intent model and Tier 1 / 2 / 3 promotion rules
- [`netcanon/api/routes/README.md`](netcanon/api/routes/README.md) — HTTP route inventory and frozen pipeline-stage signatures
- [`docs/glossary.md`](docs/glossary.md) — project-jargon reference
- [`docs/adding-a-canonical-field.md`](docs/adding-a-canonical-field.md) — worked example: MTU wire-through across every codec
- [`docs/adding-a-target-profile.md`](docs/adding-a-target-profile.md) — worked example: shipping a hardware-shape YAML for the rename UI fit-checks
- [`docs/adding-a-device-model.md`](docs/adding-a-device-model.md) — model families, deployment modes and port inventories for model-to-model port mapping
- [`docs/feature-parity-walkthrough.md`](docs/feature-parity-walkthrough.md) — worked example: SNMPv3 USM landing across canonical + codec + pipeline + UI + tests + docs
- [`translator-plans.txt`](translator-plans.txt) — active roadmap and backlog
- [`tests/fixtures/real/RESULTS.md`](tests/fixtures/real/RESULTS.md) — per-codec certification state
- [`docs/security-triage/`](docs/security-triage/) — read-only-Stage-1-agents + orchestrator-applied-dismissals process for Code Scanning / Dependabot alert waves
- [`docs/docs-audit/`](docs/docs-audit/) — sister process applied to documentation hygiene; recurring cycle that catches drift between docs and code (Evolution roadmap above was last refreshed by the 2026-05-21 audit cycle)
