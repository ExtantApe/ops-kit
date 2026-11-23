# The joint system

How a team of Claude Code sessions keeps its work store honest and its pace steady. Each team adopts this text as
its own rule and records the date it did. The tools in this repo carry it out; nothing here needs a network, an
account or a paid service.

Words used here: the **owner** is the person the sessions work for. The **chief** is the session that talks to the
owner and keeps the store. **Leads** are the sessions that own areas of work. The **store** is wherever tasks, owner
steps and decisions live (an append-only log is best).

## 1. Status in one read

`status` shows, in order: the owner's to-do list, what was done this week, what's in progress, the priority queue,
next, soon, and everything else. Run it at the start of each check-in instead of reading the store by hand.

- **The owner's to-do list** lists every open owner step and test by category, with numbered quick steps. Steps made
  only of shell commands are joined into chains (C1, C2, ...) with `&&`, so one paste runs them all and stops at the
  first failure. Anything that needs a person (a click, a phone, a browser, a decision) is never chained.
- **Short IDs.** The owner replies "done N12" or "done C1". The chief marks every member of a chain done in one write.
  A chain keeps its ID while its members stay the same, and IDs are never reused.
- **Sharing.** `status --share` shows IDs, areas, categories, buckets and generic titles only, and refuses to run
  without a readable private-terms list.

## 2. Size, payoff and buckets

Every task can carry a size and a payoff. Leads tag their own tasks.

- **Size:** Hours (under half a day), Days (half a day to a week), Weeks (a week or more).
- **Payoff:** Major, Moderate, Minor. Rank payoff in this order: children's safety and security first, then anything
  blocking a release, then member-facing value, then internal polish.

Together they give the bucket. Within each priority, work runs in bucket order:

| Order | Bucket     | Size  | Payoff   | Note                         |
|------:|------------|-------|----------|------------------------------|
| 1     | Steal      | Hours | Major    |                              |
| 2     | Win        | Days  | Major    |                              |
| 3     | Pickup     | Hours | Moderate |                              |
| 4     | Bet        | Weeks | Major    |                              |
| 5     | Routine    | Days  | Moderate |                              |
| 6     | Filler     | Hours | Minor    | only when lanes are free     |
| 7     | Investment | Weeks | Moderate |                              |
| 8     | Chore      | Days  | Minor    |                              |
| 9     | Parked     | Weeks | Minor    | needs the owner's OK to start |

Untagged tasks come after tagged ones, and `status` marks them `[untagged]` so they get tagged.

## 3. Pace

Pace turns the usage numbers the owner can see (weekly percent, reset time, credits spent, credit cap, lanes running)
into a verdict: GO HARD, STEADY, SHIP ONLY or QUEUE, and a lane ceiling. The ceiling is a hard limit. The owner can
always override it. A team picks its target and reserve (for example, 90% used by each reset, 10% kept for errors and
upkeep). Pace fails closed: when it can't tell, it never lifts a gate. See `pace/` and `rules/pace-and-heartbeat.md`.

## 4. Heartbeat

Each check-in is a one-shot timer. It reads usage, records it with pace, acts on the verdict, and schedules the next
beat at the interval pace gives: about 2 hours while queued, about 45 to 60 minutes while work runs, never more than
3 hours apart. A quiet beat says nothing to the owner. A beat that restarts work tells the owner in one line.

## 5. The morning store check

Every morning, after the daily report, the chief checks the whole store against `spec/store-check.md`. Clear cases
are closed with their evidence; everything else goes to the owner as one short list.

## 6. Not losing work across context resets

- Each active project keeps a short topic file (summary, now, decisions, don't, open, log). Update it in the same
  commit as the work, and read it first after any reset.
- Commits name their task in a `Task: K12` trailer, so a task's work can be found from the history.
- Every owner decision gets a task, or a note saying why none is needed. The morning check looks for the gap.
- After a reset, `resume/resume.py` prints a session's open tasks and the recent decisions it hasn't acknowledged.
  `topics-index/` holds the topic-file format and its index.

## 7. Vendoring

A team that uses another team's tool copies it at a pinned commit with `vendor/vendor.py`, which records a checksum of
every file. `vendor.py check` runs in CI once anything is vendored, and fails on any hand edit. Changes go upstream as a pull request, then the
copy is locked again.
