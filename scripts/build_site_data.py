"""Merge skins + model tags + hand edits into the files the website loads.

Hand edits come from data/overrides.csv and, if SHEET_CSV_URL is set, from a Google Sheet
published as CSV (File > Share > Publish to web > CSV). Both use the same columns:

  id, name, add_tags, remove_tags, verified, notes

Tags in add_tags/remove_tags are separated by spaces or commas. Rows from the Google Sheet
are applied after the CSV in the repo, so the sheet wins.

Writes:
  site/data/skins.json   - what the site loads
  site/data/vocab.json   - tag categories for the filter panel
  site/data/tags.csv     - every skin's final tags, handy for importing into Google Sheets
  data/suggestions.md    - tags the model wanted but the vocabulary lacks, most common first

Usage: python scripts/build_site_data.py
"""
import csv
import io
import json
import os
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE_DATA = ROOT / "site" / "data"


def load_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def split_tags(s):
    return [t.strip().lower().replace(" ", "_") for t in re.split(r"[,\s]+", s or "") if t.strip()]


def read_override_rows():
    rows = []
    local = DATA / "overrides.csv"
    if local.exists():
        rows += list(csv.DictReader(io.StringIO(local.read_text(encoding="utf-8-sig"))))
    url = os.environ.get("SHEET_CSV_URL")
    if url:
        import requests
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        r.encoding = "utf-8"
        sheet_rows = list(csv.DictReader(io.StringIO(r.text)))
        print(f"Read {len(sheet_rows)} rows from the Google Sheet")
        rows += sheet_rows
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in row.items()} for row in rows if row]


def derived_tags(skin):
    tags = []
    channels = skin.get("variant_channels") or []
    if skin.get("reactive"):
        tags.append("reactive_outfit")
    if any("color" in c.lower() for c in channels):
        tags.append("color_selectable")
    if channels:
        tags.append("multiple_styles")
    return tags


def main():
    skins = load_json(DATA / "skins.json", [])
    model_tags = load_json(DATA / "tags.json", {})
    vocab = load_json(ROOT / "tagging" / "vocab.json", {"categories": {}})

    overrides = {}
    for row in read_override_rows():
        sid = row.get("id")
        if not sid:
            continue
        o = overrides.setdefault(sid, {"add": set(), "remove": set(), "verified": False, "notes": ""})
        o["add"] |= set(split_tags(row.get("add_tags")))
        o["remove"] |= set(split_tags(row.get("remove_tags")))
        o["add"] -= o["remove"]
        if row.get("verified", "").lower() in ("y", "yes", "true", "1", "x", "✓"):
            o["verified"] = True
        if row.get("notes"):
            o["notes"] = row["notes"]

    out, suggestions = [], Counter()
    csv_buf = io.StringIO()
    w = csv.writer(csv_buf)
    w.writerow(["id", "name", "tags", "low_confidence_tags", "verified"])
    for s in skins:
        m = model_tags.get(s["id"], {})
        o = overrides.get(s["id"], {"add": set(), "remove": set(), "verified": False, "notes": ""})
        sure = [t for t, c in m.get("tags", []) if c != "low"]
        low = [t for t, c in m.get("tags", []) if c == "low"]
        tags = []
        for t in sure + derived_tags(s) + sorted(o["add"]):
            if t not in tags and t not in o["remove"]:
                tags.append(t)
        low = [t for t in low if t not in tags and t not in o["remove"]]
        suggestions.update(m.get("suggested", []))
        rec = {
            "id": s["id"], "n": s["name"], "d": s.get("description", ""), "r": s.get("rarity", ""),
            "sr": s.get("series", ""), "st": s.get("set", ""), "ch": s.get("chapter", ""), "se": s.get("season", ""),
            "a": s.get("added", ""), "img": s.get("small") or s.get("icon", ""),
            "big": s.get("render") or s.get("featured") or s.get("icon", ""),
            "t": tags,
        }
        if low:
            rec["low"] = low
        if m.get("caption"):
            rec["c"] = m["caption"]
        if o["verified"]:
            rec["v"] = 1
        if o["notes"]:
            rec["no"] = o["notes"]
        if not m:
            rec["u"] = 1  # not tagged by the model yet
        elif not m.get("feet_visible", True):
            rec["nf"] = 1  # feet were cut off in the tagged image, so shoes may be missing
        out.append(rec)
        w.writerow([s["id"], s["name"], " ".join(tags), " ".join(low), "yes" if o["verified"] else ""])

    cats = [{"key": k, "label": c["label"], "tags": c["tags"]} for k, c in vocab["categories"].items()]
    known = {t for c in cats for t in c["tags"]}
    extra = sorted({t for r in out for t in r["t"]} - known)
    if extra:
        cats.append({"key": "other", "label": "Other (hand-added)", "tags": extra})

    SITE_DATA.mkdir(parents=True, exist_ok=True)
    (SITE_DATA / "skins.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (SITE_DATA / "vocab.json").write_text(json.dumps({"categories": cats, "extras": vocab.get("_extras", [])}, separators=(",", ":")), encoding="utf-8")
    (SITE_DATA / "tags.csv").write_text(csv_buf.getvalue(), encoding="utf-8")

    lines = ["# Tags the model suggested that aren't in tagging/vocab.json", "",
             "Add the useful ones to a category in vocab.json, then re-tag with --retag.", "",
             "| tag | skins |", "|---|---|"]
    lines += [f"| {t} | {n} |" for t, n in suggestions.most_common(200) if t not in known]
    (DATA / "suggestions.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    tagged = sum(1 for r in out if "u" not in r)
    print(f"Built site data: {len(out)} skins, {tagged} tagged, {len(overrides)} with hand edits")


if __name__ == "__main__":
    main()
