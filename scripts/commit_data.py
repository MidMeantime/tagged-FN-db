"""Commit generated data files from a workflow without git merge conflicts.

Several workflows write to data/ (tag runs, recovery, the daily deploy's shop renders), and one
can finish while another is still running from an older checkout. A plain `git pull --rebase`
then conflicts, because git can't merge two edited JSON files. This script instead:

  1. fetches the latest main,
  2. merges each JSON dict file entry by entry: starting from the latest version on main, it applies
     only the entries this run changed or removed compared to the commit it checked out,
  3. for other files, takes this run's version (or its deletion) only if this run changed it,
  4. commits on top of the latest main and pushes, retrying if main moved again.

Usage: python scripts/commit_data.py -m "message" data/tags.json data/renders.json ...
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JSON_DICT_FILES = {"data/tags.json", "data/renders.json", "data/tag_errors.json"}
MISSING = object()


def git(*args, check=True):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r


def show(ref, path):
    r = git("show", f"{ref}:{path}", check=False)
    return r.stdout if r.returncode == 0 else MISSING


def as_dict(text):
    if text is MISSING or not text.strip():
        return {}
    return json.loads(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", "--message", required=True)
    ap.add_argument("paths", nargs="+")
    args = ap.parse_args()

    base = git("rev-parse", "HEAD").stdout.strip()
    ours = {p: ((ROOT / p).read_text(encoding="utf-8") if (ROOT / p).exists() else MISSING) for p in args.paths}

    for attempt in range(5):
        git("fetch", "-q", "origin", "main")
        theirs_ref = git("rev-parse", "FETCH_HEAD").stdout.strip()
        merged = {}
        for p in args.paths:
            if p in JSON_DICT_FILES:
                b, o, t = as_dict(show(base, p)), as_dict(ours[p]), as_dict(show(theirs_ref, p))
                for k, v in o.items():
                    if b.get(k, MISSING) != v:
                        t[k] = v            # added or changed by this run
                for k in b:
                    if k not in o:
                        t.pop(k, None)      # removed by this run
                merged[p] = json.dumps(t, indent=1, ensure_ascii=False, sort_keys=True)
            else:
                b = show(base, p)
                # Keep main's version (or its deletion) unless this run actually changed the file.
                merged[p] = show(theirs_ref, p) if ours[p] == b else ours[p]

        git("reset", "-q", "--mixed", theirs_ref)  # move onto latest main; working tree is left alone
        for p, text in merged.items():
            f = ROOT / p
            if text is MISSING:
                if f.exists():
                    f.unlink()
                git("rm", "-q", "--cached", "--ignore-unmatch", "--", p)
            else:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(text, encoding="utf-8")
                git("add", "--", p)
        if git("diff", "--cached", "--quiet", check=False).returncode == 0:
            print("No data changes to commit.")
            return
        git("commit", "-q", "-m", args.message)
        if git("push", "-q", "origin", "HEAD:main", check=False).returncode == 0:
            print(f"Committed and pushed: {args.message}")
            return
        print(f"Push rejected (main moved), retrying ({attempt + 1}/5)…")
    sys.exit("Couldn't push after 5 attempts.")


if __name__ == "__main__":
    main()
