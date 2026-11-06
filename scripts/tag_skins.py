"""Tag outfit images with Claude Haiku 5.5 using the Danbooru-style vocabulary in tagging/vocab.json.

By default only skins that don't have tags yet are sent, so re-running is cheap.
Images are sent to Claude as Fortnite-API URLs; nothing is downloaded.

Usage:
  python scripts/tag_skins.py --test 5        # tag 5 skins right away (no batch) and print results
  python scripts/tag_skins.py                 # tag every untagged skin through the Batch API (half price) and wait
  python scripts/tag_skins.py --no-wait       # submit the batch and exit; collect later with --collect
  python scripts/tag_skins.py --collect       # collect a batch submitted earlier
  python scripts/tag_skins.py --ids CID_A,CID_B --retag   # re-tag specific skins
  python scripts/tag_skins.py --upgrade       # re-tag skins whose feet were cut off, now that a shop render exists

Needs env ANTHROPIC_API_KEY.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
SKINS = ROOT / "data" / "skins.json"
TAGS = ROOT / "data" / "tags.json"
ERRORS = ROOT / "data" / "tag_errors.json"
PENDING = ROOT / "data" / "pending_batch.json"
VOCAB = ROOT / "tagging" / "vocab.json"

API = "https://api.anthropic.com/v1"
DEFAULT_MODEL = "claude-haiku-5-5"

SCHEMA = {
    "type": "object",
    "properties": {
        "tags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tag": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["tag", "confidence"],
                "additionalProperties": False,
            },
        },
        "suggested_new_tags": {"type": "array", "items": {"type": "string"}},
        "caption": {"type": "string"},
        "feet_visible": {"type": "boolean"},
    },
    "required": ["tags", "suggested_new_tags", "caption", "feet_visible"],
    "additionalProperties": False,
}

INSTRUCTIONS = """You tag Fortnite outfit (skin) renders for a searchable database, using Danbooru tag conventions.

Rules:
- Use ONLY tags from the vocabulary below, spelled exactly as written.
- Tag only what is visible in the image. The name and description are context, not evidence: do not tag things you merely expect a character with that name to have.
- Always give: one subject tag (1girl / 1boy / 1other / no_humans or a creature tag; use 1other when presentation is unclear), at least one hair tag (or bald, or hood_up/helmet when hair is hidden), 1-3 dominant color *_theme tags, exactly one main shading tag from the style category, and 1-4 theme tags.
- Then add every clearly visible accessory, headwear, face item, clothing piece and held item. Aim for 15-40 tags total.
- confidence: high = clearly visible; medium = probably right; low = guess. Prefer leaving a tag out over a low-confidence guess.
- suggested_new_tags: up to 5 important visible things the vocabulary is missing, written as Danbooru-style tags (lowercase_with_underscores). Leave empty if nothing is missing.
- caption: one plain sentence describing the outfit.
- feet_visible: true only if the character's feet are visible in an image that shows this exact style. If they are cut off, do NOT tag footwear (boots, sneakers, high_heels, sandals, barefoot) and only tag legwear you can actually see.

Images: the FIRST image always shows the exact style you are tagging, so it is the authority on colors, hair, headwear, face and materials. If there is a SECOND image, it is a larger promo render of the same outfit that may show a DIFFERENT style. Use it only for parts the first image cuts off (legs, shoes) and only when its visible parts match the first image; if it clearly shows another style, ignore it.

Shading definitions (pick the closest one as the main shading tag):
- cel_shading: hard-edged shadow bands with only 2-3 tones per color, comic or anime look, often with outlines.
- toon_(style): exaggerated cartoon proportions and simple shapes (pair with cel_shading or soft_shading).
- flat_color: almost no shading at all.
- gradient_shading: colors fade smoothly into each other as part of the design (ombre, glowing fades), not just from lighting.
- soft_shading: the standard Fortnite look, smooth stylized 3D lighting.
- realistic_3d: realistic materials, skin and fabric detail (common on licensed movie/game characters).
- lego_style: LEGO minifigure style.

Vocabulary by category:
"""


def load_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path, data):
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def vocab_tags():
    v = load_json(VOCAB, None)
    cats = {k: c for k, c in v["categories"].items() if not c.get("derived")}
    text = "\n".join(f"[{c['label']}] " + ", ".join(c["tags"]) for c in cats.values())
    allowed = {t for c in cats.values() for t in c["tags"]}
    return text, allowed


def pick_images(skin, kind):
    """Return (list of urls, label). The icon always comes first because it shows this exact style.

    'best' adds the shop render (or else the featured image) as a second image, to help with shoes.
    Style entries only have their own icon.
    """
    urls, used = [], []
    if skin.get("icon"):
        urls.append(skin["icon"]); used.append("icon")
    if kind == "best":
        for k in ("render", "featured"):
            if skin.get(k) and skin[k] not in urls:
                urls.append(skin[k]); used.append(k)
                break
    return urls, "+".join(used)


def build_params(skin, model, image_kind, mode, system_text):
    imgs, _ = pick_images(skin, image_kind)
    style = f"Style being tagged: {skin['style']} (an alternate style of {skin['name'].rsplit(' (', 1)[0]})\n" if skin.get("of") else ""
    user_text = (
        f"Outfit name: {skin['name']}\n{style}"
        f"In-game description: {skin.get('description') or '(none)'}\n"
        f"Set: {skin.get('set') or '(none)'}\n"
        "Tag the outfit shown in the image."
    )
    params = {
        "model": model,
        "max_tokens": 2000,
        "system": [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
        "messages": [{
            "role": "user",
            "content": [{"type": "image", "source": {"type": "url", "url": u}} for u in imgs]
                       + [{"type": "text", "text": user_text}],
        }],
    }
    if mode == "tool":
        # Fallback for endpoints without structured outputs: force a tool call whose input is the JSON.
        params["tools"] = [{"name": "save_tags", "description": "Save the tags for this outfit.", "input_schema": SCHEMA}]
        params["tool_choice"] = {"type": "tool", "name": "save_tags"}
    else:
        params["output_config"] = {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}}
    return params


def parse_message(msg, allowed, image_used=""):
    """Return (record, error). Keeps only vocabulary tags; unknown ones become suggestions."""
    stop = msg.get("stop_reason")
    if stop == "refusal":
        return None, "refusal"
    data = None
    for block in msg.get("content", []):
        if block.get("type") == "tool_use":
            data = block.get("input")
        elif block.get("type") == "text" and data is None:
            txt = block["text"].strip()
            start, end = txt.find("{"), txt.rfind("}")
            if start != -1:
                try:
                    data = json.loads(txt[start:end + 1])
                except json.JSONDecodeError:
                    pass
    if not isinstance(data, dict):
        return None, f"no JSON in response (stop_reason={stop})"
    tags, unknown, seen = [], [], set()
    for t in data.get("tags", []):
        name = str(t.get("tag", "")).strip().lower().replace(" ", "_")
        if not name or name in seen:
            continue
        seen.add(name)
        if name in allowed:
            tags.append([name, t.get("confidence", "medium")])
        else:
            unknown.append(name)
    suggestions = sorted(set(unknown + [str(s).strip().lower().replace(" ", "_") for s in data.get("suggested_new_tags", [])]) - {""})
    return {
        "tags": tags,
        "suggested": suggestions,
        "caption": data.get("caption", ""),
        "feet_visible": bool(data.get("feet_visible", True)),
        "image": image_used,
        "model": msg.get("model", ""),
        "tagged_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }, None


def headers():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("Set ANTHROPIC_API_KEY first.")
    return {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}


def api_error(r):
    try:
        return r.json().get("error", {}).get("message", r.text)
    except ValueError:
        return r.text


def run_test(skins, args, system_text, allowed, tags_db, errors):
    for skin in skins:
        params = build_params(skin, args.model, args.image, args.mode, system_text)
        r = requests.post(f"{API}/messages", headers=headers(), json=params, timeout=180)
        if r.status_code != 200:
            msg = api_error(r)
            print(f"[{skin['name']}] HTTP {r.status_code}: {msg}")
            if args.mode == "structured" and ("output_config" in msg or "format" in msg):
                print("  -> structured outputs were rejected; try again with --mode tool")
            continue
        rec, err = parse_message(r.json(), allowed, pick_images(skin, args.image)[1])
        if err:
            errors[skin["id"]] = err
            print(f"[{skin['name']}] error: {err}")
            continue
        tags_db[skin["id"]] = rec
        errors.pop(skin["id"], None)
        usage = r.json().get("usage", {})
        print(f"\n[{skin['name']}] ({rec['image']} image, feet visible: {rec['feet_visible']}) {rec['caption']}")
        print("  tags: " + ", ".join(f"{t}({c[0]})" for t, c in rec["tags"]))
        if rec["suggested"]:
            print("  suggested: " + ", ".join(rec["suggested"]))
        print(f"  tokens in/out: {usage.get('input_tokens', 0) + usage.get('cache_read_input_tokens', 0) + usage.get('cache_creation_input_tokens', 0)}/{usage.get('output_tokens')}")
    save_json(TAGS, tags_db)
    save_json(ERRORS, errors)


def submit_batch(skins, args, system_text):
    id_map = {f"s{i}": s["id"] for i, s in enumerate(skins)}
    by_id = {s["id"]: s for s in skins}
    reqs = [{"custom_id": cid, "params": build_params(by_id[sid], args.model, args.image, args.mode, system_text)}
            for cid, sid in id_map.items()]
    r = requests.post(f"{API}/messages/batches", headers=headers(), json={"requests": reqs}, timeout=300)
    if r.status_code != 200:
        sys.exit(f"Batch submit failed: HTTP {r.status_code}: {api_error(r)}")
    batch = r.json()
    image_map = {cid: pick_images(by_id[sid], args.image)[1] for cid, sid in id_map.items()}
    save_json(PENDING, {"batch_id": batch["id"], "id_map": id_map, "image_map": image_map,
                        "submitted": datetime.now(timezone.utc).isoformat()})
    print(f"Submitted batch {batch['id']} with {len(reqs)} skins.")
    return batch["id"]


def collect(allowed, tags_db, errors, wait=True):
    pending = load_json(PENDING, None)
    if not pending:
        print("No pending batch.")
        return
    bid = pending["batch_id"]
    last, polls = None, 0
    while True:
        r = requests.get(f"{API}/messages/batches/{bid}", headers=headers(), timeout=60)
        r.raise_for_status()
        b = r.json()
        counts = b.get("request_counts", {})
        # Only log when progress changes, plus a heartbeat every 10 minutes, so the log stays readable.
        if counts != last or polls % 10 == 0 or b["processing_status"] == "ended":
            done = sum(v for k, v in counts.items() if k != "processing")
            print(f"Batch {bid}: {b['processing_status']}, {done}/{done + counts.get('processing', 0)} finished {counts}", flush=True)
        last, polls = counts, polls + 1
        if b["processing_status"] == "ended":
            break
        if not wait:
            return
        time.sleep(60)
    res = requests.get(b["results_url"], headers=headers(), timeout=300)
    res.raise_for_status()
    ok = bad = 0
    for line in res.text.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        sid = pending["id_map"].get(row["custom_id"])
        result = row["result"]
        if result["type"] != "succeeded":
            errors[sid] = result["type"] + ": " + json.dumps(result.get("error", {}))[:300]
            bad += 1
            continue
        rec, err = parse_message(result["message"], allowed, pending.get("image_map", {}).get(row["custom_id"], ""))
        if err:
            errors[sid] = err
            bad += 1
        else:
            tags_db[sid] = rec
            errors.pop(sid, None)
            ok += 1
    save_json(TAGS, tags_db)
    save_json(ERRORS, errors)
    PENDING.unlink()
    print(f"Saved tags for {ok} skins; {bad} failed (see data/tag_errors.json).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", type=int, metavar="N", help="tag N skins immediately without the Batch API")
    ap.add_argument("--limit", type=int, help="only send this many skins")
    ap.add_argument("--ids", help="comma-separated skin IDs to tag")
    ap.add_argument("--retag", action="store_true", help="also re-tag skins that already have tags")
    ap.add_argument("--no-wait", action="store_true", help="submit the batch and exit")
    ap.add_argument("--collect", action="store_true", help="collect results of a submitted batch")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--image", choices=["best", "icon"], default="best",
                    help="best = icon plus the full-body render (or featured image) when there is one; icon = icon only, cheapest")
    ap.add_argument("--upgrade", action="store_true",
                    help="re-tag skins whose feet weren't visible, if a shop render has been saved since")
    ap.add_argument("--mode", choices=["structured", "tool"], default="structured",
                    help="how to force JSON output; use 'tool' if structured outputs are rejected")
    ap.add_argument("--yes", action="store_true", help="skip the cost confirmation")
    args = ap.parse_args()

    vocab_text, allowed = vocab_tags()
    system_text = INSTRUCTIONS + vocab_text
    tags_db = load_json(TAGS, {})
    errors = load_json(ERRORS, {})

    if args.collect:
        return collect(allowed, tags_db, errors, wait=not args.no_wait)
    if PENDING.exists():
        sys.exit("A batch is already pending. Run with --collect first (or delete data/pending_batch.json).")

    skins = load_json(SKINS, None)
    if skins is None:
        sys.exit("data/skins.json not found; run scripts/fetch_skins.py first.")
    if args.ids:
        wanted = set(args.ids.split(","))
        skins = [s for s in skins if s["id"] in wanted]
    if args.upgrade:
        skins = [s for s in skins if s["id"] in tags_db and s.get("render")
                 and not tags_db[s["id"]].get("feet_visible", True) and "render" not in tags_db[s["id"]].get("image", "")]
    elif not args.retag:
        skins = [s for s in skins if s["id"] not in tags_db]
    skins = [s for s in skins if s.get("icon")]
    if args.test:
        skins = skins[: args.test]
    elif args.limit:
        skins = skins[: args.limit]
    if not skins:
        print("Nothing to tag.")
        return

    if args.test:
        return run_test(skins, args, system_text, allowed, tags_db, errors)

    # Rough estimate at Batch prices: ~5k prompt tokens (vocab + images) and ~600 output tokens per entry.
    est = len(skins) * (5000 * 0.05 + 600 * 0.25) / 1_000_000
    print(f"About to batch-tag {len(skins)} skins with {args.model}. Rough cost: ${est:.2f}")
    if not args.yes and sys.stdin.isatty() and input("Continue? [y/N] ").strip().lower() != "y":
        return
    submit_batch(skins, args, system_text)
    collect(allowed, tags_db, errors, wait=not args.no_wait)


if __name__ == "__main__":
    main()
