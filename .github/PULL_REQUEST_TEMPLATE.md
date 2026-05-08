## Summary

<!-- One or two sentences: what changed and why. -->

## Scope

- [ ] Code change touches `netconfig/`
- [ ] Code change touches `netconfig_desktop/`
- [ ] Definition / fixture change
- [ ] Documentation only

## Doc-sync checklist

The most-skipped reviewer concern.  Audit `CLAUDE.md`'s "Documentation Sync
Checklist" table — every row that applies to your change should have its
target doc updated in this same commit.

- [ ] If a hard rule was added or modified → `CLAUDE.md`
- [ ] If a new interactive HTML element was added → `tests/testid_reference.md`
- [ ] If a new codec / module / canonical field was added → the relevant module README
- [ ] If a capability-matrix declaration changed → cross-mesh audit regenerated
- [ ] If the change touches operator-facing behaviour → `docs/CAPABILITIES.md`

## Tests

- [ ] Unit tests pass locally (`pytest tests/unit`)
- [ ] Integration tests pass locally (`pytest tests/integration`)
- [ ] E2E tests pass locally (`pytest tests/e2e`) — only if UI changed
- [ ] CI is green

## Matrix-honesty self-check

- [ ] No silent loss paths added
- [ ] Capability matrix declarations are honest (supported / lossy / unsupported with cited reasons)
- [ ] No hard-coded counts in prose docs (or a CI guard added)

## Linked issues

Closes #
