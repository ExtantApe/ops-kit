#!/usr/bin/env python3
"""vendor: copy a folder from another repo at a pinned commit, and prove later that the copy hasn't drifted.
Plain Python 3.9+, no dependencies, no network.

  vendor.py lock  NAME --source CHECKOUT --from PATH --to PATH [--copy]
      Records NAME in vendor.lock.json: the source repo's remote URL, its HEAD commit, the two paths and a sha256 of
      every file. Only files git tracks in the source are vendored (ignored files, such as a .env, never are).
      Refuses unless PATH is committed and clean in the source and the copy matches it byte for byte. --copy copies
      it first; it replaces a folder only if the lock already records it as NAME's copy (or it's empty), never a
      folder holding anything else, never a path through .git, and never when the source holds a symlink.
  vendor.py check [NAME ...] [--source NAME=CHECKOUT ...]
      Fails if a copy differs from its lock: an edited, missing or extra file. With --source it also warns, without
      failing, when the source has changed that path since the locked commit.
  vendor.py list
      One line per vendored folder: name, commit, file count, where it came from.

Options for every command: --root REPO (default: the current directory). The lock lives at REPO/vendor.lock.json.
Vendored copies are read-only by agreement: change them upstream, then lock again.
"""
import argparse, hashlib, json, os, re, shutil, subprocess, sys

LOCK = "vendor.lock.json"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


HEX = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def files(folder):
    """Every file under folder, as sorted forward-slash paths relative to it. Symlinks (files or folders) are refused."""
    out = []
    for d, dirs, fs in os.walk(folder):
        for x in dirs + fs:
            if os.path.islink(os.path.join(d, x)):
                sys.exit(f"vendor: {os.path.join(d, x)} is a symlink; vendored folders hold plain files only")
        dirs[:] = sorted(x for x in dirs if x != ".git")
        out += [os.path.relpath(os.path.join(d, f), folder).replace(os.sep, "/") for f in fs]
    return sorted(out)


def tracked(src, rel):
    """The files git tracks under rel in src, relative to rel, refusing symlinks and submodules."""
    out = []
    for line in git(src, "ls-files", "-s", "-z", "--", rel).split("\0"):
        if not line:
            continue
        meta, path = line.split("\t", 1)
        if not meta.startswith("100"):
            sys.exit(f"vendor: {path} in the source is a symlink or submodule; vendored folders hold plain files only")
        out.append(os.path.relpath(path, rel).replace(os.sep, "/"))
    return sorted(out)


def sums(folder):
    return {f: sha256(os.path.join(folder, f)) for f in files(folder)}


def git(cwd, *args):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"vendor: git {' '.join(args)} failed in {cwd}: {r.stderr.strip()}")
    return r.stdout.strip()


def inside(root, rel):
    if ".git" in rel.replace("\\", "/").split("/"):
        sys.exit(f"vendor: {rel} goes through .git")
    p = os.path.realpath(os.path.join(root, rel))
    if not (p + os.sep).startswith(os.path.realpath(root) + os.sep) or p == os.path.realpath(root):
        sys.exit(f"vendor: {rel} must be a folder inside {root}")
    return p


def read_lock(root):
    try:
        with open(os.path.join(root, LOCK), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except ValueError:
        sys.exit(f"vendor: {LOCK} isn't valid JSON")


def write_lock(root, lock):
    path = os.path.join(root, LOCK)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(lock, f, indent=1, sort_keys=True); f.write("\n")
    os.replace(path + ".tmp", path)


def diff(want, have):
    out = [f"edited: {f}" for f in sorted(want) if f in have and have[f] != want[f]]
    out += [f"missing: {f}" for f in sorted(want) if f not in have]
    out += [f"extra: {f}" for f in sorted(have) if f not in want]
    return out


def cmd_lock(a, root):
    if not NAME.match(a.name):
        sys.exit("vendor: a name is lowercase letters, digits, dots, dashes and underscores")
    src = os.path.realpath(a.source)
    from_ = inside(src, a.frm)
    to = inside(root, a.to)
    if not os.path.isdir(from_):
        sys.exit(f"vendor: {a.frm} isn't a folder in {src}")
    if git(src, "status", "--porcelain", "--", a.frm):
        sys.exit(f"vendor: {a.frm} has uncommitted changes in the source; commit them first")
    commit = git(src, "rev-parse", "HEAD")
    names = tracked(src, os.path.relpath(from_, src))            # checked before anything here is touched
    if not names:
        sys.exit(f"vendor: git tracks no files under {a.frm} in the source")
    lock = read_lock(root)
    if a.copy:
        mine = a.name in lock and os.path.realpath(os.path.join(root, lock[a.name]["to"])) == to
        if os.path.exists(to) and not mine and (not os.path.isdir(to) or os.listdir(to)):
            sys.exit(f"vendor: {a.to} already holds files that aren't {a.name}'s locked copy; refusing to replace it")
        if os.path.exists(to):
            shutil.rmtree(to)
        for n in names:
            os.makedirs(os.path.dirname(os.path.join(to, n)), exist_ok=True)
            shutil.copyfile(os.path.join(from_, n), os.path.join(to, n))
    if not os.path.isdir(to):
        sys.exit(f"vendor: no copy at {a.to}; pass --copy")
    want = {n: sha256(os.path.join(from_, n)) for n in names}
    have = sums(to)
    if want != have:
        sys.exit("vendor: the copy doesn't match the source:\n  " + "\n  ".join(diff(want, have)))
    try:
        repo = git(src, "remote", "get-url", "origin")
    except SystemExit:
        repo = ""
    lock[a.name] = {"repo": repo, "commit": commit, "from": a.frm.strip("/"), "to": a.to.strip("/"), "files": want}
    write_lock(root, lock)
    print(f"locked {a.name}: {len(want)} files at {commit[:12]}")


def cmd_check(a, root):
    lock = read_lock(root)
    names = a.names or sorted(lock)
    srcs = dict(s.split("=", 1) for s in a.source or [] if "=" in s)
    bad = 0
    for n in names:
        if n not in lock:
            print(f"FAIL  {n}: not in {LOCK}"); bad += 1; continue
        e = lock[n]
        if not HEX.match(str(e.get("commit", ""))):
            print(f"FAIL  {n}: the lock's commit isn't a full commit hash"); bad += 1; continue
        to = inside(root, e["to"])
        problems = diff(e["files"], sums(to) if os.path.isdir(to) else {})
        if problems:
            print(f"FAIL  {n}: the copy differs from its lock\n  " + "\n  ".join(problems)); bad += 1
        else:
            print(f"ok    {n}: {len(e['files'])} files match {e['commit'][:12]}")
        if n in srcs:
            r = subprocess.run(["git", "-C", srcs[n], "diff", "--quiet", e["commit"], "HEAD", "--", e["from"]],
                               capture_output=True)
            if r.returncode == 1:
                print(f"note  {n}: the source changed {e['from']} since {e['commit'][:12]}; lock again when ready")
            elif r.returncode:
                print(f"note  {n}: couldn't compare with the source at {srcs[n]}")
    sys.exit(1 if bad else 0)


def cmd_list(a, root):
    for n, e in sorted(read_lock(root).items()):
        print(f"{n}\t{e['commit'][:12]}\t{len(e['files'])} files\t{e['repo'] or '(no remote)'}:{e['from']} -> {e['to']}")


def main(argv=None):
    p = argparse.ArgumentParser(description="Vendor a folder from another repo at a pinned commit, with checksums.")
    p.add_argument("--root", default=".")
    sub = p.add_subparsers(dest="cmd", required=True)
    lk = sub.add_parser("lock"); lk.add_argument("name"); lk.add_argument("--source", required=True)
    lk.add_argument("--from", dest="frm", required=True); lk.add_argument("--to", required=True)
    lk.add_argument("--copy", action="store_true")
    ck = sub.add_parser("check"); ck.add_argument("names", nargs="*"); ck.add_argument("--source", action="append")
    sub.add_parser("list")
    a = p.parse_args(argv)
    root = os.path.realpath(a.root)
    {"lock": cmd_lock, "check": cmd_check, "list": cmd_list}[a.cmd](a, root)


if __name__ == "__main__":
    main()
