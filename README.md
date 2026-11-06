# Skin Finder

A free, static, searchable database of every Fortnite outfit, tagged with Danbooru-style tags (hair, colors, accessories, shading style, theme…) by Claude Haiku 5.5, with hand corrections from a CSV file or a Google Sheet.

- **Hosting:** GitHub Pages (free). Images are loaded straight from Fortnite-API, so the repo only stores text.
- **Skin list:** pulled from Fortnite-API every day by a GitHub Action, so new skins show up automatically (untagged until the next tagging run).
- **Tags:** `data/tags.json`, written by `scripts/tag_skins.py`. It only tags skins that don't have tags yet, so re-running costs almost nothing.
- **Hand edits:** `data/overrides.csv` and/or a published Google Sheet. These always win over the AI tags.

```
tagging/vocab.json          tag vocabulary (Danbooru names + a few marked extras)
scripts/fetch_skins.py      Fortnite-API  -> data/skins.json
scripts/tag_skins.py        Claude Haiku  -> data/tags.json
scripts/build_site_data.py  skins + tags + overrides -> site/data/*
site/                       the website (plain HTML/JS, no build step)
.github/workflows/          deploy.yml (daily + on push), tag.yml (when you start it)
```

## 1. Put it on GitHub Pages

1. Create a **public** repo on GitHub (public repos get free Pages and free Actions minutes) and push this folder to `main`.
2. In the repo, go to **Settings → Pages → Build and deployment → Source** and choose **GitHub Actions**.
3. Go to **Actions → Deploy site → Run workflow**. A couple of minutes later the site is live at `https://<you>.github.io/<repo>/`, listing every skin, untagged for now.

## 2. Tag the skins with Haiku

1. Get an API key at <https://platform.claude.com> and add it under **Settings → Secrets and variables → Actions → New repository secret**, named `ANTHROPIC_API_KEY`.
2. **Do a test run first:** go to **Actions → Tag skins → Run workflow**, enter `5` in *test_count* and run it. The log prints the tags for 5 skins. Check that they look right before you spend more.
3. Run it again with every box blank. This sends all untagged skins through the Batch API at half price. Batches usually finish within an hour; the job waits, commits `data/tags.json`, then redeploys the site.

Rough cost: about 5k input + 600 output tokens per entry. At Haiku 5.5 batch prices that's a few dollars at most, even counting every style as its own entry. The script prints an estimate before it submits.

### Running it on your own computer instead

```bash
pip install -r requirements.txt
python scripts/fetch_skins.py
export ANTHROPIC_API_KEY=sk-ant-...
python scripts/tag_skins.py --test 5      # quick check, prints tags
python scripts/tag_skins.py               # batch-tag everything untagged
python scripts/build_site_data.py
python -m http.server -d site 8000        # open http://localhost:8000
```

Useful flags: `--limit 200`, `--ids CID_A,CID_B --retag`, `--image icon` (icon only, no full-body image, cheapest), `--upgrade` (see below), `--no-wait` then `--collect` later.
If the API rejects structured outputs, add `--mode tool`.

### Styles and images

**Every selectable style is its own entry.** `fetch_skins.py` turns each style option on a skin (from Fortnite-API's `variants`) into its own entry, with its own image and tags. The ID is `BASEID::Channel::Tag`, and you can use it in the overrides sheet like any other ID.
- The default look stays on the base entry.
- Channels with lots of near-identical options are skipped (jersey numbers and similar, or more than 16 options). You can change this with `SKIP_CHANNELS` / `MAX_OPTIONS_PER_CHANNEL` in `fetch_skins.py`.
- On the site, a checkbox hides or shows styles as separate cards. Each skin's detail view shows all of its styles as thumbnails.

**What the model sees:**
1. **The icon for that exact style always comes first**, and it's the authority on colors, hair, headwear and so on.
2. **For base skins, a full-body image is sent second when there is one.** That's the shop render (`newDisplayAsset.renderImages`, saved into `data/renders.json` each day) or else `featured`. These promo images can show a different style than the default, so the model is told to use them only for parts the icon cuts off (legs, shoes) and only when they match.

Style entries only have their own icon, which is usually cut off above the feet. The model reports whether the feet were visible and skips shoe tags when they weren't. Those entries get a note in the detail view and show up under **Review status → Shoes not visible**. Once shop renders have piled up, run **Tag skins** with **upgrade** checked to re-tag base skins that now have a full-body render.

## 3. Fix tags by hand

Both options use the same columns:

| id | name | add_tags | remove_tags | verified | notes |
|---|---|---|---|---|---|
| CID_028_Athena_Commando_F | Renegade Raider | aviators | sunglasses | yes | |

- Tags are separated by spaces or commas, written Danbooru style (`red_hair`, `cel_shading`).
- `verified` = yes shows a ✓ on the site, and you can filter by review status.
- `name` is only there to make the sheet readable.
- You can add tags that aren't in the vocabulary; they show up under "Other".

**Option A: CSV in the repo.** Edit `data/overrides.csv` right on github.com. Committing it redeploys the site.

**Option B: Google Sheet** (easier for several people):
1. Make a sheet with the header row above.
2. **File → Share → Publish to web**, pick that sheet, format **CSV**, then publish and copy the link.
3. In the repo: **Settings → Secrets and variables → Actions → Variables → New repository variable**, named `SHEET_CSV_URL`, with the link as its value.
4. The site rebuilds daily with the sheet's edits. To apply them right away, run **Deploy site** by hand.

Tip: the site publishes every skin's current tags at `data/tags.csv`. Import it into a second tab of the sheet as a reference while you review.

Visitors can also click **Suggest a tag fix** on any skin. That opens a pre-filled GitHub issue you can copy into the sheet.

## 4. Grow the vocabulary

After each tagging run, `data/suggestions.md` lists tags the model wanted to use but couldn't, with the most common first. Add the good ones to a category in `tagging/vocab.json` (mark non-Danbooru tags in `_extras`), then re-tag with `--retag` (about $1 for everything).

Tags in the `outfit_traits` category (reactive, color selectable, multiple styles) come from Fortnite-API data, not from the model.

## Notes

- Fortnite-API is a free community API. If it ever starts requiring a key, add it as a repository secret named `FORTNITE_API_KEY`; the workflows already pass it along.
- Not affiliated with Epic Games. All Fortnite images and names belong to Epic Games.
