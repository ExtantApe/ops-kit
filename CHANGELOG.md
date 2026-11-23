# Changelog

## Unreleased

- Added `pace/` (usage pacing), `estimate/` (size, payoff and padded cost, with task and tag adapters),
  `store-check/` (the read-only morning check), `resume/` (the post-reset page, with an adapter) and `topics-index/`
  (topic-file format and index), each with its own README and tests. Added `rules/pace-and-heartbeat.md`.
- Every store path is a flag with `OPS_ROOT` as the base for defaults, and state files go in a configurable state
  folder.
- CI now also runs every tool's tests under `*/tests/`.
- Tested: each tool's own test script (made-up data in temp folders, cleaned up and checked for leftovers), the
  existing `tests/` suite and the leak check.
- `topics-index`: `--sections` (or `TOPICS_SECTIONS`) sets the required sections. Now, Open and Log are built-in
  aliases for Where it stands, Open questions and History. `## Don't` is an optional extra that never fails the check.
  Tested: new cases for the flag, the env fallback, the aliases and Don't. Not tested: a real store's topic files.
- Not tested: use against a second team's real store layout, and Python versions other than the one the tests ran on.
