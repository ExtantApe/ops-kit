#!/usr/bin/env python3
"""Tests for topics-index/topics_index.py. Run: python3 topics-index/tests/test_topics_index.py
Uses a temp folder, removes it, and checks nothing was left behind."""
import os, shutil, subprocess, sys, tempfile

here = os.path.dirname(os.path.abspath(__file__))
script = os.path.join(here, "..", "topics_index.py")
cwd_before = sorted(os.listdir(os.getcwd()))
fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FAIL ") + name)
    fails += 0 if cond else 1

def topic(title, summary_lines, history="- 2026-11-20: started."):
    return (f"# {title}\n\n## Summary\n" + "\n".join(summary_lines) + "\n\n## Where it stands\nx\n\n## Decisions\n- one line: x\n\n"
            f"## Open questions\nNone.\n\n## History\n{history}\n\n## Sources\n- x\n")

def run(root, *args):
    return subprocess.run([sys.executable, script, "--root", root, *args], capture_output=True, text=True)

tmp = tempfile.mkdtemp(prefix="topics-test-")
try:
    os.makedirs(os.path.join(tmp, "topics"))
    w = lambda n, t: open(os.path.join(tmp, "topics", n), "w").write(t)
    w("README.md", "# Topic files\n")
    w("beta.md", topic("Beta thing", ["Beta is the second one.", "More."], "- 2026-11-22: later.\n- 2026-11-10: earlier."))
    w("alpha.md", topic("Alpha thing", ["Alpha is the first one."]))
    r = run(tmp)
    check("it writes the index", r.returncode == 0 and os.path.exists(os.path.join(tmp, "topics", "INDEX.md")))
    idx = open(os.path.join(tmp, "topics", "INDEX.md")).read()
    lines = [l for l in idx.splitlines() if l.startswith("- ")]
    check("one line per topic, README left out", len(lines) == 2)
    check("topics are listed alphabetically", lines[0].startswith("- [Alpha thing](alpha.md)") and lines[1].startswith("- [Beta thing](beta.md)"))
    check("each line carries the first summary line", "Alpha is the first one." in lines[0])
    check("each line carries the newest history date", "updated 2026-11-22" in lines[1])
    check("--check passes on a fresh index", run(tmp, "--check").returncode == 0)
    w("gamma.md", topic("Gamma", ["x"]))
    check("--check fails when a topic is missing from the index", run(tmp, "--check").returncode == 1)
    before = open(os.path.join(tmp, "topics", "INDEX.md")).read()
    run(tmp, "--check")
    check("--check writes nothing", open(os.path.join(tmp, "topics", "INDEX.md")).read() == before)
    w("long.md", topic("Long", [f"line {i}" for i in range(21)]))
    r = run(tmp)
    check("a 21-line summary is reported and fails", r.returncode == 1 and "over 20" in r.stderr)
    w("long.md", topic("Long", [f"line {i}" for i in range(20)]))
    check("a 20-line summary is accepted", run(tmp).returncode == 0)
    w("bad.md", "# Bad\n\n## Summary\nOnly this.\n")
    r = run(tmp)
    check("a topic missing sections is reported", r.returncode == 1 and "missing sections" in r.stderr)
    os.remove(os.path.join(tmp, "topics", "bad.md"))
    w("nodate.md", topic("No date", ["x"], "- nothing dated"))
    check("a history with no date is reported", run(tmp).returncode == 1)
    os.remove(os.path.join(tmp, "topics", "nodate.md"))
    os.remove(os.path.join(tmp, "topics", "gamma.md")); os.remove(os.path.join(tmp, "topics", "long.md"))
    old = topic("Old heading", ["x"]).replace("## Decisions", "## D numbers")
    w("old.md", old)
    check("the older 'D numbers' heading is still accepted", run(tmp).returncode == 0)
    other = os.path.join(tmp, "elsewhere"); os.makedirs(other)
    open(os.path.join(other, "one.md"), "w").write(topic("One", ["x"]))
    r = run(tmp, "--topics-dir", other)
    check("--topics-dir indexes another folder", r.returncode == 0 and os.path.exists(os.path.join(other, "INDEX.md")))
    check("--topics-dir leaves the main index alone", "(one.md)" not in open(os.path.join(tmp, "topics", "INDEX.md")).read())
finally:
    shutil.rmtree(tmp)
    check("nothing left in the working folder", sorted(os.listdir(os.getcwd())) == cwd_before)
    check("test removed its temp folder", not os.path.exists(tmp))
sys.exit(1 if fails else 0)
