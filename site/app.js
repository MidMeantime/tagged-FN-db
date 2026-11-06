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
  const state = { styles: true, q: "", sort: "new", any: false, inc: new Set(), exc: new Set(), grp: new Set(), ch: new Set(), status: new Set() };

  const pretty = (t) => t.replace(/_/g, " ");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const group = (s) => s.sr || s.r || "Unknown";
  const chapterOf = (s) => (s.ch ? `Chapter ${s.ch}` : "Unknown");

  // ---------- URL hash state (makes filtered views shareable) ----------
  function readHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    state.q = p.get("q") || "";
    state.sort = p.get("sort") || "new";
    state.any = p.get("any") === "1";
    state.styles = p.get("ns") !== "1";
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
    for (const [k, key] of [["inc", "t"], ["exc", "x"], ["grp", "g"], ["ch", "c"], ["status", "s"]]) {
      if (state[k].size) p.set(key, [...state[k]].join(","));
    }
    const h = p.toString();
    history.replaceState(null, "", h ? "#" + h : location.pathname + location.search);
  }

  // ---------- filtering ----------
  function passesBase(s) {
    if (!state.styles && s.of && !s.grp) return false;  // grouped styles live inside their base card
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
    const nStyles = results.filter((c) => c.head.of).length;
    $("#count").textContent = `${results.length.toLocaleString()} results` +
      (nStyles ? ` (${(results.length - nStyles).toLocaleString()} skins + ${nStyles.toLocaleString()} styles)` : "");
    $("#empty").hidden = results.length > 0;
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

  function renderActive() {
    const parts = [];
    if (state.q) parts.push(`<button class="chip on" data-kind="q" data-val="">“${esc(state.q)}” ✕</button>`);
    for (const t of state.inc) parts.push(chip("tag", t, pretty(t) + " ✕"));
    for (const t of state.exc) parts.push(chip("tag", t, "not " + pretty(t) + " ✕"));
    for (const k of ["grp", "ch", "status"]) for (const v of state[k]) parts.push(chip(k, v, (STATUSES[v] || v) + " ✕"));
    $("#active").innerHTML = parts.join("");
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
        <img loading="lazy" src="${esc(viaStyle && !crest ? hit.img : s.img)}" alt="${esc(s.n)}">
        ${crest ? `<img class="card-crest" loading="lazy" src="${esc(hit.img)}" alt="${esc(hit.sty)}" title="${esc(hit.sty)} style">` : ""}
        <div class="name">${esc(s.n)}${s.v ? '<span class="badge" title="Tags checked by hand">✓</span>' : ""}${extra}</div>
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
    $("#dImg").src = look.big || look.img;
    $("#dImg").alt = s.n;
    $("#dCrest").hidden = look === s;
    if (look !== s) { $("#dCrest").src = s.img; $("#dCrest").alt = s.sty || ""; }
    let showingAlt = false;
    const altBtn = $("#dAltToggle");
    altBtn.hidden = !look.alt; $("#dAltNote").hidden = true;
    altBtn.textContent = "Show full-body promo image";
    altBtn.onclick = () => {
      showingAlt = !showingAlt;
      $("#dImg").src = showingAlt ? look.alt : look.big || look.img;
      altBtn.textContent = showingAlt ? "Show this style's icon" : "Show full-body promo image";
      $("#dAltNote").hidden = !showingAlt;
    };
    const fam = s.of || s.id;
    const family = skins.filter((x) => x.id === fam || x.of === fam);
    $("#dStyles").innerHTML = family.length > 1 ? family.map((x) => `
      <button class="style-thumb ${x.id === s.id ? "cur" : ""}" data-style-id="${esc(x.id)}" title="${esc(x.sty || "Default style")}">
        <img loading="lazy" src="${esc(x.img)}" alt="${esc(x.sty || "Default style")}"></button>`).join("") : "";
    $("#dName").textContent = s.n;
    $("#dMeta").textContent = [s.grp && s.sty && `Style: ${s.sty}`, group(s), s.st && `Set: ${s.st}`, s.ch && `Chapter ${s.ch}, Season ${s.se}`, s.a && `Added ${s.a}`].filter(Boolean).join(" · ");
    $("#dDesc").textContent = s.d || "";
    $("#dCaption").textContent = s.c ? (s.inh && !s.vt ? "AI caption (default style): " : "AI caption: ") + s.c : s.u && !s.sh ? "Not tagged yet." : "";
    const byCat = {};
    for (const t of s.t) (byCat[tagCat[t] || "other"] ||= []).push([t, ""]);
    for (const t of s.low || []) (byCat[tagCat[t] || "other"] ||= []).push([t, "low"]);
    $("#dTags").innerHTML = cats.filter((c) => byCat[c.key]).map((c) => `
      <div class="tag-group"><h4>${esc(c.label)}</h4><div class="chips">
        ${byCat[c.key].map(([t, low]) => chip("tag", t, pretty(t) + (low ? " (unsure)" : ""), null, low ? "low" : "")).join("")}
      </div></div>`).join("") + (s.ico && !s.grp ? `<p class="caption">This style's preview is only an icon${s.ic ? ` (${esc(s.ic)})` : ""}, not the character, so ${s.inh ? "its tags are copied from the default style, with colors taken from the icon" : "it gets its tags once the default style is tagged"}.</p>` : "")
      + (s.inh && s.sh ? `<p class="caption">This style only changes the shading, so its tags are copied from the default style with the shading tag swapped.</p>` : "")
      + (s.sh && s.u ? `<p class="caption">This style only changes the shading. It gets its tags once the default style is tagged.</p>` : "")
      + (s.nf ? `<p class="caption">The feet weren't visible in the image this skin was tagged from, so shoe tags may be missing.</p>` : "")
      + (s.no ? `<p class="caption">Note: ${esc(s.no)}</p>` : "");
    const slug = repoSlug();
    const link = $("#dReport");
    if (slug) {
      const body = `Skin: ${s.n}\nID: ${s.id}\n\nTags to add:\n\nTags to remove:\n\nCurrent tags: ${s.t.join(" ")}`;
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

  let t;
  $("#search").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { state.q = e.target.value.trim(); update(); }, 150); });
  $("#tagSearch").addEventListener("input", () => { clearTimeout(t); t = setTimeout(update, 120); });
  $("#sort").addEventListener("change", (e) => { state.sort = e.target.value; update(); });
  $("#matchAny").addEventListener("change", (e) => { state.any = e.target.checked; update(); });
  $("#showStyles").addEventListener("change", (e) => { state.styles = e.target.checked; update(); });
  $("#clearAll").addEventListener("click", () => {
    Object.assign(state, { q: "", any: false, inc: new Set(), exc: new Set(), grp: new Set(), ch: new Set(), status: new Set() });
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
      $("#search").value = state.q;
      $("#sort").value = state.sort;
      $("#matchAny").checked = state.any;
      $("#showStyles").checked = state.styles;
      update();
    })
    .catch((err) => {
      $("#count").textContent = "Couldn't load skin data. Run scripts/build_site_data.py first.";
      console.error(err);
    });
})();
