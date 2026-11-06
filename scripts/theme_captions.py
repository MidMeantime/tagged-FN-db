"""Rewrite captions for themed styles (team/house/club picks) with a short text-only Haiku call.

A themed style (group = themes in the overrides) is the base outfit representing a different
team or house, e.g. Slytherin instead of Gryffindor. Its tags are copied from the base skin, and its
caption should be too, with only the house/team name and its colors changed. This script asks Haiku
for exactly that, using the style's name and the description of its crest/logo.

Results go to data/theme_captions.json, keyed by style ID and stored with the base caption they were
made from, so a style is only rewritten again if its base skin's caption changes. Text only, no
images: a few hundred styles cost well under a cent.

Usage: python scripts/theme_captions.py [--limit N]
Needs env ANTHROPIC_API_KEY.
"""
import argparse
import json

import requests

import build_site_data as b
import tag_skins as ts

PROMPT = """Below is a one-sentence description of a Fortnite outfit in its default style{default}.

The "{style}" style is the SAME outfit, changed only to represent {style} instead.{icon}

Rewrite the description for the {style} style. Change only what represents the team, house or club: its name, and colors or symbols that belong to it. Keep everything else word for word. If nothing in the description is specific to the default team or house, return it unchanged. Reply with the new description only.

Description: {src}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--model", default=ts.DEFAULT_MODEL)
    args = ap.parse_args()

    skins = b.load_json(b.DATA / "skins.json", None)
    if skins is None:
        raise SystemExit("data/skins.json not found; run scripts/fetch_skins.py first.")
    caps = b.load_json(b.THEME_CAPTIONS, {})
    by_id, *_ = b.build_records(skins, b.load_json(b.DATA / "tags.json", {}),
                                b.load_json(b.ROOT / "tagging" / "vocab.json", {"categories": {}}), caps)
    todo = [(sid, r["_req"]) for sid, r in by_id.items() if r.get("_req")]
    if args.limit:
        todo = todo[: args.limit]
    if not todo:
        print("All themed style captions are up to date.")
        return
    print(f"Rewriting captions for {len(todo)} themed styles…")
    h = ts.headers()
    done = 0
    for sid, q in todo:
        prompt = PROMPT.format(
            default=f', which represents {q["default"]}' if q["default"] else "",
            style=q["style"],
            icon=f' Its style preview is this emblem: {q["icon"]}' if q["icon"] else "",
            src=q["src"],
        )
        r = requests.post(f"{ts.API}/messages", headers=h, timeout=120, json={
            "model": args.model, "max_tokens": 400,
            "messages": [{"role": "user", "content": prompt}],
        })
        if r.status_code != 200:
            print(f"  FAILED  {q['name']}  [{sid}]  HTTP {r.status_code}: {ts.api_error(r)}")
            continue
        msg = r.json()
        text = "".join(blk.get("text", "") for blk in msg.get("content", []) if blk.get("type") == "text").strip()
        if msg.get("stop_reason") == "refusal" or not text:
            print(f"  FAILED  {q['name']}  [{sid}]  empty reply")
            continue
        caps[sid] = {"src": q["src"], "caption": text}
        done += 1
        print(f"  ok      {q['name']}: {text}")
        if done % 25 == 0:
            ts.save_json(b.THEME_CAPTIONS, caps)  # keep progress if the job is stopped
    ts.save_json(b.THEME_CAPTIONS, caps)
    print(f"Rewrote {done} of {len(todo)} captions.")
    ts.step_summary(f"### Themed style captions: rewrote {done} of {len(todo)}")


if __name__ == "__main__":
    main()
