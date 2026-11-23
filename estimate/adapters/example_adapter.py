"""An example adapter for estimate.py. Copy it, point it at your own store, and run:

    python3 estimate/estimate.py --adapter my_adapter.py queue

tasks() returns task dicts in status.py's common schema: id, title, priority (now|next|soon|later|waiting)
and state (open|closed) are required; category, waiting_on and blocked are optional.
tags() is optional and returns {task id: {"size": "Hours|Days|Weeks", "payoff": "Major|Moderate|Minor"}} for stores
that keep size and payoff on the task itself. Without tags(), estimate reads its own tags file.
The adapter runs as Python with your permissions: use only adapters you wrote or have read.
"""
import json


def tasks():
    out = []
    with open("my-tasks.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            out.append(dict(id=r["key"], title=r["summary"], priority=r.get("priority", "next"),
                            state="closed" if r.get("done") else "open", category=r.get("kind", "")))
    return out


def tags():
    out = {}
    with open("my-tasks.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("size") and r.get("payoff"):
                out[r["key"]] = dict(size=r["size"], payoff=r["payoff"])
    return out
