# topics-index

One file per in-depth subject, so a session that picks the subject up after a reset reads one page instead of
digging through a log. Only the index (one line per topic) loads at the start. Open a topic file when you work on that
subject, and update it in the same commit as the work.

```bash
python3 topics-index/topics_index.py --root path/to/store            # rewrite topics/INDEX.md
python3 topics-index/topics_index.py --root path/to/store --check    # write nothing; exit 1 if stale or malformed
python3 topics-index/topics_index.py --topics-dir path/to/topics     # a folder that isn't ROOT/topics
python3 topics-index/topics_index.py --sections "Summary,Now,Decisions,Open,Log"   # a different required set
```

## Format

File name: `topics/<short-name>.md`, lowercase with hyphens. Sections in this order, with these exact headings:

```
# <Title>

## Summary
Twenty lines or fewer. What it is, the current answer, who owns it. The first line is the one-line
description used in the index.

## Where it stands
What is done, what is running, what is next.

## Decisions
- ID: one line on what it settled.

## Open questions
- A question, who can answer it, since when. Write "None." if there are none.

## History
- 2026-11-22: what happened, newest first.

## Sources
- Paths, task IDs, messages and commits someone can check.
```

- The summary is 20 lines or fewer, counting every line up to the next heading. `--check` fails on a longer one.
- History entries start with an ISO date. The newest date is the file's last update in the index.
- Write what is true now. Move old detail into History instead of leaving it in the summary.
- `## D numbers` is still accepted as an older name for `## Decisions`.

## Other section names

`--sections` takes a comma-separated list of the sections every topic must have, in that order. The environment
variable `TOPICS_SECTIONS` does the same when the flag is absent, and the flag wins. With neither, the six sections
above are required. Naming a subset is how a store without a `Sources` section gets a clean `--check`.

These headings are built-in aliases, in a topic file and in `--sections` alike:

| Heading | Counts as |
| --- | --- |
| Now | Where it stands |
| Open | Open questions |
| Log | History |
| D numbers | Decisions |

So a store whose topics use Summary, Now, Decisions, Open and Log runs with
`--sections "Summary,Now,Decisions,Open,Log"`. Names are matched exactly, so list a section by its heading or an alias.

`## Don't` is an optional extra. A topic may include it anywhere or leave it out, and it never fails the check.
The summary length rule applies only when `Summary` is required, and the dated-history rule only when `History` is.

## Tests

```bash
python3 topics-index/tests/test_topics_index.py
```
