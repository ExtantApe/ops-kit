# The morning store check

A daily sweep of the whole store by the chief, after the daily report. It finds what has quietly gone wrong: work
that shipped but never closed, waits on things that no longer exist, decisions nobody acted on. The aim is a store
the owner can trust at a glance.

## What to look for

Each check names what it finds and the evidence that settles it.

1. **Shipped but still open.** A task whose work is merged, released or confirmed by the owner, but which is still
   open. Evidence: the commit, PR, release URL or the owner's words. Close it with that evidence.
2. **Waiting on nothing.** A task waiting on a person, step or task that is closed, dropped or gone. Resume it, or
   re-point the wait at what it really needs.
3. **Blocked too long.** Blocked more than 3 days with no new note. Ask the owner of the block what's needed.
4. **Decisions with no task.** An owner decision from the last 14 days that no task cites and no note excuses. Add
   the task, or a note saying why none is needed.
5. **Stale owner steps.** An owner step open more than 7 days, or one whose commands or paths no longer exist. Fix
   the step, or drop it with the reason.
6. **Contradicting owner steps.** Two open steps that ask for opposite things, or one that a later decision
   replaced. Keep the newer one and drop the other with the reason.
7. **Duplicates.** Two open tasks or steps for the same work. Keep the older ID, move notes across, close the other
   pointing at it.
8. **Untagged tasks.** Open tasks without a size and payoff. Ask their lead to tag them.
9. **Over the work limit.** An owner with more tasks in progress than the limit allows. Ask which one waits.
10. **A broken chain.** If the store is hash-chained, verify it first. A break stops the sweep and goes to the owner.

## How to act

- **Clear cases** (the evidence settles it): act, and record the evidence in the same write.
- **Everything else** goes to the owner as one list: ID, one line on what's wrong, and the choice wanted.
- Never delete. Close, drop or move, with a reason.
- Write one summary line to the team's log: counts per check, and what went to the owner.

## Output

```
store check 2026-11-23: closed 4 (shipped), resumed 2 (waits), 1 decision got a task, 3 to the owner
```

A quiet morning (nothing found) still writes its one line, so a missing line means the check didn't run.
