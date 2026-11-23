"""Tests for vendor/vendor.py. Run: python3 -m unittest discover -s tests"""
import os, subprocess, sys, tempfile, unittest

VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vendor", "vendor.py")


def sh(cwd, *cmd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


class Vendor(unittest.TestCase):
    def setUp(self):
        self.src = tempfile.mkdtemp(); self.dst = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.src, "tools", "pace"))
        open(os.path.join(self.src, "tools", "pace", "pace.py"), "w").write("print('pace')\n")
        open(os.path.join(self.src, "tools", "pace", "README.md"), "w").write("# pace\n")
        sh(self.src, "git", "init", "-q"); sh(self.src, "git", "add", ".")
        sh(self.src, "git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "one")

    def v(self, *args):
        return subprocess.run([sys.executable, VENDOR, "--root", self.dst, *args], capture_output=True, text=True)

    def lock(self, *extra):
        return self.v("lock", "pace", "--source", self.src, "--from", "tools/pace", "--to", "vendor/pace", *extra)

    def test_lock_needs_a_copy_then_checks_clean(self):
        self.assertNotEqual(self.lock().returncode, 0)
        r = self.lock("--copy"); self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("2 files", r.stdout)
        self.assertEqual(self.v("check").returncode, 0)

    def test_check_catches_edit_missing_extra(self):
        self.lock("--copy")
        p = os.path.join(self.dst, "vendor", "pace")
        open(os.path.join(p, "pace.py"), "a").write("# hand edit\n")
        os.remove(os.path.join(p, "README.md"))
        open(os.path.join(p, "new.txt"), "w").write("x")
        r = self.v("check")
        self.assertEqual(r.returncode, 1)
        for want in ("edited: pace.py", "missing: README.md", "extra: new.txt"):
            self.assertIn(want, r.stdout)

    def test_refuses_uncommitted_source(self):
        open(os.path.join(self.src, "tools", "pace", "pace.py"), "a").write("# wip\n")
        self.assertIn("uncommitted", self.lock("--copy").stderr)

    def test_refuses_paths_outside(self):
        r = self.v("lock", "pace", "--source", self.src, "--from", "../", "--to", "vendor/pace", "--copy")
        self.assertNotEqual(r.returncode, 0)

    def test_notes_when_source_moves_ahead(self):
        self.lock("--copy")
        open(os.path.join(self.src, "tools", "pace", "pace.py"), "a").write("# v2\n")
        sh(self.src, "git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qam", "two")
        r = self.v("check", "--source", f"pace={self.src}")
        self.assertEqual(r.returncode, 0)
        self.assertIn("the source changed tools/pace", r.stdout)

    def test_never_replaces_another_folder_or_git(self):
        os.makedirs(os.path.join(self.dst, "status")); open(os.path.join(self.dst, "status", "keep.py"), "w").close()
        r = self.v("lock", "pace", "--source", self.src, "--from", "tools/pace", "--to", "status", "--copy")
        self.assertIn("refusing to replace", r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.dst, "status", "keep.py")))
        os.makedirs(os.path.join(self.dst, ".git"))
        r = self.v("lock", "pace", "--source", self.src, "--from", "tools/pace", "--to", ".git", "--copy")
        self.assertIn("goes through .git", r.stderr)
        self.assertTrue(os.path.isdir(os.path.join(self.dst, ".git")))

    def test_relock_replaces_its_own_copy(self):
        self.lock("--copy")
        self.assertEqual(self.lock("--copy").returncode, 0)

    def test_ignored_files_are_never_vendored(self):
        open(os.path.join(self.src, ".gitignore"), "w").write(".env\n")
        open(os.path.join(self.src, "tools", "pace", ".env"), "w").write("SECRET=1\n")
        sh(self.src, "git", "add", ".gitignore")
        sh(self.src, "git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "ignore")
        self.assertEqual(self.lock("--copy").returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.dst, "vendor", "pace", ".env")))
        self.assertNotIn(".env", open(os.path.join(self.dst, "vendor.lock.json")).read())

    def test_symlink_in_source_refused_before_touching_the_copy(self):
        self.lock("--copy")
        os.symlink("/etc/hosts", os.path.join(self.src, "tools", "pace", "hosts"))
        sh(self.src, "git", "add", ".")
        sh(self.src, "git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "link")
        self.assertIn("symlink", self.lock("--copy").stderr)
        self.assertEqual(self.v("check").returncode, 0)          # the old copy is untouched

    def test_symlinked_folder_in_copy_fails_check(self):
        self.lock("--copy")
        os.symlink(self.src, os.path.join(self.dst, "vendor", "pace", "outside"))
        self.assertNotEqual(self.v("check").returncode, 0)

    def test_bad_commit_in_lock_is_refused(self):
        import json
        self.lock("--copy")
        lk = os.path.join(self.dst, "vendor.lock.json"); d = json.load(open(lk))
        target = os.path.join(self.dst, "victim"); open(target, "w").write("keep")
        d["pace"]["commit"] = "--output=" + target; json.dump(d, open(lk, "w"))
        r = self.v("check", "--source", f"pace={self.src}")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(open(target).read(), "keep")

    def test_list(self):
        self.lock("--copy")
        self.assertIn("2 files", self.v("list").stdout)


if __name__ == "__main__":
    unittest.main()
