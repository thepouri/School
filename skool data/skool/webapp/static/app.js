/* Skool Browser — frontend logic.
 * Two views (groups / users), each with filter state, pagination and a
 * detail modal. All data comes from the /api endpoints (DB-backed). */

"use strict";

const $ = (id) => document.getElementById(id);

/* ── utilities ── */
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]),
  );

const num = (v) => {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

const fmtNum = (n) => {
  if (n === null || n === undefined) return "–";
  if (typeof n === "number" && !Number.isFinite(n)) return "–";
  return Number(n).toLocaleString("en-US");
};

const fmtPrice = (g) => {
  if (g.price_usd === null || g.price_usd === undefined) return "Free / n/a";
  if (Number(g.price_usd) <= 0) return "Free";
  const cur = (g.price_currency || "usd").toUpperCase();
  return "$" + fmtNum(g.price_usd) + " " + cur;
};

const initialsOf = (name) => {
  const parts = String(name || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!parts.length) return "?";
  return parts.slice(0, 2).map((p) => p[0]).join("").toUpperCase();
};

/* Cover fallback: if no URL, use a color + initials tile. */
const coverStyle = (g) => {
  if (g && (g.cover_url || g.logo_big_url || g.logo_url)) {
    return `background-image:url('${esc(g.cover_url || g.logo_big_url || g.logo_url)}')`;
  }
  return `background:linear-gradient(135deg, ${g.color || "#333"}, #171a21)`;
};

/* Parse the `links` column (JSON) into a list of {url, label, public}.
   Stored shape is either {"links":[{url,label,public},...]} or a bare
   single-object dict. Anything unparseable yields []. */
function parseLinks(raw) {
  if (!raw) return [];
  let data;
  try { data = JSON.parse(raw); } catch { return []; }
  if (Array.isArray(data)) return data;
  if (data && Array.isArray(data.links)) return data.links;
  if (data && typeof data === "object" && data.url) return [data];
  return [];
}

/* ── state ── */
const groupsState = {
  filters: { q: "", category: "", language: "", price_bucket: "", is_public: "", interval: "" },
  numbers: { min_price: null, max_price: null, min_members: null, max_members: null, min_courses: null, min_posts: null },
  bools: { detail: "" },
  sort: "members_desc",
  page: 1,
};
const usersState = {
  filters: { q: "", location_source: "", timezone: "", has_avatar: "", owned: "", scraped: "" },
  numbers: { min_followers: null, max_followers: null },
  sort: "followers_desc",
  page: 1,
};

/* ── http ── */
async function http(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

/* ── image handling ── */
function bindImage(img, fallback) {
  img.addEventListener("error", () => {
    img.style.display = "none";
    const holder = fallback && document.querySelector(fallback);
    if (holder) holder.style.display = "grid";
  }, { once: true });
}

/* ───────────────────────── groups ───────────────────────── */

const GROUP_CARD = (g) => `
  <div class="card" data-id="${esc(g.id)}">
    <div class="card-cover" style="${coverStyle(g)}">
      <div class="logo-badge">
        <img src="${esc(g.logo_url || g.logo_big_url || "")}" data-fallback="self"
          onerror="this.style.display='none';this.nextElementSibling.style.display='grid'"
          alt="" style="display:none">
        <span class="initials" style="display:grid">${initialsOf(g.display_name || g.name)}</span>
      </div>
    </div>
    <div class="card-body">
      <div class="card-title">${esc(g.display_name || g.name)}</div>
      <div class="card-owner">@${esc(g.owner_name || "unknown")}</div>
      <div class="card-desc">${esc(g.description)}</div>
    </div>
    <div class="card-stats">
      ${g.price_usd !== null && g.price_usd !== undefined && g.price_usd > 0
        ? `<span class="stat accent">💲 <span class="v accent">$${fmtNum(g.price_usd)}</span></span>`
        : `<span class="stat"><span class="v">Free</span></span>`}
      <span class="stat">👥 <span class="v">${fmtNum(g.total_members)}</span></span>
      <span class="stat">📚 <span class="v">${fmtNum(g.num_courses)}</span> courses</span>
      <span class="stat">📝 <span class="v">${fmtNum(g.total_posts)}</span></span>
      ${g.is_public === true ? `<span class="badge pub">public</span>` : g.is_public === false ? `<span class="badge priv">private</span>` : ""}
    </div>
  </div>`;

async function loadGroups() {
  const st = groupsState;
  const p = new URLSearchParams({ page: st.page, per_page: 30, sort: st.sort });
  for (const [k, v] of Object.entries(st.filters)) if (v) p.set(k, v);
  for (const [k, v] of Object.entries(st.numbers)) if (v !== null && v !== "") p.set(k, v);
  if (st.bools.detail) p.set("detail", st.bools.detail);

  showLoading("g");
  try {
    const data = await http("/api/groups?" + p);
    renderGroups(data);
  } catch (e) {
    console.error("loadGroups:", e);
    $("g-grid").innerHTML = `<div class="box-empty"><p>Failed to load: ${esc(e.message)}</p></div>`;
  } finally {
    hideLoading("g");
  }
}

function renderGroups(data) {
  $("g-grid").innerHTML = data.items.map(GROUP_CARD).join("");
  $("g-empty").style.display = data.items.length ? "none" : "block";
  renderPager("g", data.page, data.pages);
  $("g-summary").textContent = `${fmtNum(data.total)} groups`;
  document.querySelectorAll("#g-grid .card").forEach((card) =>
    card.addEventListener("click", () => openGroup(card.dataset.id)),
  );
}

/* ───────────────────────── users ───────────────────────── */

const USER_CARD = (u) => `
  <div class="card" data-id="${esc(u.id)}">
    <div class="card-cover" style="${u.avatar_url ? `background-image:url('${esc(u.avatar_url)}')` : `background:linear-gradient(135deg,${u.id.charCodeAt(0) % 2 ? "#6d28d9" : "#0369a1"},#171a21)`}">
      <div class="logo-badge">
        <img src="${esc(u.avatar_url || "")}" data-fallback="self"
          onerror="this.style.display='none';this.nextElementSibling.style.display='grid'"
          alt="" style="display:none">
        <span class="initials" style="display:grid">${initialsOf(u.full_name || u.name)}</span>
      </div>
    </div>
    <div class="card-body">
      <div class="card-title">${esc(u.full_name || u.name)}</div>
      <div class="card-owner">@${esc(u.name)}</div>
      <div class="card-desc">${esc(u.location || "")}</div>
      <div class="bio-snip">${esc(u.bio)}</div>
    </div>
    <div class="card-stats">
      <span class="stat">👥 <span class="v">${fmtNum(u.total_followers)}</span> followers</span>
      <span class="stat">👣 <span class="v">${fmtNum(u.total_following)}</span></span>
      <span class="stat accent">🏘️ <span class="v accent">${fmtNum(u.owned_count)}</span> owned</span>
    </div>
  </div>`;

async function loadUsers() {
  const st = usersState;
  const p = new URLSearchParams({ page: st.page, per_page: 30, sort: st.sort });
  for (const [k, v] of Object.entries(st.filters)) if (v) p.set(k, v);
  for (const [k, v] of Object.entries(st.numbers)) if (v !== null && v !== "") p.set(k, v);

  showLoading("u");
  try {
    const data = await http("/api/users?" + p);
    renderUsers(data);
  } catch (e) {
    console.error("loadUsers:", e);
    $("u-grid").innerHTML = `<div class="box-empty"><p>Failed to load: ${esc(e.message)}</p></div>`;
  } finally {
    hideLoading("u");
  }
}

function renderUsers(data) {
  $("u-grid").innerHTML = data.items.map(USER_CARD).join("");
  $("u-empty").style.display = data.items.length ? "none" : "block";
  renderPager("u", data.page, data.pages);
  $("u-summary").textContent = `${fmtNum(data.total)} users`;
  document.querySelectorAll("#u-grid .card").forEach((card) =>
    card.addEventListener("click", () => openUser(card.dataset.id)),
  );
}

/* ───────────────────────── pagination ───────────────────────── */

function renderPager(prefix, page, pages) {
  const el = $(`${prefix}-pager`);
  if (pages <= 1) { el.innerHTML = ""; return; }
  const btns = [];
  const jump = (n) => {
    if (prefix === "g") groupsState.page = n; else usersState.page = n;
    prefix === "g" ? loadGroups() : loadUsers();
  };
  const pageSet = new Set([1, pages, page - 1, page, page + 1]);
  const sorted = [...pageSet].filter((i) => i >= 1 && i <= pages).sort((a, b) => a - b);
  let prev = 0;
  for (const i of sorted) {
    if (i - prev > 1) btns.push(`<span class="ellipsis">…</span>`);
    btns.push(
      `<button class="${i === page ? "active" : ""}" data-page="${i}">${i}</button>`,
    );
    prev = i;
  }
  el.innerHTML = `
    <button ${page <= 1 ? "disabled" : ""} data-page="${page - 1}">‹</button>
    ${btns.join("")}
    <button ${page >= pages ? "disabled" : ""} data-page="${page + 1}">›</button>`;
  el.querySelectorAll("button[data-page]").forEach((b) =>
    b.addEventListener("click", () => { if (!b.disabled) jump(Number(b.dataset.page)); }),
  );
}

/* ───────────────────────── modals ───────────────────────── */

const modal = $("modal");
function openModal() { modal.classList.add("open"); document.body.style.overflow = "hidden"; }
function closeModal() { modal.classList.remove("open"); document.body.style.overflow = ""; }
modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

async function openGroup(id) {
  openModal();
  $("modal-content").innerHTML = `<div class="modal-loading">Loading group…</div>`;
  try {
    const g = await http("/api/groups/" + encodeURIComponent(id));
    $("modal-content").innerHTML = groupModal(g);
    wireModalEvents();
  } catch (e) {
    $("modal-content").innerHTML = `<div class="modal-loading">Failed: ${esc(e.message)}</div>`;
  }
}

function groupModal(g) {
  const owner = g.owner;
  const socials = owner ? [
    ["facebook", owner.link_facebook, "f"],
    ["instagram", owner.link_instagram, "◎"],
    ["linkedin", owner.link_linkedin, "in"],
    ["twitter", owner.link_twitter, "𝕏"],
    ["website", owner.link_website, "w"],
    ["youtube", owner.link_youtube, "▶"],
  ].filter(([, url]) => url) : [];
  // The long landing-page description is the "big description"; fall back to
  // the short one only when the long one is missing.
  const fullDesc = g.lp_description || g.description || "";
  const groupLinks = parseLinks(g.links);
  const cover = g.cover_url || g.logo_big_url || g.logo_url || "";
  return `
    <div class="modal-hero">
      ${cover
        ? `<img class="hero-img" src="${esc(cover)}" alt="" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
           <div class="hero-fallback" style="display:none">${initialsOf(g.display_name || g.name)}</div>`
        : `<div class="hero-fallback" style="display:flex">${initialsOf(g.display_name || g.name)}</div>`}
      <div class="avatar"><img src="${esc(g.logo_url || g.logo_big_url || "")}" data-fallback="self" onerror="this.style.display='none';this.nextElementSibling.style.display='grid'" alt="" style="display:none"><span class="initials" style="display:grid">${initialsOf(g.display_name || g.name)}</span></div>
      <button class="modal-close" data-close>✕</button>
      <span class="modal-cover-label">cover</span>
    </div>
    <div class="modal-body">
      <div class="modal-title">${esc(g.display_name || g.name)}</div>
      <div class="modal-sub">
        ${esc(g.category_slug || "")} ${esc(g.language ? "· " + g.language : "")}
        ${g.is_public === true ? '<span class="badge pub">public</span>' : g.is_public === false ? '<span class="badge priv">private</span>' : ""}
      </div>
      <div class="metric-row">
        <div class="metric"><div class="k">Members</div><div class="v">${fmtNum(g.total_members)}</div></div>
        <div class="metric"><div class="k">Posts</div><div class="v">${fmtNum(g.total_posts)}</div></div>
        <div class="metric"><div class="k">Courses</div><div class="v">${fmtNum(g.num_courses)}</div></div>
        <div class="metric"><div class="k">Modules</div><div class="v">${fmtNum(g.num_modules)}</div></div>
        <div class="metric"><div class="k">Admins</div><div class="v">${fmtNum(g.total_admins)}</div></div>
        <div class="metric"><div class="k">Price</div><div class="v">${fmtPrice(g)}</div></div>
      </div>
      ${fullDesc ? `<div class="modal-sec"><h3>About</h3><div class="modal-desc">${esc(fullDesc)}</div></div>` : ""}
      ${groupLinks.length ? `
        <div class="modal-sec">
          <h3>Links</h3>
          <div class="socials">
            ${groupLinks.map((l) => {
              const label = (l.label || l.url || "").trim();
              const url = l.url || "";
              return url
                ? `<a class="social" href="${esc(url)}" target="_blank" rel="noopener">🔗 ${esc(label)}</a>`
                : `<span class="social">🔗 ${esc(label)}</span>`;
            }).join("")}
          </div>
        </div>` : ""}
      ${owner ? `
        <div class="modal-sec">
          <h3>Owner</h3>
          <div class="socials">
            <span class="social">👤 ${esc(owner.full_name || owner.name)} · @${esc(owner.name)}</span>
            ${owner.location ? `<span class="social">📍 ${esc(owner.location)}</span>` : ""}
            ${socials.map(([, url, label]) => `<a class="social" href="${esc(url)}" target="_blank" rel="noopener">${label} ${esc(new URL(url).hostname.replace('www.',''))}</a>`).join("")}
          </div>
          ${owner.bio ? `<div class="bio-snip" style="margin-top:10px">${esc(owner.bio)}</div>` : ""}
          <div style="margin-top:10px"><button class="btn" data-user="${esc(owner.id)}">View ${esc(owner.full_name || owner.name)}'s profile →</button></div>
        </div>` : ""}
    </div>`;
}

async function openUser(id) {
  openModal();
  $("modal-content").innerHTML = `<div class="modal-loading">Loading user…</div>`;
  try {
    const u = await http("/api/users/" + encodeURIComponent(id));
    $("modal-content").innerHTML = userModal(u);
    wireModalEvents();
  } catch (e) {
    $("modal-content").innerHTML = `<div class="modal-loading">Failed: ${esc(e.message)}</div>`;
  }
}

function userModal(u) {
  const socials = [
    ["facebook", u.link_facebook],
    ["instagram", u.link_instagram],
    ["linkedin", u.link_linkedin],
    ["twitter", u.link_twitter],
    ["website", u.link_website],
    ["youtube", u.link_youtube],
  ].filter(([, url]) => url);
  return `
    <div class="modal-hero">
      ${u.avatar_url
        ? `<img class="hero-img" src="${esc(u.avatar_url)}" alt="" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
           <div class="hero-fallback" style="display:none">${initialsOf(u.full_name || u.name)}</div>`
        : `<div class="hero-fallback" style="display:flex">${initialsOf(u.full_name || u.name)}</div>`}
      <div class="avatar"><img src="${esc(u.avatar_url || "")}" data-fallback="self" onerror="this.style.display='none';this.nextElementSibling.style.display='grid'" alt="" style="display:none"><span class="initials" style="display:grid">${initialsOf(u.full_name || u.name)}</span></div>
      <button class="modal-close" data-close>✕</button>
      <span class="modal-cover-label">avatar</span>
    </div>
    <div class="modal-body">
      <div class="modal-title">${esc(u.full_name || u.name)}</div>
      <div class="modal-sub">@${esc(u.name)} ${u.location ? "· " + esc(u.location) : ""} ${u.timezone ? "· " + esc(u.timezone) : ""}</div>
      <div class="metric-row">
        <div class="metric"><div class="k">Followers</div><div class="v">${fmtNum(u.total_followers)}</div></div>
        <div class="metric"><div class="k">Following</div><div class="v">${fmtNum(u.total_following)}</div></div>
        <div class="metric"><div class="k">Contributions</div><div class="v">${fmtNum(u.total_contributions)}</div></div>
        <div class="metric"><div class="k">Owned groups</div><div class="v">${fmtNum(u.owned_count)}</div></div>
      </div>
      ${u.bio ? `<div class="modal-sec"><h3>Bio</h3><div class="modal-desc">${esc(u.bio)}</div></div>` : ""}
      ${socials.length ? `<div class="modal-sec"><h3>Socials</h3><div class="socials">${socials.map(([, url, label]) => `<a class="social" href="${esc(url)}" target="_blank" rel="noopener">${label || esc(new URL(url).hostname)}</a>`).join("")}</div></div>` : ""}
      <div class="modal-sec">
        <h3>Groups (${u.groups ? u.groups.length : 0})</h3>
        <div class="mini-grid">
          ${(u.groups || []).map((g) => `
            <div class="mini-card" data-group="${esc(g.id)}">
              <div class="t" style="${coverStyle(g)}"><div class="i"><img src="${esc(g.logo_url || g.logo_big_url || "")}" alt="" onerror="this.remove()">${g.color ? "" : ""}</div></div>
              <div class="c">
                <div class="n">${esc(g.display_name || g.name)}
                  ${g.role === "owner" ? '<span class="badge pub" style="margin-left:5px">owner</span>' : g.role === "member" ? '<span class="badge price" style="margin-left:5px">member</span>' : ""}
                </div>
                <div class="s">${fmtNum(g.total_members)} members · ${fmtPrice(g)}</div>
              </div>
            </div>`).join("")}
          ${!u.groups || !u.groups.length ? `<div style="color:var(--text-faint);font-size:13px">No groups recorded.</div>` : ""}
        </div>
      </div>
    </div>`;
}

function wireModalEvents() {
  document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", closeModal));
  document.querySelectorAll("[data-user]").forEach((b) =>
    b.addEventListener("click", () => openUser(b.dataset.user)),
  );
  document.querySelectorAll("[data-group]").forEach((b) =>
    b.addEventListener("click", () => {
      closeModal();
      openGroup(b.dataset.group);
    }),
  );
}

/* ───────────────────────── filters ───────────────────────── */

function fillSelect(el, opts, placeholder = "Any") {
  el.innerHTML = `<option value="">${placeholder}</option>` +
    opts.map((o) => `<option value="${esc(o.value)}">${esc(o.value)} (${fmtNum(o.n)})</option>`).join("");
}

async function loadFacets() {
  try {
    const g = await http("/api/filters/groups");
    fillSelect($("g-category"), g.categories, "Any category");
    fillSelect($("g-language"), g.languages, "Any language");
    fillSelect($("g-bucket"), g.price_buckets, "Any price bucket");
    fillSelect($("g-interval"), g.intervals, "Any interval");
    const u = await http("/api/filters/users");
    fillSelect($("u-locsrc"), u.location_sources, "Any source");
    // cap timezone list for sanity
    const tzs = u.timezones.slice(0, 400).map((o) => ({ value: o.value, n: o.n }));
    fillSelect($("u-tz"), tzs, "Any timezone");
    if (g.has_prices) $("g-min-price").disabled = false;
    if (g.has_courses) $("g-min-courses").disabled = false;
  } catch (e) {
    console.error("loadFacets:", e);
  }
}

function collectGroupFilters() {
  groupsState.filters = {
    q: $("g-q").value.trim(),
    category: $("g-category").value,
    language: $("g-language").value,
    price_bucket: $("g-bucket").value,
    is_public: $("g-public").value,
    interval: $("g-interval").value,
  };
  groupsState.numbers = {
    min_price: num($("g-min-price").value),
    max_price: num($("g-max-price").value),
    min_members: num($("g-min-members").value),
    max_members: num($("g-max-members").value),
    min_courses: num($("g-min-courses").value),
    min_posts: num($("g-min-posts").value),
  };
  groupsState.bools = { detail: $("g-detail").value };
  groupsState.sort = $("g-sort").value;
  groupsState.page = 1;
}

function collectUserFilters() {
  usersState.filters = {
    q: $("u-q").value.trim(),
    location_source: $("u-locsrc").value,
    timezone: $("u-tz").value,
    has_avatar: $("u-avatar").value,
    owned: $("u-owned").value,
    scraped: $("u-scraped").value,
  };
  usersState.numbers = {
    min_followers: num($("u-min-followers").value),
    max_followers: num($("u-max-followers").value),
  };
  usersState.sort = $("u-sort").value;
  usersState.page = 1;
}

function renderChips(prefix, st, mapName, clearFn) {
  const chips = [];
  for (const [k, v] of Object.entries(st.filters)) {
    if (v) chips.push({ label: `${mapName[k] || k}: ${v}`, key: `f.${k}` });
  }
  for (const [k, v] of Object.entries(st.numbers)) {
    if (v !== null && v !== "") chips.push({ label: `${mapName[k] || k}: ${v}`, key: `n.${k}` });
  }
  for (const [k, v] of Object.entries(st.bools || {})) {
    if (v) chips.push({ label: `${mapName[k] || k}: ${v}`, key: `b.${k}` });
  }
  $(`${prefix}-chips`).innerHTML = chips.map((c) =>
    `<span class="chip">${esc(c.label)}<button data-key="${esc(c.key)}">✕</button></span>`).join("");
  $(`${prefix}-chips`).querySelectorAll("button[data-key]").forEach((b) =>
    b.addEventListener("click", () => {
      const [cat, key] = b.dataset.key.split(".");
      if (cat === "f") st.filters[key] = "";
      if (cat === "n") st.numbers[key] = null;
      if (cat === "b") st.bools[key] = "";
      clearFn();
      prefix === "g" ? loadGroups() : loadUsers();
    }),
  );
  return chips.length;
}

const gMap = {
  q: "Search", category: "Category", language: "Language",
  price_bucket: "Bucket", is_public: "Privacy", interval: "Interval",
  min_price: "Min $", max_price: "Max $", min_members: "Min members",
  max_members: "Max members", min_courses: "Min courses", min_posts: "Min posts",
  detail: "Detailed",
};
const uMap = {
  q: "Search", location_source: "Location src", timezone: "Timezone",
  has_avatar: "Avatar", owned: "Owns", scraped: "Scraped",
  min_followers: "Min followers", max_followers: "Max followers",
};

function refreshChips(view) {
  if (view === "g") renderChips("g", groupsState, gMap, () => collectGroupFilters());
  else renderChips("u", usersState, uMap, () => collectUserFilters());
}

/* ───────────────────────── loading ───────────────────────── */

function showLoading(p) { $(`${p}-loading`).style.display = "block"; }
function hideLoading(p) { $(`${p}-loading`).style.display = "none"; }

/* ───────────────────────── wiring ───────────────────────── */

function wire() {
  // tabs
  document.querySelectorAll(".tab").forEach((t) =>
    t.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
      document.querySelectorAll(".view").forEach((x) => x.classList.remove("active"));
      t.classList.add("active");
      $(`view-${t.dataset.view}`).classList.add("active");
    }),
  );

  // group filters
  $("g-apply").addEventListener("click", () => { collectGroupFilters(); refreshChips("g"); loadGroups(); });
  $("g-clear").addEventListener("click", () => {
    ["g-q","g-category","g-language","g-bucket","g-public","g-interval","g-detail",
     "g-min-price","g-max-price","g-min-members","g-max-members","g-min-courses","g-min-posts"]
      .forEach((id) => { const el = $(id); el.value = el.tagName === "SELECT" ? "" : ""; });
    collectGroupFilters(); refreshChips("g"); loadGroups();
  });
  ["g-q"].forEach((id) => $(id).addEventListener("keydown", (e) => {
    if (e.key === "Enter") { collectGroupFilters(); refreshChips("g"); loadGroups(); }
  }));

  // user filters
  $("u-apply").addEventListener("click", () => { collectUserFilters(); refreshChips("u"); loadUsers(); });
  $("u-clear").addEventListener("click", () => {
    ["u-q","u-locsrc","u-tz","u-avatar","u-owned","u-scraped","u-min-followers","u-max-followers"]
      .forEach((id) => { $(id).value = ""; });
    collectUserFilters(); refreshChips("u"); loadUsers();
  });
  ["u-q"].forEach((id) => $(id).addEventListener("keydown", (e) => {
    if (e.key === "Enter") { collectUserFilters(); refreshChips("u"); loadUsers(); }
  }));

  // initial
  loadFacets();
  collectGroupFilters(); refreshChips("g"); loadGroups();
  collectUserFilters(); refreshChips("u"); loadUsers();
}

document.addEventListener("DOMContentLoaded", wire);