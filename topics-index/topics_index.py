#!/usr/bin/env python3
"""Write topics/INDEX.md: one line per topic file, from each file's title, summary and history.

  topics_index.py                    # rewrite ROOT/topics/INDEX.md
  topics_index.py --check            # write nothing; exit 1 if the index is stale or a topic breaks the format
  topics_index.py --root DIR         # the store (default: $OPS_ROOT, else the current folder)
  topics_index.py --topics-dir DIR   # a topics folder that isn't ROOT/topics
  topics_index.py --sections LIST    # required sections, comma-separated, in order (or $TOPICS_SECTIONS)
  topics_index.py --stale            # write nothing; list topics older than their tasks' newest event, open tasks
                                     # in no topic, tasks in two topics, and closed or unknown tasks still listed
  topics_index.py --stale --tasks FILE --task-re RE   # the task event log (default ROOT/tasks/log.jsonl), ID pattern

The format is in topics-index/README.md. Local only, no network.
"""
import argparse, glob, json, os, re, sys

ROOT = os.environ.get("OPS_ROOT") or os.getcwd()
SECTIONS = ["Summary", "Where it stands", "Decisions", "Open questions", "History", "Sources"]
# Other headings that count as the same section. Matching is exact, so "Open" is not "Open questions" until aliased.
ALIASES = {"D numbers": "Decisions", "Now": "Where it stands", "Open": "Open questions", "Log": "History"}
# Accepted and never required. A topic may leave them out or put them anywhere.
OPTIONAL = ["Don't", "Don\u2019t"]
MAX_SUMMARY = 20
TASK_RE = r"[A-Z]+\d+"
CLOSED_OPS = {"close": "closed", "drop": "closed", "reopen": "open"}
# A "Tasks:" line, plain or bold, optionally a list item: "Tasks: K1, K2", "- **Tasks:** K3", "Tasks: none".
TASKS_LINE = re.compile(r"^\s*(?:[-*]\s+)?\**Tasks\**\s*:\s*\**\s*(.*)$", re.M)


def canon(name):
    return ALIASES.get(name.strip(), name.strip())


def parse_sections(value):
    """'Summary, Now ,Open' -> ['Summary', 'Where it stands', 'Open questions']"""
    out = []
    for part in value.split(","):
        if part.strip() and canon(part) not in out:
            out.append(canon(part))
    return out


def sections(text):
    out, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"## (.+?)\s*$", line)
        if m:
            cur = canon(m.group(1))
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
    return out


def one_line(s, n=140):
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 3].rstrip() + "..."


def read_topic(path, required=None):
    """Return (entry, problems). entry has name, title, line, updated."""
    name = os.path.basename(path)[:-3]
    text = open(path, encoding="utf-8").read()
    required = SECTIONS if required is None else required
    problems = []
    t = re.search(r"^# (.+?)\s*$", text, re.M)
    title = t.group(1) if t else name
    if not t: problems.append("no title line")
    sec = sections(text)
    missing = [s for s in required if s not in sec]
    if missing: problems.append("missing sections: " + ", ".join(missing))
    elif [s for s in sec if s in required] != required: problems.append("sections are out of order")
    body = [l for l in sec.get("Summary", [])]
    while body and not body[-1].strip(): body.pop()
    while body and not body[0].strip(): body.pop(0)
    if "Summary" in required and len(body) > MAX_SUMMARY: problems.append(f"summary is {len(body)} lines, over {MAX_SUMMARY}")
    first = next((l for l in body if l.strip()), "")
    if "Summary" in required and not first: problems.append("summary is empty")
    dates = re.findall(r"^\s*[-*]?\s*(\d{4}-\d{2}-\d{2})\b", "\n".join(sec.get("History", [])), re.M)
    if "History" in required and not dates: problems.append("history has no dated entry")
    return dict(name=name, title=title, line=one_line(first), updated=max(dates) if dates else "undated"), problems


def topic_files(topics_dir):
    return [p for p in sorted(glob.glob(os.path.join(topics_dir, "*.md")))
            if os.path.basename(p) not in ("README.md", "INDEX.md")]


def listed_tasks(text, task_re=TASK_RE):
    """Every task ID on the file's Tasks: lines, in order, without repeats."""
    out = []
    for m in TASKS_LINE.finditer(text):
        for k in re.findall(r"\b" + task_re + r"\b", m.group(1)):
            if k not in out:
                out.append(k)
    return out


def read_task_log(path):
    """Fold a task event log (one JSON object per line with id, op, ts) into {id: {state, last}}.
    An "add" opens a task, "close" or "drop" closes it, "reopen" opens it again. Every event moves "last",
    the date (YYYY-MM-DD) of the newest event for that task."""
    tasks = {}
    if not os.path.exists(path):
        return tasks
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        k, op, ts = e.get("id"), e.get("op"), str(e.get("ts", ""))[:10]
        if not k:
            continue
        if op == "add":
            tasks[k] = {"state": "open", "last": ts, "title": str(e.get("title", ""))}
        t = tasks.get(k)
        if t is None:
            continue
        t["state"] = CLOSED_OPS.get(op, t["state"])
        if ts > t["last"]:
            t["last"] = ts
    return tasks


def stale(topics_dir, tasks_path, task_re=TASK_RE, required=None):
    """Read-only. Returns a dict of lists: stale topics, open tasks in no topic, tasks in more than one topic,
    and closed or unknown tasks still on a Tasks: line."""
    tasks = read_task_log(tasks_path)
    where, out = {}, {"stale": [], "unlisted": [], "doubled": [], "closed_listed": [], "unknown": []}
    for p in topic_files(topics_dir):
        e, _ = read_topic(p, required)
        ids = listed_tasks(open(p, encoding="utf-8").read(), task_re)
        newer = [(k, tasks[k]["last"]) for k in ids if k in tasks and tasks[k]["last"] > e["updated"].replace("undated", "")]
        if newer:
            k, d = max(newer, key=lambda x: x[1])
            out["stale"].append({"topic": e["name"], "updated": e["updated"], "task": k, "event": d})
        for k in ids:
            where.setdefault(k, []).append(e["name"])
            if k not in tasks:
                out["unknown"].append({"topic": e["name"], "task": k})
            elif tasks[k]["state"] != "open":
                out["closed_listed"].append({"topic": e["name"], "task": k})
    key = lambda k: (re.sub(r"\d+", "", k), int(re.sub(r"\D+", "", k) or 0))
    out["unlisted"] = [{"task": k, "title": tasks[k]["title"]} for k in
                       sorted((k for k, t in tasks.items() if t["state"] == "open" and k not in where), key=key)]
    out["doubled"] = [{"task": k, "topics": v} for k, v in sorted(where.items(), key=lambda x: key(x[0])) if len(v) > 1]
    return out


def stale_report(r):
    L = ["# Topics: stale check", "", "Read-only. Nothing was changed.", ""]
    def sec(title, rows, fmt):
        L.extend([f"## {title} ({len(rows)})", ""])
        L.extend("- " + fmt(x) for x in rows)
        if not rows:
            L.append("None.")
        L.append("")
    sec("Topics older than their newest task event", r["stale"],
        lambda x: f"{x['topic']}.md (updated {x['updated']}): {x['task']} changed {x['event']}")
    sec("Open tasks in no topic", r["unlisted"], lambda x: f"{x['task']} {one_line(x['title'], 90)}".rstrip())
    sec("Tasks in more than one topic", r["doubled"], lambda x: f"{x['task']}: " + ", ".join(t + ".md" for t in x["topics"]))
    sec("Closed tasks still on a Tasks line", r["closed_listed"], lambda x: f"{x['task']} in {x['topic']}.md")
    sec("Tasks on a Tasks line that the log doesn't know", r["unknown"], lambda x: f"{x['task']} in {x['topic']}.md")
    return "\n".join(L)


def build(topics_dir, required=None):
    entries, problems = [], {}
    for p in topic_files(topics_dir):
        e, pr = read_topic(p, required)
        entries.append(e)
        if pr: problems[e["name"]] = pr
    lines = ["# Topic index", "",
             "One line per topic. Open the file when you work on the subject. Generated by topics_index.py; don't edit by hand.", ""]
    for e in sorted(entries, key=lambda e: e["name"]):
        lines.append(f"- [{e['title']}]({e['name']}.md), updated {e['updated']}: {e['line']}")
    if not entries:
        lines.append("No topics yet.")
    return "\n".join(lines) + "\n", problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--topics-dir")
    ap.add_argument("--sections", default=os.environ.get("TOPICS_SECTIONS"),
                    help="required sections, comma-separated, in order (default $TOPICS_SECTIONS, else the built-in six)")
    ap.add_argument("--stale", action="store_true", help="write nothing; list stale topics and unlisted tasks")
    ap.add_argument("--tasks", help="the task event log for --stale (default ROOT/tasks/log.jsonl)")
    ap.add_argument("--task-re", default=TASK_RE, help="task ID pattern for --stale (default %(default)s)")
    a = ap.parse_args(argv)
    tdir = a.topics_dir or os.path.join(a.root, "topics")
    required = parse_sections(a.sections) if a.sections else SECTIONS
    if not required:
        print("--sections names no sections", file=sys.stderr)
        return 2
    if a.stale:
        tasks_path = a.tasks or os.path.join(a.root, "tasks", "log.jsonl")
        if not os.path.exists(tasks_path):
            print(f"no task log at {tasks_path}", file=sys.stderr)
            return 2
        r = stale(tdir, tasks_path, a.task_re, required)
        print(stale_report(r))
        return 1 if any(r.values()) else 0
    text, problems = build(tdir, required)
    out = os.path.join(tdir, "INDEX.md")
    for n, pr in sorted(problems.items()):
        print(f"{n}.md: " + "; ".join(pr), file=sys.stderr)
    if a.check:
        cur = open(out, encoding="utf-8").read() if os.path.exists(out) else None
        if cur != text:
            print("INDEX.md is out of date: run topics_index.py", file=sys.stderr)
        return 1 if problems or cur != text else 0
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"wrote {out} with {len([l for l in text.splitlines() if l.startswith('- ')])} topics")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
