"""Download every Battle Royale outfit from Fortnite-API and save a slim list to data/skins.json.

Images are NOT downloaded; the site and the tagger use Fortnite-API's image URLs directly.
Also saves any shop render images it sees today into data/renders.json (see harvest_shop_renders).

Usage: python scripts/fetch_skins.py
Optional env: FORTNITE_API_KEY (only needed if Fortnite-API starts requiring one)
"""
import json
import os
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
    }


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
    for o in outfits:
        o["render"] = (renders.get(o["id"]) or {}).get("url", "")
    outfits.sort(key=lambda s: s["added"], reverse=True)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(outfits, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {len(outfits)} outfits to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
