# store-check

A read-only report for the morning store check (`spec/store-check.md`). It finds work that shipped but never closed,
waits on things that no longer exist, decisions with no task, old owner steps and near-duplicate tasks. It changes no
file, task or git ref, and never touches the network.

```bash
python3 store-check/store_check.py --root path/to/store
python3 store-check/store_check.py --json --code path/to/clones --today 2026-11-23
```

| Check | Spec item | What it finds |
|-------|-----------|---------------|
| a | 1 | Open tasks named by a `Task: ID` trailer on `origin/main` or `origin/prod` of the clones under `--code`. Local refs only, no fetch. Skipped without `--code` (or `OPS_CODE`) |
| b | 2 | Waits that name a retired or closed session (from the roster), or an owner step that isn't listed |
| c | 4 | Decisions with no task that mentions them and no "no task needed" note |
| d | 5 | Owner steps and tests dated more than 10 days ago |
| e | 7 | Open tasks in one area with near-identical titles |

The other checks in the spec (blocked too long, contradicting steps, untagged tasks, over the work limit, a broken
chain) need a person or a store-specific reader, and are not here.

## Where it looks

Every path is a flag, and `--root` (else `OPS_ROOT`, else the current folder) is the base for the defaults:

- `--tasks FILE`: the task event log (default `ROOT/tasks/log.jsonl`)
- `--decisions GLOB`: decision files (default `ROOT/decisions/*.md`)
- `--steps FILE`, repeatable: owner-step files (default `ROOT/needs-you.md` and `ROOT/tests.md`)
- `--roster FILE`: a markdown table, name in column 1 and status in column 5 (default `ROOT/roster.md`)
- `--code DIR`: a folder of git clones
- `--task-re`, `--decision-re`, `--step-re`: ID patterns (defaults `[A-Z]+\d+`, `D\d+`, `[NT]\d+`)

Decisions are headings like `## D12 Title (2026-11-20)` or `### D12 Title`. Steps are headings like
`### N12 [command] Title (2026-11-20, 5 min)`. A decision with the words "no task needed" is not flagged.

## Tests

```bash
python3 store-check/tests/test_store_check.py
```

Builds a throwaway store and a throwaway git clone in a temp folder, removes both, and checks nothing is left.
