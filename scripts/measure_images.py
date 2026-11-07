"""Measure where the visible figure sits inside each full-body image, without changing the image.

Fortnite-API's full-body renders are squares with a lot of transparent space, mostly on the left
and right. For each image this finds the box around the non-transparent pixels (with Pillow) and
saves it in data/image_boxes.json as fractions of the image size: [left, top, right, bottom].
The site uses those numbers to zoom and center the figure with CSS. The images themselves are never
edited or re-hosted, so a bad box is fixed by deleting its entry (it's measured again next run).

Each image is measured once; later runs only measure new URLs, at most --limit per run so the
first runs don't download thousands of images at once.

Usage: python scripts/measure_images.py [--limit 600]
Also called from fetch_skins.py, so the daily deploy keeps it up to date.
"""
import argparse
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
BOXES = ROOT / "data" / "image_boxes.json"
ALPHA_CUTOFF = 16      # pixels more transparent than this count as empty (ignores faint glow/shadow)
DEFAULT_LIMIT = 600    # new images measured per run


def box_of(data):
    """[left, top, right, bottom] as fractions of the image size, or None if it can't be read."""
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        return None
    w, h = img.size
    if "A" not in img.getbands() and img.mode != "P":
        return [0, 0, 1, 1]  # no transparency at all: nothing to trim
    alpha = img.convert("RGBA").getchannel("A").point(lambda a: 255 if a > ALPHA_CUTOFF else 0)
    bbox = alpha.getbbox()
    if not bbox:
        return None  # fully transparent
    left, top, right, bottom = bbox
    return [round(left / w, 4), round(top / h, 4), round(right / w, 4), round(bottom / h, 4)]


def measure(urls, limit=DEFAULT_LIMIT, workers=8):
    """Measure any of `urls` not measured yet. Returns the full {url: box} map."""
    boxes = json.loads(BOXES.read_text(encoding="utf-8")) if BOXES.exists() else {}
    todo = [u for u in dict.fromkeys(urls) if u and u not in boxes][:limit]
    if not todo:
        return boxes

    def one(url):
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            return url, box_of(r.content)
        except requests.RequestException:
            return url, None

    measured = failed = 0
    with ThreadPoolExecutor(workers) as pool:
        for url, box in pool.map(one, todo):
            if box:
                boxes[url] = box
                measured += 1
            else:
                failed += 1
    BOXES.write_text(json.dumps(boxes, indent=0, sort_keys=True), encoding="utf-8")
    left = len([u for u in dict.fromkeys(urls) if u and u not in boxes])
    print(f"Image boxes: measured {measured} new full-body images ({failed} failed); "
          f"{len(boxes)} total, {left} still to measure on later runs")
    return boxes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = ap.parse_args()
    skins = json.loads((ROOT / "data" / "skins.json").read_text(encoding="utf-8"))
    measure([s.get("render") or s.get("featured") for s in skins if not s.get("of")], args.limit)


if __name__ == "__main__":
    main()
