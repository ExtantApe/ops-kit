# Pace, the heartbeat and size and payoff

How a team of sessions decides how fast to work, when to check in and how to rank work. A team adopts this text as
its own rule and records the date it did. `rules/joint-system.md` has the short version of each section. The tools
are `pace/`, `estimate/`, `store-check/`, `resume/` and `topics-index/`.

## The goal

- **Use the allowance well.** Work as fast as the allowance allows, aiming to have used 90% by each weekly reset. The
  last 10% is kept for errors and upkeep, and only that kind of work may use it. Both numbers are settings.
- **Plan from what's left.** Every plan comes from what's left, the time left and the resources running. Nobody
  guesses the rate, and nobody holds back out of habit.
- **Credits count too.** When usage credits exist, the rest of the week and the credits are one pool, stretched to
  the reset the same way. Pace learns how many dollars one weekly percent is worth from what a lane-hour costs in each.

## Pace

`pace` is a local script. It never calls a model or the network, so it costs nothing to run.

- **Input:** what the usage card shows: the weekly percent used, the reset time, the credits spent, the credit cap
  and the lanes running. Example: `pace record --weekly 42 --reset <iso> --spent 340.50 --cap 422 --lanes 3`.
- **Learning:** every reading is saved in the state folder, which stays out of version control. From the readings it
  learns the burn rate (spend over the last six hours), the cost of one lane-hour and how far off its own forecasts
  were. When it has been wrong, it widens its safety margin.
- **Output:** a verdict and a lane ceiling. The ceiling is a hard limit on how many sessions and agents run at once.

| Verdict | Meaning | What the team does |
| --- | --- | --- |
| GO HARD | Well under the line | Start new lanes up to the ceiling |
| STEADY | On the line | Keep what's running, and start work only into free lanes |
| SHIP ONLY | Ahead of the line | Finish release-ready work and start nothing new |
| QUEUE | Over the line, or the pool is spent | Nothing new until the line catches up or the reset comes. Upkeep only |

- **The owner can override it** at any time, in their own words: `pace override --verdict X --scope "..." --words "..."`.
  The override ends at the next reset, and every verdict output prints it while it is in force.
- **Target and reserve** are `--target` (default 90) and `--reserve` (default 10). The goal is the lower of the target
  and 100 minus the reserve. They are saved with each reading and carry forward.
- **It fails closed.** If the newest reading is older than its next beat plus 30 minutes, or the reset time is missing
  or already past, the answer is STEADY at the current lane count, never GO HARD, and the next beat is 15 minutes.
- **Pace sets speed only.** Every verdict says: "Pace sets speed only. It never lifts a gate: 2FA, going public,
  publishing, live servers, production or deletions."
- **One pool per account.** `--lanes` counts every session and subagent on the account.

## Credit top-ups

- The app shows what has been spent, never the cap. The owner says when credits are added, or gives the balance.
- If work can still go on after the weekly limit is used up, credits were added. Ask the owner how much before
  planning around it.
- Raise the cap in pace (`--cap`). The new money is stretched from the spend at that moment to the reset, at the same
  target.

## The heartbeat

- **One beat, one reading.** Each check-in reads usage, records it with pace and acts on the verdict. Then it
  schedules the next beat as a one-shot timer, `next_beat_minutes` from now.
- **The beat follows the pace.** The next beat comes when the current burn will have used 5% of what's left to the
  goal: a fast burn checks in often and a slow one rarely. When nothing is running, it comes when the six-hour average
  will have slid down to the line. A spent pool waits 3 hours. Beats stay between 15 minutes and 3 hours, and never
  more than a quarter of the time left.
- **A beat is cheap.** It's one usage read and one local script, and it does nothing else unless the verdict allows
  work.
- **It acts quietly.** A beat that finds QUEUE says nothing. A beat that resumes work says in one line what started.
- **Timers live only in the session.** After a restart, start the heartbeat again.

## Size and payoff

Every task carries a **size**, a **payoff** and the **bucket** those two give it. Each is one word.

- **Size:** Hours (under half a day), Days (half a day to a week), Weeks (a week or more). Estimates are padded
  about 20%, and the padding narrows as real costs come in.
- **Payoff:** Major, Moderate, Minor, scored against the owner's priorities.

Work runs in bucket order (Steal, Win, Pickup, Bet, Routine, Filler, Investment, Chore, Parked); the table is in
`rules/joint-system.md`. Only a person sets a tag. A tool may print a guess, labelled as a suggestion, and stores
nothing. Untagged tasks come last and are marked.

`estimate` prices a task from pace's lane-hour cost, learns from each `start` and `done` pair, and lists the queue
with what fits in what is left to the goal.

## The morning store check, resume pages and topic files

- **Store check.** `store-check` is the read-only report behind `spec/store-check.md`.
- **Resume page.** After a context reset, `resume` prints the session's open tasks, what they wait on and the recent
  decisions it hasn't acknowledged. Read it first.
- **Topic files.** One file per in-depth subject, indexed by `topics-index`. Update the file in the same commit as
  the work.
