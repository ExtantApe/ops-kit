# resume

The page a session reads first after its context was cleared: its open tasks and what each waits on, tasks moved to
it and not yet acknowledged, recent decisions that apply to it and that it hasn't named in a ledger line or task
note, and its last five ledger lines. Read-only, offline.

```bash
python3 resume/resume.py "Session A" --root path/to/store
python3 resume/resume.py "Session A" --days 30 --today 2026-11-23
```

## Formats it reads

- **Task events** (`ROOT/tasks/log.jsonl`): `{"op": "add", "id", "title", "owner", "area", "priority"}`, then `close`,
  `reopen`, `wait` (`on`, `reason`), `resume`, `set` (`priority`, `area`), `move` (`to`), `ack` (`by`) and `note`
  (`text`), each with `by` and `ts`. This is the same log `estimate` and `store-check` read.
- **Ledger** (`ROOT/ledger/*.jsonl`): `{"ts", "session", "type", "summary", "refs": []}`.
- **Decisions** (`ROOT/decisions/*.md`): headings like `## D12 Title (2026-11-20)`, with an optional `Date:` line and an
  optional `Applies to:` line (`every session`, a session name or an area). No `Applies to:` line means everyone.

## Adapters

Every path is a flag (`--tasks`, `--ledger-dir`, `--decisions`, `--decision-re`). For a store that keeps these things
in another shape, pass `--adapter FILE`: a Python file with any of `events()`, `ledger()` and `decisions()`.
`decisions()` returns dicts with `id`, `title`, `date` and `applies`. Whatever the adapter leaves out is read from the
files. An adapter runs as Python with your permissions. Use only adapters you wrote or have read.

## Tests

```bash
python3 resume/tests/test_resume.py
```
