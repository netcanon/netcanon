# Phase 4b findings — source vendor: mikrotik_routeros

Generated against `tests/fixtures/real/_phase4_runs/latest.json`.  Filter:
`source_codec == "mikrotik_routeros"` AND `field_variances[*].variance ==
"CODEC_BUG"`.

**4 CODEC_BUG findings** across 4 distinct (target, field) cells — by far
the smallest source-vendor bucket in the Phase 4 mesh.  Distribution:
arista_eos (1), cisco_iosxe_cli (1), fortigate_cli (1), opnsense (1).

The five mikrotik_routeros source fixtures driving these cells are:

* `tests/fixtures/real/mikrotik/ntc_ip_address_export.rsc`
* `tests/fixtures/real/mikrotik/routeros_diff_verbose_export.rsc`
* `tests/fixtures/real/mikrotik/taqavi_initial_provisioning.rsc`
* `tests/fixtures/real/mikrotik/user_contrib_crs310_ros7.rsc`
* `tests/fixtures/synthetic/mikrotik_routeros/kitchen_sink.rsc`

## Triage classification (3 buckets: A real-bug / B stale-YAML / C acceptable-lossy)

* **Bucket A — real codec bug**: target codec drops or mangles data the
  source carried and the YAML promised would survive.  Codec locus is
  the parse or render path of the *target*.
* **Bucket B — stale YAML**: the YAML expectation overstates what the
  current codec stack can actually do given target-vendor schema limits.
  Drift is real but expectations should be downgraded to `lossy`.
* **Bucket C — acceptable lossy**: benign canonicalisation (dedup,
  normalisation) the YAML already documents as fine elsewhere.

## Bucket totals

| Bucket | Count | Action |
|---:|---:|---|
| A | 3 | Fix target render paths (arista_eos hostname, cisco_iosxe_cli hostname, fortigate_cli static-route comment) |
| B | 1 | Downgrade YAML expectation (opnsense `interfaces[].ipv6_addresses` — schema limit on multi-v6 per zone) |
| C | 0 | — |

## Per-cell findings

### Target: arista_eos (Σ 1 codec bug)

#### Bug MT-1 (Bucket A): hostname containing whitespace round-trips to empty

* **Field**: `hostname`
* **Cell**: `mikrotik/routeros_diff_verbose_export.rsc -> arista_eos`
* **Drift detail**: source `'Quinta Router'` -> target `''`.
* **Source line** (`/system identity / set name="Quinta Router"`): mikrotik
  parser correctly strips quotes and stores the literal two-word string in
  `intent.hostname`.
* **Codec locus**: arista_eos render-side bug.
  `netcanon/migration/codecs/arista_eos/render.py:97-98` emits
  `f"hostname {tree.hostname}"` -> `hostname Quinta Router`, an invalid
  Arista line.  When that text is fed back through
  `arista_eos/parse.py:53` (`re.compile(r"^hostname\s+(\S+)\s*$",
  re.MULTILINE)`), the trailing `\s*$` anchor refuses to match because
  ` Router` is left on the line — the second-pass parse returns no
  hostname, hence the empty target value.
* **Phase 3 expectation**: `mikrotik_routeros__arista_eos.yaml` declares
  `hostname: good`.
* **Likely fix**: arista render must sanitise whitespace (replace runs
  with `-` or `_`) before emitting the `hostname` line.  Real Arista EOS
  rejects whitespace upstream, so the canonicalisation is required.

### Target: cisco_iosxe_cli (Σ 1 codec bug)

#### Bug MT-2 (Bucket A): hostname containing whitespace truncates at first space

* **Field**: `hostname`
* **Cell**: `mikrotik/routeros_diff_verbose_export.rsc -> cisco_iosxe_cli`
* **Drift detail**: source `'Quinta Router'` -> target `'Quinta'`.
* **Codec locus**: cisco_iosxe_cli render-side bug.
  `netcanon/migration/codecs/cisco_iosxe_cli/render.py:90-91` emits
  `f"hostname {tree.hostname}"` unsanitised.  The cisco_iosxe_cli parser
  pattern is more permissive (`r"^hostname\s+(\S+)"` at
  `parse.py:128`, no `$` anchor) so it captures `Quinta` but silently
  drops `Router`.  Real IOS-XE rejects whitespace in hostnames upstream.
* **Phase 3 expectation**: `mikrotik_routeros__cisco_iosxe_cli.yaml`
  declares `hostname: good`.
* **Likely fix**: same as MT-1 — sanitise whitespace before emission.

### Target: fortigate_cli (Σ 1 codec bug)

#### Bug MT-3 (Bucket A): static-route description not emitted

* **Field**: `static_routes` (sub-field `description` on every record)
* **Cell**: `synthetic/mikrotik_routeros/kitchen_sink.rsc -> fortigate_cli`
* **Drift detail**: 4 routes; on each, source `description` (`"Default
  route to ISP"`, `"Branch network via core"`, `"Blackhole RFC1918
  leakage"`, `"IPv6 default"`) -> target `""`.  Counts match (4 / 4);
  only `description` drifts.
* **Codec locus**: fortigate_cli render-side bug.
  `netcanon/migration/codecs/fortigate_cli/render.py:814-827` emits the
  `config router static / edit N / set dst / set gateway / set device /
  next` block but never emits `set comments "..."` — the canonical
  `route.description` is silently discarded.  FortiOS supports
  `set comments` on `config router static` entries.
* **Phase 3 expectation**: `mikrotik_routeros__fortigate_cli.yaml`
  declares `static_routes: good`.
* **Likely fix**: add `if route.description: out.append(f'        set
  comments "{route.description}"')` to the per-route block.

### Target: opnsense (Σ 1 codec bug)

#### Bug MT-4 (Bucket B): IPv6 link-local dropped (one v6 per zone schema)

* **Field**: `interfaces[].ipv6_addresses` (per-record, on `ether1`)
* **Cell**: `synthetic/mikrotik_routeros/kitchen_sink.rsc -> opnsense`
* **Drift detail**: source `[2001:db8:0:1::2/64 (global), fe80::1/64
  (link-local)]` -> target `[2001:db8:0:1::2/64]` only.
* **Codec locus**: opnsense render-side schema limit.
  `netcanon/migration/codecs/opnsense/render.py:259-261` deliberately
  emits only `ipv6_addresses[0]` because the OPNsense `<interfaces>`
  XML schema models exactly one `<ipaddrv6>` / `<subnetv6>` per zone.
  Additional v6 addresses on one interface are not first-class in the
  zone schema (they would have to live as `<virtualip><vip>` records).
  OPNsense also auto-derives link-local from the MAC, so explicit
  preservation is doubly synthetic.
* **Phase 3 expectation**: `mikrotik_routeros__opnsense.yaml` declares
  `interfaces[].ipv6_addresses: good` with a note implying scope is
  preserved — overstates schema reality.
* **Recommended action**: downgrade YAML to `lossy` with reason
  `OPNsense schema models one ipv6 address per zone; link-local is
  auto-derived` rather than invest in a `<virtualip>` extension that
  would also need a parser counterpart in
  `opnsense/parse.py`.  Bucket B.

## Top-2 actionable fixes (low CODEC_BUG count -> 2 not 3)

1. **Hostname whitespace sanitisation in target renderers** — clears
   MT-1 and MT-2 with a 2-line change in each of
   `netcanon/migration/codecs/arista_eos/render.py:97-98` and
   `netcanon/migration/codecs/cisco_iosxe_cli/render.py:90-91`.
   Helper could live as a shared `_sanitise_hostname` in
   `migration/_user_secrets.py`-adjacent helper if other vendors
   replicate the pattern (real Arista / IOS-XE both reject whitespace).
2. **fortigate_cli static-route `set comments` emission** — single
   conditional in `netcanon/migration/codecs/fortigate_cli/render.py`
   between lines 825 and 826 (after `set device`, before `next`).
   Clears MT-3 (4 routes) and any other source whose static routes
   carry comments.

The opnsense ipv6 case (MT-4) is a YAML downgrade rather than a code
fix — handled in the cross_vendor_expectations YAML edit, not the codec.

## See also

* `tests/fixtures/real/PHASE4_RECONCILIATION.md` — overall Phase 4b skeleton
* `tests/fixtures/real/_phase4_runs/latest.json` — raw per-cell data
* `tests/fixtures/cross_vendor_expectations/mikrotik_routeros__arista_eos.yaml`
* `tests/fixtures/cross_vendor_expectations/mikrotik_routeros__cisco_iosxe_cli.yaml`
* `tests/fixtures/cross_vendor_expectations/mikrotik_routeros__fortigate_cli.yaml`
* `tests/fixtures/cross_vendor_expectations/mikrotik_routeros__opnsense.yaml`
* `netcanon/migration/codecs/mikrotik_routeros/parse.py` — confirmed
  source-side parsing of `hostname`, `static_routes[].description`, and
  `interfaces[].ipv6_addresses` is correct; bugs are all on the target
  side (arista/cisco_iosxe_cli/fortigate render) or in the OPNsense
  YAML expectation.
