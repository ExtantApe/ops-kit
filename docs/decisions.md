# Decisions

Dated decisions for this repo, newest last.

- 2026-11-22: created as the public MIT home for the joint system's shared tools: `status` with store adapters,
  the store-check spec and rule text, a slot for pace, and lock-and-checksum vendoring.
- 2026-11-22: size and payoff buckets (Steal, Win, Pickup, Bet, Routine, Filler, Investment, Chore, Parked) order
  work within each priority; untagged tasks come last.
- 2026-11-22: pace, estimate, store-check, resume and topics-index added from one team's private store, made generic.
  Every path is configurable, state goes in a state folder, estimate reads tasks and tags through adapters (a
  separate tags file or tags in task-log events), and resume works through an adapter on the shared task-log and
  ledger formats. Both teams agreed to the joint system and the public repo before this change.
- 2026-11-23: topics-index gains `--stale` (read-only): topics older than their tasks' newest event, open tasks in no
  topic, tasks in two topics, and closed or unknown tasks still listed. It supports a store rule that every open task
  sits in exactly one topic's `Tasks:` line.
