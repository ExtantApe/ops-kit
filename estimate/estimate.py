#!/usr/bin/env python3
"""Estimate: size, payoff and padded cost for open tasks, and the queue they make.

Local only. No network, and it never writes to your task store. It reads pace's readings
(../pace/pace.py, its state folder) to price work in pace's pool units: weekly percent, or dollars
once pace knows usd_per_pct.

  estimate tag T123 --size Days --payoff Major --by NAME   # the only way a task gets a tag
  estimate start T123 --lanes 2                            # note the pool spend at the newest reading
  estimate done T123                                       # spend since start becomes a real cost
  estimate queue [--json] [--limit N] [--suggest]
  estimate show                                            # the cost table and the padding now

Size: Hours (under half a day), Days (half a day to a week), Weeks (a week or more).
Payoff: Major, Moderate, Minor. Together they give the bucket, in work order:
  Steal (Hours, Major), Win (Days, Major), Pickup (Hours, Moderate), Bet (Weeks, Major),
  Routine (Days, Moderate), Filler (Hours, Minor), Investment (Weeks, Moderate),
  Chore (Days, Minor), Parked (Weeks, Minor).

Tags are only ever set by a person (or a session acting for one) with `tag`. An untagged task shows
as "untagged". --suggest prints guesses labelled as suggestions and stores nothing.

Cost: pace's learned per_lane_hour times typical hours (Hours 3, Days 16, Weeks 50), padded 20%.
Each `start` and `done` pair records the real spend between the two readings and updates a
per-size average (EWMA). The padding narrows by one point per sample from 20% toward 10% and
never goes below 10%. A pair is not learned when the pool or unit changed in between.

Where things come from (every path is a flag, with an environment fallback):
  Tasks   --source FILE      rows in status.py's common schema (JSON list or JSON Lines), or
          --task-log FILE    an append-only event log (add, close, reopen, wait, resume, set, block,
                             unblock), or
          --adapter FILE     a Python file with tasks() returning common-schema rows and, optionally,
                             tags() returning {id: {"size": ..., "payoff": ...}}.
          Default: --task-log $ESTIMATE_TASKS, else $OPS_ROOT/tasks/log.jsonl.
  Tags    --tags FILE        a separate tags file of {id, size, payoff, by, at} rows, newest wins. This is
                             the default: <state dir>/estimate-tags.jsonl, and `tag` appends to it.
          --tags-from-log    read tags from the task-log events instead: any `set` event that carries
                             size and payoff, newest wins. `tag` then refuses, because this tool never
                             writes to the log; tag with the tool that owns the log.
          An adapter's tags() is read as well and wins over the file.
  State   --state-dir DIR    estimate-tags.jsonl and estimate-runs.jsonl (default: ESTIMATE_DIR, else
                             PACE_STATE_DIR, else $OPS_ROOT/state, else ./state). Pace's readings
                             are found in the same folder unless PACE_STATE_DIR says otherwise.

Pace sets speed only. It never lifts a gate, and neither does this.
"""
import argparse, importlib.util, json, os, re, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

SIZES = ("Hours", "Days", "Weeks")
PAYOFFS = ("Major", "Moderate", "Minor")
BUCKETS = [("Steal", "Hours", "Major"), ("Win", "Days", "Major"), ("Pickup", "Hours", "Moderate"),
           ("Bet", "Weeks", "Major"), ("Routine", "Days", "Moderate"), ("Filler", "Hours", "Minor"),
           ("Investment", "Weeks", "Moderate"), ("Chore", "Days", "Minor"), ("Parked", "Weeks", "Minor")]
BUCKET_OF = {(s, p): n for n, s, p in BUCKETS}
BUCKET_ORDER = {n: i for i, (n, _, _) in enumerate(BUCKETS)}
HOURS = {"Hours": 3.0, "Days": 16.0, "Weeks": 50.0}
PRIORITY_ORDER = {"now": 0, "next": 1, "soon": 2, "later": 3}
WEIGHT = {"Major": 3.0, "Moderate": 2.0, "Minor": 1.0}
PAD_START, PAD_FLOOR, PAD_STEP = 0.20, 0.10, 0.01
ALPHA = 0.35


def _load_pace():
    path = os.environ.get("ESTIMATE_PACE") or os.path.join(HERE, "..", "pace", "pace.py")
    spec = importlib.util.spec_from_file_location("pace_for_estimate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pace = _load_pace()
NOTICE = pace.NOTICE

# Set by main() from the flags. Module-level so the helpers stay short; main() resets them on every call.
CFG = {}


def root():
    return os.environ.get("OPS_ROOT") or os.getcwd()


def state_dir():
    return (CFG.get("state_dir") or os.environ.get("ESTIMATE_DIR") or os.environ.get("PACE_STATE_DIR")
            or os.path.join(root(), "state"))


def tags_path():
    return CFG.get("tags") or os.path.join(state_dir(), "estimate-tags.jsonl")


def runs_path():
    return os.path.join(state_dir(), "estimate-runs.jsonl")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def read_rows(path):
    """A JSON list or JSON Lines, like status.py reads them."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return json.loads(text) if text.lstrip().startswith("[") else [json.loads(l) for l in text.splitlines() if l.strip()]


def append(path, rec):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")


def natural(task_id):
    """Sort key that puts T2 before T10: letters, then the number."""
    m = re.match(r"^(\D*)(\d+)", str(task_id))
    return (m.group(1), int(m.group(2))) if m else (str(task_id), 0)


def norm_size(v):
    v = (v or "").strip().capitalize()
    return v if v in SIZES else ""


def norm_payoff(v):
    v = (v or "").strip().capitalize()
    return v if v in PAYOFFS else ""


# ---- adapters: tasks and tags ------------------------------------------------------------------------------------

def fold_log(events):
    """Fold an event log into (tasks by id, tags by id). Read-only; unknown ops are ignored."""
    tasks, tags = {}, {}
    for e in events:
        k, op = e.get("id"), e.get("op")
        if not k:
            continue
        if op == "add":
            tasks[k] = dict(id=k, title=e.get("title", ""), priority=e.get("priority", "later"), state="open",
                            category=e.get("category", ""), waiting_on="", blocked="")
            if e.get("size") or e.get("payoff"):
                tags[k] = dict(size=e.get("size", ""), payoff=e.get("payoff", ""))
            continue
        t = tasks.get(k)
        if t is None:
            continue
        if op == "close":
            t["state"] = "closed"
        elif op == "reopen":
            t["state"] = "open"
        elif op == "set":
            for f in ("priority", "category"):
                if f in e:
                    t[f] = e[f]
            if "size" in e or "payoff" in e:
                tags[k] = dict(size=e.get("size", ""), payoff=e.get("payoff", ""))
        elif op == "wait":
            t["priority"], t["waiting_on"], t["blocked"] = "waiting", e.get("on", ""), ""
        elif op == "resume":
            t["priority"], t["waiting_on"], t["blocked"] = "next", "", ""
        elif op == "block":
            t["blocked"] = e.get("reason", "blocked")
        elif op == "unblock":
            t["blocked"] = ""
    return tasks, tags


def from_rows(rows):
    tasks, tags = {}, {}
    for r in rows:
        if not r.get("id"):
            continue
        tasks[r["id"]] = dict(id=r["id"], title=r.get("title", ""), priority=r.get("priority", "later"),
                              state=r.get("state", "open"), category=r.get("category", "") or "",
                              waiting_on=r.get("waiting_on", "") or "", blocked=r.get("blocked", "") or "")
        if r.get("size") or r.get("payoff"):
            tags[r["id"]] = dict(size=r.get("size", ""), payoff=r.get("payoff", ""))
    return tasks, tags


def load_adapter(path):
    if not path.endswith(".py") or not os.path.isfile(path):
        sys.exit(f"estimate: the adapter must be an existing .py file: {path}")
    spec = importlib.util.spec_from_file_location("ops_kit_estimate_adapter", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "tasks"):
        sys.exit(f"estimate: the adapter needs a tasks() function: {path}")
    return mod


def load_store():
    """(tasks by id, tags from the store itself by id). Never writes."""
    if CFG.get("adapter"):
        mod = load_adapter(CFG["adapter"])
        tasks, tags = from_rows(mod.tasks())
        if hasattr(mod, "tags"):
            tags.update({k: v for k, v in mod.tags().items()})
        return tasks, tags
    if CFG.get("source"):
        return from_rows(read_rows(CFG["source"]))
    path = CFG.get("task_log") or os.environ.get("ESTIMATE_TASKS") or os.path.join(root(), "tasks", "log.jsonl")
    return fold_log(read_jsonl(path))


def open_tasks():
    return load_store()[0]


def current_tags():
    """Tags by id: the tags file (unless --tags-from-log), then whatever the store or adapter carries."""
    tasks, from_store = load_store()
    tags = {}
    if not CFG.get("tags_from_log"):
        for t in read_jsonl(tags_path()):
            if t.get("id"):
                tags[t["id"]] = dict(size=t.get("size"), payoff=t.get("payoff"), by=t.get("by"))
    if CFG.get("tags_from_log") or CFG.get("adapter"):
        for k, v in from_store.items():
            tags[k] = dict(v)
    out = {}
    for k, v in tags.items():
        s, p = norm_size(v.get("size")), norm_payoff(v.get("payoff"))
        if s and p:
            out[k] = dict(v, size=s, payoff=p)
    return out


# ---- pace --------------------------------------------------------------------------------------------------------

def pace_view():
    """Newest pace reading and its verdict, or None."""
    h = pace.load(os.path.join(os.environ.get("PACE_STATE_DIR") or state_dir(), "pace.jsonl"))
    if not h:
        return None
    r = h[-1]
    v = pace.verdict(r, h, now=pace.parse_ts(r["at"]))
    return {"reading": r, "v": v}


def stats():
    """Per-size learned averages from finished runs, in the unit of the newest one."""
    done = [r for r in read_jsonl(runs_path()) if r.get("event") == "done" and r.get("learned")]
    out = {}
    unit = done[-1]["unit"] if done else None
    for r in done:
        if r["unit"] != unit:
            continue
        s = out.setdefault(r["size"], {"n": 0, "avg": None, "unit": unit})
        s["avg"] = r["spend"] if s["avg"] is None else ALPHA * r["spend"] + (1 - ALPHA) * s["avg"]
        s["n"] += 1
    return out


def padding(n):
    return max(PAD_FLOOR, PAD_START - PAD_STEP * n)


def cost_table(pv):
    """Padded cost per size in pace's unit, or None values when pace cannot price work yet."""
    st = stats()
    table = {}
    per_lane = pv["v"]["per_lane_hour"] if pv else None
    unit = pv["v"]["unit"] if pv else None
    for size in SIZES:
        s = st.get(size)
        if s and s["avg"] is not None and (unit is None or s["unit"] == unit):
            n, base, src = s["n"], s["avg"], "learned"
        elif per_lane:
            n, base, src = 0, per_lane * HOURS[size], "default"
        else:
            table[size] = {"cost": None, "base": None, "padding": PAD_START, "samples": 0, "source": "unknown", "unit": unit}
            continue
        pad = padding(n)
        table[size] = {"cost": round(base * (1 + pad), 3), "base": round(base, 3), "padding": round(pad, 2),
                       "samples": n, "source": src, "unit": unit or s["unit"]}
    return table


def fmt_cost(c, unit):
    if c is None:
        return "no cost yet"
    return f"${c:,.2f}" if unit == "$" else f"{c:.1f}%"


def suggest(t):
    """Guess only. Printed as a suggestion and never stored."""
    payoff = {"security": "Major", "release": "Major", "feature": "Moderate", "fix": "Moderate"}.get(t["category"], "Minor")
    return "Days", payoff


# ---- commands ----------------------------------------------------------------------------------------------------

def cmd_tag(a):
    if CFG.get("tags_from_log"):
        print("estimate: tags live in your task log (--tags-from-log), and this tool never writes to it. "
              "Tag the task with the tool that owns the log.", file=sys.stderr)
        return 1
    if a.size not in SIZES:
        print(f"size must be one of {', '.join(SIZES)}", file=sys.stderr)
        return 2
    if a.payoff not in PAYOFFS:
        print(f"payoff must be one of {', '.join(PAYOFFS)}", file=sys.stderr)
        return 2
    if a.id not in open_tasks():
        print(f"no task {a.id} in the task store", file=sys.stderr)
        return 1
    append(tags_path(), {"id": a.id, "size": a.size, "payoff": a.payoff, "by": a.by, "at": now_iso()})
    print(f"{a.id}: {a.size}, {a.payoff} = {BUCKET_OF[(a.size, a.payoff)]}")
    return 0


def cmd_start(a):
    if a.id not in open_tasks():
        print(f"no task {a.id} in the task store", file=sys.stderr)
        return 1
    tag = current_tags().get(a.id)
    if not tag:
        print(f"{a.id} is untagged: run estimate tag first", file=sys.stderr)
        return 1
    pv = pace_view()
    if not pv:
        print("no pace reading yet: run pace record first", file=sys.stderr)
        return 1
    v = pv["v"]
    append(runs_path(), {"event": "start", "id": a.id, "size": tag["size"], "lanes": a.lanes, "at": now_iso(),
                         "reading_at": pv["reading"]["at"], "pool": v["pool"], "unit": v["unit"], "used": v["used"]})
    print(f"{a.id} started with {a.lanes} lane(s) at {fmt_cost(v['used'], v['unit'])} used in the {v['pool']} pool.")
    return 0


def cmd_done(a):
    start = None
    for r in read_jsonl(runs_path()):
        if r.get("id") == a.id:
            start = r if r["event"] == "start" else None
    if not start:
        print(f"{a.id} has no open start: run estimate start first", file=sys.stderr)
        return 1
    pv = pace_view()
    if not pv:
        print("no pace reading yet: run pace record first", file=sys.stderr)
        return 1
    v = pv["v"]
    spend = round(v["used"] - start["used"], 3)
    learned = v["pool"] == start["pool"] and v["unit"] == start["unit"] and spend >= 0 \
        and pv["reading"]["at"] != start["reading_at"]
    append(runs_path(), {"event": "done", "id": a.id, "size": start["size"], "lanes": start["lanes"], "at": now_iso(),
                         "reading_at": pv["reading"]["at"], "pool": v["pool"], "unit": v["unit"], "spend": spend,
                         "learned": learned})
    if learned:
        s = stats().get(start["size"])
        print(f"{a.id} done: {fmt_cost(spend, v['unit'])} spent. {start['size']} average is now "
              f"{fmt_cost(s['avg'], v['unit'])} over {s['n']} sample(s), padding {padding(s['n']):.0%}.")
    else:
        print(f"{a.id} done: {fmt_cost(spend, v['unit'])}, not learned (no newer reading, the pool changed or the spend fell).")
    return 0


def row(t, tag, table, pv, left):
    size = tag["size"] if tag else None
    bucket = BUCKET_OF[(tag["size"], tag["payoff"])] if tag else "untagged"
    cost = table[size]["cost"] if tag else None
    unit = pv["v"]["unit"] if pv else None
    fits = None if cost is None or left is None else cost <= left
    value = None if cost in (None, 0) or not tag else round(WEIGHT[tag["payoff"]] / cost, 4)
    return {"id": t["id"], "title": t["title"], "bucket": bucket, "size": size, "payoff": tag["payoff"] if tag else None,
            "priority": t["priority"], "cost": cost, "unit": unit, "fits": fits, "payoff_per_cost": value,
            "waiting_on": t["waiting_on"] or None, "blocked": t["blocked"] or None}


def sort_key(r):
    return (BUCKET_ORDER.get(r["bucket"], 99), PRIORITY_ORDER.get(r["priority"], 9),
            -(r["payoff_per_cost"] or 0), natural(r["id"]))


def cmd_queue(a):
    pv = pace_view()
    table = cost_table(pv)
    left = pv["v"]["left_to_goal"] if pv else None
    tags = current_tags()
    rows, waiting = [], []
    for t in open_tasks().values():
        if t["state"] != "open":
            continue
        r = row(t, tags.get(t["id"]), table, pv, left)
        if t["priority"] == "waiting" or t["blocked"]:
            waiting.append(r)
        else:
            if r["bucket"] == "untagged" and a.suggest:
                s, p = suggest(t)
                r["suggestion"] = {"size": s, "payoff": p, "note": "suggestion only, not set"}
            rows.append(r)
    rows.sort(key=sort_key)
    waiting.sort(key=lambda r: natural(r["id"]))
    total = len(rows)
    if a.limit:
        rows = rows[:a.limit]
    unit = pv["v"]["unit"] if pv else None
    if a.json:
        print(json.dumps({"notice": NOTICE, "pace": None if not pv else {"verdict": pv["v"]["verdict"], "unit": unit,
              "left_to_goal": left}, "costs": table, "queue": rows, "queue_total": total, "waiting": waiting}, sort_keys=True))
        return 0
    if pv:
        print(f"Pace: {pv['v']['verdict']}, {fmt_cost(left, unit)} left to goal.")
    else:
        print("Pace: no readings yet, so no costs and no fit check.")
    for r in rows:
        fit = "fits" if r["fits"] else ("over" if r["fits"] is False else "fit unknown")
        pri = f"[{r['priority']}]"
        print(f"{r['id']:>7}  {r['bucket']:<10} {fmt_cost(r['cost'], unit):>12}  {fit:<11} {pri:<8} {r['title'][:80]}")
        if r.get("suggestion"):
            s = r["suggestion"]
            print(f"         suggestion only: {s['size']}, {s['payoff']} (not set)")
    if total > len(rows):
        print(f"  ... {total - len(rows)} more (raise --limit)")
    if waiting:
        print(f"Waiting or blocked ({len(waiting)}):")
        for r in (waiting[:a.limit] if a.limit else waiting):
            why = f"waiting on {r['waiting_on']}" if r["waiting_on"] else f"blocked: {r['blocked']}"
            print(f"{r['id']:>7}  {r['bucket']:<10} {why[:60]:<60} {r['title'][:60]}")
    print(NOTICE)
    return 0


def cmd_show(a):
    pv = pace_view()
    table = cost_table(pv)
    unit = pv["v"]["unit"] if pv else None
    for size in SIZES:
        t = table[size]
        print(f"{size:<6} {fmt_cost(t['cost'], unit):>12}  {t['source']}, padding {t['padding']:.0%}, {t['samples']} sample(s)")
    print(NOTICE)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", help="task rows in the common schema (JSON list or JSON Lines)")
    ap.add_argument("--task-log", help="an append-only task event log")
    ap.add_argument("--adapter", help="a Python file with tasks() and, optionally, tags()")
    ap.add_argument("--tags", help="the separate tags file (default: <state dir>/estimate-tags.jsonl)")
    ap.add_argument("--tags-from-log", action="store_true", help="read size and payoff from the task store's own events or rows")
    ap.add_argument("--state-dir", help="folder for tags, runs and pace readings")
    sub = ap.add_subparsers(dest="cmd", required=True)
    tg = sub.add_parser("tag")
    tg.add_argument("id")
    tg.add_argument("--size", required=True)
    tg.add_argument("--payoff", required=True)
    tg.add_argument("--by", required=True)
    st = sub.add_parser("start")
    st.add_argument("id")
    st.add_argument("--lanes", type=int, required=True)
    dn = sub.add_parser("done")
    dn.add_argument("id")
    q = sub.add_parser("queue")
    q.add_argument("--json", action="store_true")
    q.add_argument("--limit", type=int, default=0)
    q.add_argument("--suggest", action="store_true", help="print guesses for untagged tasks, labelled as suggestions")
    sub.add_parser("show")
    a = ap.parse_args(argv)
    CFG.clear()
    CFG.update(source=a.source, task_log=a.task_log, adapter=a.adapter, tags=a.tags,
               tags_from_log=a.tags_from_log, state_dir=a.state_dir)
    try:
        return {"tag": cmd_tag, "start": cmd_start, "done": cmd_done, "queue": cmd_queue, "show": cmd_show}[a.cmd](a)
    finally:
        CFG.clear()


if __name__ == "__main__":
    sys.exit(main())
