"""Merge skins + model tags + hand edits into the files the website loads.

Hand edits come from data/overrides.csv and, if SHEET_CSV_URL is set, from a Google Sheet
published as CSV (File > Share > Publish to web > CSV). Both use the same columns:

  id, name, add_tags, remove_tags, verified, notes, group, caption, caption_replace

Only id is required. Tags in add_tags/remove_tags are separated by spaces or commas. An id ending
in * matches every skin and style whose id starts with the rest (Character_DroveRay* covers
Character_DroveRay, Character_DroveRay_B... and all their styles). Rows from the Google Sheet are
applied after the CSV in the repo, so the sheet wins.

group (on a base skin, or on one style):
  themes - each style is the same outfit for a different team/house/club. Styles fold into the
           base card, each style gets its style name as a tag (slytherin), and the base gets its
           default style's name (gryffindor). Captions swap the default name for the style's name.
  yes    - fold styles into the base card without adding name tags.
  no     - keep styles as separate cards.
  (blank) - styles whose preview is only an icon fold in; others stay separate.
caption: replaces the AI caption. caption_replace: "Gryffindor => Slytherin; red => green".

Writes:
  site/data/skins.json   - what the site loads
  site/data/vocab.json   - tag categories for the filter panel
  site/data/tags.csv     - every skin's final tags, handy for importing into Google Sheets
  data/suggestions.md    - tags the model wanted but the vocabulary lacks, most common first

Usage: python scripts/build_site_data.py
"""
import csv
import fnmatch
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


# Style names that say nothing about a team or house, so they never become tags.
GENERIC_STYLE_NAMES = {"default", "standard", "original", "classic", "normal", "base", "stage_1", "style_1"}


def norm_tag(name):
    tag = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return "" if tag in GENERIC_STYLE_NAMES else tag


def parse_replacements(text):
    pairs = []
    for part in (text or "").split(";"):
        if "=>" in part:
            a, b = part.split("=>", 1)
            if a.strip():
                pairs.append((a.strip(), b.strip()))
    return pairs


def swap_words(text, old, new):
    """Replace whole-word `old` with `new`, keeping it case-insensitive. Returns (text, changed)."""
    if not text or not old:
        return text, False
    pat = re.compile(r"\b" + re.escape(old) + r"\b", re.I)
    return (pat.sub(new, text), True) if pat.search(text) else (text, False)


WARNINGS = set()  # problems in the overrides worth printing in the build log

# Captions where the model said the style's image was blank, so its own tags are useless.
# Only used together with a near-empty tag list, so a loose match is safe.
BLANK_CAPTION = re.compile(
    r"\b(?:blank|empty)\b|nothing (?:is )?visible|no (?:visible )?(?:character|outfit)s? (?:is |are )?visible"
    r"|no visible (?:character|outfit)|cannot be (?:determined|identified|seen|described|made out)", re.I)


def match_ids(pattern, all_ids):
    """IDs an override row applies to. A * matches anything, anywhere ("Character_DroveRay*::Parts::*").
    A pattern with a * also covers everything under what it matches, so "Character_DroveRay*::Parts"
    means every Parts style of every DroveRay skin. Without a *, only that exact ID."""
    if "*" not in pattern:
        return [pattern]
    return [i for i in all_ids if fnmatch.fnmatchcase(i, pattern) or fnmatch.fnmatchcase(i, pattern + "::*")]


def load_overrides(all_ids):
    """Read override rows (repo CSV, then Google Sheet) and expand wildcard ids."""
    overrides = {}
    for row in read_override_rows():
        rid = row.get("id")
        if not rid:
            continue
        targets = match_ids(rid, all_ids)
        # A wildcard over whole families sets group on the main skins only. One that names a style
        # channel (it has ::, like "Character_DroveRay*::Parts") sets it on the styles it matches.
        family_wildcard = "*" in rid and "::" not in rid
        raw_group = row.get("group", "").strip()
        if raw_group and raw_group.partition(":")[0].strip().lower() not in ("themes", "theme", "yes", "no", "y", "n", "true", "false", "icon"):
            WARNINGS.add(f"{rid}: group '{raw_group}' isn't recognized, so it was ignored. Use themes, yes, no or icon.")
        if "*" in rid and not targets:
            WARNINGS.add(f"{rid}: matches no skins.")
        for sid in targets:
            o = overrides.setdefault(sid, {"add": set(), "remove": set(), "verified": False, "notes": "",
                                           "group": "", "caption": "", "replace": []})
            o["add"] |= set(split_tags(row.get("add_tags")))
            o["remove"] |= set(split_tags(row.get("remove_tags")))
            o["add"] -= o["remove"]
            if row.get("verified", "").lower() in ("y", "yes", "true", "1", "x", "✓"):
                o["verified"] = True
            for k in ("notes", "caption"):
                if row.get(k):
                    o[k] = row[k]
            # A wildcard row's group setting is meant for the base skins it matches, not each style.
            g = "" if (family_wildcard and "::" in sid) else row.get("group", "").strip()
            mode, _, chans = g.partition(":")
            mode = mode.strip().lower()
            if mode in ("themes", "theme", "yes", "no", "y", "n", "true", "false", "icon"):
                o["group"] = {"theme": "themes", "y": "yes", "true": "yes", "n": "no", "false": "no"}.get(mode, mode)
                # Accept "themes:Outfit", "themes::Outfit" and "themes: Outfit, Parts".
                names = {c.strip(" :").lower() for c in chans.split(",") if c.strip(" :")}
                if o["group"] == "themes" and names:
                    o["theme_channels"] = names
            o["replace"] += parse_replacements(row.get("caption_replace"))
            if row.get("caption_replace") and "=>" not in row["caption_replace"]:
                WARNINGS.add(f"{rid}: caption_replace has no '=>', so it was ignored. "
                             f"To replace the whole caption, put the text in the caption column instead.")
    return overrides


# Tags removed from an effect toggle's "Off" style, and added (if none is there) to its "On" style.
GLOW_TAGS = {"glowing", "glowing_lines", "emissive", "glowing_eyes", "neon_trim"}

# The "main shading" tags a shading-only style swaps out for its own.
MAIN_SHADING = {"cel_shading", "toon_(style)", "flat_color", "gradient_shading", "soft_shading", "realistic_3d"}


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


THEME_CAPTIONS = DATA / "theme_captions.json"


def build_records(skins, model_tags, vocab, theme_caps=None):
    """Merge everything into one record per entry. Returns (by_id, suggestions, variant_tags, overrides).

    Records for themed styles whose caption still needs rewriting carry a temporary "_req" key
    (used by scripts/theme_captions.py, stripped before writing the site data).
    """
    theme_caps = theme_caps or {}
    skin_by_id = {s["id"]: s for s in skins}
    overrides = load_overrides([s["id"] for s in skins])
    EMPTY = {"add": set(), "remove": set(), "verified": False, "notes": "", "group": "", "caption": "", "replace": []}
    style_channels, icon_channels = {}, {}
    for s in skins:
        if s.get("of"):
            style_channels.setdefault(s["of"], []).append(s.get("channel", ""))
            if model_tags.get(s["id"], {}).get("icon_only"):
                per = icon_channels.setdefault(s["of"], Counter())
                per[s.get("channel", "")] += 1

    def themed_channels(base_id):
        """Channels a "themes" base treats as team/house picks: the ones you named; else channels with
        at least two crest/logo (icon-only) styles, since a team picker always offers several; else
        the channel with the most icon-only styles; else all of them."""
        o = overrides.get(base_id, EMPTY)
        named = o.get("theme_channels")
        chans = style_channels.get(base_id, [])
        if named:
            found = {c for c in chans if c.lower() in named}
            missing = named - {c.lower() for c in chans}
            if missing:
                WARNINGS.add(f"{base_id}: group names style channel(s) {', '.join(sorted(missing))}, but its styles "
                             f"use {', '.join(sorted(set(chans))) or 'no channels'}.")
            return found
        per = icon_channels.get(base_id) or Counter()
        multi = {c for c, n in per.items() if n >= 2}
        if multi:
            return multi
        if per:
            return {per.most_common(1)[0][0]}
        return set(chans)

    variant_tags = set()  # team/house/club name tags made from style names

    color_tags = set(vocab["categories"].get("color", {}).get("tags", []))
    by_id, suggestions = {}, Counter()
    # Styles go after base skins so the base's final tags (hand edits included) exist already.
    for s in sorted(skins, key=lambda x: "of" in x):
        m = model_tags.get(s["id"], {})
        o = overrides.get(s["id"], EMPTY)
        base = by_id.get(s.get("of"))
        base_ok = base is not None and "u" not in base
        # group = no on a style's own row means "this is a real, different look": no copying from the base.
        own_look = bool(s.get("of")) and o["group"] == "no"
        copy_kind = ("shading_only" in s or "effect_toggle" in s) and not own_look
        inherit = base_ok and copy_kind
        # group = icon on a style's own row: its image is only a preview (swatch, emblem, blank...).
        icon_only = bool(s.get("of") and (m.get("icon_only") or o["group"] == "icon"))
        # The model got a blank image for this style (it says so, and found almost nothing to tag).
        blank = bool(s.get("of") and m and len(m.get("tags", [])) < 4 and BLANK_CAPTION.search(m.get("caption", "")))
        # Grouping: the style's own override wins, then the base skin's, then the default.
        base_group = overrides.get(s.get("of"), EMPTY)["group"] if s.get("of") else ""
        group_mode = o["group"] or base_group
        themed = bool(s.get("of")) and (o["group"] == "themes" or (
            base_group == "themes" and o["group"] != "no" and s.get("channel", "") in themed_channels(s["of"])))
        # Icon-only and shading-only styles are the base outfit, so they fold into its card unless group = no.
        grouped = bool(s.get("of")) and (themed or group_mode == "yes" or
                                         ((icon_only or blank or copy_kind or s.get("reactive_state"))
                                          and group_mode != "no"))
        # Accessory toggles ("Glasses: Off", "Cape: Off") really look different, so they keep their own
        # cards. To fold a family's broken ones, use a row like Character_X*::Parts with group = icon.
        name_tags = []
        default_name = ""
        if s.get("of"):
            default_name = (skin_by_id.get(s["of"], {}).get("default_styles") or {}).get(s.get("channel", ""), "")
            if themed and norm_tag(s.get("style")):
                name_tags = [norm_tag(s["style"])]
        elif o["group"] == "themes":
            ds = s.get("default_styles") or {}
            name_tags = [norm_tag(ds.get(c)) for c in sorted(themed_channels(s["id"])) if norm_tag(ds.get(c))]
        variant_tags.update(name_tags)
        copied = False  # caption copied from the base skin
        req = None      # caption rewrite request for scripts/theme_captions.py
        if base_ok and (icon_only or blank or (themed and "shading_only" not in s)):
            # The style is the base outfit in another color/team, or its preview is just an icon (swatch,
            # emblem...) or came through blank. Copy the base skin's tags; if the style's own image showed
            # colors, use those instead of the base's colors.
            icon_colors = [t for t, c in m.get("tags", []) if t in color_tags and c != "low"]
            sure = ([t for t in base["t"] if t not in color_tags] + icon_colors) if icon_colors else list(base["t"])
            low = [t for t in base.get("low", []) if t not in color_tags or not icon_colors]
            # A themed style is the base outfit with another team/house: drop the base's name tags.
            # Other copies (a cape-off look, a blank preview) are still the base's team, so keep them.
            base_names = set(base.get("vt", [])) if themed else set()
            sure = [t for t in sure if t not in base_names]
            m = {"caption": base.get("c", ""), "feet_visible": "nf" not in base,
                 "icon_caption": "" if blank else m.get("caption", "")}
            copied = True
            extra_tags = []
        elif inherit and "effect_toggle" in s:
            # Same outfit with lights/effects switched on or off: copy its tags, adjusting the glow ones.
            if s["effect_toggle"] == "off":
                sure = [t for t in base["t"] if t not in GLOW_TAGS]
            else:
                sure = list(base["t"]) + ([] if GLOW_TAGS & set(base["t"]) else ["glowing"])
            low = [t for t in base.get("low", []) if t not in GLOW_TAGS]
            m = {"caption": base.get("c", ""), "feet_visible": "nf" not in base}
            copied = True
            extra_tags = []
        elif inherit:
            # Same outfit as the default look: copy its tags and swap the shading tag.
            sure = [t for t in base["t"] if t not in MAIN_SHADING] + s["shading_only"]
            low = [t for t in base.get("low", []) if t not in MAIN_SHADING]
            m = {"caption": base.get("c", ""), "feet_visible": "nf" not in base}
            copied = True
            extra_tags = []
        else:
            sure = [t for t, c in m.get("tags", []) if c != "low"]
            low = [t for t, c in m.get("tags", []) if c == "low"]
            extra_tags = derived_tags(s)
            suggestions.update(m.get("suggested", []))
        tags = []
        for t in sure + extra_tags + name_tags + sorted(o["add"]):
            if t not in tags and t not in o["remove"]:
                tags.append(t)
        low = [t for t in low if t not in tags and t not in o["remove"]]
        rec = {
            "id": s["id"], "n": s["name"], "d": s.get("description", ""), "r": s.get("rarity", ""),
            "sr": s.get("series", ""), "st": s.get("set", ""), "ch": s.get("chapter", ""), "se": s.get("season", ""),
            "a": s.get("added", ""), "img": s.get("small") or s.get("icon", ""),
            "big": s.get("icon") or s.get("small", ""),
            "t": tags,
        }
        alt = s.get("render") or s.get("featured")
        if alt and alt != rec["big"]:
            rec["alt"] = alt  # full-body promo image; may show a different style
        if s.get("of"):
            rec["of"], rec["sty"] = s["of"], s.get("style", "")
        if low:
            rec["low"] = low
        caption = m.get("caption", "")
        if caption and copied:
            base_caption = caption
            rewritten = theme_caps.get(s["id"], {})
            if themed and rewritten.get("src") == base_caption and rewritten.get("caption"):
                caption = rewritten["caption"]  # rewritten by scripts/theme_captions.py
            else:
                # Swap the default style's name for this style's name; for themes, say which one it is.
                caption, swapped = swap_words(caption, default_name, s.get("style", ""))
                if themed and not swapped and s.get("style"):
                    caption = f"{caption.rstrip('.')} ({s['style']} style)."
                if themed and s.get("style"):
                    req = {"src": base_caption, "style": s["style"], "default": default_name,
                           "icon": m.get("icon_caption", ""), "name": s["name"]}
        for old, new in o["replace"]:
            caption = swap_words(caption, old, new)[0]
        if o["caption"]:
            caption = o["caption"]
            rec["cv"] = 1  # caption written by hand in the overrides
        if caption:
            rec["c"] = caption
        if name_tags:
            rec["vt"] = name_tags  # team/house name tags
        if grouped:
            rec["grp"] = 1  # folds into the base skin's card on the site
        if req:
            rec["_req"] = req
        if o["verified"]:
            rec["v"] = 1
        if o["notes"]:
            rec["no"] = o["notes"]
        if "effect_toggle" in s and not own_look:
            rec["fx"] = s["effect_toggle"]  # lights/effects on or off
            if inherit:
                rec["inh"] = 1
        if "shading_only" in s and not own_look:
            rec["sh"] = 1  # shading-only style
            if inherit:
                rec["inh"] = 1  # tags copied from the base skin
        if icon_only or blank:
            rec["ico"] = 1  # style preview is only an icon (or blank), so the site shows the base outfit
            if base_ok:
                rec["inh"] = 1
                if m.get("icon_caption"):
                    rec["ic"] = m["icon_caption"]
        if not m:
            rec["u"] = 1  # not tagged yet (for shading-only styles: the base skin isn't tagged yet)
        elif not m.get("feet_visible", True):
            rec["nf"] = 1  # feet were cut off in the tagged image, so shoes may be missing
        by_id[s["id"]] = rec

    return by_id, suggestions, variant_tags, overrides


def main():
    skins = load_json(DATA / "skins.json", [])
    model_tags = load_json(DATA / "tags.json", {})
    vocab = load_json(ROOT / "tagging" / "vocab.json", {"categories": {}})
    by_id, suggestions, variant_tags, overrides = build_records(skins, model_tags, vocab, load_json(THEME_CAPTIONS, {}))
    EMPTY = {"group": ""}  # stand-in for skins without override rows
    pending_captions = 0
    for r in by_id.values():
        if r.pop("_req", None):
            pending_captions += 1
    out = [by_id[s["id"]] for s in skins]
    csv_buf = io.StringIO()
    w = csv.writer(csv_buf)
    w.writerow(["id", "name", "tags", "low_confidence_tags", "verified"])
    for r in out:
        w.writerow([r["id"], r["n"], " ".join(r["t"]), " ".join(r.get("low", [])), "yes" if r.get("v") else ""])

    cats = [{"key": k, "label": c["label"], "tags": c["tags"]} for k, c in vocab["categories"].items()]
    if variant_tags:
        cats.insert(0, {"key": "variant", "label": "Style", "tags": sorted(variant_tags)})
    known = {t for c in cats for t in c["tags"]}
    extra = sorted({t for r in out for t in r["t"]} - known)
    if extra:
        cats.append({"key": "other", "label": "Other (hand-added)", "tags": extra})

    SITE_DATA.mkdir(parents=True, exist_ok=True)
    (SITE_DATA / "skins.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (SITE_DATA / "vocab.json").write_text(json.dumps({"categories": cats, "extras": vocab.get("_extras", [])}, separators=(",", ":")), encoding="utf-8")
    (SITE_DATA / "tags.csv").write_text(csv_buf.getvalue(), encoding="utf-8")

    # Overrides template: every base skin with icon-only styles, to mark as themes/yes/no in the sheet.
    tpl = io.StringIO()
    tw = csv.writer(tpl)
    tw.writerow(["id", "name", "add_tags", "remove_tags", "verified", "notes", "group", "caption", "caption_replace", "styles (reference only)"])
    fams = {}
    for r in out:
        if r.get("ico"):
            fams.setdefault(r["of"], []).append(r.get("sty", ""))
    for bid, names in fams.items():
        b = by_id.get(bid)
        if b:
            ob = overrides.get(bid, EMPTY)
            g = ob["group"] + (":" + ",".join(sorted(ob["theme_channels"])) if ob.get("theme_channels") else "")
            tw.writerow([bid, b["n"], "", "", "", "", g, "", "", "; ".join(names)])
    (SITE_DATA / "style_groups.csv").write_text(tpl.getvalue(), encoding="utf-8")

    lines = ["# Tags the model suggested that aren't in tagging/vocab.json", "",
             "Add the useful ones to a category in vocab.json, then re-tag with --retag.", "",
             "| tag | skins |", "|---|---|"]
    lines += [f"| {t} | {n} |" for t, n in suggestions.most_common(200) if t not in known]
    (DATA / "suggestions.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    tagged = sum(1 for r in out if "u" not in r)
    styles = sum(1 for r in out if "of" in r)
    copied = sum(1 for r in out if "inh" in r and "sh" in r)
    icons = sum(1 for r in out if "ico" in r)
    grouped = sum(1 for r in out if "grp" in r)
    for w in sorted(WARNINGS):
        print("Warning: " + w)
    if WARNINGS and os.environ.get("GITHUB_STEP_SUMMARY"):
        # Also show them on the Actions run's summary page, where they're hard to miss.
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("### Problems in data/overrides.csv\n\n" + "\n".join(f"- {w}" for w in sorted(WARNINGS)) + "\n")
    if pending_captions:
        print(f"{pending_captions} themed styles still use a simple name swap; run scripts/theme_captions.py to rewrite them.")
    print(f"Built site data: {len(out) - styles} skins + {styles} styles ({copied} shading-only and {icons} icon-only styles use their base's tags; {grouped} styles fold into their base card), {tagged} tagged, {len(overrides)} with hand edits")


if __name__ == "__main__":
    main()
