#!/usr/bin/env python3
"""Tests for store-check/store_check.py. Run: python3 store-check/tests/test_store_check.py
Builds a throwaway store and clone in a temp folder, removes it, and checks nothing was left behind."""
import importlib.util, json, os, shutil, subprocess, sys, tempfile
from datetime import date

here = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(here, "..", "store_check.py")
spec = importlib.util.spec_from_file_location("store_check", SCRIPT)
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)
cwd_before = sorted(os.listdir(os.getcwd()))

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FAIL ") + name)
    fails += 0 if cond else 1

tmp = tempfile.mkdtemp(prefix="store-check-test-")
try:
    ops, code = os.path.join(tmp, "ops"), os.path.join(tmp, "code")
    os.makedirs(os.path.join(ops, "tasks")); os.makedirs(os.path.join(ops, "decisions")); os.makedirs(code)
    ts = "2026-11-20T00:00:00+00:00"
    def add(i, title, area="web", owner="Alpha"):
        return dict(op="add", id=i, by="x", owner=owner, area=area, title=title, source="s", ts=ts)
    log = [
        add("K1", "Ship the widget"), add("K2", "Ship the widget thing"), add("K3", "Closed one"),
        add("K4", "Waits on a retired session"), add("K5", "Waits on a step that is gone"),
        add("K6", "Waits on a live step"), add("K7", "Fix the zebra importer for tortoise lineage data", area="web"),
        add("K8", "Fix the zebra importer for tortoise lineage data now", area="web"),
        add("K9", "Fix the zebra importer for tortoise lineage data", area="other"),
        dict(op="close", id="K3", by="x", ts=ts),
        dict(op="wait", id="K4", by="x", on="Old Helper", reason="needs review", ts=ts),
        dict(op="wait", id="K5", by="x", on="owner", reason="N99: owner does it", ts=ts),
        dict(op="wait", id="K6", by="x", on="owner", reason="N10: owner does it", ts=ts),
        dict(op="note", id="K1", by="x", text="covers D2", ts=ts),
    ]
    open(os.path.join(ops, "tasks", "log.jsonl"), "w").write("\n".join(json.dumps(e) for e in log) + "\n")
    open(os.path.join(ops, "roster.md"), "w").write(
        "| Session | Role | Area | Where | Status | Notes |\n| --- | --- | --- | --- | --- | --- |\n"
        "| Alpha | lead | web | desktop | active | |\n| Old Helper | helper | web | desktop | retired 2026-11-14 | |\n")
    open(os.path.join(ops, "needs-you.md"), "w").write(
        "# Needs you\n\n### N10 [command] Fresh step (2026-11-22, 5 min)\nSteps.\n\n### N11 [setup] Stale step (2026-11-01, 5 min)\nSteps.\n")
    open(os.path.join(ops, "tests.md"), "w").write("# To test\n\n### T5 [test] Old test (2026-11-05)\nSteps.\n")
    open(os.path.join(ops, "decisions", "all.md"), "w").write(
        "# Decisions\n\n## D1 Has no task\nDate: 2026-11-10 | Area: all\n\nBody.\n\n"
        "## D2 Has a task\nDate: 2026-11-11 | Area: all\n\nBody.\n\n"
        "### D3 Exempt (2026-11-12)\n- Means: no task needed, it is a rule only.\n\n"
        "### D4 Newer without a task (2026-11-13)\n- Means: something.\n")

    # a clone with a Task trailer on origin/main, plus one with a commit not on origin
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    def git(repo, *a):
        return subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, text=True, env=env).stdout.strip()
    repo = os.path.join(code, "clone-a")
    os.makedirs(repo)
    git(repo, "init", "-q", "-b", "main")
    open(os.path.join(repo, "f"), "w").write("1")
    git(repo, "add", "f")
    git(repo, "commit", "-q", "-m", "Ship the widget\n\nTask: K1, K3\n")
    sha = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    open(os.path.join(repo, "f"), "w").write("2")
    git(repo, "commit", "-q", "-am", "Local only\n\nTask: K6\n")   # not on origin/main: must not count
    head_before = git(repo, "rev-parse", "HEAD")

    snapshot = {p: open(p, "rb").read() for p in [os.path.join(ops, "tasks", "log.jsonl"), os.path.join(ops, "needs-you.md")]}
    today = date(2026, 11, 23)
    r = sc.run(ops, code, today)

    a = {x["task"]: x for x in r["a_shipped_but_open"]}
    check("a: an open task named by a trailer on origin/main is flagged with its SHA", "K1" in a and sha.startswith(a["K1"]["sha"]))
    check("a: a closed task is not flagged", "K3" not in a)
    check("a: a commit that is only local is not counted", "K6" not in a)
    b = {(x["task"], x["problem"]) for x in r["b_bad_waits"]}
    check("b: a wait on a retired session is flagged", any(t == "K4" and "retired" in p for t, p in b))
    check("b: a wait on a missing N step is flagged", any(t == "K5" and "N99" in p for t, p in b))
    check("b: a wait on a step that exists is not flagged", not any(t == "K6" for t, _ in b))
    c = {x["decision"] for x in r["c_decisions_without_task"]}
    check("c: a decision with no task is flagged", "D1" in c and "D4" in c)
    check("c: a decision a task mentions is not flagged", "D2" not in c)
    check("c: a decision with a no-task-needed note is not flagged", "D3" not in c)
    check("c: newest decisions come first", [x["decision"] for x in r["c_decisions_without_task"]][0] == "D4")
    d = {x["step"]: x["days"] for x in r["d_old_steps"]}
    check("d: steps and tests over 10 days old are flagged", d.get("N11") == 22 and d.get("T5") == 18)
    check("d: a fresh step is not flagged", "N10" not in d)
    e = [tuple(x["tasks"]) for x in r["e_near_duplicates"]]
    check("e: near-identical titles in one area are flagged", ("K7", "K8") in e)
    check("e: the same title in another area is not a duplicate", not any("K9" in t for t in e))
    check("e: different titles are not duplicates", ("K1", "K2") not in e)
    md = sc.markdown(r, 40)
    check("markdown lists each section", all(s in md for s in ("## a.", "## b.", "## c.", "## d.", "## e.")))
    check("markdown says nothing was changed", "Nothing was changed" in md)
    out = subprocess.run([sys.executable, SCRIPT, "--json", "--root", ops, "--code", code, "--today", "2026-11-23"],
                         capture_output=True, text=True)
    check("--json prints parseable JSON with every section", out.returncode == 0 and set(json.loads(out.stdout)) >= {"a_shipped_but_open", "b_bad_waits", "c_decisions_without_task", "d_old_steps", "e_near_duplicates"})
    check("it changed no store file", all(open(p, "rb").read() == v for p, v in snapshot.items()))
    check("it changed no git ref", git(repo, "rev-parse", "HEAD") == head_before)
    # every path is configurable: a store laid out differently, other ID shapes, no code folder at all
    alt = os.path.join(tmp, "alt")
    os.makedirs(alt)
    open(os.path.join(alt, "events.jsonl"), "w").write("\n".join(json.dumps(e) for e in [
        dict(op="add", id="PRJ-7", by="x", owner="Z", area="w", title="Alt task", ts=ts),
        dict(op="wait", id="PRJ-7", by="x", on="owner", reason="S-3 is gone", ts=ts)]) + "\n")
    open(os.path.join(alt, "choices.md"), "w").write("## ADR-5 Alt decision (2026-11-12)\nBody.\n")
    open(os.path.join(alt, "todo.md"), "w").write("### S-9 Old thing (2026-10-01)\nSteps.\n")
    out = subprocess.run([sys.executable, SCRIPT, "--json", "--root", alt, "--tasks", os.path.join(alt, "events.jsonl"),
                          "--decisions", os.path.join(alt, "choices.md"), "--steps", os.path.join(alt, "todo.md"),
                          "--task-re", r"PRJ-\d+", "--decision-re", r"ADR-\d+", "--step-re", r"S-\d+", "--today", "2026-11-23"],
                         capture_output=True, text=True, env=dict(os.environ, OPS_ROOT="", OPS_CODE=""))
    j = json.loads(out.stdout) if out.returncode == 0 else {}
    check("flags point it at another layout", out.returncode == 0 and j.get("open_tasks") == 1)
    check("custom step IDs are understood", [x["step"] for x in j.get("d_old_steps", [])] == ["S-9"])
    check("a wait on an unlisted custom step is flagged", any("S-3" in x["problem"] for x in j.get("b_bad_waits", [])))
    check("custom decision IDs are understood", [x["decision"] for x in j.get("c_decisions_without_task", [])] == ["ADR-5"])
    check("with no code folder, check a is empty", j.get("a_shipped_but_open") == [])
    check("natural ID order puts T2 before T10", sc.num("T2") < sc.num("T10"))
finally:
    shutil.rmtree(tmp)
    check("nothing left in the working folder", sorted(os.listdir(os.getcwd())) == cwd_before)
    check("test removed its temp folder", not os.path.exists(tmp))
sys.exit(1 if fails else 0)
