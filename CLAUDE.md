# ops-kit

Shared tools for teams of Claude Code sessions. Read `README.md`, `rules/joint-system.md` and `docs/decisions.md`
before changing anything.

- Plain Python 3.9+, standard library only. No network calls, no accounts, no telemetry.
- Every change keeps `python3 -m unittest discover -s tests` and `bash scripts/leak-check.sh` passing, and adds tests
  for new behavior.
- Nothing team-specific goes in this repo: no people's names, addresses, internal project names or private paths.
  Examples use made-up values.
- Vendored folders (listed in `vendor.lock.json`) are never edited here. Change them upstream, then lock again.
- Changes arrive as pull requests. Decisions go in `docs/decisions.md`, dated.
