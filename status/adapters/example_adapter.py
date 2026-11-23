"""An example adapter for status.py. Copy it, point it at your own store, and run:

    python3 status/status.py --adapter my_adapter.py

tasks() returns task dicts in the common schema (see status.py's help). steps() is optional and returns owner steps.
WIP_LIMIT is optional (default 3): how many tasks one owner works at once.
"""
import json

WIP_LIMIT = 3


def tasks():
    # Replace with a read of your store. Here: a JSON Lines file with your own field names, mapped to the schema.
    out = []
    with open("my-tasks.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            out.append(dict(id=r["key"], title=r["summary"], priority=r.get("priority", "next"),
                            state="closed" if r.get("done") else "open", area=r.get("project", ""),
                            category=r.get("kind", ""), owner=r.get("assignee", ""),
                            size=r.get("size", ""), payoff=r.get("payoff", "")))
    return out


def steps():
    return []
