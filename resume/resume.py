#!/usr/bin/env python3
r"""Resume page: what a session needs to read first after its context was cleared.

  resume.py SESSION [--days 14] [--root DIR] [--today YYYY-MM-DD]

It prints, for one session (matched without regard to case):
  - its open tasks and what each waits on,
  - tasks moved to it that it has not acknowledged yet,
  - decisions from the last --days days that apply to it and that it has not named in a ledger line or a task note,
  - its last 5 ledger lines.
Read-only: it never writes to the store, never calls the network.

Where things are (every path is a flag; OPS_ROOT, else the current folder, is the base):
  --root DIR          the store
  --tasks FILE        the task event log (default ROOT/tasks/log.jsonl)
  --ledger-dir DIR    folder of *.jsonl ledger files (default ROOT/ledger)
  --decisions GLOB    decision files (default ROOT/decisions/*.md)
  --decision-re RE    decision ID pattern (default D\d+)
  --adapter FILE      a Python file that supplies any of these functions, for stores laid out differently:
                        events()     task events, one dict per event
                        ledger()     ledger entries, one dict per line
                        decisions()  dicts with id, title, date (YYYY-MM-DD) and applies (text, may be empty)
                      Anything the adapter leaves out is read from the files above. An adapter runs as Python
                      with your permissions: use only adapters you wrote or have read.

Shared formats
  Task events: {"op": "add", "id", "title", "owner", "area", "priority"} then close, reopen, wait (on, reason),
    resume, set (priority, area), move (to), ack (by), note (text), each with "by" and "ts".
  Ledger lines: {"ts", "session", "type", "summary", "refs": []}.
  Decisions: markdown headings "## D12 Title (2026-11-20)" or "### D12 Title", with an optional
    "Date: 2026-11-20" and "Applies to: every session | a session name | an area" line. A decision with no
    Applies line applies to everyone.
"""
import argparse, glob, importlib.util, json, os, re, sys
from datetime import date, timedelta

DEFAULT_ROOT = os.environ.get("OPS_ROOT") or os.getcwd()


def num(i):
    m = re.match(r"^(\D*)(\d+)", str(i))
    return (m.group(1), int(m.group(2))) if m else (str(i), 0)


def read_jsonl(path):
    out = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return out


def read_ledger(folder):
    out = []
    for p in sorted(glob.glob(os.path.join(folder, "*.jsonl"))):
        out += read_jsonl(p)
    return out


def read_decisions(pattern, did):
    out = []
    for p in sorted(glob.glob(pattern)):
        with open(p, encoding="utf-8") as f:
            text = f.read()
        for part in re.split(r"^(?=#{2,3} " + did + r"\b)", text, flags=re.M):
            m = re.match(r"#{2,3} (" + did + r")\s+(.*)", part)
            if not m:
                continue
            first = m.group(2).split("\n")[0]
            d = re.search(r"\((\d{4}-\d{2}-\d{2})\)\s*$", first) or re.search(r"Date:\s*(\d{4}-\d{2}-\d{2})", part)
            ap = re.search(r"Applies to:\s*(.+)", part)
            out.append(dict(id=m.group(1), title=re.sub(r"\s*\(\d{4}-\d{2}-\d{2}\)\s*$", "", first),
                            date=d.group(1) if d else "", applies=ap.group(1) if ap else ""))
    return out


def load_adapter(path):
    if not path.endswith(".py") or not os.path.isfile(path):
        sys.exit(f"resume: the adapter must be an existing .py file: {path}")
    spec = importlib.util.spec_from_file_location("ops_kit_resume_adapter", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fold(events, who):
    """Fold task events. Also collects the text of this session's own events (for decision acks)."""
    tasks, mine_text = {}, []
    for e in events:
        k, op = e.get("id"), e.get("op")
        if op == "add":
            tasks[k] = dict(id=k, title=e.get("title", ""), owner=e.get("owner", ""), area=e.get("area", ""), state="open",
                            priority=e.get("priority", "later"), on="", why="", pending=None)
        t = tasks.get(k)
        if not t:
            continue
        if op == "close": t["state"] = "closed"
        elif op == "reopen": t["state"] = "open"
        elif op == "wait": t.update(priority="waiting", on=e.get("on", ""), why=e.get("reason", ""))
        elif op == "resume": t.update(priority="next", on="", why="")
        elif op == "set":
            for f in ("priority", "area"):
                if f in e: t[f] = e[f]
        elif op == "move": t["pending"] = e.get("to")
        elif op == "ack": t["owner"], t["pending"] = e.get("by", t["owner"]), None
        if (e.get("by") or "").lower() == who:
            mine_text.append(" ".join(str(e.get(f, "")) for f in ("text", "reason", "refs")))
    return tasks, mine_text


def page(who, events, led, decisions, today, days=14, did=r"D\d+"):
    w = who.strip().lower()
    tasks, mine_text = fold(events, w)
    mine = [t for t in tasks.values() if t["state"] == "open" and t["owner"].lower() == w and not t["pending"]]
    incoming = [t for t in tasks.values() if t["state"] == "open" and (t["pending"] or "").lower() == w]
    areas = {t["area"].lower() for t in mine + incoming if t["area"]}
    order = {"now": 0, "next": 1, "soon": 2, "waiting": 3, "later": 4}
    key = lambda t: (order.get(t["priority"], 5), num(t["id"]))
    L = [f"Resume page: {who}", "", f"Open tasks ({len(mine)}):"]
    for t in sorted(mine, key=key):
        wait = f"  waits on {t['on']}: {t['why'][:80]}" if t["priority"] == "waiting" else ""
        L.append(f"  {t['id']} [{t['priority']}] {t['title'][:80]}{wait}")
    if not mine:
        L.append("  none")
    if incoming:
        L += ["", f"Moved to {who}, waiting for an ack ({len(incoming)}):"]
        L += [f"  {t['id']} {t['title'][:80]}" for t in sorted(incoming, key=key)]

    mine_led = [e for e in led if (e.get("session") or "").lower() == w]
    named = set(re.findall(r"\b" + did + r"\b", " ".join(
        mine_text + [(e.get("summary", "") or "") + " " + " ".join(e.get("refs", []) or []) for e in mine_led])))
    cutoff = (today - timedelta(days=days)).isoformat()
    todo = []
    for d in decisions:
        ap = (d.get("applies") or "all").lower()
        applies = "all" in re.split(r"\W+", ap) or "every" in ap or w in ap or any(a in ap for a in areas)
        if d.get("date") and d["date"] >= cutoff and applies and d["id"] not in named:
            todo.append((d["date"], d["id"], d.get("title", "")))
    L += ["", f"Decisions from the last {days} days that apply to it and it hasn't named in a ledger line or task note ({len(todo)}):"]
    todo.sort(reverse=True)
    L += [f"  {i} ({dt}) {title[:90]}" for dt, i, title in todo[:25]]
    if len(todo) > 25:
        L.append(f"  ...and {len(todo) - 25} more")
    if not todo:
        L.append("  none")
    L += ["", "Last 5 ledger lines:"]
    L += [f"  {e.get('ts', '')}  {str(e.get('type', '')):<10} {(e.get('summary') or '')[:110]}" for e in mine_led[-5:]]
    if not mine_led:
        L.append("  none")
    L += ["", "Read the decisions and acknowledge each one in the ledger."]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--tasks")
    ap.add_argument("--ledger-dir")
    ap.add_argument("--decisions")
    ap.add_argument("--decision-re", default=r"D\d+")
    ap.add_argument("--adapter")
    ap.add_argument("--today")
    a = ap.parse_args(argv)
    mod = load_adapter(a.adapter) if a.adapter else None
    has = lambda n: mod is not None and hasattr(mod, n)
    events = list(mod.events()) if has("events") else read_jsonl(a.tasks or os.path.join(a.root, "tasks", "log.jsonl"))
    led = list(mod.ledger()) if has("ledger") else read_ledger(a.ledger_dir or os.path.join(a.root, "ledger"))
    decs = list(mod.decisions()) if has("decisions") else read_decisions(a.decisions or os.path.join(a.root, "decisions", "*.md"), a.decision_re)
    today = date.fromisoformat(a.today) if a.today else date.today()
    print(page(a.session, events, led, decs, today, a.days, a.decision_re))
    return 0


if __name__ == "__main__":
    sys.exit(main())
