#!/usr/bin/env python3
"""Tests for estimate/estimate.py. Run: python3 estimate/tests/test_estimate.py
Temp state, a fake task log and fake pace readings, all removed at the end, and checked for leftovers."""
import hashlib, importlib.util, json, os, shutil, sys, tempfile
from io import StringIO

here = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp(prefix="estimate-test-")
os.environ["PACE_STATE_DIR"] = os.path.join(tmp, "pace")
os.environ["ESTIMATE_DIR"] = os.path.join(tmp, "est")
os.environ["ESTIMATE_TASKS"] = os.path.join(tmp, "log.jsonl")
os.environ.pop("OPS_ROOT", None)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

pace = load("pace_t", os.path.join(here, "..", "..", "pace", "pace.py"))
est = load("estimate_t", os.path.join(here, "..", "estimate.py"))
cwd_before = sorted(os.listdir(os.getcwd()))

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FAIL ") + name)
    fails += 0 if cond else 1

def run(*args, tool=None):
    tool = tool or est
    old, olderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = StringIO(), StringIO()
    try:
        rc = tool.main(list(args))
        return rc, sys.stdout.getvalue(), sys.stderr.getvalue()
    except SystemExit as e:
        return e.code, sys.stdout.getvalue(), sys.stderr.getvalue()
    finally:
        sys.stdout, sys.stderr = old, olderr

def rec(args):
    run(*args, tool=pace)

def queue():
    rc, out, _ = run("queue", "--json")
    return json.loads(out)

def snapshot(path):
    h = hashlib.sha256()
    for d, _, fs in sorted(os.walk(path)):
        for f in sorted(fs):
            if f == "__pycache__":
                continue
            h.update(open(os.path.join(d, f), "rb").read())
    return h.hexdigest()

def add(log, k, pri, cat="ops", title=None):
    log.append({"op": "add", "id": k, "by": "t", "owner": "t", "area": "a", "title": title or f"Task {k}",
                "source": "s", "priority": pri, "category": cat, "ts": "2026-11-22T00:00:00+00:00"})

def op(log, k, name, **kw):
    log.append(dict({"op": name, "id": k, "by": "t", "ts": "2026-11-22T01:00:00+00:00"}, **kw))

def write_log(log):
    prev = "0" * 64
    with open(os.environ["ESTIMATE_TASKS"], "w") as f:
        for e in log:
            e = dict(e, prev=prev)
            e["hash"] = hashlib.sha256(json.dumps({k: v for k, v in e.items() if k != "hash"}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            prev = e["hash"]
            f.write(json.dumps(e) + "\n")

try:
    R = "2026-11-30T18:00:00Z"
    # pace: weekly pool, 1 lane burns 1% an hour, so per_lane_hour = 1.0
    rec(["record", "--weekly", "30", "--reset", R, "--at", "2026-11-23T18:00:00Z", "--lanes", "1"])
    rec(["record", "--weekly", "31", "--reset", R, "--at", "2026-11-23T19:00:00Z", "--lanes", "1"])

    log = []
    add(log, "K1", "later"); add(log, "K2", "now"); add(log, "K3", "next"); add(log, "K4", "now")
    add(log, "K5", "now"); add(log, "K6", "now"); add(log, "K7", "soon"); add(log, "K8", "next")
    add(log, "K9", "now"); add(log, "K10", "now")
    op(log, "K9", "close", refs=["x"])
    op(log, "K10", "wait", on="owner", reason="r")
    op(log, "K8", "block", reason="stuck")
    write_log(log)
    task_before = open(os.environ["ESTIMATE_TASKS"], "rb").read()

    # tagging
    rc, out, _ = run("tag", "K1", "--size", "Weeks", "--payoff", "Minor", "--by", "tester")
    check("tag prints the bucket", rc == 0 and "Parked" in out)
    check("unknown size is refused", run("tag", "K2", "--size", "Years", "--payoff", "Major", "--by", "t")[0] == 2)
    check("unknown payoff is refused", run("tag", "K2", "--size", "Days", "--payoff", "Huge", "--by", "t")[0] == 2)
    check("unknown task is refused", run("tag", "K999", "--size", "Days", "--payoff", "Major", "--by", "t")[0] == 1)
    check("refused tags are not stored", len(est.read_jsonl(est.tags_path())) == 1)
    run("tag", "K2", "--size", "Hours", "--payoff", "Major", "--by", "t")     # Steal
    run("tag", "K3", "--size", "Days", "--payoff", "Major", "--by", "t")      # Win
    run("tag", "K4", "--size", "Hours", "--payoff", "Moderate", "--by", "t")  # Pickup
    run("tag", "K5", "--size", "Weeks", "--payoff", "Major", "--by", "t")     # Bet
    run("tag", "K6", "--size", "Days", "--payoff", "Major", "--by", "t")      # Win, now beats K3 (next)
    run("tag", "K7", "--size", "Days", "--payoff", "Minor", "--by", "t")      # Chore
    run("tag", "K5", "--size", "Hours", "--payoff", "Major", "--by", "t")     # retag: newest wins -> Steal
    q = queue()
    ids = [r["id"] for r in q["queue"]]
    b = {r["id"]: r["bucket"] for r in q["queue"]}
    check("newest tag wins", b["K5"] == "Steal")
    check("Steal first, both now, lower id first", ids[:2] == ["K2", "K5"])
    check("Win: now before next", ids[2:4] == ["K6", "K3"])
    check("bucket order continues Pickup, Chore, Parked", ids[4:7] == ["K4", "K7", "K1"])
    check("closed task is left out", "K9" not in ids)
    check("waiting task is shown apart", {r["id"] for r in q["waiting"]} == {"K8", "K10"})
    check("waiting task is not in the queue", "K8" not in ids and "K10" not in ids)
    check("notice is in the JSON", "never lifts a gate" in q["notice"])
    rc, out, _ = run("queue")
    check("notice is in the text", "never lifts a gate" in out)
    check("limit trims the queue", len(json.loads(run("queue", "--json", "--limit", "2")[1])["queue"]) == 2)
    # untagged and suggestions
    add(log, "K11", "now", "security"); write_log(log)
    task_before = open(os.environ["ESTIMATE_TASKS"], "rb").read()
    q = queue()
    r11 = [r for r in q["queue"] if r["id"] == "K11"][0]
    check("untagged shows as untagged, last", r11["bucket"] == "untagged" and q["queue"][-1]["id"] == "K11")
    check("no suggestion unless asked", "suggestion" not in r11)
    q = json.loads(run("queue", "--json", "--suggest")[1])
    r11 = [r for r in q["queue"] if r["id"] == "K11"][0]
    check("suggestion is labelled and not stored", "suggestion only" in r11["suggestion"]["note"] and "K11" not in est.current_tags())
    # cost and fit
    pv = est.pace_view()
    per = pv["v"]["per_lane_hour"]
    check("pace learned 1.0 per lane hour", per == 1.0)
    t = est.cost_table(pv)
    check("default Hours cost is 3h at 20% padding", abs(t["Hours"]["cost"] - 3.6) < 0.01)
    check("default Weeks cost is 50h at 20% padding", abs(t["Weeks"]["cost"] - 60.0) < 0.01)
    q = queue()
    check("a cost under left_to_goal fits", [r for r in q["queue"] if r["id"] == "K2"][0]["fits"] is True)
    check("a cost over left_to_goal does not fit", [r for r in q["queue"] if r["id"] == "K1"][0]["fits"] is False)
    # learning: Hours task spends 2% between two readings
    check("start refuses an untagged task", run("start", "K11", "--lanes", "1")[0] == 1)
    check("done refuses without a start", run("done", "K2")[0] == 1)
    rec(["record", "--weekly", "32", "--reset", R, "--at", "2026-11-23T20:00:00Z", "--lanes", "1"])
    run("start", "K2", "--lanes", "1")
    check("done with no newer reading is not learned", "not learned" in run("done", "K2")[1])
    run("start", "K2", "--lanes", "1")
    rec(["record", "--weekly", "34", "--reset", R, "--at", "2026-11-23T21:00:00Z", "--lanes", "1"])
    rc, out, _ = run("done", "K2")
    st = est.stats()
    check("spend between readings is learned", rc == 0 and abs(st["Hours"]["avg"] - 2.0) < 0.01 and st["Hours"]["n"] == 1)
    check("one sample narrows padding to 19%", abs(est.cost_table(est.pace_view())["Hours"]["cost"] - 2.0 * 1.19) < 0.01)
    # EWMA and padding floor
    for i in range(15):
        a = f"2026-11-24T{i:02d}:00:00Z"
        rec(["record", "--weekly", str(35 + i * 0.1), "--reset", R, "--at", a, "--lanes", "1"])
        run("start", "K2", "--lanes", "1")
        rec(["record", "--weekly", str(36.1 + i * 0.1), "--reset", R, "--at", a.replace(":00:00", ":30:00"), "--lanes", "1"])
        run("done", "K2")
    st = est.stats()["Hours"]
    check("EWMA moves toward new samples", 1.0 < st["avg"] < 2.0)
    check("padding never goes below 10%", est.padding(st["n"]) == 0.10 and est.padding(1000) == 0.10)
    check("padding starts at 20%", est.padding(0) == 0.20)
    # unit change is not learned
    n_before = len(est.read_jsonl(est.runs_path()))
    run("start", "K3", "--lanes", "1")
    rec(["record", "--weekly", "100", "--reset", R, "--spent", "10", "--cap", "100", "--base", "0", "--at", "2026-11-25T00:00:00Z", "--lanes", "1"])
    out = run("done", "K3")[1]
    check("a pool change is not learned", "not learned" in out)
    # the real store is untouched
    check("task log untouched by every command", open(os.environ["ESTIMATE_TASKS"], "rb").read() == task_before)
    check("tags and runs live only in the temp dir", est.tags_path().startswith(tmp) and est.runs_path().startswith(tmp))
    check("nothing was written to the working folder", sorted(os.listdir(os.getcwd())) == cwd_before)
    # adapters: tags kept in the task-log events themselves
    log2 = list(log)
    op(log2, "K2", "set", size="Weeks", payoff="Minor")
    op(log2, "K1", "set", size="hours", payoff="major")
    write_log(log2)
    task_before2 = open(os.environ["ESTIMATE_TASKS"], "rb").read()
    def qj(*extra):
        rc, out, err = run(*extra, "queue", "--json")
        return rc, (json.loads(out) if out.strip() else None), err
    rc, q2, _ = qj("--tags-from-log")
    b2 = {r["id"]: r["bucket"] for r in q2["queue"]}
    check("tags-from-log reads size and payoff from set events", b2["K2"] == "Parked" and b2["K1"] == "Steal")
    check("tags-from-log ignores the separate tags file", b2["K3"] == "untagged")
    tags_bytes = open(est.tags_path(), "rb").read()
    rc, _, err = run("--tags-from-log", "tag", "K3", "--size", "Days", "--payoff", "Major", "--by", "t")
    check("tag refuses when tags live in the log", rc == 1 and "never writes" in err)
    check("a refused tag changes neither the log nor the tags file", open(os.environ["ESTIMATE_TASKS"], "rb").read() == task_before2
          and open(est.tags_path(), "rb").read() == tags_bytes)
    rc, q3, _ = qj()
    check("the default layout still reads the separate file", {r["id"]: r["bucket"] for r in q3["queue"]}["K2"] == "Steal")
    # --source: common-schema rows, and a --tags file elsewhere
    rows_path = os.path.join(tmp, "rows.jsonl")
    with open(rows_path, "w") as f:
        f.write(json.dumps(dict(id="X1", title="Row one", priority="now", state="open", size="days", payoff="major")) + "\n")
        f.write(json.dumps(dict(id="X2", title="Row two", priority="next", state="open")) + "\n")
        f.write(json.dumps(dict(id="X3", title="Row three", priority="now", state="closed")) + "\n")
    tags_file = os.path.join(tmp, "my-tags.jsonl")
    with open(tags_file, "w") as f:
        f.write(json.dumps(dict(id="X2", size="Hours", payoff="Major")) + "\n")
    rc, q4, _ = qj("--source", rows_path, "--tags", tags_file)
    b4 = {r["id"]: r["bucket"] for r in q4["queue"]}
    check("--source rows come in with no log at all", set(b4) == {"X1", "X2"})
    check("--tags names another tags file", b4["X2"] == "Steal")
    rc, q5, _ = qj("--source", rows_path, "--tags-from-log")
    b5 = {r["id"]: r["bucket"] for r in q5["queue"]}
    check("tags-from-log also reads size and payoff from source rows", b5["X1"] == "Win" and b5["X2"] == "untagged")
    # --adapter: a Python file with tasks() and tags()
    adapter = os.path.join(tmp, "adapter.py")
    with open(adapter, "w") as f:
        f.write("def tasks():\n    return [dict(id='A1', title='Adapter task', priority='now', state='open'),"
                " dict(id='A10', title='Later one', priority='now', state='open')]\n"
                "def tags():\n    return {'A1': {'size': 'Hours', 'payoff': 'Moderate'}, 'A10': {'size': 'Hours', 'payoff': 'Moderate'}}\n")
    rc, q6, _ = qj("--adapter", adapter)
    check("an adapter supplies tasks and tags", [r["id"] for r in q6["queue"]] == ["A1", "A10"] and q6["queue"][0]["bucket"] == "Pickup")
    check("ids sort as numbers, not text", est.natural("T2") < est.natural("T10"))
    rc, _, err = run("--adapter", os.path.join(tmp, "nope.txt"), "queue")
    check("an adapter must be an existing .py file", rc not in (0, None))
    check("every adapter command left the log alone", open(os.environ["ESTIMATE_TASKS"], "rb").read() == task_before2)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
    check("nothing left in the working folder", sorted(os.listdir(os.getcwd())) == cwd_before)
    check("temp folder removed", not os.path.exists(tmp))

print(f"\n{fails} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
