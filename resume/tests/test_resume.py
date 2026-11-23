#!/usr/bin/env python3
"""Tests for resume/resume.py. Run: python3 resume/tests/test_resume.py
Builds a throwaway store in a temp folder, removes it, and checks nothing was left behind."""
import json, os, shutil, subprocess, sys, tempfile
from datetime import date, timedelta

here = os.path.dirname(os.path.abspath(__file__))
script = os.path.join(here, "..", "resume.py")
cwd_before = sorted(os.listdir(os.getcwd()))
fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FAIL ") + name)
    fails += 0 if cond else 1

tmp = tempfile.mkdtemp(prefix="resume-test-")
try:
    for d in ("tasks", "decisions", "ledger"):
        os.makedirs(os.path.join(tmp, d))
    ts = "2026-11-20T00:00:00+00:00"
    log = [
        dict(op="add", id="K1", by="x", owner="Alpha", area="web", title="Alpha open now", source="s", priority="now", ts=ts),
        dict(op="add", id="K2", by="x", owner="Alpha", area="web", title="Alpha waits", source="s", ts=ts),
        dict(op="wait", id="K2", by="Alpha", on="owner", reason="N7: owner decides", ts=ts),
        dict(op="add", id="K3", by="x", owner="Alpha", area="web", title="Alpha closed", source="s", ts=ts),
        dict(op="close", id="K3", by="Alpha", ts=ts),
        dict(op="add", id="K4", by="x", owner="Beta", area="web", title="Beta's task", source="s", ts=ts),
        dict(op="add", id="K5", by="x", owner="Beta", area="web", title="Moved to Alpha", source="s", ts=ts),
        dict(op="move", id="K5", by="Beta", to="Alpha", reason="r", ts=ts),
        dict(op="note", id="K1", by="Alpha", text="D102 applied", ts=ts),
    ]
    open(os.path.join(tmp, "tasks", "log.jsonl"), "w").write("\n".join(json.dumps(e) for e in log) + "\n")
    recent = (date.today() - timedelta(days=2)).isoformat()
    old = (date.today() - timedelta(days=60)).isoformat()
    open(os.path.join(tmp, "decisions", "all.md"), "w").write(
        f"## D101 Fresh and unacked\nDate: {recent} | Area: all | Applies to: every session.\n\n"
        f"## D102 Fresh but acked in a task note\nDate: {recent} | Area: all | Applies to: every session.\n\n"
        f"## D103 Fresh and acked in the ledger\nDate: {recent} | Area: all | Applies to: every session.\n\n"
        f"## D104 Old\nDate: {old} | Area: all | Applies to: every session.\n\n"
        f"### D105 Other session only ({recent})\n- Applies to: Beta.\n")
    led = [dict(ts=f"2026-11-{10 + i:02d}T00:00:00Z", session="Alpha", type="report", summary=f"entry {i}" + (" D103 applied" if i == 0 else ""), refs=[]) for i in range(7)]
    led.append(dict(ts="2026-11-21T00:00:00Z", session="Beta", type="report", summary="beta entry", refs=[]))
    open(os.path.join(tmp, "ledger", "2026-11.jsonl"), "w").write("\n".join(json.dumps(e) for e in led) + "\n")
    before = {p: open(p, "rb").read() for p in (os.path.join(tmp, "tasks", "log.jsonl"), os.path.join(tmp, "ledger", "2026-11.jsonl"))}

    out = subprocess.run([sys.executable, script, "alpha", "--root", tmp], capture_output=True, text=True)
    o = out.stdout
    check("it runs", out.returncode == 0)
    check("name matches without regard to case", o.startswith("Resume page: alpha"))
    check("lists the session's open tasks", "K1 [now]" in o and "K2 [waiting]" in o)
    check("shows what a waiting task waits on", "waits on owner: N7: owner decides" in o)
    check("leaves out closed tasks and other sessions' tasks", "K3" not in o and "K4" not in o)
    check("lists a task moved to it as awaiting an ack", "waiting for an ack" in o and "K5" in o)
    check("lists a recent decision it has not named", "D101" in o)
    check("skips a decision named in its task note", "D102" not in o)
    check("skips a decision named in its ledger line", "D103" not in o)
    check("skips decisions older than the window", "D104" not in o)
    check("skips decisions for another session", "D105" not in o)
    check("shows its last 5 ledger lines only", "entry 6" in o and "entry 2" in o and "entry 1" not in o and "beta entry" not in o)
    check("it changed nothing", all(open(p, "rb").read() == v for p, v in before.items()))
    out = subprocess.run([sys.executable, script, "nobody", "--root", tmp], capture_output=True, text=True)
    check("an unknown session gets a page with 'none' lines", out.returncode == 0 and "Open tasks (0)" in out.stdout)
    # a different layout through flags, and through an adapter
    alt = os.path.join(tmp, "alt"); os.makedirs(alt)
    shutil.copy(os.path.join(tmp, "tasks", "log.jsonl"), os.path.join(alt, "events.jsonl"))
    out = subprocess.run([sys.executable, script, "alpha", "--tasks", os.path.join(alt, "events.jsonl"), "--root", os.path.join(tmp, "nowhere")],
                         capture_output=True, text=True)
    check("--tasks points at another log", "K1 [now]" in out.stdout and "D101" not in out.stdout)
    adapter = os.path.join(alt, "adapter.py")
    open(adapter, "w").write("def decisions():\n    return [dict(id='D7', title='From the adapter', date='%s', applies='every session')]\n" % recent)
    out = subprocess.run([sys.executable, script, "alpha", "--root", tmp, "--adapter", adapter], capture_output=True, text=True)
    check("an adapter can supply decisions", "D7" in out.stdout and "From the adapter" in out.stdout and "D101" not in out.stdout)
    check("the adapter left tasks and ledger to the files", "K1 [now]" in out.stdout and "entry 6" in out.stdout)
    out = subprocess.run([sys.executable, script, "alpha", "--root", tmp, "--adapter", os.path.join(alt, "x.txt")], capture_output=True, text=True)
    check("an adapter must be an existing .py file", out.returncode != 0)
    out = subprocess.run([sys.executable, script, "alpha", "--root", tmp, "--days", "90"], capture_output=True, text=True)
    check("--days widens the window", "D104" in out.stdout)
    out = subprocess.run([sys.executable, script, "alpha", "--root", tmp, "--today", "2027-01-01"], capture_output=True, text=True)
    check("--today sets the clock", "D101" not in out.stdout)
finally:
    shutil.rmtree(tmp)
    check("nothing left in the working folder", sorted(os.listdir(os.getcwd())) == cwd_before)
    check("test removed its temp folder", not os.path.exists(tmp))
sys.exit(1 if fails else 0)
