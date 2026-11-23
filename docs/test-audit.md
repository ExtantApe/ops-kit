# Test audit

Newest first.

## 2026-11-22: pace, estimate, store-check, resume, topics-index

- Promises: pace verdicts, fail-closed, overrides, settings and a configurable state folder (49 checks);
  estimate buckets and queue order, padding and learning, read-only toward the task store, and all three
  task and tag layouts: log, rows, adapter (49 checks); store-check checks a to e, read-only, other paths and ID
  shapes (28 checks); resume sections, windows, adapters and flags (22 checks); topics-index format, index and
  `--check` (17 checks).
- Every test removes its temp folders and checks the working folder for leftovers.
- Gaps: none of this has run against a second team's real store layout, and the tools' text output is checked only
  for the key lines, not its whole layout.

## 2026-11-22: after the first-public security review

- Added tests for every finding: --share hides a private category (text and JSON); the adapter must be a .py file;
  vendor never replaces another folder or anything under .git, re-locks its own copy, never vendors ignored files,
  refuses a source symlink before touching the copy, fails check on a symlinked folder in the copy, and refuses a lock
  whose commit isn't a full hash (no argument injection into git). 27 tests.

## 2026-11-22: first audit

- Promises (README): status sections in order; bucket order with untagged last; done-this-week window; --share
  refuses without terms and hides private titles, areas and owners; the to-do list with chains joined by &&; person
  steps and decisions never chained; chain IDs stable and never reused; resolve; short view folds tests; --json;
  bad rows refused; adapters; --tags overlay. vendor: lock needs a matching copy; check catches edited, missing and
  extra files; refuses an uncommitted source and paths outside the repo; notes when upstream moves on; list.
- Covered: every promise above has a test in `tests/` (19 tests then).
- Gaps: pace isn't here yet. `--since` parsing of bad dates errors without a friendly message.
