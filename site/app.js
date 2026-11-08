(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const PAGE = 120;
  const RARITY_ORDER = ["Common", "Uncommon", "Rare", "Epic", "Legendary", "Mythic"];
  const RARITY_COLORS = {
    Common: "#8c8c8c", Uncommon: "#60aa3a", Rare: "#3d9ff0", Epic: "#b45af0", Legendary: "#e0812c",
    Mythic: "#f0d15a", "Icon Series": "#3fd5d5", "Marvel Series": "#c53333", "DC Series": "#5475c7",
    "Star Wars Series": "#3a4fb8", "Gaming Legends Series": "#7b5cf0", "Shadow Series": "#6b6b6b",
    "Slurp Series": "#29d0e8", "Dark Series": "#d63fc4", "Frozen Series": "#9ad4f5", "Lava Series": "#d9551e",
  };
  const STATUSES = { verified: "Hand-verified", unverified: "Not verified", untagged: "Not tagged yet", unsure: "Has unsure tags", nofeet: "Shoes not visible", copied: "Shading-only style (tags copied)", icononly: "Style shown only as an icon" };

  let skins = [], cats = [], tagCat = {}, results = [], shown = 0, byId = {}, groupedCount = {};
  let savedView = "icon";
  try { savedView = localStorage.getItem("view") || "icon"; } catch (e) { /* storage blocked */ }
  const state = { col: "", shared: null, view: savedView, styles: true, q: "", sort: "new", any: false, inc: new Set(), exc: new Set(), grp: new Set(), ch: new Set(), status: new Set() };

  const pretty = (t) => t.replace(/_/g, " ");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const group = (s) => s.sr || s.r || "Unknown";
  const chapterOf = (s) => (s.ch ? `Chapter ${s.ch}` : "Unknown");

  // ---------- collections (saved in this browser) ----------
  // [{ id, name, items: [skin or style IDs] }]. localStorage can be blocked or cleared, so it's wrapped
  // in try/catch and falls back to memory for the visit; "Export" gives people a backup file.
  let collections = [];
  try { collections = JSON.parse(localStorage.getItem("collections") || "[]"); } catch (e) { collections = []; }
  if (!Array.isArray(collections)) collections = [];
  function saveCollections() {
    try { localStorage.setItem("collections", JSON.stringify(collections)); return true; }
    catch (e) { return false; }
  }
  const colById = (id) => collections.find((c) => c.id === id);
  const inAnyCollection = (id) => collections.some((c) => c.items.includes(id));
  function newCollection(name, items = []) {
    name = (name || "").trim().slice(0, 60) || `Collection ${collections.length + 1}`;
    const c = { id: "c" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6), name, items: [...new Set(items)] };
    collections.push(c);
    saveCollections();
    return c;
  }
  function toggleInCollection(colId, skinId, on) {
    const c = colById(colId);
    if (!c) return;
    const has = c.items.includes(skinId);
    if (on && !has) c.items.push(skinId);
    if (!on && has) c.items = c.items.filter((x) => x !== skinId);
    saveCollections();
  }
  // Share links pack a collection into the URL: deflate-compressed when the browser can, else plain.
  const b64url = (bytes) => btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const unb64url = (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/")), (ch) => ch.charCodeAt(0));
  async function packShare(c) {
    const json = new TextEncoder().encode(JSON.stringify({ n: c.name, i: c.items }));
    if (window.CompressionStream) {
      const z = await new Response(new Blob([json]).stream().pipeThrough(new CompressionStream("deflate-raw"))).arrayBuffer();
      return "z" + b64url(new Uint8Array(z));
    }
    return "j" + b64url(json);
  }
  async function unpackShare(s) {
    let bytes = unb64url(s.slice(1));
    if (s[0] === "z") bytes = new Uint8Array(await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate-raw"))).arrayBuffer());
    const o = JSON.parse(new TextDecoder().decode(bytes));
    return { name: String(o.n || "Shared collection").slice(0, 60), items: (o.i || []).filter((x) => typeof x === "string") };
  }

  // ---------- URL hash state (makes filtered views shareable) ----------
  function readHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    state.q = p.get("q") || "";
    state.sort = p.get("sort") || "new";
    state.any = p.get("any") === "1";
    state.styles = p.get("ns") !== "1";
    state.col = p.get("col") || "";
    if (state.col && !colById(state.col)) state.col = "";
    if (p.get("v")) state.view = p.get("v") === "body" ? "body" : "icon";
    for (const [k, key] of [["inc", "t"], ["exc", "x"], ["grp", "g"], ["ch", "c"], ["status", "s"]]) {
      state[k] = new Set((p.get(key) || "").split(",").filter(Boolean));
    }
  }
  function writeHash() {
    const p = new URLSearchParams();
    if (state.q) p.set("q", state.q);
    if (state.sort !== "new") p.set("sort", state.sort);
    if (state.any) p.set("any", "1");
    if (!state.styles) p.set("ns", "1");
    if (state.col) p.set("col", state.col);
    if (state.shared) p.set("share", state.shared.packed);
    if (state.view === "body") p.set("v", "body");
    for (const [k, key] of [["inc", "t"], ["exc", "x"], ["grp", "g"], ["ch", "c"], ["status", "s"]]) {
      if (state[k].size) p.set(key, [...state[k]].join(","));
    }
    const h = p.toString();
    history.replaceState(null, "", h ? "#" + h : location.pathname + location.search);
  }

  // ---------- filtering ----------
  function passesBase(s) {
    if (state.shared) { if (!state.shared.set.has(s.id)) return false; }
    else if (state.col) { const c = colById(state.col); if (!c || !c.items.includes(s.id)) return false; }
    // Inside a collection every saved entry shows, even styles normally hidden or folded away.
    else if (!state.styles && s.of && !s.grp) return false;  // grouped styles live inside their base card
    if (state.q) {
      const words = state.q.toLowerCase().split(/\s+/).filter(Boolean);
      if (!words.every((w) => s._hay.includes(w))) return false;
    }
    if (state.grp.size && !state.grp.has(group(s))) return false;
    if (state.ch.size && !state.ch.has(chapterOf(s))) return false;
    if (state.status.size) {
      const st = new Set();
      if (s.v) st.add("verified"); else st.add("unverified");
      if (s.u) st.add("untagged");
      if (s.low && s.low.length) st.add("unsure");
      if (s.nf) st.add("nofeet");
      if (s.inh && s.sh) st.add("copied");
      if (s.ico) st.add("icononly");
      for (const want of state.status) if (!st.has(want)) return false;
    }
    for (const t of state.exc) if (s._tags.has(t)) return false;
    return true;
  }
  function passesTags(s) {
    if (!state.inc.size) return true;
    if (state.any) { for (const t of state.inc) if (s._tags.has(t)) return true; return false; }
    for (const t of state.inc) if (!s._tags.has(t)) return false;
    return true;
  }
  const rarityRank = (s) => { const i = RARITY_ORDER.indexOf(s.r); return s.sr ? 10 : i === -1 ? -1 : i; };
  const sorters = {
    new: (a, b) => (b.a || "").localeCompare(a.a || ""),
    old: (a, b) => (a.a || "").localeCompare(b.a || ""),
    az: (a, b) => a.n.localeCompare(b.n),
    za: (a, b) => b.n.localeCompare(a.n),
    rarity: (a, b) => rarityRank(b) - rarityRank(a) || a.n.localeCompare(b.n),
    tags: (a, b) => b.t.length - a.t.length,
  };

  // Fold grouped styles (team/house crests etc.) into one card per base skin.
  // Each card remembers which entry matched, so opening it selects that style.
  function fold(list) {
    const cards = new Map();
    for (const s of list) {
      const key = s.grp ? s.of : s.id;
      let c = cards.get(key);
      if (!c) { c = { head: byId[key] || s, hit: s, tags: new Set() }; cards.set(key, c); }
      if (!s.grp) c.hit = s;
      for (const t of s._tags) c.tags.add(t);
    }
    return [...cards.values()];
  }

  function update() {
    const base = skins.filter(passesBase);
    const sorter = sorters[state.sort] || sorters.new;
    results = fold(base.filter(passesTags)).sort((a, b) => sorter(a.head, b.head));
    renderFacets(state.any ? fold(base) : results);
    renderActive();
    renderCollections();
    const nStyles = results.filter((c) => c.head.of).length;
    $("#count").textContent = `${results.length.toLocaleString()} results` +
      (nStyles ? ` (${(results.length - nStyles).toLocaleString()} skins + ${nStyles.toLocaleString()} styles)` : "");
    $("#empty").hidden = results.length > 0;
    $("#empty").textContent = state.col && colById(state.col) && !colById(state.col).items.length
      ? "This collection is empty. Open any skin and tick the collection in its popup."
      : "No skins match these filters.";
    $("#grid").innerHTML = "";
    shown = 0;
    renderMore();
    writeHash();
  }

  // ---------- rendering ----------
  function chip(kind, val, label, n, extraClass = "") {
    let cls = "chip " + extraClass;
    if (kind === "tag") cls += state.inc.has(val) ? " on" : state.exc.has(val) ? " off" : "";
    else if (state[kind]?.has(val)) cls += " on";
    if (n === 0) cls += " zero";
    const count = n == null ? "" : `<span class="n">${n}</span>`;
    return `<button class="${cls}" data-kind="${kind}" data-val="${esc(val)}">${esc(label)}${count}</button>`;
  }

  function renderFacets(pool) {
    const tagCounts = {}, grpCounts = {}, chCounts = {};
    for (const c of pool) {
      for (const t of c.tags) tagCounts[t] = (tagCounts[t] || 0) + 1;
    }
    // Group/chapter counts ignore their own filter so you can pick several.
    for (const s of skins) {
      if (s.grp || !passesTags(s)) continue;
      const g = group(s), c = chapterOf(s);
      const savedG = state.grp, savedC = state.ch;
      state.grp = new Set(); if (passesBase(s)) grpCounts[g] = (grpCounts[g] || 0) + 1; state.grp = savedG;
      state.ch = new Set(); if (passesBase(s)) chCounts[c] = (chCounts[c] || 0) + 1; state.ch = savedC;
    }
    const grpNames = [...new Set(skins.map(group))].sort((a, b) => {
      const ia = RARITY_ORDER.indexOf(a), ib = RARITY_ORDER.indexOf(b);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib) || a.localeCompare(b);
    });
    $("#rarityList").innerHTML = grpNames.map((g) => chip("grp", g, g, grpCounts[g] || 0)).join("");
    const chNames = [...new Set(skins.map(chapterOf))].sort((a, b) => (parseInt(a.split(" ")[1]) || 999) - (parseInt(b.split(" ")[1]) || 999));
    $("#chapterList").innerHTML = chNames.map((c) => chip("ch", c, c, chCounts[c] || 0)).join("");
    $("#statusList").innerHTML = Object.entries(STATUSES).map(([k, l]) => chip("status", k, l)).join("");

    const filter = $("#tagSearch").value.trim().toLowerCase().replace(/\s+/g, "_");
    const openNow = new Set([...document.querySelectorAll("#tagFacets details[open]")].map((d) => d.dataset.key));
    $("#tagFacets").innerHTML = cats.map((c) => {
      const tags = c.tags
        .filter((t) => !filter || t.includes(filter))
        .filter((t) => tagCounts[t] || state.inc.has(t) || state.exc.has(t))
        .sort((a, b) => (tagCounts[b] || 0) - (tagCounts[a] || 0));
      if (!tags.length) return "";
      const isOpen = filter || openNow.has(c.key) || tags.some((t) => state.inc.has(t) || state.exc.has(t));
      return `<details class="facet" data-key="${c.key}" ${isOpen ? "open" : ""}>
        <summary>${esc(c.label)} <span class="n">(${tags.length})</span></summary>
        <div class="chips">${tags.map((t) => chip("tag", t, pretty(t), tagCounts[t] || 0)).join("")}</div>
      </details>`;
    }).join("");
  }

  function renderCollections() {
    $("#colCount").textContent = collections.length ? `(${collections.length})` : "";
    $("#colList").innerHTML = collections.length
      ? collections.map((c) => `<button class="chip ${state.col === c.id ? "on" : ""}" data-kind="col" data-val="${esc(c.id)}">${esc(c.name)}<span class="n">${c.items.length}</span></button>`).join("")
      : `<p class="hint">Save skins from their popup to build named collections. They're kept in this browser.</p>`;
    $("#colActions").hidden = !state.col;
    const banner = $("#sharedBanner");
    banner.hidden = !state.shared;
    if (state.shared) {
      banner.innerHTML = `Viewing a shared collection: <b>${esc(state.shared.name)}</b> (${state.shared.items.length})
        <button class="link-btn" id="saveShared">Save to my collections</button>
        <button class="link-btn" id="closeShared">Close</button>`;
    }
  }

  function renderDetailCollections(s) {
    const box = $("#dCollections");
    box.dataset.id = s.id;
    box.innerHTML = `<h4>Collections</h4>
      <div class="d-col-list">${collections.map((c) => `
        <label class="d-col"><input type="checkbox" data-col-check="${esc(c.id)}" ${c.items.includes(s.id) ? "checked" : ""}> ${esc(c.name)}</label>`).join("")}</div>
      <form class="col-new" id="dColNew"><input placeholder="New collection…" maxlength="60" aria-label="New collection name"><button>Add</button></form>`;
  }

  function renderActive() {
    const parts = [];
    if (state.q) parts.push(`<button class="chip on" data-kind="q" data-val="">“${esc(state.q)}” ✕</button>`);
    for (const t of state.inc) parts.push(chip("tag", t, pretty(t) + " ✕"));
    for (const t of state.exc) parts.push(chip("tag", t, "not " + pretty(t) + " ✕"));
    for (const k of ["grp", "ch", "status"]) for (const v of state[k]) parts.push(chip(k, v, (STATUSES[v] || v) + " ✕"));
    if (state.col && colById(state.col)) parts.unshift(`<button class="chip on" data-kind="col" data-val="">★ ${esc(colById(state.col).name)} ✕</button>`);
    $("#active").innerHTML = parts.join("");
  }

  // Full-body images are squares with lots of empty space at the sides. build_site_data.py gives each
  // one a measured box ("ab": [left, top, right, bottom] as fractions) around the visible figure. This
  // zooms and centers the figure inside a frame of the given aspect ratio (width / height) with CSS,
  // leaving the image itself untouched. Without a box it falls back to showing the whole image.
  const FIT_PAD = 0.03;
  function fitImg(url, box, aspect, alt, extraClass = "") {
    if (!box) return `<img class="${extraClass}" loading="lazy" src="${esc(url)}" alt="${esc(alt)}" style="object-fit:contain">`;
    const [l, t, r, b] = box;
    const H = 1 / aspect;                                      // frame height, in frame widths
    const bw = r - l + 2 * FIT_PAD, bh = b - t + 2 * FIT_PAD;
    const S = Math.min(1 / bw, H / bh);                        // image size, in frame widths
    const left = 0.5 - ((l + r) / 2) * S, top = H / 2 - ((t + b) / 2) * S;
    const st = `position:absolute;width:${(S * 100).toFixed(2)}%;height:auto;max-width:none;aspect-ratio:1;` +
               `left:${(left * 100).toFixed(2)}%;top:${((top / H) * 100).toFixed(2)}%`;
    return `<img class="fitted ${extraClass}" loading="lazy" src="${esc(url)}" alt="${esc(alt)}" style="${st}">`;
  }

  function renderMore() {
    const slice = results.slice(shown, shown + PAGE);
    shown += slice.length;
    $("#grid").insertAdjacentHTML("beforeend", slice.map(({ head: s, hit }) => {
      const viaStyle = hit !== s && hit.grp;
      const crest = viaStyle && hit.ico;  // crest/logo previews sit in the corner; real renders replace the image
      const extra = groupedCount[s.id] ? `<span class="badge" title="Selectable styles shown in the popup">+${groupedCount[s.id]} styles</span>` : "";
      return `
      <button class="card rar" style="--rc:${RARITY_COLORS[group(s)] || "#555"}" data-id="${esc(hit.id)}">
        ${state.view === "body" && s.alt && !(viaStyle && !crest)
          ? `<div class="card-media body">${fitImg(s.alt, s.ab, 3 / 4, s.n)}</div>`
          : `<div class="card-media${state.view === "body" ? " body icon-fallback" : ""}"><img loading="lazy" src="${esc(viaStyle && !crest ? hit.img : s.img)}" alt="${esc(s.n)}"></div>`}
        ${crest ? `<img class="card-crest" loading="lazy" src="${esc(hit.img)}" alt="${esc(hit.sty)}" title="${esc(hit.sty)} style">` : ""}
        <div class="name">${inAnyCollection(hit.id) || inAnyCollection(s.id) ? '<span class="star" title="In one of your collections">★</span>' : ""}${esc(s.n)}${s.v ? '<span class="badge" title="Tags checked by hand">✓</span>' : ""}${extra}</div>
        <div class="sub">${viaStyle ? `<span class="style-badge">${esc(hit.sty)}</span> · ` : s.of ? '<span class="style-badge">style</span> · ' : ""}${esc(group(s))}${s.ch ? ` · C${esc(s.ch)}S${esc(s.se)}` : ""}${s.u ? " · untagged" : ""}</div>
      </button>`;
    }).join(""));
  }

  function repoSlug() {
    const set = document.body.dataset.repo;
    if (set) return set;
    const m = location.hostname.match(/^([^.]+)\.github\.io$/);
    const path = location.pathname.split("/").filter(Boolean)[0];
    return m && path ? `${m[1]}/${path}` : "";
  }

  function openDetail(id) {
    const s = byId[id];
    if (!s) return;
    // An icon-only style's image is just a crest/logo, so show the base outfit with the crest on top.
    // Other folded styles (e.g. shading-only) have real renders of their own.
    const look = s.grp && s.ico && byId[s.of] ? byId[s.of] : s;
    $("#dCrest").hidden = look === s;
    if (look !== s) { $("#dCrest").src = s.img; $("#dCrest").alt = s.sty || ""; }
    // Open on the full-body image when there is one; the button switches to the icon and back.
    let showingAlt = !!look.alt;
    const altBtn = $("#dAltToggle");
    const showImage = () => {
      const wrap = $("#dImgFrame");
      wrap.classList.toggle("body", showingAlt);
      wrap.innerHTML = showingAlt ? fitImg(look.alt, look.ab, 3 / 4, s.n)
                                  : `<img src="${esc(look.big || look.img)}" alt="${esc(s.n)}">`;
      altBtn.textContent = showingAlt ? "Show icon" : "Show full-body image";
      // The promo image belongs to the default look, so say so when a different style is selected.
      $("#dAltNote").hidden = !(showingAlt && s.of);
    };
    altBtn.hidden = !look.alt;
    altBtn.onclick = () => { showingAlt = !showingAlt; showImage(); };
    showImage();
    const fam = s.of || s.id;
    const family = skins.filter((x) => x.id === fam || x.of === fam);
    $("#dStyles").innerHTML = family.length > 1 ? family.map((x) => `
      <button class="style-thumb ${x.id === s.id ? "cur" : ""}" data-style-id="${esc(x.id)}" title="${esc(x.sty || "Default style")}">
        <img loading="lazy" src="${esc(x.img)}" alt="${esc(x.sty || "Default style")}"></button>`).join("") : "";
    renderDetailCollections(s);
    $("#dName").textContent = s.n;
    $("#dMeta").textContent = [s.grp && s.sty && `Style: ${s.sty}`, group(s), s.st && `Set: ${s.st}`, s.ch && `Chapter ${s.ch}, Season ${s.se}`, s.a && `Added ${s.a}`].filter(Boolean).join(" · ");
    $("#dDesc").textContent = s.d || "";
    const captionLabel = s.cv ? "Verified caption: " : s.inh && !s.vt ? "AI caption (default style): " : "AI caption: ";
    $("#dCaption").textContent = s.c ? captionLabel + s.c : s.u && !s.sh ? "Not tagged yet." : "";
    const byCat = {};
    for (const t of s.t) (byCat[tagCat[t] || "other"] ||= []).push([t, ""]);
    for (const t of s.low || []) (byCat[tagCat[t] || "other"] ||= []).push([t, "low"]);
    $("#dTags").innerHTML = cats.filter((c) => byCat[c.key]).map((c) => `
      <div class="tag-group"><h4>${esc(c.label)}</h4><div class="chips">
        ${byCat[c.key].map(([t, low]) => chip("tag", t, pretty(t) + (low ? " (unsure)" : ""), null, low ? "low" : "")).join("")}
      </div></div>`).join("") + (s.ico && !s.grp ? `<p class="caption">This style's preview is only an icon${s.ic ? ` (${esc(s.ic)})` : ""}, not the character, so ${s.inh ? "its tags are copied from the default style, with colors taken from the icon" : "it gets its tags once the default style is tagged"}.</p>` : "")
      + (s.acc ? `<p class="caption">This style is the default look with the ${esc(s.acc.split(" ")[0])} ${s.acc.endsWith(" on") ? "on" : "off"}, so ${s.inh ? "its tags are copied from the default style with just that changed" : "it gets its tags once the default style is tagged"}.</p>` : "")
      + (s.fx ? `<p class="caption">This style only switches lights or effects ${s.fx === "on" ? "on" : "off"}, so ${s.inh ? "its tags are copied from the default style" : "it gets its tags once the default style is tagged"}.</p>` : "")
      + (s.inh && s.sh ? `<p class="caption">This style only changes the shading, so its tags are copied from the default style with the shading tag swapped.</p>` : "")
      + (s.sh && s.u ? `<p class="caption">This style only changes the shading. It gets its tags once the default style is tagged.</p>` : "")
      + (s.nf ? `<p class="caption">The feet weren't visible in the image this skin was tagged from, so shoe tags may be missing.</p>` : "")
      + (s.no ? `<p class="caption">Note: ${esc(s.no)}</p>` : "");
    const slug = repoSlug();
    const link = $("#dReport");
    if (slug) {
      // Like a Danbooru tag edit: the reporter fixes the whole list in place (delete wrong tags, type
      // missing ones), and maintainers diff it against the current tags.
      const body = `Skin: ${s.n}\nID: ${s.id}\n\nEdit the tag list below: delete wrong tags and add missing ones, separated by spaces.\n\n` +
        "```\n" + s.t.join(" ") + "\n```" +
        (s.low && s.low.length ? `\n\nUnsure tags (shown as \"unsure\" and left out of filters; move any that are right into the list above): ${s.low.join(" ")}` : "");
      link.href = `https://github.com/${slug}/issues/new?title=${encodeURIComponent("Tag fix: " + s.n)}&body=${encodeURIComponent(body)}&labels=tag-fix`;
      link.hidden = false;
    } else link.hidden = true;
    $("#dId").textContent = s.id;
    if (!$("#detail").open) $("#detail").showModal();
    $(".detail-info").scrollTop = 0;
  }

  // ---------- events ----------
  function toggle(kind, val) {
    if (kind === "tag") {
      if (state.inc.has(val)) { state.inc.delete(val); state.exc.add(val); }
      else if (state.exc.has(val)) state.exc.delete(val);
      else state.inc.add(val);
    } else if (kind === "q") {
      state.q = ""; $("#search").value = "";
    } else if (kind === "col") {
      state.col = state.col === val ? "" : val;
      state.shared = null;
    } else {
      state[kind].has(val) ? state[kind].delete(val) : state[kind].add(val);
    }
    update();
  }

  document.addEventListener("click", (e) => {
    const c = e.target.closest(".chip");
    if (c) {
      e.preventDefault();
      const inDialog = c.closest("dialog");
      if (inDialog) {
        // From the detail view, a tag click means "show me more like this".
        state.inc.add(c.dataset.val); state.exc.delete(c.dataset.val);
        $("#detail").close(); update(); return;
      }
      return toggle(c.dataset.kind, c.dataset.val);
    }
    const thumb = e.target.closest(".style-thumb");
    if (thumb) return openDetail(thumb.dataset.styleId);
    const card = e.target.closest(".card");
    if (card) return openDetail(card.dataset.id);
  });
  $("#detail").addEventListener("click", (e) => { if (e.target === $("#detail")) $("#detail").close(); });
  // Refresh stars and the collection view once the popup closes (not while it's open, to keep scroll).
  let collectionsChanged = false;
  $("#detail").addEventListener("close", () => { if (collectionsChanged) { collectionsChanged = false; update(); } });
  $("#dCollections").addEventListener("change", (e) => {
    const cb = e.target.closest("[data-col-check]");
    if (!cb) return;
    toggleInCollection(cb.dataset.colCheck, $("#dCollections").dataset.id, cb.checked);
    collectionsChanged = true;
  });
  $("#dCollections").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = e.target.querySelector("input");
    const c = newCollection(input.value, [$("#dCollections").dataset.id]);
    collectionsChanged = true;
    renderDetailCollections(byId[$("#dCollections").dataset.id]);
    flash(`Saved to "${c.name}"`);
  });

  // Sidebar: new / rename / delete / share / export / import
  $("#colNew").addEventListener("submit", (e) => {
    e.preventDefault();
    const c = newCollection($("#colNewName").value);
    $("#colNewName").value = "";
    flash(`Created "${c.name}". Add skins from their popup.`);
    renderCollections();
  });
  $("#colActions").addEventListener("click", async (e) => {
    const act = e.target.closest("[data-col-act]")?.dataset.colAct;
    const c = colById(state.col);
    if (!act || !c) return;
    if (act === "rename") {
      const name = prompt("Rename collection", c.name);
      if (name && name.trim()) { c.name = name.trim().slice(0, 60); saveCollections(); update(); }
    } else if (act === "delete") {
      if (confirm(`Delete the collection "${c.name}"? The skins themselves aren't affected.`)) {
        collections = collections.filter((x) => x !== c); saveCollections(); state.col = ""; update();
      }
    } else if (act === "share") {
      const url = location.origin + location.pathname + "#share=" + await packShare(c);
      try { await navigator.clipboard.writeText(url); flash("Share link copied"); }
      catch (err) { prompt("Copy this link to share the collection:", url); }
    }
  });
  $("#colExport").addEventListener("click", () => {
    const blob = new Blob([JSON.stringify({ collections }, null, 1)], { type: "application/json" });
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: "skin-finder-collections.json" });
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });
  $("#colImport").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      let added = 0;
      for (const c of data.collections || []) {
        if (c && c.name && Array.isArray(c.items)) { newCollection(c.name, c.items.filter((x) => typeof x === "string")); added++; }
      }
      flash(`Imported ${added} collection${added === 1 ? "" : "s"}`);
      update();
    } catch (err) { flash("That file isn't a Skin Finder collections export"); }
  });
  $("#sharedBanner").addEventListener("click", (e) => {
    if (e.target.id === "saveShared" && state.shared) {
      const c = newCollection(state.shared.name, state.shared.items);
      state.shared = null; state.col = c.id; flash(`Saved "${c.name}"`); update();
    } else if (e.target.id === "closeShared") {
      state.shared = null; update();
    }
  });
  let flashTimer;
  function flash(msg) {
    const el = $("#flash");
    el.textContent = msg; el.hidden = false;
    clearTimeout(flashTimer); flashTimer = setTimeout(() => { el.hidden = true; }, 2200);
  }

  let t;
  $("#search").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { state.q = e.target.value.trim(); update(); }, 150); });
  $("#tagSearch").addEventListener("input", () => { clearTimeout(t); t = setTimeout(update, 120); });
  $("#sort").addEventListener("change", (e) => { state.sort = e.target.value; update(); });
  $("#matchAny").addEventListener("change", (e) => { state.any = e.target.checked; update(); });
  $("#showStyles").addEventListener("change", (e) => { state.styles = e.target.checked; update(); });
  document.querySelectorAll("#viewSwitch button").forEach((b) => b.addEventListener("click", () => {
    state.view = b.dataset.view;
    try { localStorage.setItem("view", state.view); } catch (e) { /* storage blocked */ }
    syncViewSwitch();
    update();
  }));
  function syncViewSwitch() {
    document.querySelectorAll("#viewSwitch button").forEach((b) => b.classList.toggle("on", b.dataset.view === state.view));
    $("#grid").classList.toggle("body-view", state.view === "body");
  }
  $("#clearAll").addEventListener("click", () => {
    Object.assign(state, { col: "", shared: null, q: "", any: false, inc: new Set(), exc: new Set(), grp: new Set(), ch: new Set(), status: new Set() });
    $("#search").value = ""; $("#tagSearch").value = ""; $("#matchAny").checked = false; update();
  });
  $("#filtersToggle").addEventListener("click", () => $("#filters").classList.toggle("open"));
  new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting && shown < results.length) renderMore();
  }, { rootMargin: "800px" }).observe($("#sentinel"));

  // ---------- load ----------
  Promise.all([fetch("data/skins.json").then((r) => r.json()), fetch("data/vocab.json").then((r) => r.json())])
    .then(([data, vocab]) => {
      cats = vocab.categories;
      for (const s of data) { byId[s.id] = s; if (s.grp) groupedCount[s.of] = (groupedCount[s.of] || 0) + 1; }
      for (const c of cats) for (const tag of c.tags) tagCat[tag] = c.key;
      skins = data.map((s) => (byId[s.id] = {
        ...s,
        _tags: new Set(s.t),
        _hay: [s.n, s.d, s.st, s.sr, s.r, s.c, s.sty, ...s.t.map(pretty)].join(" ").toLowerCase(),
      }));
      readHash();
      const share = new URLSearchParams(location.hash.slice(1)).get("share");
      if (share) {
        unpackShare(share).then((c) => { state.shared = { ...c, packed: share, set: new Set(c.items) }; update(); })
          .catch(() => flash("That share link couldn't be read"));
      }
      $("#search").value = state.q;
      $("#sort").value = state.sort;
      $("#matchAny").checked = state.any;
      $("#showStyles").checked = state.styles;
      syncViewSwitch();
      update();
    })
    .catch((err) => {
      $("#count").textContent = "Couldn't load skin data. Run scripts/build_site_data.py first.";
      console.error(err);
    });
})();
