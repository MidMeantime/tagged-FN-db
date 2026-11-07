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
from collections import Counter
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


# Styles named just "On"/"Off" (or "Lights Off", "Always On"...) usually toggle something. The style
# channel's type (the label the locker shows, e.g. "Lights", "Hat", "Glasses") says what:
#   effect - lights, glow, reactive or particle effects: the same outfit, so it copies the base's tags
#   part   - an accessory or piece (hat, mask, cape...): a real visual change, tagged on its own
ONOFF_NAME = re.compile(r"\s*(?:all |always |lights? |glow |fx |effects? |reactive |shader )?(on|off)\s*", re.I)
EFFECT_WORDS = ("light", "glow", "emissive", "fx", "effect", "reactive", "particle", "shader", "neon",
                "energy", "aura", "flame", "fire", "sparkle", "holo", "lumin", "shine", "visualizer")
GENERIC_TYPES = {"", "style", "styles", "material", "materials", "part", "parts", "color", "colors",
                 "variant", "variants", "mesh", "pattern", "progressive", "option", "options"}


# A style channel whose type or option names mention these holds reactive states, e.g. the FNAF skins'
# "Full Damage" style. Those styles fold into the base card but keep their own tags (they look
# different), and the outfit gets the reactive tag.
REACTIVE_WORDS = ("reactive", "react", "damage")


def is_reactive_channel(ctype, options):
    names = " ".join([ctype] + [o.get("name") or "" for o in options[1:]]).lower()
    return any(w in names for w in REACTIVE_WORDS)


def channel_type(v):
    t = v.get("type")
    if isinstance(t, dict):
        t = t.get("value") or t.get("displayValue") or t.get("name")
    return str(t or "").strip()


def toggle_kind(style_name, channel, ctype):
    """Return ("effect"|"part", "on"|"off") for an On/Off style, or None for anything else."""
    m = ONOFF_NAME.fullmatch(style_name or "")
    if not m:
        return None
    state = m.group(1).lower()
    words = f"{style_name} {channel} {ctype}".lower()
    if any(w in words for w in EFFECT_WORDS):
        return "effect", state
    if ctype.lower() not in GENERIC_TYPES:
        return "part", state
    if channel.lower() in ("emissive", "particle", "particles"):
        return "effect", state
    return None


# Accessories that styles switch on or off. Each entry: the words that name it, the tag to add when
# it's switched on, and every tag that belongs to it (removed when it's switched off). A style whose
# name or channel type names one of these ("Glasses" -> "Off", "Hat Off", "No Mask", "Unmasked")
# copies its main skin's tags with just that accessory's tags changed, instead of being tagged.
ACCESSORIES = {
    "hat": (["hat", "hats", "cap", "beanie", "fedora", "beret", "headwear", "top hat", "cowboy hat"], "hat",
            ["hat", "baseball_cap", "beanie", "cowboy_hat", "top_hat", "witch_hat", "pirate_hat", "santa_hat",
             "beret", "bucket_hat", "fedora"]),
    "helmet": (["helmet", "helm"], "helmet",
               ["helmet", "motorcycle_helmet", "space_helmet", "military_helmet", "visor"]),
    "hood": (["hood", "hoodie hood"], "hood_up", ["hood", "hood_up", "hood_down", "animal_hood"]),
    "mask": (["mask", "masks", "masked", "facemask", "face mask", "balaclava"], "mask",
             ["mask", "face_mask", "mouth_mask", "gas_mask", "skull_mask", "oni_mask", "masquerade_mask",
              "full_face_covered", "balaclava"]),
    "bandana": (["bandana", "bandanna", "neckerchief"], "bandana", ["bandana"]),
    "glasses": (["glasses", "sunglasses", "shades", "eyewear", "specs", "spectacles", "aviators", "monocle"],
                "glasses", ["glasses", "sunglasses", "aviators", "monocle"]),
    "goggles": (["goggles"], "goggles", ["goggles", "goggles_on_head"]),
    "visor": (["visor"], "visor", ["visor"]),
    "cape": (["cape", "capes", "cloak", "mantle"], "cape", ["cape", "cloak"]),
    "scarf": (["scarf", "scarves"], "scarf", ["scarf"]),
    "headphones": (["headphones", "headset", "earphones"], "headphones", ["headphones", "headset"]),
    "crown": (["crown", "tiara"], "crown", ["crown", "tiara"]),
    "backpack": (["backpack", "bag", "pack"], "backpack", ["backpack", "bag", "satchel"]),
    "wings": (["wings"], "wings", ["wings", "angel_wings", "demon_wings", "bat_wings", "mechanical_wings"]),
    "jacket": (["jacket", "coat", "hoodie", "vest"], "jacket",
               ["jacket", "hooded_jacket", "leather_jacket", "bomber_jacket", "hoodie", "coat", "trench_coat", "vest"]),
    "gloves": (["gloves", "gauntlets"], "gloves", ["gloves", "fingerless_gloves", "gauntlets"]),
    "earrings": (["earrings", "earring"], "earrings", ["earrings"]),
    "headband": (["headband"], "headband", ["headband"]),
    "necklace": (["necklace", "chain", "chains"], "necklace", ["necklace", "chain_necklace", "chain"]),
}
_ACC_WORDS = sorted(((w, k) for k, (words, _, _) in ACCESSORIES.items() for w in words), key=lambda x: -len(x[0]))
_ACC_ALT = "|".join(re.escape(w) for w, _ in _ACC_WORDS)
ON_WORDS, OFF_WORDS = ("on", "up", "equipped", "with"), ("off", "down", "removed", "none", "no", "without")
ACC_NAME = [
    re.compile(rf"(?P<state>no|without)\s+(?:the\s+)?(?P<acc>{_ACC_ALT})", re.I),                 # "No Hat"
    re.compile(rf"(?P<acc>{_ACC_ALT})\s*[:\-]?\s*(?P<state>on|off|up|down|removed|equipped)", re.I),  # "Hat Off"
    re.compile(rf"(?P<state>on|off|up|down|with)\s*[:\-]?\s*(?:the\s+)?(?P<acc>{_ACC_ALT})", re.I),  # "With Cape"
    re.compile(rf"(?P<acc>{_ACC_ALT})(?P<state>less)", re.I),                                       # "Hatless"
]


def accessory_toggle(style_name, ctype):
    """Return (accessory key, "on"|"off") if this style just puts an accessory on or takes it off."""
    name = (style_name or "").strip()
    words = {w: k for w, k in _ACC_WORDS}
    m = ONOFF_NAME.fullmatch(name)
    if m and ctype.lower() in words:                       # channel type "Glasses", style "Off"
        return words[ctype.lower()], m.group(1).lower()
    if re.fullmatch(r"un-?masked", name, re.I):
        return "mask", "off"
    if re.fullmatch(r"masked", name, re.I):
        return "mask", "on"
    for pat in ACC_NAME:
        m = pat.fullmatch(name)
        if m:
            state = m.group("state").lower()
            state = "off" if state in OFF_WORDS or state == "less" else "on"
            return words[m.group("acc").lower()], state
    return None


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
        ctype = channel_type(v)
        options = v.get("options") or []
        if channel.lower() in SKIP_CHANNELS or len(options) > MAX_OPTIONS_PER_CHANNEL:
            continue
        reactive_channel = is_reactive_channel(ctype, options)
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
            toggle = toggle_kind(style_name, channel, ctype)
            acc = accessory_toggle(style_name, ctype)
            if acc and not (toggle and toggle[0] == "effect"):
                _, add_tag, all_tags = ACCESSORIES[acc[0]]
                # Copies the base's tags, adding or removing just this accessory's tags.
                e["accessory"] = {"key": acc[0], "state": acc[1], "tag": add_tag, "tags": all_tags}
            if toggle and toggle[0] == "effect":
                e["effect_toggle"] = toggle[1]       # same outfit with lights/effects on or off
            elif toggle and toggle[0] == "part":
                style_name = f"{ctype}: {style_name.strip()}"  # "Off" -> "Hat: Off"
                e["part_toggle"] = True  # same skin with a piece on/off: folds in, keeps its own tags
            if ctype:
                e["channel_type"] = ctype
            if reactive_channel:
                e["reactive_state"] = True
                e["reactive"] = True
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


def is_placeholder(name):
    """True for outfits Epic hasn't named yet ("TBD", "tbd", "TBD." ...)."""
    return re.fullmatch(r"\s*(?:tbd|null)?\W*", name or "", re.I) is not None


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
    # Placeholder outfits Epic hasn't named yet (mostly NPCs) are called "TBD"; leave them out.
    # Their styles go with them, since styles are built from these entries below.
    tbd = [o for o in outfits if is_placeholder(o["name"])]
    if tbd:
        print(f"Skipping {len(tbd)} placeholder outfits named TBD")
        outfits = [o for o in outfits if not is_placeholder(o["name"])]
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
        if any(st.get("reactive_state") for st in styles):
            o["reactive"] = True  # has reactive styles, even if Fortnite-API doesn't flag it
        entries.append(o)
        entries += styles
    shading = [e for e in entries if "shading_only" in e]
    print(f"{len(outfits)} outfits + {len(entries) - len(outfits)} alternate styles "
          f"({len(shading)} are shading-only and will copy their base skin's tags)")
    toggles = Counter((e["channel"], e.get("channel_type", ""), "effect" if "effect_toggle" in e else
                       ("part" if ":" in e["style"] else "unsorted"))
                      for e in entries if e.get("of") and ONOFF_NAME.fullmatch(e["style"].split(": ")[-1]))
    if toggles:
        print(f"On/Off styles: {sum(n for k, n in toggles.items() if k[2] == 'effect')} lighting/effect toggles "
              f"(copy their base's tags), {sum(n for k, n in toggles.items() if k[2] == 'part')} accessory toggles, "
              f"{sum(n for k, n in toggles.items() if k[2] == 'unsorted')} unsorted. By channel / type:")
        for (ch, ct, kind), n in toggles.most_common(30):
            print(f"  {n:4}  {ch} / {ct or '(no type)'} -> {kind}")
    reactive = [e for e in entries if e.get("reactive_state")]
    if reactive:
        fams = Counter((e["of"], e["channel"]) for e in reactive)
        print(f"Reactive styles: {len(reactive)} in {len(fams)} channels (fold into their base card, keep their own tags). "
              "Style names: " + ", ".join(sorted({e["style"] for e in reactive})[:40]))
    accs = [e for e in entries if e.get("accessory")]
    if accs:
        per = Counter(e["accessory"]["key"] for e in accs)
        print(f"Accessory styles: {len(accs)} (copy their base's tags, adding/removing just the accessory): "
              + ", ".join(f"{k} {n}" for k, n in per.most_common()))
    unknown = Counter(e.get("channel_type", "") for e in entries if e.get("part_toggle") and not e.get("accessory"))
    if unknown:
        print("  On/off styles with an accessory type not in ACCESSORIES (tagged on their own): "
              + ", ".join(f"{t} {n}" for t, n in unknown.most_common(25)))
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
