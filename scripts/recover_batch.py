"""Import results from a tag batch whose pending_batch.json (result number -> skin ID map) was lost.

A batch numbers its entries s0, s1, ... in the order of the untagged skin list at submit time.
This script rebuilds that list from data/skins.json, leaving out the skins that were already
tagged at git ref --tagged-at, and only imports anything if the rebuilt list passes two checks:

  1. it has exactly as many entries as the batch, and
  2. (optional) it matches the map of another batch built from the same list (--check-map-at),
     entry for entry, over that batch's length.

Skins that already have tags are left alone. Run fetch_skins.py first, the same day if possible,
so the skin list matches what the batch was built from.

Usage:
  python scripts/recover_batch.py --batch-id msgbatch_... --tagged-at 5eff338 --check-map-at 8650551
Needs env ANTHROPIC_API_KEY.
"""
import argparse
import json
import subprocess
import sys

import requests

import tag_skins as ts


def git_json(ref, path):
    out = subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True, text=True, cwd=ts.ROOT)
    if out.returncode != 0:
        sys.exit(f"Couldn't read {path} at {ref}: {out.stderr.strip()}")
    return json.loads(out.stdout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-id", required=True)
    ap.add_argument("--tagged-at", required=True, help="git ref whose data/tags.json was current when the batch was submitted")
    ap.add_argument("--check-map-at", help="git ref with a data/pending_batch.json built from the same skin list")
    ap.add_argument("--image", choices=["best", "icon"], default="best", help="the --image setting the batch used")
    args = ap.parse_args()

    skins = ts.load_json(ts.SKINS, None)
    if skins is None:
        sys.exit("data/skins.json not found; run scripts/fetch_skins.py first.")
    already = set(git_json(args.tagged_at, "data/tags.json"))
    candidates = [s for s in skins if s["id"] not in already and s.get("icon")]

    h = ts.headers()
    b = requests.get(f"{ts.API}/messages/batches/{args.batch_id}", headers=h, timeout=60)
    b.raise_for_status()
    b = b.json()
    if b["processing_status"] != "ended":
        sys.exit(f"Batch is still {b['processing_status']}; try again once it has ended.")
    total = sum(b.get("request_counts", {}).values())

    problems = []
    if len(candidates) != total:
        problems.append(f"rebuilt list has {len(candidates)} entries but the batch has {total}")
    if args.check_map_at:
        other = git_json(args.check_map_at, "data/pending_batch.json")["id_map"]
        mismatched = [cid for cid, sid in other.items()
                      if int(cid[1:]) >= len(candidates) or candidates[int(cid[1:])]["id"] != sid]
        if mismatched:
            problems.append(f"{len(mismatched)} of {len(other)} entries differ from the map at {args.check_map_at} (first: {mismatched[0]})")
        else:
            print(f"Rebuilt order matches the {len(other)}-entry map at {args.check_map_at}.")
    if problems:
        print("Not importing, because the rebuilt order can't be trusted:")
        for p in problems:
            print("  - " + p)
        print("The skin list has probably changed since the batch was submitted.")
        sys.exit(1)

    _, allowed = ts.vocab_tags()
    tags_db = ts.load_json(ts.TAGS, {})
    res = requests.get(b["results_url"], headers=h, timeout=300)
    res.raise_for_status()
    imported = skipped = failed = 0
    report = []
    for line in res.text.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["result"]["type"] != "succeeded":
            continue
        skin = candidates[int(row["custom_id"][1:])]
        if skin["id"] in tags_db:
            skipped += 1
            continue
        rec, err = ts.parse_message(row["result"]["message"], allowed, ts.pick_images(skin, args.image)[1])
        if err:
            failed += 1
            print(f"  FAILED  {skin['name']}  [{skin['id']}]  {err}")
            continue
        tags_db[skin["id"]] = rec
        imported += 1
        print(f"  ok      {skin['name']}  [{skin['id']}]  {len(rec['tags'])} tags")
        report.append(f"| {ts.md_cell(skin['name'])} | `{ts.md_cell(skin['id'])}` | {len(rec['tags'])} |")
    ts.save_json(ts.TAGS, tags_db)
    msg = f"Imported {imported} entries from {args.batch_id}; skipped {skipped} that already had tags; {failed} unreadable."
    print(msg)
    rows = "\n".join(report[: ts.SUMMARY_ROWS])
    ts.step_summary(f"### {msg}\n\n<details><summary>Imported entries</summary>\n\n| Name | ID | Tags |\n|---|---|---|\n{rows}\n\n</details>\n")


if __name__ == "__main__":
    main()
