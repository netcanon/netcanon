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
| a group's **`prefix`** | the interface type a grammar that names by type puts in front of the number (`TenGigabitEthernet`) |
| a group's **`multi_lane`** | the ports are a grammar's multi-lane ports, each configured as one interface and named by its first lane (`Ethernet49/1`) |
| a group's **`skip`** | port numbers the device does not have, in the state the mode describes, passed over before the group (a Dell S4148F-ON's default port profile turns ports 27 and 28 off) |
| a **deployment port** | a port of the whole deployment rather than of one member, by its literal name (a C9300 stack's one `GigabitEthernet0/0`) |
| a **capture claim** | a committed real capture, and the exact deployment it is of |

and in code, beside the vendor's codec, there is one small **naming
rule** per naming grammar — not per product line.  Every AOS-S
fixed-port switch is the single `aoss` rule
(`physical_port_name` in
[`codecs/aruba_aoss/port_names.py`](../netcanon/migration/codecs/aruba_aoss/port_names.py)),
every Catalyst stackable the `catalyst` rule (`catalyst_port_name`
in
[`codecs/cisco_iosxe_cli/port_names.py`](../netcanon/migration/codecs/cisco_iosxe_cli/port_names.py)),
every CX 6200 and 6300 the `aoscx` rule (`vsf_switch_port_name` in
[`codecs/aruba_aoscx/port_names.py`](../netcanon/migration/codecs/aruba_aoscx/port_names.py)),
every Arista fixed switch the `eos` rule (`fixed_switch_port_name`
in
[`codecs/arista_eos/port_names.py`](../netcanon/migration/codecs/arista_eos/port_names.py)),
every Cisco Nexus 9300 the `nxos` rule (`nexus_port_name` in
[`codecs/cisco_nxos/port_names.py`](../netcanon/migration/codecs/cisco_nxos/port_names.py)),
every Juniper EX and QFX switch the `junos` rule
(`ex_qfx_port_name` in
[`codecs/juniper_junos/port_names.py`](../netcanon/migration/codecs/juniper_junos/port_names.py)),
every Dell PowerSwitch on SmartFabric OS10 the `os10` rule
(`os10_port_name` in
[`codecs/dell_os10/port_names.py`](../netcanon/migration/codecs/dell_os10/port_names.py)),
every fixed Cisco router on IOS XR the `iosxr` rule
(`iosxr_port_name` in
[`codecs/cisco_iosxr/port_names.py`](../netcanon/migration/codecs/cisco_iosxr/port_names.py)),
and every MikroTik CRS switch and CCR router on RouterOS the
`routeros` rule (`routeros_port_name` in
[`codecs/mikrotik_routeros/port_names.py`](../netcanon/migration/codecs/mikrotik_routeros/port_names.py)).

A Catalyst names a port by its type, then switch, module and port
(`TwoGigabitEthernet1/0/36`), and the type is the port's top speed, so
a panel of two speeds is two types numbered straight through.  The
type is **stated** on each port group as `prefix:`, from the vendor's
own interface lists, and never derived from a speed: a rule cannot
know that a 25G module's ports are `TwentyFiveGigE` while a 10G
panel's are `TenGigabitEthernet`.  A rule that puts no type in a name
refuses a `prefix`.  Where the type is the optic's and not the port's
-- a Catalyst 3750-X's C3KX-NM-10G names a slot `GigabitEthernet1/1/2`
with a 1G SFP in it and `TenGigabitEthernet1/1/1` with an SFP+ --
describe the module in ONE state and say which in its `caveat`, which
the inventory carries: a port's name is a function of its state, and
two states are not one module.

An Arista fixed switch names a single-lane port by its number
(`Ethernet3`) and a multi-lane port -- a QSFP+, QSFP100, OSFP or
QSFP-DD cage -- by port and lane (`Ethernet49/1`).  Which ports are
named by lane is **stated** on the group as `multi_lane: true`, from
the vendor's port list, and never derived from a cage: a 7050QX-32's
ports 25-32 are QSFP+ cages that run at 40G only, and two public
running-configs print them with no lane.  A family describes each
multi-lane port configured as ONE interface, named by its first lane,
and its mode's label says so; a port broken out into lanes is not
modelled.  A rule that puts no lane in a name refuses `multi_lane`.
An EOS switch numbers its ports in one run, so on some models the
uplinks come before the access ports, or between two runs of them (a
7050SX3-96YC8's two SFP+ ports are 105 and 106); the groups still go
in port-number order.

A Cisco Nexus 9300 names a port by module and port
(`Ethernet1/49`).  A switch's own panel is module 1, and a
first-generation switch's uplink module is the module of its bay, so
the bay is named by that number (`"2"`) and the rule refuses a bay
named otherwise.  What a module contributes can depend on the switch
it is fitted in -- an N9K-M12PQ has twelve active ports in a 9396PX
and eight in a 93128TX -- and a module is described once per family,
so such a switch is a family of its own.

A Juniper EX or QFX switch names a port `type-fpc/pic/port`
(`xe-0/2/3`).  The FPC is the Virtual Chassis member id, 0 on a
switch that has never been in one, so a Junos mode always states
`member_ids`.  The panel's own ports are PIC 0 and state no slot; a
bank of the panel that is a PIC of its own (an EX2300's uplinks are
PIC 1) and a module bay are named by their PIC (`"1"` or `"2"`),
and the rule refuses any other slot.  Ports count from 0 within a
PIC, by the number the CLI shows, not the faceplate label (an
EX4300-32F's SFP+ ports are labelled 0 to 3 and are `xe-0/0/32` to
`xe-0/0/35`).  The prefix is the optic's speed, not the cage's, so
every group states its `prefix` and the mode says which optics its
names are for.  A port the switch holds as a Virtual Chassis port by
default is no interface, and is left out.  A Virtual Chassis is of
the models one family describes, so models that cannot share one
(each QFX5120) are families of their own.

A Dell PowerSwitch on SmartFabric OS10 names a port
`ethernet1/1/<port>`: node 1, slot 1 and the port's number (Dell's
user guide gives an Ethernet interface as `ethernet
node/slot/port[:subport]`, with 1/1 for a switch on its own).  OS10
has no stacking -- each switch of a VLT pair is a device of its own --
so the rule refuses a member id and any slot, and an OS10 mode states
no `member_ids`.  The management port, `mgmt1/1/1`, is a deployment
port.  A port broken out is named by lane (`ethernet1/1/25:1`), which
is not modelled: a family describes every port whole, and its mode's
label says so.  Which ports exist can depend on a setting: an S4148's
switch-port profile adds or removes ports by number and never
renumbers one, and its default turns the QSFP+ ports 27 and 28 off.
So a family describes one profile, in the mode's label, and the group
after such a gap states how many numbers it passes over (`skip: 2`
before ports 29 and 30).  `skip` is for a number the device does not
have in that state, stated from the vendor's own port list; a port
the device has and nobody uses is a port, and is counted.

A fixed Cisco router on IOS XR names a port
`<Type>0/0/<module>/<port>`: rack 0, slot 0, the module and the
port's number, counting from 0 (Cisco's guides give the
interface-path-id as rack/slot/module/port).  A fixed router stands
alone, so the rule refuses a member id, and an IOS XR mode states no
`member_ids`.  Module 0 is the panel's own run of ports, which
states no `slot`; a group on another module states its number
(`slot: "1"` for an N540-24Z8Q2C-SYS's `HundredGigE0/0/1/0` and
`HundredGigE0/0/1/1`), and `slot: "0"` is refused.  The type names
the speed a port runs at, and that follows the optic fitted: an
SFP+ port is `TenGigE` with a 10G optic and `GigabitEthernet` with a
1G one.  So, as on a Catalyst, a family names each port by the type
of its top speed, and its mode's label says so; a port that holds a
slower optic, and a lane of a port broken out
(`<Type>0/0/0/<port>/<lane>`), come back as off-inventory.  The
management port, `MgmtEth0/RP0/CPU0/0`, is a deployment port.  A
port is an `uplink` when it is of the router's fastest class of
cage: its QSFP-class ports where it has any, otherwise the ports of
its top speed.

A MikroTik switch or router on RouterOS names a port by its type
and a number (`ether1`, `sfp-sfpplus16`, `sfp28-2`), with no member
and no slot, as MikroTik's table of each model's interfaces ("MTU
in RouterOS") prints them.  So the rule refuses a member id and any
slot, and a RouterOS mode states no `member_ids`.  Each type counts
from 1 on its own -- a CRS354-48G-4S+2Q+ has `ether1` to `ether49`,
`sfp-sfpplus1` to `sfp-sfpplus4`, `qsfpplus1-1` and `qsfpplus2-1` --
so the rule numbers the ports of each type apart (`counts_by_type`),
and a `skip` passes over numbers of the group's own type.  A QSFP
port is named by its first lane (`qsfp28-1-1`), so its group states
`multi_lane`, and a family describes it as one link; its other
lanes are not modelled.  The name is the port's factory name, which
RouterOS keeps in `default-name` when the operator gives the port a
name of its own.  Some models set one Ethernet port apart for
management, and which one is the model's (`ether1` on a
CRS309-1G-8S+, `ether49` on a CRS354): such a port is a group of the
model's panel in the role `mgmt`, not a deployment port.  It is
compiled as a port of the whole deployment all the same (no member
rank), so that it pairs with the other side's management port, and
that is right only for a deployment of one device: the loader
refuses it in a mode that numbers its members, and in a family that
also states a management port under `deployment_ports`.  A port is
an `uplink` when it is of the model's QSFP-class cages, or, on a
model with none, of its fastest ports; a management port is
neither.

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
sibling's `skus:`.  A port of the whole deployment
(`deployment_ports:`) is graded `capture` only where the claim is the
whole deployment, every member of it: a capture of one switch does
not show the management port of a stack it is a member of.

Every claim is re-proven on every test run: the fixture must contain
the marker, the marker must carry a part number of the claimed model,
the fixture must belong to the family's vendor, and the hardware ports
it names must **equal** the compiled inventory.  A capture that names
only some of the device's ports cannot be claimed — the claim would
grant the grade to ports it never shows.  A sub-interface the capture
configures (`Ethernet1.2`) counts as the port it rides on.  In a mode
whose names carry a member id, every member of the claim states the
`id` the capture shows.

`capture` means exactly that re-proof, so a claim grants the grade
only when it is one the test re-proves: it is listed in
`PROVEN_CAPTURE_CLAIMS` in `device_models.py` — the whole claim:
family, fixture, mode, and each member's model, id and modules — and
the test requires that list to equal the claims it checks.  A claim
in an operator's own family file is read, logged and grants nothing.

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
   (`*name`) are not allowed in a family file.
3. **Pin the inventory by hand** in
   [`tests/unit/migration/test_device_models_shipped.py`](../tests/unit/migration/test_device_models_shipped.py):
   the access names and the uplink names, in order, for every mode and
   every module choice.  Type them from your sources.  A capture can
   only prove names — it cannot prove which ports are uplinks, since
   many grammars carry no role in the name — so this table is the only
   thing that catches two port groups written in the wrong order.  The
   test fails if any shipped combination is not pinned.  A family's
   deployment ports are pinned in `EXPECTED_DEPLOYMENT_PORTS`, by
   family.  In the same file add each `(vendor, part number)` to
   `EXPECTED_PART_NUMBERS` (which part number is which model is data
   there, not a comment), and a part you graded `inferred` to
   `KNOWN_INFERRED_PARTS`.
4. **Add the capture claim**, if a committed capture of that exact
   model exists and names every port of it: in the family file, in
   `EXPECTED_CLAIMS` in the same test file (fixture, marker, mode and
   each member), and in `PROVEN_CAPTURE_CLAIMS` in `device_models.py`.
   A new fixture needs its rows in
   [`tests/fixtures/real/NOTICE.md`](../tests/fixtures/real/NOTICE.md)
   and `RESULTS.md` there, as for any real capture.
5. **If a flat target profile describes the same device**, add the pair
   to `PROFILE_AGREES_WITH` (addressed by part number, never by key —
   legacy keys are not consistent with each other), with the module
   the profile preselects.  The test finds such profiles by the part
   number in their display name, or by a profile model that is a part
   number a family models, and fails until the pair is listed.  The
   two must list the same ports with the same roles, in the same order
   within each role; a profile's management port may sit among its
   chassis ports, and a family's comes after every member's.  Where
   both exist the family is authoritative for port mapping.
6. **Run** `pytest tests/unit/migration/test_device_models.py
   tests/unit/migration/test_device_models_shipped.py`.

### Reading the device from its config

Where a vendor's `show running-config` states its own hardware, a
**detector** lets an operator confirm the source device instead of
typing it.  It is a pure function over the config text, beside the
vendor's codec (`deployment_detect.py`), registered in `_detectors()` in
[`netcanon/migration/deployment_detect.py`](../netcanon/migration/deployment_detect.py).
The rules:

* **Read what the config states; infer nothing.**  A detector returns
  the part numbers, member ids and modules the config states.  It has
  no table of models — resolving a part number is the registry's job —
  and it must not guess a model from the shape or number of the port
  names.
* **Say what the lines do not prove**, in the detection's notes.  A
  member or module line is provisioning; the device may differ.
* **Say what was left out and what was chosen.**  A line that set out
  to state a member or a module and could not be read, a member stated
  two ways: a note each, so that a stack does not come back a member
  or a module short with nothing to show for it.  A note names a few
  member numbers and counts the rest; the proposer cuts a long note
  and keeps the first few, whatever a detector does.
* **When no device is read, the first note is the reason.**  A
  proposal with no deployment shows its first note as why; the remarks
  about what else was or was not read come after it.
* **Keep device identifiers out of the evidence lines.**  They are
  shown to an operator and may be logged; a MAC address or a serial
  number says nothing about what the device is.  End each pattern at
  the part number rather than scrubbing what a wider one matched.
* **The text is not vouched for.**  The route hands a detector whatever
  was pasted.  Anchor every pattern to a line, bound what it takes (a
  member number, a part), and apply none to a fragment another pattern
  matched unless that fragment is itself bounded: a pattern that
  backtracks over a run of spaces holds the server.  A detector must
  not raise on any text; one that does is answered as "could not be
  read".
* **Read the lines the parser reads.**  Cut the text into lines where
  the parser cuts it, and empty a banner's text with the parser's own
  helper (`without_banner_bodies`), so that a banner's words are not
  hardware.
* **A vendor id can be more than one codec.**  The detector is chosen
  by the codec's vendor id, so it is handed the text of every codec
  that shares it: the Catalyst detector gets IOS-XE CLI text and the
  NETCONF codec's XML.  A form it does not read is said in a note, not
  answered as a config that states no device.

Test it on every stanza form the vendor's documents and real captures
show, and on the committed captures.  Name the vendor's codec in
`_CODEC_OF` in `tests/unit/migration/test_deployment_detect.py`, and
its configs' word for a stack (the detection's `fabric`) in
`_STANZA_WORDS`: the guards that walk every detector then run for it
by themselves.  The
detector must propose, for every capture a capture claim of that vendor
cites, the deployment the claim states; it is handed text made to be
slow; and a vendor whose ports keep a factory name
(`ports_keep_a_factory_name`) fails until it has tables of its own in
`TestTheCheckIsTheOneATranslationMakes`, as RouterOS has: configs
whose renamed ports a translation pairs, and configs whose names it
pairs no port for, each held to the plan a translation makes.
Those slow texts state no device, so they stop at the detector's first
patterns: write the vendor's own (as `TestTheAossDetectorOnTextMadeToBeSlow`,
`TestTheCatalystDetectorOnTextMadeToBeSlow`,
`TestTheAoscxDetectorOnTextMadeToBeSlow`,
`TestTheAristaDetectorOnTextMadeToBeSlow` and
`TestTheRouterOSDetectorOnTextMadeToBeSlow` do) with a device stated
and a tail made for each pattern.

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

A rule that names a port by its interface type also states the types
it accepts (`prefixes`); every group of a family under that rule must
state one of them, and a group under any other rule must state none.
A rule whose names carry a lane says so (`lanes`); a group may state
`multi_lane` only under such a rule.  A rule whose types each count
from 1 says so (`counts_by_type`): a port's position is then counted
among the ports of its own type in its slot.
Ports that no rule names — a stack's one management interface — go
under `deployment_ports:` by their literal names: each belongs to no
member and comes after every member's ports.  A management port that
is one model's own, under a rule that can name it, is a `mgmt` group
of that model's panel instead (RouterOS, above).

Test the rule against the vendor's own printed examples, including one
whose member number is not 1, and name the codec whose grammar it
writes in `_CODEC_OF_RULE` in the shipped-data test, which classifies
every compiled name back through that codec.

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
  the naming rule refuses; a port named twice, a deployment port
  included;
* a group with no `prefix` under a rule that names a port by its type,
  a `prefix` that rule does not take, or a `prefix` under a rule that
  puts no type in a name;
* `multi_lane` on a group under a rule that puts no lane in a name;
* a negative `skip`;
* a mode that states `member_ids` under a rule whose names carry no
  member number (`os10`, `iosxr`, `routeros`);
* a group `slot` of `"0"` under `iosxr`: module 0 is the panel's own
  run of ports, and states none;
* a group `slot` under `routeros`, which names no slot;
* a `mgmt` group in a module; a `mgmt` group on a model's panel
  where a mode that model takes states `member_ids`, or where the
  family states a management port under `deployment_ports` too;
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
lanes, ports a stack consumes as links, literal non-systematic names
on one model's own panel (a FortiGate's `wan1`, `dmz`), and the names
a Catalyst lists for the network modules that are NOT fitted (its
config holds an interface for every port of every module the bay can
take; the inventory has the fitted module's, so a job that uses the
others asks what to do with each).  The schema has room for each as
an additive field; none has data or a consumer today.  A device of one of those kinds can still be declared
through its flat target profile, as one device in the one state that
profile documents.
