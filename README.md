# Skin Finder

**[midmeantime.github.io/tagged-FN-db](https://midmeantime.github.io/tagged-FN-db/)**

Skin Finder is a searchable catalog of every Fortnite outfit and its styles, tagged by what they actually look like. Instead of searching by name, you can filter by hair, colors, accessories, headwear, art style, theme and more: "blonde, ponytail, sunglasses, cel-shaded", "anything with wings", or "every Slytherin style".

The tags were written by an AI model (Claude Haiku) that looked at each outfit's image, and people correct them by hand over time. Expect some mistakes. If you spot one, you can [help fix it](#contributing).

## Using the site

- **Search** matches names, in-game descriptions and tags.
- **Filters** on the left group tags by category. Click a tag once to require it, again to exclude it, and a third time to clear it. "Match any tag" switches from all-of to any-of.
- **Styles:** most selectable styles appear as their own cards, so a style with a different color or look can be found by its own tags. Styles that only change the shading (like "Gradient"), only change the team or house (like the Hogwarts houses or club kits), or whose preview is just a crest or swatch are folded into the main skin's card and appear as previews in its popup.
- **The popup** shows the skin's tags by category, an AI-written description, all of its styles, and a full-body promo image when one exists.
- **Review status** filters show what has been checked by hand (✓), which tags the model was unsure about, and where the image didn't show the shoes.
- **Links** to filtered views can be shared; the filters are kept in the URL.
- **All tags** can be downloaded as a CSV from the link in the footer.

## How it works

Everything runs on free GitHub services. There's no server or database: the site is a static page, and the repo only stores text. Images load directly from [Fortnite-API](https://fortnite-api.com).

1. **Daily skin list.** A GitHub Action pulls every outfit and its selectable styles from Fortnite-API, then rebuilds and redeploys the site. New skins show up the next day, untagged until the next tagging run.
2. **Tagging.** When a maintainer runs it, `scripts/tag_skins.py` sends each untagged outfit or style image to Claude Haiku through the Batch API. The model picks tags from a fixed vocabulary (`tagging/vocab.json`), rates its confidence in each, writes a one-line description, and reports whether the feet were visible and whether the image shows the character or just an icon. Only untagged entries are sent, so each run costs a few cents to a few dollars.
3. **Hand edits** from `data/overrides.csv` are applied on top of the AI tags and always win.
4. **Build.** `scripts/build_site_data.py` merges skins, AI tags and hand edits into the JSON files the site loads.

### Tags

Tags follow [Danbooru](https://danbooru.donmai.us/wiki_pages/tag_groups) naming (`blonde_hair`, `cel_shading`, `red_theme`), grouped into categories such as subject, hair, eyes, headwear, face, clothing, accessories, held items, colors, art style and theme. Danbooru has no good term for some things common in Fortnite, so about 20 extra tags were added (`gradient_shading`, `food_costume`…); these are listed under `_extras` in the vocabulary. A few tags come from Fortnite-API data rather than the model: reactive outfits, color-selectable outfits and outfits with multiple styles.

### Styles

Each selectable style is its own entry, with an ID like `BASEID::Channel::Tag`. A few kinds of style are handled specially, so they don't need their own tagging or clutter the grid:

- **Shading-only styles** ("Gradient", "Cel Shaded", "Toon"…) are the same outfit with different shading. They copy the main skin's tags, swap in the right shading tag, and fold into the main skin's card.
- **Icon-only styles**, whose preview is a swatch, emblem or logo rather than the character, copy the main skin's tags and take their colors from the icon.
- **Reactive styles**, like the Five Nights at Freddy's skins' damage states, are detected when a style channel's name or styles mention "reactive" or "damage". They fold into the main skin's card but keep their own tags, since they look different, and the whole outfit is tagged `reactive_outfit`.
- **On/off styles** that switch lighting or effects fold into the main skin's card and copy its tags. Accessory toggles ("Glasses: Off", "Hat: On") keep their own cards and tags, since they change how the outfit looks.
- **Team, house and club styles** are marked by hand as "themes". Each style gets its team or house as a tag (`slytherin`, `hufflepuff`…), and its description is rewritten from the main skin's, changing only the team or house and its colors.
- Style pickers with lots of near-identical options (jersey numbers and similar) are skipped.

### Images

Fortnite-API has no guaranteed full-body image. The model always sees the icon for the exact style it's tagging first. For main skins it also gets a full-body promo image when one exists: a shop render (collected daily into `data/renders.json`) or the featured image. Promo images can show a different style, so the model only uses them for parts the icon cuts off, like legs and shoes. When the feet aren't visible, shoe tags are left out, and the entry is listed under **Review status → Shoes not visible**.

## Contributing

### Report a wrong or missing tag

The easiest way: open a skin on the site and click **Suggest a tag fix**. That opens a GitHub issue with the skin's ID and current tags filled in. Just write which tags to add or remove.

### Fix tags directly

Hand edits live in `data/overrides.csv`. Edit it on GitHub (or in your fork) and open a pull request. Only `id` is required; leave other columns blank.

| column | what it does |
|---|---|
| `id` | Skin or style ID, shown at the bottom of each popup. An ID ending in `*` matches every skin and style starting with it (`Character_DroveRay*`). |
| `name` | Ignored; just makes the file easier to read. |
| `add_tags`, `remove_tags` | Tags separated by spaces or commas, in Danbooru style (`red_hair`). Tags outside the vocabulary are allowed and appear under "Other". |
| `verified` | `yes` once every tag on the skin has been checked. Shows a ✓ on the site. |
| `notes` | Shown in the popup. |
| `group` | For skins whose styles are different teams or houses: `themes`, or `themes:Material` to name the style channel. `yes` folds the styles into one card without team tags; `no` keeps them as separate cards. On a single style: `no` gives it its own card and tags, `icon` marks its image as just a preview. |
| `caption` | Replaces the AI description. |
| `caption_replace` | Swaps words in the description, e.g. `Gryffindor => Slytherin; red => green`. |

Example:

| id | name | add_tags | remove_tags | verified | notes | group | caption | caption_replace |
|---|---|---|---|---|---|---|---|---|
| CID_028_Athena_Commando_F | Renegade Raider | aviators | sunglasses | yes | | | | |
| Character_ToadCycle* | Hogwarts students | | | | | themes | | |

Helpful files the site publishes:
- [`data/tags.csv`](https://midmeantime.github.io/tagged-FN-db/data/tags.csv): every entry's current tags.
- [`data/style_groups.csv`](https://midmeantime.github.io/tagged-FN-db/data/style_groups.csv): skins whose style previews are crests or logos, likely candidates for `group = themes`, with their style names.

### Common fixes

**A style was folded into its main skin, but it really looks different.** Some styles are folded into the main skin's card automatically: shading-only styles ("Gradient", "Toon"…), lighting on/off toggles, reactive states, and styles whose preview is only an icon or came through blank. Most folded styles copy the main skin's tags. If one actually changes the outfit, for example an "Off" style that removes a cape:

1. Open the main skin on the site and click the style's thumbnail in the popup.
2. Copy the style's ID from the bottom of the popup. Style IDs have two `::`, like `Character_Example::Parts::Stage2`.
3. Add a row to `data/overrides.csv` with that full ID and `no` in the `group` column:

   | id | name | add_tags | remove_tags | verified | notes | group | caption | caption_replace |
   |---|---|---|---|---|---|---|---|---|
   | Character_Example::Parts::Stage2 | Example (Cape Off) | | | | | no | | |

4. Open a pull request. Once it's merged, the style gets its own card, and the next tagging run tags it from its own image. Until then it shows as "Not tagged yet". If you know the right tags, fill in `add_tags` in the same row so it's correct right away.

Use the style's own ID, not the main skin's: `no` on a main skin keeps all of its styles apart, and a wildcard ID (`*`) only sets `group` for main skins.

**A style's preview is just an icon, but it shows up as its own card.** Styles whose preview image is only a crest, logo, color swatch or blank square are usually caught automatically. They fold into the main skin's card and show the main outfit with the preview in the corner. If one slips through, it shows its icon as if it were the whole outfit, either as its own card or as a full-size style in the popup. To fix it:

1. Open the style and copy its ID from the bottom of the popup (the one with two `::`, like `Character_Example::Material::Mat2`).
2. Add a row with that full ID and `icon` in the `group` column:

   | id | name | add_tags | remove_tags | verified | notes | group | caption | caption_replace |
   |---|---|---|---|---|---|---|---|---|
   | Character_Example::Material::Mat2 | Example (No) | | | | | icon | | |

3. Open a pull request. Once it's merged, the style folds into the main card, copies the main skin's tags (taking colors from the icon, if the model saw any), and its icon appears in the corner of the main outfit's picture.

Use `icon` rather than `yes`: `yes` only folds a style in, so its icon still stands in for the outfit.

**A skin reacts in game (changes as you play) but isn't tagged "reactive outfit".** Reactive skins are detected from Fortnite-API data, which misses some. To add the tag:

1. Copy the main skin's ID from the bottom of its popup.
2. Add a row with `reactive_outfit` in `add_tags`:

   | id | name | add_tags | remove_tags | verified | notes | group | caption | caption_replace |
   |---|---|---|---|---|---|---|---|---|
   | Character_Example | Example | reactive_outfit | | | | | | |

3. Open a pull request. The tag appears under **Outfit traits** on the site after the next deploy.

To tag every skin in a family at once, end the ID with `*` (`Character_Example*`); that covers its styles too. To remove the tag from a skin that isn't reactive, put `reactive_outfit` in `remove_tags` instead.

### Improve the vocabulary

After each tagging run, [`data/suggestions.md`](data/suggestions.md) lists tags the model wanted to use but couldn't, most common first. To add tags, open a pull request against `tagging/vocab.json`: put each tag in the category where it fits, and list any tag that isn't a real Danbooru tag in `_extras`. New tags apply to entries the next time they're tagged.

### Improve the code

The site is plain HTML, CSS and JavaScript in `site/`, with no build step. The scripts are Python and need only `requests`. To work on it locally:

```bash
pip install -r requirements.txt
python scripts/fetch_skins.py          # download the skin list from Fortnite-API
python scripts/build_site_data.py      # merge it with the committed tags and hand edits
python -m http.server -d site 8000     # open http://localhost:8000
```

You don't need an API key for any of that; the AI tags are already in `data/tags.json`. Tagging (`scripts/tag_skins.py`) needs an Anthropic API key, and you'll rarely need to run it yourself: `--test 5` tags five entries right away, prints the results and saves them to `data/tags.json`.

```
tagging/vocab.json          tag vocabulary
scripts/fetch_skins.py      Fortnite-API -> data/skins.json (outfits + styles, shop renders)
scripts/tag_skins.py        Claude Haiku -> data/tags.json
scripts/theme_captions.py   rewrites descriptions for team/house styles
scripts/build_site_data.py  skins + tags + overrides -> site/data/*
scripts/commit_data.py      lets workflows commit data files without merge conflicts
scripts/recover_batch.py    imports a tagging batch whose bookkeeping was lost
site/                       the website
.github/workflows/          deploy (daily + on push), tag (manual), recover (manual)
```

## Maintaining

These need repository admin access.

- **Secrets and variables:** `ANTHROPIC_API_KEY` (secret) for tagging. Optionally `FORTNITE_API_KEY` (secret), in case Fortnite-API ever requires one.
- **Actions → Tag skins** tags everything untagged through the half-price Batch API, then rewrites team/house descriptions and redeploys. Options: `test_count` (tag a few right away and print them), `limit`, `ids` + `retag`, `recheck_icons` (re-tag older styles whose description shows they were icons), `upgrade` (re-tag skins whose feet were cut off once a full-body render is available) and `image` (`icon` sends only the icon, which is cheaper). Every entry sent and every result is listed in the run's log and summary page.
- **Actions → Recover tag batch** imports results from a batch whose `data/pending_batch.json` was lost (for example, a run cancelled before it saved). Give it the batch ID and the commit whose `data/tags.json` was current when the batch was submitted. It only imports if the rebuilt order checks out, so run it the same day.

## Credits

Item data and images come from [Fortnite-API](https://fortnite-api.com). Tags and descriptions are written by Claude Haiku and corrected by contributors. Skin Finder is a fan project, not affiliated with or endorsed by Epic Games; Fortnite and all related names and images belong to Epic Games.
