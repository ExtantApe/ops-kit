"""Tests for status/status.py. Run: python3 -m unittest discover -s tests"""
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
STATUS = os.path.join(HERE, "..", "status", "status.py")
FENCE = "```"


def task(i, title, priority="next", state="open", **kw):
    return dict(id=i, title=title, priority=priority, state=state, area=kw.pop("area", "alpha"),
                category=kw.pop("category", "fix"), owner=kw.pop("owner", "Lead A"), **kw)


class Status(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.tasks = os.path.join(self.d, "tasks.jsonl")
        self.steps = os.path.join(self.d, "steps.jsonl")
        self.chains = os.path.join(self.d, "chains.json")
        self.write(self.tasks, [
            task("K1", "In flight", "now"),
            task("K2", "Untagged next"),
            task("K3", "Quick big win", size="hours", payoff="major"),
            task("K4", "Long bet", size="Weeks", payoff="Major"),
            task("K5", "Small chore", size="days", payoff="minor"),
            task("K6", "Shipped", "next", "closed", closed="2999-01-01T10:00:00Z", ref="abc123"),
            task("K7", "Private codename project", "soon", area="secret-area"),
        ])
        self.write(self.steps, [
            dict(id="N1", title="Approve Alpha on npm", state="open", category="Releases", duration="5 min",
                 body=f"1. In Terminal:\n{FENCE}\nnpm login\nnpm stage approve aaa\n{FENCE}\n2. Say done.\n"),
            dict(id="N2", title="Approve Beta on npm", state="open", category="Releases",
                 body=f"1. Run:\n{FENCE}\nnpm stage approve bbb\n{FENCE}\n"),
            dict(id="N3", title="Tidy two folders", state="open", category="Personal",
                 body=f"1. Run:\n{FENCE}\nmkdir -p /tmp/x-made-up\nls /tmp/x-made-up\n{FENCE}\n"),
            dict(id="N4", title="Click the thing", state="open", category="Personal",
                 body=f"1. Open the app and click Save, then:\n{FENCE}\nls\npwd\n{FENCE}\n"),
            dict(id="N5", title="Pick a name", state="open", category="Personal", kind="pick",
                 body=f"1. Then:\n{FENCE}\nls\npwd\n{FENCE}\n"),
            dict(id="N6", title="Already done", state="reported", category="Personal", body="1. x\n"),
            dict(id="T1", title="Play the lobby", state="open", kind="test", body="1. Walk around.\n"),
        ])

    def write(self, path, rows):
        with open(path, "w") as f:
            f.write("\n".join(json.dumps(r) for r in rows) + "\n")

    def run_status(self, *args, ok=True):
        r = subprocess.run([sys.executable, STATUS, "--source", self.tasks, "--chains", self.chains, *args],
                           capture_output=True, text=True)
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def out(self, *args):
        return self.run_status(*args).stdout

    def test_sections_in_order(self):
        o = self.out()
        names = [l for l in o.splitlines() if l.startswith("## ")]
        self.assertEqual([n.split(" (")[0] for n in names],
                         ["## Done this week", "## In progress", "## Priority queue", "## Next", "## Soon", "## Everything else"])

    def test_bucket_order_and_untagged_last(self):
        q = self.out().split("## Priority queue")[1].split("## Next")[0]
        ids = [l.split()[1] for l in q.splitlines() if l.startswith("- ")]
        self.assertEqual(ids, ["K3", "K4"])            # 2 free slots (WIP 3, one "now"): Steal, then Bet
        nxt = self.out().split("## Next")[1].split("## Soon")[0]
        self.assertIn("K5  [Chore]", nxt)
        self.assertIn("K2  [untagged]", nxt)
        self.assertLess(nxt.index("K5"), nxt.index("K2"))

    def test_done_this_week(self):
        self.assertIn("ref abc123", self.out("--since", "2000-01-01").split("## In progress")[0])

    def test_share_needs_terms_and_hides_private(self):
        self.assertNotEqual(self.run_status("--share", ok=False).returncode, 0)
        terms = os.path.join(self.d, "terms"); open(terms, "w").write("codename\nsecret-area\n")
        o = self.out("--share", "--terms", terms)
        self.assertNotIn("codename", o); self.assertNotIn("secret-area", o); self.assertNotIn("Lead A", o)
        self.assertIn("K7  [untagged]  Fix task", o)

    def test_share_hides_a_private_category(self):
        self.write(self.tasks, [task("K9", "Codename work", "later", category="codename")])
        terms = os.path.join(self.d, "terms"); open(terms, "w").write("codename\n")
        o = self.out("--share", "--terms", terms); j = self.out("--share", "--terms", terms, "--json")
        self.assertNotIn("codename", o.lower()); self.assertNotIn("codename", j.lower())
        self.assertIn("K9  [untagged]  Private task", o)

    def test_adapter_must_be_a_py_file(self):
        r = subprocess.run([sys.executable, STATUS, "--adapter", os.path.join(self.d, "nope.txt")], capture_output=True, text=True)
        self.assertIn("must be an existing .py file", r.stderr)

    def test_todo_and_chains(self):
        o = self.out("--steps", self.steps, "--full")
        self.assertTrue(o.split("\n", 3)[2].startswith("## Your to-do (6)"))
        self.assertIn("npm login && npm stage approve aaa && npm stage approve bbb", o)
        self.assertIn("mkdir -p /tmp/x-made-up && ls /tmp/x-made-up", o)
        self.assertNotRegex(o, r"N4 Click the thing.*\[C")
        self.assertNotRegex(o, r"N5 Pick a name.*\[C")
        self.assertNotIn("N6 ", o)

    def test_chain_ids_stable_and_never_reused(self):
        self.out("--steps", self.steps); self.out("--steps", self.steps)
        self.assertEqual(sorted(json.load(open(self.chains))), ["C1", "C2"])
        rows = [json.loads(l) for l in open(self.steps)]
        rows[1]["state"] = "reported"; self.write(self.steps, rows)
        o = self.out("--steps", self.steps)
        self.assertNotIn("C1 =", o)          # N1 alone is login + 1 command: still a chain, with a new ID
        self.assertIn("C3 = N1", o)

    def test_resolve(self):
        self.out("--steps", self.steps)
        r = subprocess.run([sys.executable, STATUS, "resolve", "c2", "--chains", self.chains], capture_output=True, text=True)
        self.assertEqual(r.stdout.split(), ["N3"])

    def test_short_view_folds_tests(self):
        self.assertIn("### Tests (1): T1. Steps: --full", self.out("--steps", self.steps))

    def test_share_has_no_todo(self):
        terms = os.path.join(self.d, "terms"); open(terms, "w").write("nothing-matches-this\n")
        self.assertNotIn("Your to-do", self.out("--steps", self.steps, "--share", "--terms", terms))

    def test_json(self):
        d = json.loads(self.out("--steps", self.steps, "--json"))
        self.assertEqual(d["todo"]["count"], 6)
        self.assertEqual([s["name"] for s in d["sections"]][0], "Done this week")

    def test_bad_rows_refused(self):
        self.write(self.tasks, [dict(id="K1", title="x", priority="someday", state="open")])
        self.assertNotEqual(self.run_status(ok=False).returncode, 0)

    def test_tags_file_overlays_size_and_payoff(self):
        tags = os.path.join(self.d, "tags.json"); open(tags, "w").write('[{"id": "K2", "size": "Hours", "payoff": "Moderate"}]')
        self.assertIn("K2  [Pickup]", self.out("--tags", tags))

    def test_adapter(self):
        ad = os.path.join(self.d, "ad.py")
        open(ad, "w").write("WIP_LIMIT = 1\ndef tasks():\n    return [dict(id='X-1', title='From an adapter', priority='next', state='open', owner='B'),"
                            " dict(id='X-2', title='Second', priority='next', state='open', owner='B')]\n")
        r = subprocess.run([sys.executable, STATUS, "--adapter", ad, "--chains", self.chains], capture_output=True, text=True)
        q = r.stdout.split("## Priority queue")[1].split("## Next")[0]
        self.assertIn("X-1", q); self.assertNotIn("X-2", q)


if __name__ == "__main__":
    unittest.main()
