"""Tests for pace/pace.py. Run: python3 pace/tests/test_pace.py
Uses its own temp state folder and removes it, then checks nothing was left behind."""
import importlib.util, json, os, shutil, sys, tempfile

here = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp(prefix="pace-test-")
os.environ["PACE_STATE_DIR"] = tmp
STATE = os.path.join(tmp, "pace.jsonl")
spec = importlib.util.spec_from_file_location("pace", os.path.join(here, "..", "pace.py"))
pace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pace)

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FAIL ") + name)
    fails += 0 if cond else 1

def run(*args):
    from io import StringIO
    old = sys.stdout; sys.stdout = StringIO()
    try:
        pace.main(list(args) + ["--json"])
        return json.loads(sys.stdout.getvalue())
    finally:
        sys.stdout = old

try:
    R = "2026-11-30T18:00:00Z"
    v = run("record", "--weekly", "10", "--reset", R, "--at", "2026-11-23T18:00:00Z", "--lanes", "2")
    check("first reading has no history, so STEADY", v["verdict"] == "STEADY")
    check("goal is 90% of the weekly pool", v["goal"] == 90.0)
    # slow burn: 1%/h with 2 lanes, while the line allows about 0.47%/h -> over the line
    v = run("record", "--weekly", "11", "--reset", R, "--at", "2026-11-23T19:00:00Z", "--lanes", "2")
    check("burning about twice the line is QUEUE", v["verdict"] == "QUEUE")
    check("learns cost per lane-hour", v["per_lane_hour"] == 0.5)
    # very slow burn later in the week -> go hard
    os.remove(STATE)
    run("record", "--weekly", "20", "--reset", R, "--at", "2026-11-28T18:00:00Z", "--lanes", "1")
    v = run("record", "--weekly", "20.2", "--reset", R, "--at", "2026-11-28T20:00:00Z", "--lanes", "1")
    check("well under the line is GO HARD", v["verdict"] == "GO HARD")
    check("GO HARD allows more than one lane", v["lane_ceiling"] > 1)
    # weekly pool spent -> credits pool, stretched to the reset
    os.remove(STATE)
    run("record", "--weekly", "100", "--reset", R, "--spent", "340", "--cap", "422", "--at", "2026-11-30T00:00:00Z", "--lanes", "2")
    v = run("record", "--weekly", "100", "--reset", R, "--spent", "350", "--at", "2026-11-30T02:00:00Z", "--lanes", "2")
    check("switches to the credits pool at 100% weekly", v["pool"] == "credits")
    check("cap carries forward when not given", v["total"] == 82)
    check("credits goal is 90% of what was left at the cap", abs(v["goal"] - 73.8) < 0.01)
    check("10 of 82 dollars in 2h, with 16h left, is over the line", v["verdict"] in ("SHIP ONLY", "QUEUE"))
    # credits added: raise the cap and it recomputes
    v = run("record", "--weekly", "100", "--reset", R, "--spent", "350", "--cap", "600", "--at", "2026-11-30T02:30:00Z", "--lanes", "1")
    check("raising the cap reopens work", v["verdict"] != "QUEUE" or v["left_to_goal"] > 0)
    check("raised cap stretches from the spend then", v["total"] == 250)
    # a quiet spell shows at once: spend over the window, not a slow average
    os.remove(STATE)
    run("record", "--weekly", "100", "--reset", R, "--spent", "0", "--cap", "100", "--base", "0", "--at", "2026-11-30T00:00:00Z", "--lanes", "2")
    run("record", "--weekly", "100", "--reset", R, "--spent", "40", "--at", "2026-11-30T02:00:00Z", "--lanes", "0")
    v = run("record", "--weekly", "100", "--reset", R, "--spent", "40", "--at", "2026-11-30T09:00:00Z", "--lanes", "0")
    check("after 7 quiet hours the burn reads zero", v["rate_per_hour"] == 0.0)
    check("and work may resume", v["verdict"] == "GO HARD")
    # heartbeat follows the pace
    fast = pace.verdict({"at": "2026-11-30T10:00:00Z", "reset": R, "weekly": 100, "spent": 50, "cap": 100, "base": 0, "lanes": 3},
        [{"at": "2026-11-30T09:00:00Z", "reset": R, "weekly": 100, "spent": 30, "cap": 100, "base": 0, "lanes": 3},
         {"at": "2026-11-30T10:00:00Z", "reset": R, "weekly": 100, "spent": 50, "cap": 100, "base": 0, "lanes": 3}])
    slow = pace.verdict({"at": "2026-11-30T10:00:00Z", "reset": R, "weekly": 100, "spent": 31, "cap": 100, "base": 0, "lanes": 1},
        [{"at": "2026-11-30T09:00:00Z", "reset": R, "weekly": 100, "spent": 30, "cap": 100, "base": 0, "lanes": 1},
         {"at": "2026-11-30T10:00:00Z", "reset": R, "weekly": 100, "spent": 31, "cap": 100, "base": 0, "lanes": 1}])
    check("a fast burn beats sooner than a slow one", fast["next_beat_minutes"] < slow["next_beat_minutes"])
    check("beats stay between 15 minutes and 3 hours", 15 <= fast["next_beat_minutes"] <= 180 and 15 <= slow["next_beat_minutes"] <= 180)
    # combined pool: 50% of the week left at $2 per percent, plus $100 of credits
    os.remove(STATE)
    v = run("record", "--weekly", "50", "--reset", R, "--spent", "0", "--cap", "100", "--usd-per-pct", "2", "--at", "2026-11-29T18:00:00Z", "--lanes", "1")
    check("week and credits combine into one pool", v["pool"] == "combined")
    check("combined total is 100% x $2 plus $100", v["total"] == 300)
    check("combined used counts the week in dollars", v["used"] == 100)
    v = run("record", "--weekly", "52", "--reset", R, "--spent", "0", "--at", "2026-11-29T20:00:00Z", "--lanes", "1")
    check("combined rate is in dollars per hour", v["rate_per_hour"] == 2.0)
    check("exchange rate carries forward", v["pool"] == "combined")
    # a new week does not mix rates across the reset
    hist = pace.load()
    check("history file only holds this test's readings", all(r["reset"].startswith("2026-11-30") for r in hist) and len(hist) == 2)
    # fail closed: a stale reading, or a reset that is missing or past, gives STEADY at the current lane count
    os.remove(STATE)
    run("record", "--weekly", "20", "--reset", R, "--at", "2026-11-28T18:00:00Z", "--lanes", "3")
    v = run("record", "--weekly", "20.2", "--reset", R, "--at", "2026-11-28T20:00:00Z", "--lanes", "3")
    check("fresh reading under the line is GO HARD", v["verdict"] == "GO HARD" and not v["failed_closed"])
    beat = v["next_beat_minutes"]
    v = run("now", "--now", "2026-11-28T20:%02d:00Z" % (beat % 60) if beat < 60 else "2026-11-28T21:00:00Z")
    check("a reading inside its beat stays GO HARD", v["verdict"] == "GO HARD")
    v = run("now", "--now", "2026-11-29T20:00:00Z")
    check("a stale reading fails closed to STEADY", v["verdict"] == "STEADY" and v["failed_closed"])
    check("stale reading keeps the current lane count", v["lane_ceiling"] == 3)
    check("fail-closed asks for a fresh reading soon", v["next_beat_minutes"] <= 30)
    v = run("now", "--now", "2026-12-01T00:00:00Z")
    check("a reset in the past fails closed", v["verdict"] == "STEADY" and "past" in v["why"])
    r_missing = {"at": "2026-11-28T20:00:00Z", "weekly": 20, "lanes": 2}
    v = pace.verdict(r_missing, [r_missing])
    check("a missing reset fails closed at the current lanes", v["verdict"] == "STEADY" and v["lane_ceiling"] == 2 and "missing" in v["why"])
    check("fail-closed is never GO HARD even when idle", pace.verdict({"at": "2026-11-28T20:00:00Z", "reset": "2026-11-28T19:00:00Z", "weekly": 1, "lanes": 0}, [])["verdict"] != "GO HARD")
    # settings: target and reserve
    os.remove(STATE)
    v = run("record", "--weekly", "10", "--reset", R, "--at", "2026-11-23T18:00:00Z", "--lanes", "1")
    check("defaults are target 90 and reserve 10", v["target"] == 90 and v["reserve"] == 10 and v["goal"] == 90)
    v = run("record", "--weekly", "10", "--reset", R, "--at", "2026-11-23T19:00:00Z", "--lanes", "1", "--target", "80")
    check("--target moves the goal", v["goal"] == 80)
    v = run("record", "--weekly", "10", "--reset", R, "--at", "2026-11-23T20:00:00Z", "--lanes", "1", "--reserve", "25")
    check("--reserve can tighten the goal further", v["goal"] == 75 and v["target"] == 80)
    v = run("now")
    check("settings carry forward to now", v["goal"] == 75)
    # notice and overrides
    check("verdict JSON carries the gate notice", v["notice"] == pace.NOTICE and pace.NOTICE.startswith("Pace sets speed only. It never lifts a gate: 2FA, going public, publishing, live servers, production or deletions."))
    from io import StringIO
    old = sys.stdout; sys.stdout = StringIO()
    try:
        pace.main(["now"]); text = sys.stdout.getvalue()
    finally:
        sys.stdout = old
    check("verdict text carries the gate notice", pace.NOTICE in text)
    check("no override in force at first", v["overrides"] == [])
    old = sys.stdout; sys.stdout = StringIO()
    try:
        pace.main(["override", "--verdict", "ship_only", "--scope", "Feature work", "--words", "Hold new features", "--now", "2026-11-23T20:30:00Z"])
    finally:
        sys.stdout = old
    v = run("now", "--now", "2026-11-23T20:40:00Z")
    check("an override in force is listed", len(v["overrides"]) == 1 and v["overrides"][0]["verdict"] == "SHIP ONLY" and v["overrides"][0]["scope"] == "Feature work")
    check("the override ends at the reset", v["overrides"][0]["expires"].startswith("2026-11-30T18:00"))
    old = sys.stdout; sys.stdout = StringIO()
    try:
        pace.main(["now", "--now", "2026-11-23T20:40:00Z"]); text = sys.stdout.getvalue()
    finally:
        sys.stdout = old
    check("text output prints the override", "OWNER OVERRIDE" in text and "Hold new features" in text)
    v = run("now", "--now", "2026-11-30T17:59:00Z")
    check("override still in force just before the reset", len(v["overrides"]) == 1)
    r2 = pace.overrides_in_force(pace.parse_ts("2026-11-30T18:00:01Z"))
    check("override is gone after the reset", r2 == [])
    old = sys.stdout; sys.stdout = StringIO(); err = sys.stderr; sys.stderr = StringIO()
    try:
        rc = pace.main(["override", "--verdict", "FASTEST", "--scope", "x", "--words", "y"])
    finally:
        sys.stdout = old; sys.stderr = err
    check("an unknown override verdict is refused", rc == 2)
    # the state folder is configurable: --state-dir wins, then PACE_STATE_DIR, then OPS_ROOT/state
    other = tempfile.mkdtemp(prefix="pace-test-other-")
    try:
        from io import StringIO
        old = sys.stdout; sys.stdout = StringIO()
        try:
            pace.main(["--state-dir", other, "record", "--weekly", "5", "--reset", R, "--at", "2026-11-23T18:00:00Z", "--json"])
        finally:
            sys.stdout = old
        check("--state-dir writes the readings there", os.path.exists(os.path.join(other, "pace.jsonl")))
        check("--state-dir leaves PACE_STATE_DIR alone", all(r["weekly"] != 5 for r in pace.load()))
        del os.environ["PACE_STATE_DIR"]
        os.environ["OPS_ROOT"] = other
        check("OPS_ROOT/state is the fallback", pace.state_dir() == os.path.join(other, "state"))
        del os.environ["OPS_ROOT"]
        check("with nothing set it is ./state", pace.state_dir() == os.path.join(os.getcwd(), "state"))
        os.environ["PACE_STATE_DIR"] = tmp
    finally:
        shutil.rmtree(other)
    check("test removed its second temp folder", not os.path.exists(other))
finally:
    shutil.rmtree(tmp)
    check("test removed its temp folder", not os.path.exists(tmp))
sys.exit(1 if fails else 0)
