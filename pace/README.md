# pace

Turns the usage numbers you can see (weekly percent, reset time, credits spent, credit cap, lanes running) into a
verdict and a lane ceiling, so a team of sessions works as fast as the allowance allows and lands near its target at
the reset. No model calls and no network, so running it costs nothing.

```bash
python3 pace/pace.py record --weekly 42 --reset 2026-11-30T18:00:00Z --lanes 3
python3 pace/pace.py record --weekly 100 --reset 2026-11-30T18:00:00Z --spent 340.50 --cap 422 --lanes 2
python3 pace/pace.py now [--json]
python3 pace/pace.py history -n 20
python3 pace/pace.py override --verdict SHIP_ONLY --scope "Feature work" --words "the owner's words"
```

Verdicts: GO HARD, STEADY, SHIP ONLY, QUEUE. Each comes with a lane ceiling and the minutes until the next
check-in. The rule text is in `rules/pace-and-heartbeat.md`.

## Where it keeps its readings

`pace.jsonl` and `pace-overrides.jsonl` in one state folder: `--state-dir DIR`, else `PACE_STATE_DIR`, else
`$OPS_ROOT/state`, else `./state`. Keep that folder out of version control. Nothing is written anywhere else.

## How it works

- Every reading is saved. From consecutive readings it learns the burn rate (spend over the last six hours), what one
  lane-hour costs and how wrong its own last forecast was, and widens its margin when it was wrong.
- With both a weekly percent and credits, the two are one pool, stretched to the reset together. The dollar value of
  one percent is learned from lane-hour costs, or given with `--usd-per-pct`.
- `--target` (default 90) and `--reserve` (default 10) are saved with each reading. The goal is the lower of the
  target and 100 minus the reserve.
- It fails closed. A reading older than its beat plus 30 minutes, or a missing or past reset time, gives STEADY at
  the current lane count, never GO HARD.
- It sets speed only. Every output says so: it never lifts a gate.

## Tests

```bash
python3 pace/tests/test_pace.py
```

Uses made-up readings in a temp folder, removes it, and checks that the folder is gone.
