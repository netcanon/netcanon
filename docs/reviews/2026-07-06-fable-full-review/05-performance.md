# Lens 05 — Performance & resource bounds

Summary: Found **4 confirmed super-linear (O(n²)) hot paths** reachable from parse / diff, none of which
were in the prior review's PERF-1..5 list (those covered the aoss port-range OOM [now fixed], the
`transforms._add_unique` VLAN projection, opnsense parent rescan, classify, and report bloat). The
strongest is a shared trunk-VLAN helper whose `add` branch does list-membership over the accumulating
VLAN set: **an 8.6 KB config drives a 6.9 s parse**, and it is shared by three shipped codecs
(arista_eos / cisco_nxos / cisco_iosxe_cli). All caps that *do* exist (VLAN-id 1..4094, aoss port-range
1024, profile-range 4096, junos block-depth 100, sanitize 16 MB, raw_text 10 MB, XXE via defusedxml,
`sanitize` offloaded via `asyncio.to_thread`, sync routes → threadpool) hold up. The findings below are
amplification (small input → large CPU), not raw-size, so the 10 MB `raw_text` cap does not bound them.

---

### F1 (MAJOR, confirmed) — `merge_trunk_allowed` `add` branch is O(|ids|·|base|); 8.6 KB → 6.9 s across 3 codecs

**file:** `netcanon/migration/codecs/_helpers.py:199` (helper); call sites
`arista_eos/parse.py:1210`, `cisco_nxos/parse.py:805`, `cisco_iosxe_cli/parse.py:883`

The `add` branch tests membership against a **list**:
```python
base = list(existing)
if keyword == "add":
    return base + [vid for vid in ids if vid not in base]   # <-- `not in base` is a linear scan
```
`existing` is the interface's accumulating `trunk_allowed` list (grows to the full 4094-VLAN space).
For each `switchport trunk allowed vlan add <list>` line, this is O(|ids| × |base|). With `add 1-4094`
that is 4094 × ~2047 ≈ 8.4e6 int-comparisons **per line**, repeated once per add-line. `remove`/`except`
already use a `set`; only `add` regressed.

**Failure scenario (reproduced):** `POST /api/v1/migration/plan` with `source=arista_eos` (or
`cisco_nxos` / `cisco_iosxe_cli`) and a body of one interface stanza followed by K identical
`switchport trunk allowed vlan add 1-4094` lines:
- K=200 → **8.6 KB → 6.83 s** (cisco_nxos), 6.92 s (arista)
- K=400 → 17 KB → 13.8 s
- K=800 → 35 KB → 27.8 s (linear in K, ~790 ms per KB)
- isolated helper micro-bench: 200 `add` calls with base=4094 = **6.92 s**

A ~250 KB config (utterly normal size, well under any cap) hangs a threadpool worker for ~3 minutes;
1 MB → ~15 minutes. Reachable unauthenticated in the default local bind (auth is opt-in); on a keyed
multi-user deployment any authenticated user or the shared UI can exhaust the worker pool.

**Fix:** hoist a membership set:
```python
if keyword == "add":
    seen = set(base)
    return base + [vid for vid in ids if vid not in seen]
```
O(|ids| + |base|) per line — drops the 6.9 s repro to milliseconds. No behavior change (order preserved).

**Confidence:** confirmed (reproduced end-to-end on arista + nxos, and in isolation on the shared helper;
read the exact contradicting code path in all three call sites).

---

### F2 (MEDIUM, confirmed) — fortigate LAG first-pass reverse-link is a redundant O(L²)/O(M·I) scan

**file:** `netcanon/migration/codecs/fortigate_cli/parse.py:428` (loop body 427-430)

```python
for m in members:                         # M members on the `set member` line
    for prev in intent.interfaces:        # every interface parsed so far
        if prev.name == m and prev.lag_member_of is None:
            prev.lag_member_of = name
```
This nested scan runs per `aggregate` interface. A **second pass** (lines 524-532) already reverse-links
*every* member via a `dict` (`lag_members`) in O(I) and is order-independent — so the first-pass loop is
**fully redundant**. Verified: parsing an interleaved config (members defined both before and after their
LAG) and comparing the actual `lag_member_of` result against the second-pass-only result gives
**0 mismatches over 150 interfaces**.

**Failure scenario (reproduced):** `POST /plan` with `source=fortigate_cli` and a `config system interface`
block of many `type aggregate` edits:
- L aggregates × 1 member each: L=8000 → 677 KB → 0.997 s (quadratic: ~4× per doubling)
- I plain ifaces + 1 aggregate with M members: I=M=8000 → **437 KB → 1.78 s**
Extrapolates to ~15 min at a ~10 MB config. Blocks a threadpool worker.

**Fix:** delete lines 427-430 entirely; the dict-based second pass (524-532) produces identical output in
O(I). (If defence-in-depth is wanted for the first pass, index `iface_by_name` once and do a dict lookup.)

**Confidence:** confirmed (reproduced quadratic scaling; proved redundancy by diffing against
second-pass-only output — 0 mismatches).

---

### F3 (MEDIUM, confirmed) — arista channel-group reverse-link is O(D²) via `next(intent.lags)` scan

**file:** `netcanon/migration/codecs/arista_eos/parse.py:804`

```python
for chan_id, members in lag_members.items():           # D distinct channel-group ids
    lag_name = f"Port-Channel{chan_id}"
    existing = next((lag for lag in intent.lags if lag.name == lag_name), None)  # linear scan, grows to D
```
`intent.lags` grows as synthesized LAGs are appended, so the `next(...)` scan is O(D) inside a D-iteration
loop → O(D²), where D = number of distinct channel-group ids referenced by child interfaces.

**Failure scenario (reproduced):** `POST /plan` with `source=arista_eos` and D interfaces each carrying a
distinct `channel-group <i> mode active`:
- D=2000 → 112 KB → 0.077 s; D=4000 → 226 KB → 0.272 s (~4× per doubling → O(D²))
- extrapolates to ~8 min at a ~10 MB config.

**Fix:** build `lags_by_name = {lag.name: lag for lag in intent.lags}` once (or track synthesized LAGs in a
dict as they are created) and replace the `next(...)` with an O(1) lookup.

**Confidence:** confirmed (reproduced quadratic scaling).

---

### F4 (MEDIUM, confirmed quadratic; reachability indirect) — `compute_diff` uses `SequenceMatcher(autojunk=False)` → O(n²) on repeated lines

**file:** `netcanon/services/diff.py:119` (`autojunk=False`)

difflib added `autojunk` specifically to keep `SequenceMatcher` near-linear when an element (line) is
"popular" (appears in >1% of a sequence ≥200 long). Passing `autojunk=False` disables that guard —
and network configs are dense with repeated lines (`!`, `exit`, `next`, blank). The result is O(n·m)
on exactly the inputs autojunk was meant to protect.

**Failure scenario (reproduced):** diffing two configs of n identical delimiter lines
(`difflib.SequenceMatcher(a, b, autojunk=False).get_opcodes()`):
- n=4000 → 1.48 s; n=8000 → 6.5 s; n=16000 → **25.1 s** (clean O(n²)); n=50000 → est. ~4 min.
Reached via `POST /api/v1/configs/diff` and the UI `/diff` page. The `context` fold (line 340) only
trims the *serialized* output — it runs *after* the quadratic `compute_diff`, so it does not bound the
cost. Reachability is one step indirect: the two sides are **stored** configs (from backup jobs or the
store), not direct paste — but a config-backup source that returns pathological output, or simply two
genuinely large chassis configs (10-50 k lines with thousands of repeated delimiters), triggers it with
no attacker at all.

**Fix:** drop `autojunk=False` (accept difflib's default popularity heuristic — it only affects which
lines are treated as junk in the *display*, and near-identical configs still diff correctly), OR guard
`compute_diff` with a line-count threshold above which it refuses / falls back to a cheaper unified diff.
The comment does not state why autojunk was disabled, so the tradeoff should be re-confirmed.

**Confidence:** confirmed for the quadratic (measured); the end-to-end HTTP reachability with
attacker-chosen content is indirect (stored-config sourced), hence MEDIUM not MAJOR.

---

## Checked and found SOUND (no finding)

- VLAN-id range expanders **clamp before materializing**: `_helpers._parse_vlan_list` (1..4094),
  `arista._expand_vlan_list` (1..4094). aoss port-range `_MAX_PORT_RANGE_SPAN=1024`,
  target-profile `_MAX_PROFILE_RANGE_SPAN=4096`, junos `_MAX_BLOCK_DEPTH=100`. All hold.
- XML codecs (opnsense, cisco_iosxe) use **defusedxml** → billion-laughs / XXE rejected.
- `POST /sanitize` is `async` but **offloads the CPU pipeline via `asyncio.to_thread`** and bounds the
  read at `cap+1` (16 MB default) — event loop not blocked. All migration `/plan*` routes are **sync**
  `def` → run in the threadpool, so a slow parse blocks a worker, not the loop (relevant to F1-F3 as
  worker-pool exhaustion, not loop stalls).
- Per-line parse regexes are anchored on a leading keyword and use `\S+`/`[^\S\n]` (not overlapping
  quantifiers); no catastrophic-backtracking ReDoS found. `re.MULTILINE` only re-anchors `^`/`$`.
- `scan_stanzas` (`_scanner.py`) and the fortigate block tokenizer are single-pass / stack-based (linear).

## Known/deferred siblings (NOT re-reported as new)
- `canonical/transforms.py` `_add_unique` list-membership in VLAN projection = prior **PERF-2** (MINOR,
  deferred). F1 is a *different, far worse* site of the same anti-class (parse-time, 8.6 KB → 6.9 s).
- opnsense per-VLAN parent rescan = prior **PERF-3** (MINOR, deferred).
- A structural twin of F3 exists in `juniper_junos/parse.py:616`
  (`next((v for v in intent.vlans if v.id == vid), None)` inside the irb-fold loop → O(vids²)); **not
  measured**, plausible, same one-line dict fix. Flagged for awareness, not counted as confirmed.
