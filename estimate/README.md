# estimate

Size, payoff and a padded cost for open tasks, and the queue they make. It prices work in pace's units (weekly
percent, or dollars once pace knows the exchange rate), so it needs `pace/` beside it and at least two readings.
It never writes to your task store.

```bash
python3 estimate/estimate.py tag T12 --size Days --payoff Major --by alice
python3 estimate/estimate.py start T12 --lanes 2
python3 estimate/estimate.py done T12
python3 estimate/estimate.py queue [--json] [--limit N] [--suggest]
python3 estimate/estimate.py show
```

Sizes are Hours, Days and Weeks. Payoffs are Major, Moderate and Minor. The pair gives the bucket (Steal, Win,
Pickup, Bet, Routine, Filler, Investment, Chore, Parked; the table is in `rules/joint-system.md`). The queue runs in
bucket order, then priority, then payoff per cost, and marks each task as fitting or not in what pace has left to the
goal. Waiting and blocked tasks are listed apart. Untagged tasks come last and say so. `--suggest` prints guesses
labelled as suggestions and stores nothing.

A task's cost is pace's learned lane-hour cost times 3, 16 or 50 hours, plus 20%. Each `start` and `done` pair records
the real spend between two readings and feeds a per-size average. The padding falls one point per sample, to a floor
of 10%. A pair is not learned when the pool changed between the two.

## Adapters

Two things come from your store: the tasks and their tags.

| Flag | What it reads |
|------|---------------|
| `--task-log FILE` (default `$ESTIMATE_TASKS`, else `$OPS_ROOT/tasks/log.jsonl`) | An append-only event log: `add`, `close`, `reopen`, `wait`, `resume`, `set`, `block`, `unblock` |
| `--source FILE` | Rows in the common schema `status/status.py` reads (JSON list or JSON Lines) |
| `--adapter FILE` | A Python file with `tasks()` and, optionally, `tags()`. See `adapters/example_adapter.py` |

Tags have two layouts:

- **A separate file** (the default): `<state dir>/estimate-tags.jsonl`, or `--tags FILE`. Rows are
  `{id, size, payoff, by, at}`, the newest wins, and it is the same shape as `status.py --tags`. `tag` appends here.
- **Tags in the task store** (`--tags-from-log`): a `set` event that carries `size` and `payoff`, or the `size` and
  `payoff` fields of a `--source` row, or an adapter's `tags()`. Estimate never writes to the log, so `tag` refuses in
  this mode. Tag with the tool that owns the log.

An adapter runs as Python with your permissions. Use only adapters you wrote or have read.

## State

`estimate-tags.jsonl` and `estimate-runs.jsonl` go in `--state-dir`, else `ESTIMATE_DIR`, else `PACE_STATE_DIR`, else
`$OPS_ROOT/state`, else `./state`. Pace's readings are read from `PACE_STATE_DIR` or the same folder. If `pace` lives
somewhere else, set `ESTIMATE_PACE` to its `pace.py`.

## Tests

```bash
python3 estimate/tests/test_estimate.py
```
