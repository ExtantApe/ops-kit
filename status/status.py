#!/usr/bin/env python3
"""status: where every task stands, and what the owner has to do, in one read. Local only: it never calls Claude or
the network. Plain Python 3.9+, no dependencies.

  status.py --source tasks.jsonl [--steps steps.jsonl]      read task (and owner-step) files in the common schema
  status.py --adapter my_store.py                           or a small adapter for your own store (see README). The
                                                            adapter runs as Python with your permissions: use only
                                                            adapters you wrote or have read
  status.py ... --tags tags.jsonl                           size and payoff kept apart from the tasks: {id, size, payoff}
  status.py ... --full                                      the to-do list with every step and the chain commands
  status.py ... --json                                      the same, as JSON
  status.py ... --since 2026-11-17                          "done" counts from this date (default: Monday 00:00 local)
  status.py ... --share --terms FILE                        safe to show outside: IDs, areas, categories, buckets and
                                                            generic titles only; refuses if the terms can't be read.
                                                            The terms file holds one regular expression per line
                                                            (case-insensitive); escape ( ) . + * ? [ ] if literal
  status.py resolve C1 [--chains FILE]                      the step IDs in chain C1, one per line (for your "done")

Sections, in order:
  0. Your to-do: every open owner step, by category, with chains (C1, C2, ...) of command-only steps joined by && so
     they stop at the first failure. Only with --steps or an adapter that has steps(). Not in --share.
  1. Done this week.  2. In progress ("now"), by area.  3. Priority queue: what each owner pulls next into a free
  slot.  4. Next.  5. Soon.  6. Everything else ("later" and "waiting"), by category.
Within each section tasks run in bucket order (size x payoff; see rules/joint-system.md), untagged last.

Task schema (one JSON object per task; a file is a JSON list or JSON Lines):
  id, title, priority (now|next|soon|later|waiting), state (open|closed)    required
  area, category, owner, rank (number or null), closed (ISO time or null), ref, waiting_on, blocked,
  size (hours|days|weeks), payoff (major|moderate|minor)                    optional
Step schema (owner steps and tests):
  id, title, state (open|...), body                                          required (only "open" ones are listed)
  category, duration, kind (command|setup|pick|review|test|...)              optional
"""
import argparse, datetime, importlib.util, json, os, re, sys

PRIORITIES = ["now", "next", "soon", "later", "waiting"]
FIELDS = ("id", "title", "area", "category", "priority", "state", "owner", "rank", "closed", "ref", "waiting_on", "blocked",
          "size", "payoff")
BUCKETS = {("hours", "major"): "Steal", ("days", "major"): "Win", ("hours", "moderate"): "Pickup",
           ("weeks", "major"): "Bet", ("days", "moderate"): "Routine", ("hours", "minor"): "Filler",
           ("weeks", "moderate"): "Investment", ("days", "minor"): "Chore", ("weeks", "minor"): "Parked"}
BUCKET_ORDER = list(BUCKETS.values())
WIP = 3
# Words that mean a person has to do something a shell can't. Such steps are never chained.
PERSON = re.compile(r"\b(click|tap|phone|iphone|ipad|browser|https?://|system settings|drag|right-click|"
                    r"password manager|passwords app|by cable|desktop app|dashboard|your call|choose|decide|pick one|"
                    r"sign in to|in the app|window|open -e|editor)\b", re.I)
FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.S)


# ---- reading ----------------------------------------------------------------------------------------------------

def rows(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return json.loads(text) if text.lstrip().startswith("[") else [json.loads(l) for l in text.splitlines() if l.strip()]


def check_task(r, where):
    missing = [k for k in ("id", "title", "priority", "state") if not r.get(k)]
    if missing:
        sys.exit(f"status: {where} lacks {', '.join(missing)}")
    if r["priority"] not in PRIORITIES or r["state"] not in ("open", "closed"):
        sys.exit(f"status: {where}: priority or state isn't one of the schema's values")
    t = {k: r.get(k, None if k in ("rank", "closed") else "") for k in FIELDS}
    for k in ("size", "payoff"):
        t[k] = (t[k] or "").lower()
    if t["closed"]:
        t["closed"] = local(t["closed"])
    return t


def load_adapter(path):
    if not path.endswith(".py") or not os.path.isfile(path):
        sys.exit(f"status: the adapter must be an existing .py file: {path}")
    spec = importlib.util.spec_from_file_location("ops_kit_adapter", path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    if not hasattr(mod, "tasks"):
        sys.exit(f"status: {path} has no tasks() function")
    return mod


# ---- time -------------------------------------------------------------------------------------------------------

def when(ts):
    d = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return d if d.tzinfo else d.astimezone()


def local(ts):
    return when(ts).astimezone().isoformat(timespec="seconds")


def monday():
    today = datetime.date.today()
    return datetime.datetime.combine(today - datetime.timedelta(days=today.weekday()), datetime.time()).astimezone()


# ---- tasks ------------------------------------------------------------------------------------------------------

def num(tid):
    m = re.search(r"\d+", str(tid))
    return int(m.group()) if m else 0


def bucket(t):
    return BUCKETS.get((t.get("size") or "", t.get("payoff") or ""), "")


def order(t):
    b = bucket(t)
    return (BUCKET_ORDER.index(b) if b else len(BUCKET_ORDER), t["rank"] if t["rank"] is not None else 10**6, num(t["id"]))


def sections(tasks, wip, since):
    open_ = [t for t in tasks if t["state"] == "open"]
    done = sorted((t for t in tasks if t["state"] == "closed" and t["closed"] and when(t["closed"]) >= since),
                  key=lambda t: t["closed"], reverse=True)
    now = sorted((t for t in open_ if t["priority"] == "now"), key=order)
    nxt = sorted((t for t in open_ if t["priority"] == "next"), key=order)
    queue = []
    for owner in sorted({t["owner"] for t in nxt}):
        free = wip - sum(1 for t in now if t["owner"] == owner)
        queue += [t for t in nxt if t["owner"] == owner][:max(free, 0)]
    queue.sort(key=order)
    qids = {t["id"] for t in queue}
    return [("Done this week", "", done), ("In progress", "area", now), ("Priority queue", "", queue),
            ("Next", "", [t for t in nxt if t["id"] not in qids]),
            ("Soon", "", sorted((t for t in open_ if t["priority"] == "soon"), key=order)),
            ("Everything else", "category", sorted((t for t in open_ if t["priority"] in ("later", "waiting")), key=order))]


# ---- owner steps and chains -------------------------------------------------------------------------------------

def commands(body):
    out = []
    for block in FENCE.findall(body or ""):
        cur = ""
        for line in block.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.endswith("\\"):
                cur += s[:-1] + " "; continue
            out.append((cur + s).strip()); cur = ""
    return out


def chainable(st):
    body = st.get("body") or ""
    if st.get("kind") in ("pick", "think", "review", "test") or not commands(body) or PERSON.search(body) \
            or re.search(r"not needed", body, re.I):
        return False
    for s in re.split(r"\n\s*\d+\.\s", "\n" + body)[1:]:
        if "```" not in s and not re.match(r"\s*(\(?done|tell |say |then say|nothing to report)", s, re.I):
            return False
    return True


def chains(steps, path, save=True):
    groups = {}
    for st in steps:
        if chainable(st):
            cmds = commands(st["body"])
            g = "npm" if any(c.startswith("npm ") for c in cmds) else "shell"
            groups.setdefault(g, []).append((st["id"], [c for c in cmds if c not in ("npm login", "npm whoami")]))
    try:
        with open(path, encoding="utf-8") as f:
            reg = json.load(f)
    except (OSError, ValueError):
        reg = {}
    out, changed = [], False
    for g in sorted(groups):
        members = sorted((i for i, _ in groups[g]), key=lambda x: (x[:1], num(x)))
        cmds = (["npm login"] if g == "npm" else []) + [c for i in members for c in dict(groups[g])[i]]
        if len(cmds) < 2:
            continue
        cid = next((k for k, v in reg.items() if sorted(v["members"]) == sorted(members) and v.get("group") == g), None)
        if not cid:
            cid = f"C{max([num(k) for k in reg] or [0]) + 1}"
            reg[cid] = {"members": members, "group": g}; changed = True
        out.append({"id": cid, "group": g, "members": members, "commands": cmds, "chain": " && ".join(cmds)})
    if changed and save:
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(reg, f, indent=1); f.write("\n")
        os.replace(path + ".tmp", path)
    return out


def quick_steps(st):
    text = (st.get("body") or "").strip()
    if "```" in text and not re.search(r"iTerm|Terminal", text):
        text = "In Terminal:\n" + text
    return text


def todo(steps, chains_path, save=True):
    open_ = sorted((s for s in steps if s.get("state") == "open"), key=lambda s: (str(s["id"])[:1], num(s["id"])))
    cs = chains(open_, chains_path, save)
    in_chain = {m: c["id"] for c in cs for m in c["members"]}
    cats = {}
    for s in open_:
        cats.setdefault(s.get("category") or ("Tests" if s.get("kind") == "test" else "Other"), []).append(dict(
            id=s["id"], title=re.sub(r"\*+", "", s.get("title") or "").strip(), duration=s.get("duration") or "",
            chain=in_chain.get(s["id"]), steps=quick_steps(s)))
    names = sorted(cats, key=lambda n: (n == "Tests", n == "Other", n))
    return {"categories": [{"name": n, "items": cats[n]} for n in names], "chains": cs, "count": len(open_)}


def todo_text(td, full=False):
    out = [f"## Your to-do ({td['count']}). Say \"done <ID>\" or \"done C1\" when finished.", ""]
    for cat in td["categories"]:
        its = cat["items"]
        if cat["name"] == "Tests" and not full:
            out += [f"### Tests ({len(its)}): " + ", ".join(i["id"] for i in its) + ". Steps: --full", ""]
            continue
        out.append(f"### {cat['name']} ({len(its)})")
        for i in its:
            tail = " ".join(x for x in (f"({i['duration']})" if i["duration"] else "", f"[{i['chain']}]" if i["chain"] else "") if x)
            out.append(f"- {i['id']} {i['title'][:78]}" + (f"  {tail}" if tail else ""))
            if full:
                out += ["", *("  " + l for l in i["steps"].splitlines()), ""]
        out.append("")
    if td["chains"]:
        out.append("### Chains (each stops at the first failure)")
        for c in td["chains"]:
            out += ([f"**{c['id']}** ({', '.join(c['members'])}). In Terminal:", "```bash", c["chain"], "```",
                     f"Then say \"done {c['id']}\".", ""] if full else
                    [f"- {c['id']} = {', '.join(c['members'])}: {len(c['commands'])} commands ({c['group']}). The command: --full"])
        out.append("")
    return "\n".join(out)


# ---- sharing ----------------------------------------------------------------------------------------------------

def load_terms(path):
    try:
        with open(path, encoding="utf-8") as f:
            pats = [l.strip() for l in f if l.strip() and not l.lstrip().startswith("#")]
    except (OSError, TypeError):
        pats = []
    if not pats:
        sys.exit("status: --share needs a readable private terms list (--terms FILE); refusing rather than guess")
    try:
        return [re.compile(p, re.I) for p in pats]
    except re.error:
        sys.exit("status: a private term isn't a valid pattern; refusing --share")


def shared(t, terms):
    priv = lambda s: any(p.search(s or "") for p in terms)
    cat = "private" if priv(t["category"]) else t["category"]
    title = t["title"]
    if priv(title):
        title = "Private task" if cat == "private" or not cat else f"{cat} task".capitalize()
    return dict(id=t["id"], title=title, area="private" if priv(t["area"]) else t["area"], category=cat, priority=t["priority"],
                state=t["state"], closed=(t["closed"] or "")[:10] or None, bucket=bucket(t) or None)


# ---- output -----------------------------------------------------------------------------------------------------

def line(t, share):
    b = t.get("bucket") if share else bucket(t)
    tag = (f"[{b}]" if b else "[untagged]") if t["state"] == "open" else ""
    bits = [t["id"]] + ([tag] if tag else []) + [t["title"]]
    if not share:
        extra = [t["owner"]] if t.get("owner") else []
        if t.get("blocked") and t["state"] == "open": extra.append("BLOCKED: " + t["blocked"])
        if t.get("waiting_on") and t["state"] == "open": extra.append("waiting on " + t["waiting_on"])
        if t.get("ref") and t["state"] == "closed": extra.append("ref " + t["ref"])
        if extra: bits.append("(" + "; ".join(extra)[:160] + ")")
    if t["state"] == "closed" and t.get("closed"): bits.insert(1, t["closed"][:10])
    return "- " + "  ".join(bits)


def text(secs, since, share):
    out = []
    for name, group, ts in secs:
        out += [f"## {name} ({len(ts)})" + (f" since {since:%a %Y-%m-%d}" if name == "Done this week" else ""), ""]
        if not ts:
            out += ["- none", ""]; continue
        if group:
            for g in sorted({t[group] or "other" for t in ts}):
                out += [f"### {g}"] + [line(t, share) for t in ts if (t[group] or "other") == g] + [""]
        else:
            out += [line(t, share) for t in ts] + [""]
    return "\n".join(out).rstrip() + "\n"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["resolve"]:
        p = argparse.ArgumentParser(prog="status.py resolve")
        p.add_argument("cmd"); p.add_argument("chain"); p.add_argument("--chains", default="todo-chains.json")
        a = p.parse_args(argv)
        try:
            with open(a.chains, encoding="utf-8") as f:
                reg = json.load(f)
        except (OSError, ValueError):
            sys.exit(f"status: can't read {a.chains}")
        if a.chain.upper() not in reg:
            sys.exit(f"status: no chain {a.chain.upper()}")
        print("\n".join(reg[a.chain.upper()]["members"])); return
    p = argparse.ArgumentParser(description="Where every task stands, and what the owner has to do. Local only.")
    p.add_argument("--source", action="append", help="a task file in the common schema (repeatable)")
    p.add_argument("--steps", action="append", help="an owner-step file in the step schema (repeatable)")
    p.add_argument("--adapter", help="a Python file with tasks() and, optionally, steps() and WIP_LIMIT")
    p.add_argument("--tags", action="append", help="a file of {id, size, payoff} rows laid over the tasks (repeatable)")
    p.add_argument("--chains", default="todo-chains.json", help="where chain IDs are kept (default ./todo-chains.json)")
    p.add_argument("--full", action="store_true"); p.add_argument("--json", action="store_true")
    p.add_argument("--share", action="store_true"); p.add_argument("--terms", help="the private terms list for --share")
    p.add_argument("--since", help="YYYY-MM-DD; default Monday 00:00 local")
    a = p.parse_args(argv)
    if not a.source and not a.adapter:
        p.error("give --source FILE or --adapter FILE")
    since = datetime.datetime.fromisoformat(a.since).astimezone() if a.since else monday()
    tasks, steps, wip = [], [], WIP
    for s in a.source or []:
        tasks += [check_task(r, f"{s} row {i}") for i, r in enumerate(rows(s), 1)]
    for s in a.steps or []:
        steps += rows(s)
    if a.adapter:
        mod = load_adapter(a.adapter)
        tasks += [check_task(r, f"{a.adapter} task {i}") for i, r in enumerate(mod.tasks(), 1)]
        steps += list(mod.steps()) if hasattr(mod, "steps") else []
        wip = getattr(mod, "WIP_LIMIT", WIP)
    for tf in a.tags or []:
        tags = {str(r.get("id")): r for r in rows(tf)}
        for t in tasks:
            for k in ("size", "payoff"):
                v = (tags.get(str(t["id"]), {}).get(k) or "").lower()
                if v: t[k] = v
    secs = sections(tasks, wip, since)
    td = todo(steps, a.chains) if steps and not a.share else None
    if a.share:
        terms = load_terms(a.terms)
        secs = [(n, g, [shared(t, terms) for t in ts]) for n, g, ts in secs]
    if a.json:
        print(json.dumps({"since": since.isoformat(), "share": a.share, "todo": td,
                          "sections": [{"name": n, "group_by": g or None, "tasks": ts} for n, g, ts in secs]},
                         indent=1, ensure_ascii=False)); return
    head = f"# Status, {datetime.datetime.now():%Y-%m-%d %H:%M}" + (" (shareable)" if a.share else "") + "\n\n"
    sys.stdout.write(head + (todo_text(td, a.full).rstrip() + "\n\n" if td else "") + text(secs, since, a.share))


if __name__ == "__main__":
    main()
