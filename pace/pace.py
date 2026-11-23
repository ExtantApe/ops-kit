#!/usr/bin/env python3
"""Pace: how fast work may go so the week's allowance lands near the target at the reset.

Work as fast as the allowance allows, aiming for 90% by each weekly reset and keeping 10% for
errors and upkeep (both are settings). Extra-usage credits are stretched the same way, and
everything is recomputed when credits are added. It learns from its own history, at no cost.

It never calls a model or the network. Feed it the numbers the usage card shows:

  pace record --weekly 42 --reset 2026-11-23T18:00:00Z [--spent 340.50] [--cap 422] [--lanes 3]
  pace now                 # verdict from the latest reading, no new record
  pace now --json          # the same, for the console or scripts
  pace history [-n 20]

Where readings are kept (nothing is ever written anywhere else):
  --state-dir DIR   or PACE_STATE_DIR, else $OPS_ROOT/state, else ./state.
  pace.jsonl holds the readings and pace-overrides.jsonl the owner overrides. Put the folder
  outside version control: the readings are yours alone.

One combined pool when both are known: the rest of the week, converted to
dollars, plus the credits, stretched together to the reset. The exchange rate (--usd-per-pct)
is learned from what one lane-hour costs in each pool, or can be given. Until it's known, the
two pools are used in order:
  1. The weekly plan allowance (percent). Target: --target (default 90) by the reset.
  2. Extra-usage credits (dollars), once the weekly pool is spent. Target: 90% of what was left when the
     cap was set (spend at that moment, the base) by the reset. Raise --cap when credits are
     added: the base resets to the spend then, so the new money is stretched to the reset too.

How it learns (cheap, no model calls): every reading is saved. From consecutive readings it
measures the real burn rate and the cost of one lane-hour, smoothed (EWMA), and it scores its
own last forecast against what happened, widening its safety margin when it was wrong.

Verdicts: GO HARD (well under the line), STEADY (on it), SHIP ONLY (ahead of it: finish what
is ready, start nothing new), QUEUE (over budget: nothing new until the reset). Each comes with
a lane ceiling.

Settings: --target (default 90) is the share of the pool to have used by the reset and --reserve
(default 10) is the share kept for errors and upkeep. The goal is the lower of target and
100 minus reserve, so either one can tighten it. They are saved with each reading and carry forward.

Fails closed: if the newest reading is older than its next_beat_minutes plus 30 minutes, or the
reset time is missing or already past, the answer is STEADY at the current lane count and never
GO HARD, whatever the numbers say.

Owner overrides (the owner's own words, they expire at the next reset and print while in force):
  pace override --verdict SHIP_ONLY --scope "Feature work" --words "the owner's words"

Every verdict output says what pace does not do: it sets speed only and never lifts a gate.
"""
import argparse, json, math, os, sys
from datetime import datetime, timedelta, timezone

_state_dir = None     # set by main(--state-dir); None means "work it out from the environment"
NOTICE = "Pace sets speed only. It never lifts a gate: 2FA, going public, publishing, live servers, production or deletions."
VERDICTS = ("GO HARD", "STEADY", "SHIP ONLY", "QUEUE")
STALE_GRACE_MIN = 30
DEFAULT_TARGET, DEFAULT_RESERVE = 90.0, 10.0
ALPHA = 0.35          # smoothing for learned rates
WINDOW_H = 6.0        # how far back the burn rate looks
MAX_LANES = 8


def state_dir():
    """The folder readings live in: --state-dir, PACE_STATE_DIR, $OPS_ROOT/state, or ./state."""
    if _state_dir:
        return _state_dir
    if os.environ.get("PACE_STATE_DIR"):
        return os.environ["PACE_STATE_DIR"]
    return os.path.join(os.environ.get("OPS_ROOT") or os.getcwd(), "state")


def readings_path():
    return os.path.join(state_dir(), "pace.jsonl")


def overrides_path():
    return os.path.join(state_dir(), "pace-overrides.jsonl")


def now_utc():
    return datetime.now(timezone.utc)


def parse_ts(s):
    s = s.strip().replace("Z", "+00:00")
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def load(path=None):
    path = path or readings_path()
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def save(rec, path=None):
    path = path or readings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")


def overrides_in_force(now, path=None):
    path = path or overrides_path()
    out = []
    for o in load(path):
        try:
            if parse_ts(o["expires"]) > now:
                out.append(o)
        except (KeyError, ValueError):
            continue
    return out


def pool_of(r):
    """Which pool is live in a reading, and its used and total, in that pool's unit."""
    if r["weekly"] < 100 or r.get("cap") is None:
        return "weekly", float(r["weekly"]), 100.0
    base = float(r.get("base") or 0.0)            # spend when this cap was set
    return "credits", float(r.get("spent") or 0.0) - base, float(r["cap"]) - base


def learn(history):
    """Smoothed burn per hour and per lane-hour for each pool, plus forecast error."""
    m = {"weekly": {}, "credits": {}}
    prev = None
    for r in history:
        if prev is not None:
            dt = (parse_ts(r["at"]) - parse_ts(prev["at"])).total_seconds() / 3600
            p0, u0, _ = pool_of(prev)
            p1, u1, _ = pool_of(r)
            same_week = r.get("reset") == prev.get("reset")
            if dt > 0.05 and p0 == p1 and same_week and u1 >= u0:
                rate = (u1 - u0) / dt
                s = m[p1]
                s["rate"] = rate if "rate" not in s else ALPHA * rate + (1 - ALPHA) * s["rate"]
                lanes = prev.get("lanes")
                if lanes:
                    per = rate / max(lanes, 1)
                    s["per_lane"] = per if "per_lane" not in s else ALPHA * per + (1 - ALPHA) * s["per_lane"]
                f = prev.get("forecast")
                if f and f.get("pool") == p1 and f.get("rate"):
                    err = abs(rate - f["rate"]) / max(f["rate"], 1e-6)
                    s["err"] = err if "err" not in s else ALPHA * err + (1 - ALPHA) * s["err"]
        prev = r
    # The burn rate is spend over the last WINDOW_H hours, so one reading after a quiet spell
    # shows the quiet at once (the smoothed per-reading rate stays for lane costs and errors).
    if history:
        last = history[-1]
        pl, ul, _ = pool_of(last)
        tl = parse_ts(last["at"])
        pick = None
        for r in reversed(history[:-1]):          # newest first; keep going back within the window
            dt = (tl - parse_ts(r["at"])).total_seconds() / 3600
            p, u, _ = pool_of(r)
            if p != pl or r.get("reset") != last.get("reset") or u > ul or dt <= 0.05:
                continue
            if pick is None or dt <= WINDOW_H:
                pick = (dt, u)                      # oldest inside the window, or the newest before it
            if dt > WINDOW_H:
                break
        if pick:
            m[pl]["rate"] = (ul - pick[1]) / pick[0]
    w, c = m["weekly"].get("per_lane"), m["credits"].get("per_lane")
    if w and c:
        m["usd_per_pct"] = c / w        # one lane-hour costs w% of the week or c dollars
    return m


def verdict(r, history, target=None, reserve=None, now=None, promised_beat=None):
    """now defaults to the reading's own time. promised_beat is the beat the newest reading promised."""
    target = float(target if target is not None else r.get("target", DEFAULT_TARGET))
    reserve = float(reserve if reserve is not None else r.get("reserve", DEFAULT_RESERVE))
    goal_pct = min(target, 100.0 - reserve)
    at = parse_ts(r["at"])
    now = now or at
    reset = None
    try:
        reset = parse_ts(r["reset"]) if r.get("reset") else None
    except ValueError:
        reset = None
    closed_reason = None
    if reset is None:
        closed_reason = "the reset time is missing"
        reset = at + timedelta(hours=1)           # placeholder so the maths below runs
    elif reset <= now or reset <= at:
        closed_reason = "the reset time is already past"
    hours = max((reset - at).total_seconds() / 3600, 0.01)
    pool, used, total = pool_of(r)
    learned = learn(history)
    m = dict(learned.get(pool, {}))
    k = r.get("usd_per_pct") or learned.get("usd_per_pct")
    if k and r.get("cap") is not None:
        # Combined: what's left of the week plus the credits, in dollars,
        # stretched as one pool to the reset.
        base = float(r.get("base") or 0.0)
        cr_used = float(r.get("spent") or 0.0) - base
        cr_total = float(r["cap"]) - base
        f = 1.0 if pool == "credits" else k     # convert this pool's rates to dollars
        pool, used, total = "combined", min(r["weekly"], 100.0) * k + cr_used, 100.0 * k + cr_total
        m = {key: (v * f if key in ("rate", "per_lane") else v) for key, v in m.items()}
    goal = total * goal_pct / 100.0
    left = goal - used
    allowed = left / hours                       # units per hour that land exactly on the goal
    rate = m.get("rate")
    per_lane = m.get("per_lane")
    err = min(m.get("err", 0.25), 1.0)           # unknown history: assume 25% forecast error
    margin = 1.0 + err                           # widen caution when it has been wrong
    lanes_now = r.get("lanes") or 0

    if left <= 0:
        kind, ceiling = "QUEUE", 0
        why = f"{pool} pool is at or past {goal_pct:.0f}% of its total; only upkeep until the reset"
    else:
        if per_lane:
            ceiling = int(max(0, min(MAX_LANES, math.floor(allowed / (per_lane * margin)))))
        else:
            ceiling = max(1, lanes_now) if lanes_now else 2
        if rate is None:
            kind = "STEADY"
            why = "no burn history yet; record again in an hour to learn the rate"
        else:
            ratio = rate / allowed if allowed > 0 else math.inf
            if ratio < 0.6:
                kind = "GO HARD"
            elif ratio <= 1.1:
                kind = "STEADY"
            elif ratio <= 1.6:
                kind = "SHIP ONLY"
                ceiling = min(ceiling, max(lanes_now - 1, 1))
            else:
                kind = "QUEUE"
                ceiling = min(ceiling, 1)
            why = f"burning {rate:.2f}/h against {allowed:.2f}/h allowed ({ratio:.0%} of the line)"
    # Heartbeat, relative to the pace. The beat is the
    # time it takes the current burn to use BEAT_SHARE of what's left to the goal, so a fast burn
    # checks in often and a slow one rarely. When nothing is burning, the beat is the time it takes
    # the six-hour window to slide far enough for the verdict to change. 15 minutes to 3 hours,
    # and never more than a quarter of the time left.
    BEAT_SHARE = 0.05
    if left <= 0:
        beat = 180                                # spent: only the reset or a top-up changes it
    elif rate and rate > 0 and (lanes_now or kind != "QUEUE"):
        beat = 60 * BEAT_SHARE * left / rate
    elif rate and rate > allowed:
        beat = 60 * WINDOW_H * (1 - allowed / rate)   # idle: when the window's average falls to the line
    else:
        beat = 180
    beat = int(max(15, min(180, beat, hours * 60 / 4)))
    if kind in ("GO HARD", "STEADY") and ceiling < 1:
        ceiling = 1                               # a go verdict always allows at least one lane
    unit = "%" if pool == "weekly" else "$"
    eta = None
    if rate and rate > 0:
        hrs_to_total = (total - used) / rate
        eta = (at.timestamp() + hrs_to_total * 3600)
    if closed_reason is None:
        promised = promised_beat if promised_beat is not None else r.get("beat", beat)
        age_min = (now - at).total_seconds() / 60
        if age_min > promised + STALE_GRACE_MIN:
            closed_reason = f"the newest reading is {age_min:.0f} minutes old, more than its beat of {promised} minutes plus {STALE_GRACE_MIN}"
    if closed_reason:
        kind, ceiling, beat = "STEADY", lanes_now, 15
        why = f"failed closed: {closed_reason}; holding the current lane count until a fresh reading"
    return {
        "notice": NOTICE, "target": target, "reserve": reserve, "failed_closed": bool(closed_reason),
        "verdict": kind, "lane_ceiling": ceiling, "pool": pool, "unit": unit,
        "used": round(used, 2), "total": total, "goal": round(goal, 2), "left_to_goal": round(left, 2),
        "hours_to_reset": round(hours, 1), "allowed_per_hour": round(allowed, 3),
        "rate_per_hour": None if rate is None else round(rate, 3),
        "per_lane_hour": None if per_lane is None else round(per_lane, 3),
        "forecast_error": round(err, 2),
        "runs_out_at": None if eta is None else datetime.fromtimestamp(eta, timezone.utc).isoformat(timespec="minutes"),
        "why": why, "next_beat_minutes": beat,
    }


def show(v, ovr=()):
    u = v["unit"]
    fmt = (lambda x: f"${x:,.2f}") if u == "$" else (lambda x: f"{x:.1f}%")
    print(f"{v['verdict']}: up to {v['lane_ceiling']} lanes")
    print(f"  {v['pool']} pool: {fmt(v['used'])} used of {fmt(v['total'])}, goal {fmt(v['goal'])}, "
          f"{v['hours_to_reset']}h to reset")
    print(f"  {v['why']}")
    print(f"  next heartbeat in {v['next_beat_minutes']} minutes")
    if v["runs_out_at"]:
        print(f"  at this rate the pool runs out {v['runs_out_at']}")
    print(f"  goal {v['target']:.0f}% used, reserve {v['reserve']:.0f}% kept for errors and upkeep")
    for o in ovr:
        print(f"  OWNER OVERRIDE in force until {o['expires']}: {o['verdict']} for {o['scope']}. \"{o['words']}\"")
    print(f"  {NOTICE}")


def main(argv=None):
    global _state_dir
    try:
        return _main(argv)
    finally:
        _state_dir = None             # --state-dir lasts for one call only


def _main(argv):
    global _state_dir
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state-dir", help="folder for pace.jsonl and pace-overrides.jsonl (default: PACE_STATE_DIR, $OPS_ROOT/state, ./state)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("--weekly", type=float, required=True, help="weekly all-models percent used")
    rec.add_argument("--reset", required=True, help="weekly reset time, ISO 8601")
    rec.add_argument("--spent", type=float, help="extra-usage dollars spent")
    rec.add_argument("--cap", type=float, help="extra-usage dollars available in total")
    rec.add_argument("--base", type=float, help="spend when the cap was set (default: spend at the first reading with this cap)")
    rec.add_argument("--usd-per-pct", type=float, help="dollars one weekly percent is worth; learned when not given, carried forward")
    rec.add_argument("--lanes", type=int, help="sessions and agents working right now, every session and subagent on the account")
    rec.add_argument("--target", type=float, help="percent of the pool to have used by the reset (default 90, then the last reading's)")
    rec.add_argument("--reserve", type=float, help="percent kept for errors and upkeep (default 10, then the last reading's)")
    rec.add_argument("--at", help="reading time (default now)")
    rec.add_argument("--json", action="store_true")
    nw = sub.add_parser("now")
    nw.add_argument("--target", type=float)
    nw.add_argument("--reserve", type=float)
    nw.add_argument("--now", help="pretend it is this time (ISO 8601), for tests")
    nw.add_argument("--json", action="store_true")
    hi = sub.add_parser("history")
    hi.add_argument("-n", type=int, default=20)
    ov = sub.add_parser("override", help="record an owner override; it ends at the next reset")
    ov.add_argument("--verdict", required=True, help="one of: GO HARD, STEADY, SHIP ONLY, QUEUE (SHIP_ONLY and go-hard also work)")
    ov.add_argument("--scope", required=True, help="what the override covers")
    ov.add_argument("--words", required=True, help="the owner's words, verbatim")
    ov.add_argument("--until", help="expiry, ISO 8601 (default: the reset in the latest reading)")
    ov.add_argument("--now", help="pretend it is this time (ISO 8601), for tests")
    ov.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    _state_dir = a.state_dir or None
    h = load()

    if a.cmd == "history":
        for r in h[-a.n:]:
            print(json.dumps(r, sort_keys=True))
        return 0
    if a.cmd == "override":
        kind = a.verdict.strip().upper().replace("_", " ").replace("-", " ")
        if kind not in VERDICTS:
            print(f"verdict must be one of {', '.join(VERDICTS)}", file=sys.stderr)
            return 2
        when = parse_ts(a.now) if a.now else now_utc()
        until = a.until or (h[-1].get("reset") if h else None)
        if not until:
            print("no reset time known: record a reading first or give --until", file=sys.stderr)
            return 1
        until = parse_ts(until)
        if until <= when:
            print("that expiry is already past", file=sys.stderr)
            return 1
        o = {"at": when.isoformat(timespec="seconds"), "verdict": kind, "scope": a.scope, "words": a.words,
             "expires": until.isoformat(timespec="seconds")}
        save(o, overrides_path())
        if a.json:
            print(json.dumps({"override": o, "notice": NOTICE}, sort_keys=True))
        else:
            print(f"Override recorded: {kind} for {a.scope}, until {o['expires']} (the next reset).")
            print(NOTICE)
        return 0
    if a.cmd == "now":
        if not h:
            print("no readings yet: run pace record first", file=sys.stderr)
            return 1
        when = parse_ts(a.now) if a.now else now_utc()
        v = verdict(h[-1], h, a.target, a.reserve, now=when)
    else:
        last = h[-1] if h else {}
        if a.cap is None and last.get("cap") is not None:
            a.cap = last["cap"]                  # the cap carries forward until changed
        if a.base is None:
            # a new or raised cap stretches from the spend at that moment; otherwise keep the old base
            a.base = last.get("base") if a.cap == last.get("cap") else (a.spent or 0.0)
        at = parse_ts(a.at) if a.at else now_utc()
        r = {"at": at.isoformat(timespec="seconds"),
             "weekly": a.weekly, "reset": parse_ts(a.reset).isoformat(timespec="seconds"),
             "spent": a.spent, "cap": a.cap, "base": a.base, "lanes": a.lanes,
             "target": a.target if a.target is not None else last.get("target", DEFAULT_TARGET),
             "reserve": a.reserve if a.reserve is not None else last.get("reserve", DEFAULT_RESERVE),
             "usd_per_pct": a.usd_per_pct if a.usd_per_pct is not None else last.get("usd_per_pct")}
        v = verdict(r, h + [r], now=at)
        r["forecast"] = {"pool": v["pool"], "rate": v["allowed_per_hour"]}
        r["beat"] = v["next_beat_minutes"]
        save(r)
        when = at
    ovr = overrides_in_force(when)
    v["overrides"] = ovr
    if a.json:
        print(json.dumps(v, sort_keys=True))
    else:
        show(v, ovr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
