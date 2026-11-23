# ops-kit

Small, local-only tools for running a work store with a team of Claude Code sessions: one read of where every task
stands, the owner's to-do list with chained commands, a daily store check, and pinned, checksummed copies of other
teams' tools. Plain Python 3.9+, no dependencies, no network, no accounts.

**Status:** early. `status` and `vendor` are tested (unit tests, run in CI). `pace` is a slot, waiting for a
partner team's tool.

## What's here

| Path | What it is |
|------|------------|
| `status/status.py` | Where every task stands, and what the owner has to do, in one read |
| `status/adapters/` | How to plug in your own store |
| `vendor/vendor.py` | Copy a folder from another repo at a pinned commit, with a checksum per file |
| `rules/joint-system.md` | The rule text a team adopts: status, size and payoff buckets, pace, heartbeat, store check |
| `spec/store-check.md` | The morning store check, step by step |
| `pace/` | Slot for pace (usage pacing), to be vendored in |

## status

```bash
python3 status/status.py --source tasks.jsonl --steps steps.jsonl          # text, about one screen
python3 status/status.py --source tasks.jsonl --steps steps.jsonl --full   # every step and chain command
python3 status/status.py --adapter my_adapter.py --json
python3 status/status.py --source tasks.jsonl --share --terms private-terms.txt
python3 status/status.py resolve C1                                         # the step IDs in chain C1
```

Tasks and steps use a small common schema (`python3 status/status.py --help`). If your store looks different, write
an adapter: a Python file with `tasks()` and, optionally, `steps()` (see `status/adapters/example_adapter.py`). An
adapter runs as Python with your permissions, so use only adapters you wrote or have read. Size
and payoff tags kept in a separate file can be laid over the tasks with `--tags`.

`--share` reads a terms file with one regular expression per line (case-insensitive) and refuses without one. Chain
IDs are kept in `./todo-chains.json` (or `--chains FILE`).

Within each section tasks run in bucket order (size x payoff; see `rules/joint-system.md`), untagged ones last.

## vendor

```bash
python3 vendor/vendor.py lock pace --source ../their-repo --from tools/pace --to pace --copy
python3 vendor/vendor.py check                       # fails on any edited, missing or extra file
python3 vendor/vendor.py check --source pace=../their-repo   # also notes when upstream has moved on
python3 vendor/vendor.py list
```

## Tests

```bash
python3 -m unittest discover -s tests
```

## Contributing

Changes come as pull requests. Only the maintainers merge to `main`; the leak check and the tests must pass.

## License

MIT. See `LICENSE`.
