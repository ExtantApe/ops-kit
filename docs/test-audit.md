# Test audit

Newest first.

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
