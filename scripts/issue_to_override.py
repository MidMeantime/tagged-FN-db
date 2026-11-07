"""Turn a "Tag fix" issue into a row in data/overrides.csv.

The site's "Suggest a tag fix" button opens an issue with the skin's ID and its tag list in a code
block, which the reporter edits in place (Danbooru style). This script reads that issue, compares
the edited list with the skin's current tags on the live site, and writes the difference into
data/overrides.csv as add_tags / remove_tags. If the skin already has a row, the row is updated.

Usage:
  python scripts/issue_to_override.py 42              # read issue #42 from GitHub
  python scripts/issue_to_override.py --file fix.txt  # or from text you saved / pasted into a file
  python scripts/issue_to_override.py 42 --dry-run    # show the change without writing it
  python scripts/issue_to_override.py 42 --verified   # also mark the skin as verified

Current tags come from the published site (data/tags.csv). Use --tags-csv to point at a local
copy instead, e.g. site/data/tags.csv after running build_site_data.py.
"""
import argparse
import csv
import difflib
import io
import re
import subprocess
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OVERRIDES = ROOT / "data" / "overrides.csv"
DEFAULT_REPO = "MidMeantime/tagged-FN-db"
COLUMNS = ["id", "name", "add_tags", "remove_tags", "verified", "notes", "group", "caption", "caption_replace"]


def split_tags(text):
    return [t.strip().lower() for t in re.split(r"[,\s]+", text or "") if t.strip()]


def repo_slug():
    """owner/repo from the git remote, so the script also works in forks."""
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
        m = re.search(r"github\.com[:/]([^/]+/[^/.]+?)(?:\.git)?$", url)
        if m:
            return m.group(1)
    except (OSError, subprocess.CalledProcessError):
        pass
    return DEFAULT_REPO


def read_issue(number, repo):
    r = requests.get(f"https://api.github.com/repos/{repo}/issues/{number}", timeout=30,
                     headers={"Accept": "application/vnd.github+json"})
    if r.status_code == 404:
        sys.exit(f"Issue #{number} not found in {repo}.")
    r.raise_for_status()
    return r.json().get("body") or ""


def parse_issue(body):
    """Return (skin id, skin name, edited tag list) from the issue text."""
    m = re.search(r"^\s*ID:\s*(\S+)", body, re.M)
    if not m:
        sys.exit("Couldn't find an 'ID:' line in the issue.")
    sid = m.group(1)
    name_m = re.search(r"^\s*Skin:\s*(.+?)\s*$", body, re.M)
    block = re.search(r"```[^\n]*\n(.*?)```", body, re.S)
    if not block:
        sys.exit("Couldn't find the tag list (the block between ``` lines) in the issue.")
    return sid, (name_m.group(1) if name_m else ""), split_tags(block.group(1))


def vocab_tags():
    import json
    try:
        v = json.loads((ROOT / "tagging" / "vocab.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [t for c in v.get("categories", {}).values() for t in c.get("tags", [])]


def current_tags(sid, tags_csv):
    if tags_csv:
        text = Path(tags_csv).read_text(encoding="utf-8")
    else:
        owner, repo = repo_slug().split("/")
        url = f"https://{owner.lower()}.github.io/{repo}/data/tags.csv"
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        r.encoding = "utf-8"
        text = r.text
    for row in csv.DictReader(io.StringIO(text)):
        if row["id"] == sid:
            return split_tags(row.get("tags"))
    sys.exit(f"{sid} isn't in the published tag list. Check the ID, or pass --tags-csv.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("issue", nargs="?", type=int, help="issue number on GitHub")
    ap.add_argument("--file", help="read the issue text from this file instead")
    ap.add_argument("--repo", help="owner/repo (default: from the git remote)")
    ap.add_argument("--tags-csv", help="local tags.csv to compare against (default: the live site's)")
    ap.add_argument("--verified", action="store_true", help="also set verified = yes on the row")
    ap.add_argument("--dry-run", action="store_true", help="print the change without writing it")
    args = ap.parse_args()
    if not args.issue and not args.file:
        ap.error("give an issue number or --file")

    body = Path(args.file).read_text(encoding="utf-8") if args.file else read_issue(args.issue, args.repo or repo_slug())
    sid, name, wanted = parse_issue(body)
    now = current_tags(sid, args.tags_csv)
    add = [t for t in wanted if t not in now]
    remove = [t for t in now if t not in wanted]
    known = vocab_tags()
    unknown = [t for t in add if known and t not in known]
    print(f"{name or sid} [{sid}]")
    print(f"  add:    {' '.join(add) or '(nothing)'}")
    print(f"  remove: {' '.join(remove) or '(nothing)'}")
    if unknown:
        close = {t: difflib.get_close_matches(t, known, n=1) for t in unknown}
        hints = ", ".join(f"{t} (did you mean {c[0]}?)" if c else t for t, c in close.items())
        print(f"  note: not in tagging/vocab.json: {hints}. They'll still be added, under \"Other\".")
    if not add and not remove and not args.verified:
        print("The edited list matches the current tags; nothing to change.")
        return

    # Read the overrides, keeping its column order and line endings.
    raw = OVERRIDES.read_bytes().decode("utf-8-sig") if OVERRIDES.exists() else ""
    newline = "\r\n" if "\r\n" in raw else "\n"
    reader = csv.DictReader(io.StringIO(raw))
    fields = reader.fieldnames or COLUMNS
    rows = list(reader)
    for col in ("add_tags", "remove_tags", "verified", "name"):
        if col not in fields:
            fields.append(col)

    row = next((r for r in rows if r.get("id") == sid), None)
    if row is None:
        row = {f: "" for f in fields}
        row.update({"id": sid, "name": name})
        rows.append(row)
        print("  -> new row in data/overrides.csv")
    else:
        print("  -> updating the existing row in data/overrides.csv")
    # Current tags already include this row's earlier edits, so fold the new diff into them.
    old_add, old_remove = split_tags(row.get("add_tags")), split_tags(row.get("remove_tags"))
    new_add = [t for t in old_add if t not in remove] + [t for t in add if t not in old_add]
    new_remove = [t for t in old_remove if t not in add] + [t for t in remove if t not in old_remove]
    row["add_tags"], row["remove_tags"] = " ".join(new_add), " ".join(new_remove)
    if args.verified:
        row["verified"] = "yes"
    if not row.get("name"):
        row["name"] = name

    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=fields, lineterminator=newline, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    if args.dry_run:
        print("\nDry run; the row would be:")
        print("  " + out.getvalue().splitlines()[1 + rows.index(row)])
        return
    OVERRIDES.write_bytes(out.getvalue().encode("utf-8"))
    print("Saved. Commit data/overrides.csv (mention the issue, e.g. 'Fixes #12') to apply it.")


if __name__ == "__main__":
    main()
