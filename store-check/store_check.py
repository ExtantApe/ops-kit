#!/usr/bin/env python3
r"""Store check: a read-only report on what has gone missing in a work store (spec/store-check.md).

It reads a task event log, decision files, owner-step files, an optional roster and the git logs of
local clones. It never fetches, never calls the network and never changes a file, a task or a ref.
It prints markdown, or JSON with --json.

  store_check.py [--json] [--limit N] [--root DIR] [--code DIR] [--today YYYY-MM-DD]

Where things are (every path is a flag, with OPS_ROOT as the default base):
  --root DIR         the store (default: $OPS_ROOT, else the current folder)
  --tasks FILE       the task event log (default: ROOT/tasks/log.jsonl)
  --decisions GLOB   decision files (default: ROOT/decisions/*.md)
  --steps FILE       an owner-step file, repeatable (default: ROOT/needs-you.md and ROOT/tests.md)
  --roster FILE      a markdown table of sessions: name in column 1, status in column 5 (default: ROOT/roster.md)
  --code DIR         a folder of git clones to scan for task trailers (default: $OPS_CODE; without one, check a is skipped)

IDs are patterns, because every store numbers things its own way:
  --task-re   (default [A-Z]+\d+)   --decision-re (default D\d+)   --step-re (default [NT]\d+)

Checks (numbers are the spec's):
  a  (1) Tasks named by a "Task: ID" trailer in a commit on origin/main or origin/prod that are still open.
  b  (2) Waits that name a retired or closed session, or an owner step that is not listed.
  c  (4) Decisions with no task that mentions them and no "no task needed" note.
  d  (5) Owner steps and tests dated more than 10 days ago.
  e  (7) Open tasks in the same area with near-identical titles.

Decision files use headings like "## D12 Title (2026-11-20)" or "### D12 Title", with an optional
"Date: 2026-11-20" line. Step files use "### N12 [kind] Title (2026-11-20, 5 min)" headings.
--limit caps the decisions listed in the markdown (newest first, default 40; JSON always has all).
"""
import argparse, difflib, glob, json, os, re, subprocess, sys
from datetime import date, datetime, timezone

DEFAULT_ROOT = os.environ.get("OPS_ROOT") or os.getcwd()
DEFAULT_CODE = os.environ.get("OPS_CODE") or None
PATTERNS = {"task": r"[A-Z]+\d+", "decision": r"D\d+", "step": r"[NT]\d+"}
OLD_STEP_DAYS = 10
SIMILAR = 0.86
RETIRED = re.compile(r"^(retired|closed|done|gone)\b", re.I)


def num(i):
    """Sort key for IDs like T2 and T10: letters, then the number."""
    m = re.match(r"^(\D*)(\d+)", str(i))
    return (m.group(1), int(m.group(2))) if m else (str(i), 0)


def read_tasks(path):
    """Fold the task event log (add, close, reopen, wait, resume, set, move), keeping what the checks need."""
    tasks, texts = {}, {}
    if not os.path.exists(path):
        return tasks, texts
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        k, op = e.get("id"), e.get("op")
        if not k:
            continue
        if op == "add":
            tasks[k] = dict(id=k, title=e.get("title", ""), owner=e.get("owner", ""), area=e.get("area", ""),
                            state="open", priority=e.get("priority", "later"), waiting_on="", wait_reason="", added=e.get("ts", ""))
        t = tasks.get(k)
        if t is None:
            continue
        texts.setdefault(k, []).append(" ".join(str(e.get(f, "")) for f in ("title", "source", "text", "reason", "refs", "note")))
        if op == "close": t["state"] = "closed"
        elif op == "reopen": t["state"] = "open"
        elif op == "wait": t.update(priority="waiting", waiting_on=e.get("on", ""), wait_reason=e.get("reason", ""))
        elif op == "resume": t.update(priority="next", waiting_on="", wait_reason="")
        elif op == "set" and "priority" in e: t["priority"] = e["priority"]
        elif op == "move": t["owner"] = e.get("to", t["owner"])
        elif op == "set" and "area" in e: t["area"] = e["area"]
    return tasks, {k: " ".join(v) for k, v in texts.items()}


def roster(p):
    out = {}
    if p and os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            c = [x.strip() for x in line.strip().strip("|").split("|")]
            if len(c) >= 5 and c[0] not in ("Session", "---") and not c[0].startswith("---"):
                out[c[0]] = c[4]
    return out


def steps(paths):
    """Owner steps and tests listed now: id -> (title, first date, file)."""
    out = {}
    for p in paths:
        if not os.path.exists(p):
            continue
        for m in re.finditer(r"^### (" + PATTERNS["step"] + r")\b(.*)$", open(p, encoding="utf-8").read(), re.M):
            d = re.search(r"\((\d{4}-\d{2}-\d{2})", m.group(2))
            out[m.group(1)] = (m.group(2).strip(), d.group(1) if d else None, os.path.basename(p))
    return out


def decisions(pattern):
    out = []
    D = PATTERNS["decision"]
    for p in sorted(glob.glob(pattern)):
        txt = open(p, encoding="utf-8").read()
        parts = re.split(r"^(?=#{2,3} " + D + r"\b)", txt, flags=re.M)
        for part in parts:
            m = re.match(r"#{2,3} (" + D + r")\s+(.*)", part)
            if not m:
                continue
            d = re.search(r"\((\d{4}-\d{2}-\d{2})\)\s*$", m.group(2).split("\n")[0]) or re.search(r"Date:\s*(\d{4}-\d{2}-\d{2})", part)
            title = re.sub(r"\s*\(\d{4}-\d{2}-\d{2}\)\s*$", "", m.group(2).split("\n")[0])
            out.append(dict(id=m.group(1), title=title, date=d.group(1) if d else "",
                            file=os.path.basename(p), no_task_needed=bool(re.search(r"no task needed", part, re.I))))
    return out


def trailer_commits(code):
    """(task id, repo, sha) for commits on origin/prod or origin/main with a Task trailer. Local refs only."""
    hits = []
    if not code:
        return hits
    for gitdir in sorted(glob.glob(os.path.join(code, "*", ".git"))):
        repo = os.path.dirname(gitdir)
        name = os.path.basename(repo)
        refs = [r for r in ("origin/prod", "origin/main") if subprocess.run(
            ["git", "-C", repo, "rev-parse", "--verify", "-q", r + "^{commit}"], capture_output=True).returncode == 0]
        if not refs:
            continue
        r = subprocess.run(["git", "-C", repo, "log", *refs, "--format=%H%x1f%B%x1e"], capture_output=True, text=True)
        if r.returncode:
            continue
        seen = set()
        for rec in r.stdout.split("\x1e"):
            if "\x1f" not in rec:
                continue
            sha, body = rec.strip().split("\x1f", 1)
            if sha in seen:
                continue
            seen.add(sha)
            for line in body.splitlines():
                m = re.match(r"\s*Task:\s*(.+)$", line, re.I)
                if m:
                    for k in re.findall(r"\b" + PATTERNS["task"] + r"\b", m.group(1)):
                        hits.append((k, name, sha))
    return hits


def norm_title(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def run(root, code, today, limit=40, tasks_path=None, decisions_glob=None, step_files=None, roster_path=None):
    tasks_path = tasks_path or os.path.join(root, "tasks", "log.jsonl")
    decisions_glob = decisions_glob or os.path.join(root, "decisions", "*.md")
    step_files = step_files or [os.path.join(root, "needs-you.md"), os.path.join(root, "tests.md")]
    roster_path = roster_path or os.path.join(root, "roster.md")
    tasks, texts = read_tasks(tasks_path)
    opens = {k: t for k, t in tasks.items() if t["state"] == "open"}
    report = {"generated": today.isoformat(), "open_tasks": len(opens)}

    seen = {}
    for k, repo, sha in trailer_commits(code):
        if k in opens and k not in seen:
            seen[k] = {"task": k, "title": opens[k]["title"], "repo": repo, "sha": sha[:10]}
    report["a_shipped_but_open"] = sorted(seen.values(), key=lambda x: num(x["task"]))

    ros, st = roster(roster_path), steps(step_files)
    bad = []
    for k, t in opens.items():
        if t["priority"] != "waiting":
            continue
        who, why = t["waiting_on"], t["wait_reason"]
        for name, status in ros.items():
            if RETIRED.match(status) and who.strip().lower() == name.lower():
                bad.append({"task": k, "title": t["title"], "problem": f"waits on {name}, which is {status}"})
        for sid in sorted(set(re.findall(r"\b" + PATTERNS["step"] + r"\b", who + " " + why))):
            if sid not in st:
                bad.append({"task": k, "title": t["title"], "problem": f"waits on {sid}, which is not in the owner-step files"})
    report["b_bad_waits"] = sorted(bad, key=lambda x: num(x["task"]))

    ds = decisions(decisions_glob)
    nodtask = []
    for d in ds:
        pat = re.compile(r"\b" + re.escape(d["id"]) + r"\b")
        linked = sorted(k for k, tx in texts.items() if pat.search(tx))
        if not linked and not d["no_task_needed"]:
            nodtask.append({"decision": d["id"], "title": d["title"], "date": d["date"]})
    nodtask.sort(key=lambda x: (x["date"], num(x["decision"])), reverse=True)
    report["c_decisions_without_task"] = nodtask
    report["decisions_checked"] = len(ds)

    old = []
    for sid, (title, d, f) in st.items():
        if d:
            age = (today - date.fromisoformat(d)).days
            if age > OLD_STEP_DAYS:
                old.append({"step": sid, "title": title, "dated": d, "days": age})
    report["d_old_steps"] = sorted(old, key=lambda x: -x["days"])

    dup = []
    by_area = {}
    for t in opens.values():
        by_area.setdefault(t["area"], []).append(t)
    for area, ts in by_area.items():
        ts = sorted(ts, key=lambda t: num(t["id"]))
        nt = [(t, norm_title(t["title"])) for t in ts]
        for i in range(len(nt)):
            for j in range(i + 1, len(nt)):
                a, b = nt[i][1], nt[j][1]
                if not a or not b or abs(len(a) - len(b)) > 0.3 * max(len(a), len(b)):
                    continue
                r = difflib.SequenceMatcher(None, a, b).ratio()
                if r >= SIMILAR:
                    dup.append({"area": area, "tasks": [nt[i][0]["id"], nt[j][0]["id"]], "titles": [nt[i][0]["title"], nt[j][0]["title"]], "similarity": round(r, 2)})
    report["e_near_duplicates"] = sorted(dup, key=lambda x: (x["area"], num(x["tasks"][0])))
    return report


def short(s, n=90):
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[: n - 1].rstrip() + "..."


def markdown(r, limit):
    L = [f"# Store check, {r['generated']}", "", f"Read-only. {r['open_tasks']} open tasks, {r['decisions_checked']} decisions. Nothing was changed.", ""]
    def sec(title, rows, fmt, cap=None):
        L.append(f"## {title} ({len(rows)})")
        L.append("")
        if not rows:
            L.append("None.")
        for x in rows[:cap]:
            L.append("- " + fmt(x))
        if cap and len(rows) > cap:
            L.append(f"- ...and {len(rows) - cap} more (use --json for all)")
        L.append("")
    sec("a. Merged with a Task trailer, still open", r["a_shipped_but_open"], lambda x: f"{x['task']} {short(x['title'])} ({x['repo']} {x['sha']})")
    sec("b. Waits that name something gone", r["b_bad_waits"], lambda x: f"{x['task']} {short(x['title'], 60)}: {x['problem']}")
    sec("c. Decisions with no task and no note", r["c_decisions_without_task"], lambda x: f"{x['decision']} {short(x['title'], 70)} ({x['date'] or 'undated'})", limit)
    sec(f"d. Owner steps older than {OLD_STEP_DAYS} days", r["d_old_steps"], lambda x: f"{x['step']} {short(x['title'], 70)}: {x['days']} days")
    sec("e. Open tasks with near-identical titles", r["e_near_duplicates"], lambda x: f"{x['area']}: {x['tasks'][0]} and {x['tasks'][1]} ({x['similarity']:.0%}): {short(x['titles'][0], 70)}")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--code", default=DEFAULT_CODE)
    ap.add_argument("--today")
    ap.add_argument("--tasks")
    ap.add_argument("--decisions")
    ap.add_argument("--steps", action="append")
    ap.add_argument("--roster")
    ap.add_argument("--task-re", default=PATTERNS["task"])
    ap.add_argument("--decision-re", default=PATTERNS["decision"])
    ap.add_argument("--step-re", default=PATTERNS["step"])
    a = ap.parse_args(argv)
    PATTERNS.update(task=a.task_re, decision=a.decision_re, step=a.step_re)
    today = date.fromisoformat(a.today) if a.today else datetime.now(timezone.utc).date()
    r = run(a.root, a.code, today, a.limit, a.tasks, a.decisions, a.steps, a.roster)
    print(json.dumps(r, sort_keys=True, indent=1) if a.json else markdown(r, a.limit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
