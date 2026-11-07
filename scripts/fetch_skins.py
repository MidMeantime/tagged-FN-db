"""Download every Battle Royale outfit from Fortnite-API and save a slim list to data/skins.json.

Images are NOT downloaded; the site and the tagger use Fortnite-API's image URLs directly.
Also saves any shop render images it sees today into data/renders.json (see harvest_shop_renders).

Usage: python scripts/fetch_skins.py
Optional env: FORTNITE_API_KEY (only needed if Fortnite-API starts requiring one)
"""
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "skins.json"
RENDERS = ROOT / "data" / "renders.json"
URL = "https://fortnite-api.com/v2/cosmetics/br"
SHOP_URL = "https://fortnite-api.com/v2/shop"


def val(obj, key="value"):
    return obj.get(key) if isinstance(obj, dict) else None


def slim(item):
    images = item.get("images") or {}
    intro = item.get("introduction") or {}
    tags = item.get("gameplayTags") or []
    variants = item.get("variants") or []
    return {
        "id": item["id"],
        "name": item.get("name") or item["id"],
        "description": item.get("description") or "",
        "rarity": val(item.get("rarity"), "displayValue") or "",
        "series": val(item.get("series")) or "",
        "set": val(item.get("set")) or "",
        "chapter": intro.get("chapter") or "",
        "season": intro.get("season") or "",
        "added": (item.get("added") or "")[:10],
        "icon": images.get("icon") or images.get("smallIcon") or "",
        "featured": images.get("featured") or "",
        "small": images.get("smallIcon") or images.get("icon") or "",
        "reactive": any("Reactive" in t for t in tags),
        "variant_channels": [val(v, "channel") or "" for v in variants],
        "last_seen_in_shop": (item.get("shopHistory") or [""])[-1][:10] if item.get("shopHistory") else "",
        "_variants": variants,
    }


# Style channels that would flood the list with near-identical entries (jersey numbers, etc.).
SKIP_CHANNELS = {"numeric", "jerseycolor", "jerseynumber", "particle", "emote", "lobbymusic"}
MAX_OPTIONS_PER_CHANNEL = 16

# Styles whose name only describes shading ("Gradient", "Gradient Outline", "Cel Shaded"...) are the
# same outfit as the default look. They aren't sent to the tagger; the site copies the base skin's
# tags and swaps in these shading tags. A style counts as shading-only when EVERY word of its name
# is in SHADING_WORDS or FILLER_WORDS, so "Gold Gradient" or "Shadow" are still tagged on their own.
SHADING_WORDS = {
    "gradient": ["gradient_shading"],
    "gradients": ["gradient_shading"],
    "outline": ["outline"],
    "outlined": ["outline"],
    "outlines": ["outline"],
    "cel": ["cel_shading"],
    "cel-shaded": ["cel_shading"],
    "celshaded": ["cel_shading"],
    "toon": ["toon_(style)", "cel_shading"],
    "toon-shaded": ["toon_(style)", "cel_shading"],
    "inked": ["outline"],
    "flat": ["flat_color"],
    "shaded": [],
    "shading": [],
}
FILLER_WORDS = {"style", "styled", "version", "look", "mode", "with", "and", "&", "+", "-", "/"}

# "Toon" styles are always the cel-shaded version of the outfit, but Epic often mixes "toon" into
# other words: "Toon Daphne", "iToonSpeed". So any "toon" in a style name counts, even inside a
# word, except in real words that just happen to contain it.
TOON_TAGS = ["toon_(style)", "cel_shading"]
TOON_EXCEPTIONS = ("platoon", "pontoon", "spittoon", "festoon")


def shading_only_tags(style_name):
    """Return the shading tags for a shading-only style name, or None if the name means more than that."""
    name = (style_name or "").lower()
    words = re.findall(r"[a-z]+(?:-[a-z]+)?|[&+/]", name)
    stripped = name
    for w in TOON_EXCEPTIONS:
        stripped = stripped.replace(w, "")
    if "toon" in stripped:
        tags = list(TOON_TAGS)
        for w in words:  # keep extra shading words, e.g. "Toon Outline"
            for t in SHADING_WORDS.get(w, []):
                if t not in tags:
                    tags.append(t)
        return tags
    if not words or not any(w in SHADING_WORDS and SHADING_WORDS[w] for w in words):
        return None
    if any(w not in SHADING_WORDS and w not in FILLER_WORDS for w in words):
        return None
    tags = []
    for w in words:
        for t in SHADING_WORDS.get(w, []):
            if t not in tags:
                tags.append(t)
    return tags


def style_entries(base):
    """Turn each selectable style of an outfit into its own entry, with that style's own image.

    The first option of each channel is the default look, which the base entry already covers.
    Channels with very many options are skipped (usually number/jersey pickers).
    """
    out, seen_images = [], {base.get("icon"), base.get("small")}
    for v in base.get("_variants") or []:
        channel = val(v, "channel") or ""
        options = v.get("options") or []
        if channel.lower() in SKIP_CHANNELS or len(options) > MAX_OPTIONS_PER_CHANNEL:
            continue
        for opt in options[1:]:
            img = opt.get("image")
            tag = opt.get("tag") or ""
            if not img or not tag or img in seen_images:
                continue
            seen_images.add(img)
            style_name = opt.get("name") or tag
            e = {k: val_ for k, val_ in base.items() if k != "_variants"}
            shading = shading_only_tags(style_name)
            if shading is not None:
                e["shading_only"] = shading
            e.update({
                "id": f"{base['id']}::{channel}::{tag}",
                "of": base["id"],
                "style": style_name,
                "channel": channel,
                "name": f"{base['name']} ({style_name})",
                "icon": img, "small": img, "featured": "", "render": "",
            })
            out.append(e)
    return out


def harvest_shop_renders(headers, outfit_ids):
    """Save today's shop render images (newDisplayAsset.renderImages) into data/renders.json.

    These are often fuller-body than the locker icon, but only exist for skins that have been in
    the shop, so we keep every one we see. The file is committed, so coverage grows every day.
    """
    renders = json.loads(RENDERS.read_text(encoding="utf-8")) if RENDERS.exists() else {}
    try:
        r = requests.get(SHOP_URL, headers=headers, timeout=120)
        r.raise_for_status()
        entries = (r.json().get("data") or {}).get("entries") or []
    except (requests.RequestException, ValueError) as e:
        print(f"Shop fetch failed, keeping existing renders: {e}")
        return renders
    added = 0
    for e in entries:
        nda = e.get("newDisplayAsset") or {}
        images = nda.get("renderImages") or []
        if not images:
            continue
        outfits_here = [i["id"] for i in (e.get("brItems") or []) if val(i.get("type")) == "outfit"]
        cid = nda.get("cosmeticId")
        # Only trust the render when we know which outfit it shows (bundles can show several).
        sid = cid if cid in outfit_ids else (outfits_here[0] if len(outfits_here) == 1 else None)
        if not sid or sid in renders:
            continue
        best = next((i for i in images if i.get("productTag") == "Product.BR"), images[0])
        if best.get("image"):
            renders[sid] = {"url": best["image"], "seen": date.today().isoformat()}
            added += 1
    RENDERS.write_text(json.dumps(renders, indent=1, sort_keys=True), encoding="utf-8")
    print(f"Shop renders: {added} new, {len(renders)} total")
    return renders


def main():
    headers = {}
    if os.environ.get("FORTNITE_API_KEY"):
        headers["Authorization"] = os.environ["FORTNITE_API_KEY"]
    r = requests.get(URL, headers=headers, timeout=120)
    r.raise_for_status()
    items = r.json().get("data") or []
    outfits = [slim(i) for i in items if val(i.get("type")) == "outfit"]
    if not outfits:
        sys.exit("No outfits returned; Fortnite-API response format may have changed.")
    renders = harvest_shop_renders(headers, {o["id"] for o in outfits})
    entries = []
    for o in outfits:
        o["render"] = (renders.get(o["id"]) or {}).get("url", "")
        styles = style_entries(o)
        # Name of each channel's default option (e.g. "Gryffindor"), used to swap names in captions.
        o["default_styles"] = {val(v, "channel") or "": ((v.get("options") or [{}])[0].get("name") or "")
                               for v in o.get("_variants") or [] if v.get("options")}
        o.pop("_variants", None)
        o["styles"] = len(styles)
        entries.append(o)
        entries += styles
    shading = [e for e in entries if "shading_only" in e]
    print(f"{len(outfits)} outfits + {len(entries) - len(outfits)} alternate styles "
          f"({len(shading)} are shading-only and will copy their base skin's tags)")
    names = sorted({e["style"] for e in shading})
    if names:
        print("  Shading-only style names: " + ", ".join(names[:60]) + (" …" if len(names) > 60 else ""))
    outfits = entries
    outfits.sort(key=lambda s: s["added"], reverse=True)  # stable sort keeps styles right after their base
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(outfits, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {len(outfits)} entries to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
