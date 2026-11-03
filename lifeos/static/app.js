// LifeOS 前端：零构建、原生 JS。每个标签页一个 render 函数。
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let META = { domains: [], currency: "£" };

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || r.status);
  return data;
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove("show"), 3500);
}

async function feedback(id, verdict) {
  let reason = "";
  if (verdict !== "accept") {
    reason = prompt(verdict === "reject" ? "哪里不合适？（不想说也没关系）" : "你改成了什么？（不想说也没关系）") ?? "";
  }
  await api("/api/feedback", { id, verdict, reason });
  toast("收到，它会慢慢更懂你");
  render(current);
}

const fbButtons = (id) =>
  `<span class="row fb"><button class="btn sm" onclick="feedback(${id},'accept')">👍</button>` +
  `<button class="btn sm" onclick="feedback(${id},'modify')">✏️</button>` +
  `<button class="btn sm" onclick="feedback(${id},'reject')">👎</button></span>`;

// ------------------------------------------------------------------ 今日
async function renderToday(el) {
  const p = await api("/api/today");
  el.innerHTML = `
    <p class="small"><a href="#now">← 回到此刻</a></p>
    <h2>🗓 今天的结构 · ${p.date} 周${p.weekday}</h2>
    <p class="small muted">这是你选择要的结构。它是工具，不是命令；随时可以不按它来。</p>
    <div class="card"><b>🎯 今天只需记住的 3 件事</b>
      <ol class="top3">${p.top3.map((t) => `<li>${esc(t)}</li>`).join("")}</ol>
      <div class="row small muted">这个日程好用吗？ ${fbButtons(p.suggestion_id)}</div>
    </div>
    <h2>🕐 时间块</h2>
    <ul class="timeline">${p.timeline.map((b) => `
      <li class="${b.kind} ${b.domain === "关系" ? "love" : ""}">
        <span class="time">${b.time}</span><span>${esc(b.title)}</span>
        ${b.kind === "task" ? `<button class="btn sm" onclick="doneTask(${b.task_id})">✓</button>` : "<span></span>"}
        ${(b.with || []).map((w) => `<span class="with">└ 可以一起做：${esc(w.title)}</span>`).join("")}
      </li>`).join("")}
    </ul>
    ${p.unscheduled.length ? `<p class="small muted">⏳ 今天排不下：${p.unscheduled.map(esc).join("；")}</p>` : ""}
    ${p.nudges.length ? `<h2>🔔 提醒</h2><div class="card"><ul class="nudges">${p.nudges.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></div>` : ""}
    <h2>➕ 加任务</h2>
    <form class="inline card" id="task-form">
      <input name="title" placeholder="任务" required>
      <select name="domain">${META.domains.map((d) => `<option>${esc(d)}</option>`).join("")}</select>
      <select name="priority"><option value="5">P5 最重要</option><option value="4">P4</option><option value="3" selected>P3</option><option value="2">P2</option><option value="1">P1</option></select>
      <select name="energy"><option value="high">高能量</option><option value="medium" selected>中能量</option><option value="low">低能量</option></select>
      <input name="minutes" type="number" value="30" style="max-width:80px">
      <input name="due" type="date" style="max-width:150px">
      <button class="btn primary">添加</button>
    </form>
    <h2>⏱ 记录时间</h2>
    <form class="inline card" id="time-form">
      <select name="domain">${META.domains.map((d) => `<option>${esc(d)}</option>`).join("")}</select>
      <input name="minutes" type="number" placeholder="分钟" required style="max-width:100px">
      <input name="note" placeholder="备注">
      <button class="btn">记录</button>
    </form>`;
  $("#task-form").onsubmit = async (e) => {
    e.preventDefault();
    await api("/api/tasks", Object.fromEntries(new FormData(e.target)));
    toast("任务已添加");
    render("today");
  };
  $("#time-form").onsubmit = async (e) => {
    e.preventDefault();
    await api("/api/timelog", Object.fromEntries(new FormData(e.target)));
    toast("已记录");
    e.target.reset();
  };
}

async function doneTask(id) {
  await api(`/api/tasks/${id}/done`, {});
  toast("✓ 完成");
  render(current);
}

// ------------------------------------------------------------------ 记忆
async function renderMemory(el, q = "") {
  const [mems, noticed] = await Promise.all([
    api("/api/memories" + (q ? `?q=${encodeURIComponent(q)}` : "?days=60")), api("/api/reflections")]);
  const pending = mems.filter((m) => m.status === "needs_confirm");
  el.innerHTML = `
    <p class="small muted">记忆在后台记着、连着，影响此刻的建议、信、问卦和捡漏。这里只是让你想找什么时能找到。</p>
    <form class="inline" id="mem-search"><input name="q" value="${esc(q)}" placeholder="检索记忆：冰岛 / 50/1.4 / 她喜欢…"><button class="btn">检索</button></form>
    ${!q && noticed.length ? `<h2>🧠 它注意到的</h2><div class="card">${noticed.slice(0, 5).map((r) => `
      <div class="mem"><div>${esc(r.content)}</div>
      <div class="row small" style="margin-top:4px"><button class="btn sm ghost" onclick="confirmMem(${r.id},false)">不对，别再提</button></div></div>`).join("")}</div>` : ""}
    ${pending.length ? `<h2>❓ AI 不太确定的记忆</h2>${pending.map((m) => `
      <div class="card">${esc(m.content)} <span class="chip">${esc(m.domain)}</span>
      <div class="row" style="margin-top:6px"><button class="btn sm" onclick="confirmMem(${m.id},true)">✓ 对</button><button class="btn sm" onclick="confirmMem(${m.id},false)">✗ 删掉</button></div></div>`).join("")}` : ""}
    <h2>${q ? "🔍 检索结果（时近性 + 重要性 + 相关性）" : "🌊 时间河流（近 60 天）"}</h2>
    <div class="card">${mems.map((m) => `
      <div class="mem"><div class="row small muted"><span>${m.occurred_at.slice(0, 16).replace("T", " ")}</span>
        <span class="chip ${m.domain === "关系" ? "love" : ""}">${esc(m.domain)}</span><span>${"★".repeat(Math.round((m.importance || 5) / 2))}</span>
        ${m.score !== undefined ? `<span>score ${m.score}</span>` : ""}</div>
        <div>${esc(m.content)}</div></div>`).join("") || '<p class="muted">还没有记忆。用下方输入框随手记一句吧。</p>'}
    </div>`;
  $("#mem-search").onsubmit = (e) => {
    e.preventDefault();
    renderMemory(el, new FormData(e.target).get("q"));
  };
}

async function confirmMem(id, keep) {
  await api("/api/confirm", { id, keep });
  render("memory");
}

// ------------------------------------------------------------------ 星图
const KIND_COLOR = { domain: "#b4532a", person: "#c2416b", project: "#2f7d5b", item: "#6b7280", place: "#2563eb", book: "#7c3aed" };
const EDGE_STYLE = {
  synergy: { color: "#2f7d5b", label: "协同" }, competition: { color: "#b83a3a", label: "竞争" },
  influence: { color: "#2563eb", label: "影响" }, dependency: { color: "#b7791f", label: "依赖" }, related: { color: "#a8a29e", label: "相关" },
};
// 自带的力导向布局（不依赖 CDN，离线可用，数据不出本机）
function layout(nodes, edges, W, H) {
  const pos = new Map(nodes.map((n, i) => [n.id, { x: W / 2 + 200 * Math.cos(i), y: H / 2 + 200 * Math.sin(i), vx: 0, vy: 0 }]));
  for (let step = 0; step < 300; step++) {
    const t = 1 - step / 300;
    for (const a of nodes) for (const b of nodes) {
      if (a.id >= b.id) continue;
      const p = pos.get(a.id), q = pos.get(b.id);
      let dx = p.x - q.x, dy = p.y - q.y, d2 = dx * dx + dy * dy + 0.01;
      const f = 9000 / d2, d = Math.sqrt(d2);
      p.vx += (f * dx) / d; p.vy += (f * dy) / d; q.vx -= (f * dx) / d; q.vy -= (f * dy) / d;
    }
    for (const e of edges) {
      const p = pos.get(e.source_id), q = pos.get(e.target_id);
      if (!p || !q) continue;
      const dx = q.x - p.x, dy = q.y - p.y, d = Math.sqrt(dx * dx + dy * dy) + 0.01, f = (d - 130) * 0.02;
      p.vx += (f * dx) / d; p.vy += (f * dy) / d; q.vx -= (f * dx) / d; q.vy -= (f * dy) / d;
    }
    for (const p of pos.values()) {
      p.vx += (W / 2 - p.x) * 0.01; p.vy += (H / 2 - p.y) * 0.01;
      p.x += Math.max(-20, Math.min(20, p.vx * t)); p.y += Math.max(-20, Math.min(20, p.vy * t));
      p.vx *= 0.5; p.vy *= 0.5;
      p.x = Math.max(40, Math.min(W - 40, p.x)); p.y = Math.max(30, Math.min(H - 30, p.y));
    }
  }
  return pos;
}

async function renderGraph() {
  const g = await api("/api/graph");
  $("#graph-legend").innerHTML =
    Object.entries(EDGE_STYLE).map(([, s]) => `<span><i style="background:${s.color}"></i>${s.label}</span>`).join("") +
    "<span>虚线 = 待验证假设 · 节点越大 = 相关记忆越多 · 点击节点查看相关记忆</span>";
  const W = 900, H = 640;
  const pos = layout(g.nodes, g.edges, W, H);
  const r = (n) => 6 + Math.min(Math.sqrt(n.size) * 3, 18) + (n.kind === "domain" ? 4 * (g.weights[n.name] || 1) : 0);
  const edges = g.edges.map((e) => {
    const p = pos.get(e.source_id), q = pos.get(e.target_id), st = EDGE_STYLE[e.kind] || EDGE_STYLE.related;
    if (!p || !q) return "";
    return `<line x1="${p.x}" y1="${p.y}" x2="${q.x}" y2="${q.y}" stroke="${st.color}" stroke-opacity=".75"
      stroke-width="${Math.min(1 + e.strength * 0.6, 6)}" ${e.status === "hypothesis" ? 'stroke-dasharray="5 4"' : ""}
      ${e.kind === "influence" ? 'marker-end="url(#arrow)"' : ""}><title>${esc(st.label)}：${esc(e.note || "")}</title></line>`;
  }).join("");
  const nodes = g.nodes.map((n) => {
    const p = pos.get(n.id);
    return `<g class="node" data-name="${esc(n.name)}" style="cursor:pointer"><circle cx="${p.x}" cy="${p.y}" r="${r(n)}" fill="${KIND_COLOR[n.kind] || "#888"}"/>
      <text x="${p.x}" y="${p.y + r(n) + 14}" font-size="13" text-anchor="middle" fill="var(--fg)">${esc(n.name)}</text></g>`;
  }).join("");
  $("#network").innerHTML = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:100%">
    <defs><marker id="arrow" viewBox="0 0 10 10" refX="18" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0L10,5L0,10z" fill="#2563eb"/></marker></defs>
    ${edges}${nodes}</svg><div id="graph-detail"></div>`;
  document.querySelectorAll("#network .node").forEach((el) => (el.onclick = async () => {
    const mems = await api(`/api/memories?q=${encodeURIComponent(el.dataset.name)}&limit=8`);
    toast(`「${el.dataset.name}」相关记忆：\n` + (mems.map((m) => "· " + m.content).join("\n") || "暂无"));
  }));
}

// ------------------------------------------------------------------ 器材
async function renderGear(el) {
  const d = await api("/api/items");
  const c = d.currency, s = d.stats;
  const tile = (v, label) => `<div class="stat"><b>${v ?? "—"}</b><span>${label}</span></div>`;
  const next = (st) => d.statuses[d.statuses.indexOf(st) + 1];
  el.innerHTML = `
    <div class="grid">
      ${tile(c + s.profit_month, "本月净利润")}${tile(c + s.profit_total, "累计净利润")}${tile(s.hourly_rate !== null ? c + s.hourly_rate : null, "时薪")}
      ${tile(s.avg_turnover_days !== null ? s.avg_turnover_days + " 天" : null, "平均周转")}${tile(`${s.stock_count} 件`, `库存 ${c}${s.stock_value}`)}
    </div>
    ${d.funds.map((f) => `<div class="card" style="margin-top:12px">✈️ <b>${esc(f.name)}</b> ${c}${f.saved} / ${c}${f.target}
      <span class="muted small">（器材利润按比例自动计入）</span><div class="bar"><i style="width:${Math.min((f.progress || 0) * 100, 100)}%"></i></div></div>`).join("")}
    ${s.stale.length ? `<p>📦 滞销：${s.stale.map(esc).join(", ")} —— 考虑降价或换平台</p>` : ""}
    <h2>🔍 捡漏评估</h2>
    <form class="inline card" id="deal-form">
      <input name="model" placeholder="型号 如 50/1.4" required><input name="price" type="number" placeholder="对方报价" required>
      <input name="defects" placeholder="瑕疵（空格分隔）"><input name="est" type="number" placeholder="预估售价（无历史时）">
      <button class="btn primary">评估</button>
    </form>
    <div id="deal-result"></div>
    <h2>🗂 库存流水线 <a class="small" href="/shop">打开器材橱窗 →</a></h2>
    <div class="kanban">${d.statuses.map((st) => `
      <div class="col"><h3>${st} · ${d.items.filter((i) => i.status === st).length}</h3>
      ${d.items.filter((i) => i.status === st).map((i) => `
        <div class="item"><b>${esc(i.model)}</b> <span class="muted small">${i.code}</span><br>
          <span class="small">收 ${c}${i.buy_price}${i.est_price ? ` · 估 ${c}${i.est_price}` : ""}${i.list_price ? ` · 标 ${c}${i.list_price}` : ""}${i.profit !== null ? ` · 利 ${c}${i.profit}` : ""}</span>
          ${i.defects.length ? `<br><span class="small muted">瑕疵：${i.defects.map(esc).join("、")}</span>` : ""}
          <div class="actions">
            ${st === "待拍照" ? `<button class="btn sm" onclick="listItem('${i.code}')">定价上架</button>` : ""}
            ${st === "在售" ? `<button class="btn sm" onclick="sellItem('${i.code}')">售出</button>` : ""}
            ${next(st) && st !== "待拍照" && st !== "在售" ? `<button class="btn sm" onclick="moveItem('${i.code}','${next(st)}')">→ ${next(st)}</button>` : ""}
          </div></div>`).join("")}
      </div>`).join("")}
    </div>
    <h2>➕ 收入器材</h2>
    <form class="inline card" id="item-form">
      <input name="model" placeholder="型号" required><input name="price" type="number" placeholder="收价" required>
      <input name="platform" placeholder="平台"><input name="defects" placeholder="瑕疵（空格分隔）"><input name="condition" placeholder="成色">
      <button class="btn primary">入库</button>
    </form>`;
  const split = (v) => (v || "").split(/\s+/).filter(Boolean);
  $("#deal-form").onsubmit = async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    const r = await api("/api/deal", { ...f, defects: split(f.defects) });
    $("#deal-result").innerHTML = `<div class="card"><b>${esc(r.verdict)}</b><ul>${(r.reasons || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
      ${r.suggestion_id ? `<div class="row small muted">判断准吗？${fbButtons(r.suggestion_id)}</div>` : ""}</div>`;
  };
  $("#item-form").onsubmit = async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    const r = await api("/api/items", { ...f, defects: split(f.defects) });
    toast(`已入库 ${r.code}`);
    render("gear");
  };
}
async function moveItem(code, status) { await api(`/api/items/${code}`, { status }); render("gear"); }
async function listItem(code) {
  const p = prompt("上架定价？");
  if (p) { await api(`/api/items/${code}`, { status: "在售", list_price: Number(p) }); render("gear"); }
}
async function sellItem(code) {
  const p = prompt("成交价？");
  if (!p) return;
  const platform = prompt("成交平台？", "闲鱼") || null;
  const hours = prompt("这件总共花了几小时？（检测+拍照+沟通+发货）", "1.5");
  const r = await api(`/api/items/${code}`, { sell_price: Number(p), platform, hours: hours ? Number(hours) : null });
  toast(`✅ 售出 ${r.code}`);
  render("gear");
}

// ------------------------------------------------------------------ 她
async function renderHer(el) {
  const [d, f] = await Promise.all([api("/api/her"), api("/api/family")]);
  const statuses = ["想法", "规划中", "进行中", "已实现"];
  const hz = f.horizons;
  if (!HOME.notes) HOME.notes = (await api("/api/ai")).notes || {};
  const note = HOME.notes.her;
  el.innerHTML = `
    ${note ? `<p class="ai-note">❤️ ${esc(note)}</p>` : ""}
    <div class="card star"><div class="small muted">⭐ 我们的北极星</div>
      <div class="star-text">${esc(f.north_star.text) || '<span class="muted">还没写。找一个安静的晚上，和她一起写一句。</span>'}</div>
      <button class="btn sm" onclick="editStar()">${f.north_star.text ? "重写" : "写下"}</button>
      ${f.north_star.history.length ? `<details><summary class="small muted">过去的北极星</summary>${f.north_star.history.map((x) => `<p class="small muted">${esc(x.text)}（至 ${x.until}）</p>`).join("")}</details>` : ""}</div>
    <h2>✨ 地平线上</h2>
    ${hz.to_reflect.map((x) => `<div class="card"><b>${esc(x.title)}</b> 已经过去了。怎么样？
      <form class="inline" onsubmit="liveHorizon(event, ${x.id})"><input name="r" placeholder="一句话，会变成一段记忆"><button class="btn primary">记下</button></form></div>`).join("")}
    <div class="horizon big">${hz.ahead.map((x) => `<div><span class="hz-days">${x.days_left}</span><span class="hz-title">天后 · ${esc(x.title)}<br><span class="small muted">${x.date}</span></span></div>`).join("") ||
      `<p class="muted">地平线上空着。期待本身就是幸福的很大一部分。可以是：${hz.ideas.map(esc).join("；")}</p>`}</div>
    <form class="inline card" id="horizon-form"><input name="title" placeholder="一件你们期待的事" required>
      <input name="date" type="date" required style="max-width:160px"><button class="btn primary">放上地平线</button></form>
    <h2>🕯 我们的仪式</h2>
    <div class="card">${f.rituals.map((r) => `<div class="mem row" style="justify-content:space-between"><span>${esc(r.name)} <span class="small muted">${esc(r.when)}${r.note ? " · " + esc(r.note) : ""}</span></span>
        <span>${r.done_this_period ? `<span class="small muted">这一期做过了</span>` : `<button class="btn sm" onclick="logRitual(${r.id})">做了</button>`}</span></div>`).join("")}
      <p class="small muted">不打卡，不计算断了几次。仪式是"想要做"，不是"必须做"。</p>
      <form class="inline" id="ritual-form"><input name="name" placeholder="新的仪式" required>
        <select name="cadence"><option value="weekly">每周</option><option value="monthly">每月</option><option value="yearly">每年</option></select>
        <select name="weekday">${["一", "二", "三", "四", "五", "六", "日"].map((x, i) => `<option value="${i + 1}">周${x}</option>`).join("")}</select>
        <button class="btn">添加</button></form></div>
    <h2>📍 我们去过的地方</h2>
    <div class="card"><div id="map"></div>
      ${f.places.map((p) => `<div class="small">${p.visited_on || ""} ${esc(p.name)}${p.note ? " · " + esc(p.note) : ""}</div>`).join("") || '<p class="muted small">还没有。冰岛之后，这张地图会很好看。</p>'}
      <form class="inline" id="place-form" style="margin-top:8px"><input name="name" placeholder="地名，如 雷克雅未克" required>
        <input name="visited_on" type="date" style="max-width:160px"><button class="btn">添加</button></form></div>
    <h2>🌙 这周在一起</h2>
    <div class="grid"><div class="stat"><b>${d.love_hours}h</b><span>这周在一起的时间</span></div>
      ${d.dates.slice(0, 2).map((x) => `<div class="stat"><b>${x.days_left} 天</b><span>${esc(x.name)} ${x.date}</span></div>`).join("")}</div>
    <h2>💡 惊喜建议（微 / 中 / 大）</h2>
    <div class="card">${d.ideas.map((i) => `<p><span class="chip love">${i.scale}</span> ${esc(i.idea)} <span class="muted small">——「${esc(i.wish)}」</span></p>`).join("") || '<p class="muted">先记下她的愿望。</p>'}
      <p class="small muted">AI 只负责记住和启发；表达和执行是你自己的。</p></div>
    <h2>❤️ 她的愿望</h2>
    ${d.wishes.map((w) => `
      <div class="card wish"><div class="row"><b style="flex:1">${esc(w.content)}</b>
        <select onchange="wishStatus(${w.id}, this.value)">${statuses.map((s) => `<option ${s === w.status ? "selected" : ""}>${s}</option>`).join("")}</select></div>
        <div class="small muted">${w.mentioned_at} 提到${w.project ? ` · 项目：${esc(w.project)}` : ""}</div>
        ${w.project && d.projects[w.project]?.length ? `<ul>${d.projects[w.project].map((t) => `<li>${esc(t.title)} <button class="btn sm" onclick="doneTask(${t.id})">✓</button></li>`).join("")}</ul>` : ""}
      </div>`).join("")}
    <form class="inline card" id="wish-form"><input name="content" placeholder="她又说想……" required>
      <select name="category"><option value="travel">旅行</option><option value="project">一起做的事</option><option value="health">健康</option><option value="gift">礼物</option><option value="experience" selected>体验</option></select>
      <button class="btn primary">记下</button></form>
    <h2>🎁 重要日期</h2>
    <div class="card">${d.dates.map((x) => `<div>${esc(x.name)} · ${x.date} · 还有 ${x.days_left} 天</div>`).join("") || '<p class="muted">还没有。生日、纪念日记下来，系统会提前 30 / 7 / 1 天提醒。</p>'}
      <form class="inline" id="date-form" style="margin-top:8px"><input name="name" placeholder="生日 / 纪念日" required>
        <input name="month" type="number" min="1" max="12" placeholder="月" required style="max-width:70px">
        <input name="day" type="number" min="1" max="31" placeholder="日" required style="max-width:70px"><button class="btn">添加</button></form></div>`;
  $("#wish-form").onsubmit = async (e) => { e.preventDefault(); await api("/api/wishes", Object.fromEntries(new FormData(e.target))); render("her"); };
  $("#horizon-form").onsubmit = async (e) => { e.preventDefault(); await api("/api/horizons", Object.fromEntries(new FormData(e.target))); toast("✨ 放上地平线了"); render("her"); };
  $("#ritual-form").onsubmit = async (e) => { e.preventDefault(); await api("/api/rituals", Object.fromEntries(new FormData(e.target))); render("her"); };
  $("#place-form").onsubmit = async (e) => { e.preventDefault(); const r = await api("/api/places", Object.fromEntries(new FormData(e.target))); toast(r.lat ? `📍 ${r.name}` : "📍 记下了（没找到坐标）"); render("her"); };
  drawMap(f.places.filter((p) => p.lat !== null));
  $("#date-form").onsubmit = async (e) => { e.preventDefault(); await api("/api/dates", Object.fromEntries(new FormData(e.target))); render("her"); };
}
async function editStar() {
  const t = prompt("你们的北极星（一句话，和她一起写）");
  if (t) { await api("/api/northstar", { text: t }); render("her"); }
}
async function liveHorizon(e, id) {
  e.preventDefault();
  await api(`/api/horizons/${id}/live`, { reflection: new FormData(e.target).get("r") });
  toast("记下了。下一个盼头是什么？");
  render("her");
}
function loadLeaflet() {
  if (window.L) return Promise.resolve();
  return new Promise((ok, fail) => {
    const css = document.createElement("link");
    css.rel = "stylesheet"; css.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
    document.head.appendChild(css);
    const js = document.createElement("script");
    js.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    js.onload = ok; js.onerror = fail;
    document.head.appendChild(js);
  });
}
async function drawMap(points) {
  const box = $("#map");
  if (!points.length) { box.style.display = "none"; return; }
  try { await loadLeaflet(); } catch { box.innerHTML = '<p class="small muted">地图需要联网加载。</p>'; return; }
  const map = L.map(box, { scrollWheelZoom: false });
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OpenStreetMap" }).addTo(map);
  const ll = points.map((p) => [p.lat, p.lon]);
  points.forEach((p) => L.circleMarker([p.lat, p.lon], { radius: 7, color: "#c2416b" }).addTo(map).bindPopup(`${esc(p.name)}<br>${p.visited_on || ""}`));
  if (ll.length > 1) L.polyline(ll, { color: "#c2416b", weight: 1, dashArray: "4 4" }).addTo(map);
  ll.length === 1 ? map.setView(ll[0], 6) : map.fitBounds(ll, { padding: [24, 24] });
}
async function wishStatus(id, status) { await api(`/api/wishes/${id}`, { status }); toast(status === "已实现" ? "🎉 又实现了她的一个愿望" : "已更新"); }

// ------------------------------------------------------------------ 复盘
function md(text) {
  const lines = text.split("\n");
  let html = "", table = [];
  const flush = () => {
    if (!table.length) return;
    const rows = table.filter((r) => !/^\|[-|\s]+\|$/.test(r)).map((r) => r.split("|").slice(1, -1).map((c) => c.trim()));
    html += `<table>${rows.map((r, i) => `<tr>${r.map((c) => (i ? `<td>${esc(c)}</td>` : `<th>${esc(c)}</th>`)).join("")}</tr>`).join("")}</table>`;
    table = [];
  };
  for (const l of lines) {
    if (l.startsWith("|")) { table.push(l); continue; }
    flush();
    if (l.startsWith("# ")) html += `<h1>${esc(l.slice(2))}</h1>`;
    else if (l.startsWith("## ")) html += `<h2>${esc(l.slice(3))}</h2>`;
    else if (l.startsWith("- ")) html += `<div>• ${esc(l.slice(2))}</div>`;
    else if (l.startsWith("> ")) html += `<blockquote>${esc(l.slice(2))}</blockquote>`;
    else if (l.trim()) html += `<p>${esc(l)}</p>`;
  }
  flush();
  return html;
}

function radar(ledger) {
  const items = ledger.filter((x) => x.budget > 0);
  const n = items.length, R = 110, cx = 150, cy = 140;
  if (n < 3) return "";
  const pt = (i, r) => [cx + r * Math.sin((2 * Math.PI * i) / n), cy - r * Math.cos((2 * Math.PI * i) / n)];
  const ring = (k) => items.map((_, i) => pt(i, R * k).join(",")).join(" ");
  const actual = items.map((x, i) => pt(i, R * Math.min(x.hours / x.budget, 1.5) / 1.5).join(",")).join(" ");
  const budget = items.map((_, i) => pt(i, R / 1.5).join(",")).join(" ");
  return `<svg viewBox="0 0 300 290" style="width:100%;max-width:420px;display:block;margin:auto">
    ${[0.5, 1].map((k) => `<polygon points="${ring(k)}" fill="none" stroke="var(--line)"/>`).join("")}
    <polygon points="${budget}" fill="none" stroke="var(--muted)" stroke-dasharray="4 3"/>
    <polygon points="${actual}" fill="var(--accent)" fill-opacity=".25" stroke="var(--accent)" stroke-width="2"/>
    ${items.map((x, i) => { const [x1, y1] = pt(i, R + 16); return `<text x="${x1}" y="${y1}" font-size="11" text-anchor="middle" fill="var(--fg)">${esc(x.domain)}</text>`; }).join("")}
  </svg><p class="small muted" style="text-align:center">人生平衡轮：虚线 = 预算，橙色 = 本周实际（记录时间后才有数据）</p>`;
}

async function renderReview(el) {
  const r = await api("/api/review");
  el.innerHTML = `<p class="small"><a href="#more">← 更多</a></p><p class="small muted">这里是数据。它们只是参考，不是对你的评分。</p><div class="card">${radar(r.ledger)}</div>
    <div class="row"><button class="btn primary" id="save-review">生成并保存本周复盘（含 AI 教练点评）</button></div>
    <div class="card md" style="margin-top:12px">${md(r.markdown)}</div>`;
  $("#save-review").onclick = async () => {
    toast("生成中…");
    const s = await api("/api/review", {});
    el.querySelector(".md").innerHTML = md(s.markdown);
    toast("已保存到 data/reviews/");
  };
}

// ------------------------------------------------------------------ 系统
async function renderSystem(el) {
  const [a, menu] = await Promise.all([api("/api/autonomy"), api("/api/menu")]);
  el.innerHTML = `
    <p class="small"><a href="#more">← 更多</a></p>
    <h2>🤝 交给它的小事</h2>
    <p class="small muted">只有琐碎的决定才会慢慢交给系统（菜单、发货日、定价）。关于她、关于人生的事，它永远只是提建议。</p>
    <div class="card md"><table><tr><th>决策</th><th>当前</th><th>上限</th><th>最近采纳率</th></tr>
      ${a.overview.map((o) => `<tr><td>${esc(o.desc)}</td><td>${esc(o.level)}</td><td>${esc(o.cap)}</td><td>${o.rate === null ? "—" : Math.round(o.rate * 100) + "%"}（${o.n}）</td></tr>`).join("")}</table>
      ${a.promotions.map((p) => `<p>⬆️ 「${esc(p.category)}」可从 ${esc(p.from)} 升到 ${esc(p.to)}（命令行：lifeos autonomy set ${esc(p.category)} +1）</p>`).join("")}
      <p class="small muted">采纳率连续达标才会提议升级；任何一次"错得离谱"立即降级。感情和人生大事永远只做建议。</p></div>
    <h2>📝 它给过的建议（想反馈就反馈，不想也没关系）</h2>
    ${a.pending.map((s) => `<div class="card"><span class="chip">${esc((a.overview.find((o) => o.category === s.category) || {}).desc || s.category)}</span> ${esc(s.content).slice(0, 300)}<div class="row" style="margin-top:6px">${fbButtons(s.id)}</div></div>`).join("") || '<p class="muted">没有待反馈的建议。</p>'}
    <h2>🍳 本周菜单（🥗 = 轻食，支持她的健康目标）</h2>
    <div class="card">${menu.days.map((d) => `<div>${d.day} ${esc(d.dish)} ${d.light ? "🥗" : ""}</div>`).join("")}
      <p class="small muted">🛒 ${menu.shopping.map(esc).join("、")}</p></div>`;
}


// ------------------------------------------------------------------ 此刻
const NOW = { feeling: null, minutes: null, seen: [], note: "", place: null, her: null };
const MINUTES = [[15, "一会儿"], [45, "半小时多"], [120, "一两个小时"], ["", "不确定"]];

let HOME = { skip_reasons: [] };
async function renderNow(el) {
  const h = await api("/api/home");
  HOME = h;
  const evening = h.hour >= 20 || h.hour < 3;
  const morning = h.hour >= 5 && h.hour < 11;
  const anchors = h.anchors.filter((a) => !a.includes("💼"));
  el.innerHTML = `
    <p class="greet">${esc(h.greeting)} ${esc(h.term.name)}时节${h.weather ? ` · ${h.weather.icon} ${esc(h.weather.label)} ${h.weather.tmin}–${h.weather.tmax}°C` : ""}</p>
    <p class="small"><a href="#tianshi">${h.cast ? `☯ ${h.cast.symbol} ${esc(h.cast.full)} · ${esc(h.cast.stance)}` : "☯ 今日还未起卦 →"}</a></p>
    ${h.notes && h.notes.morning ? `<p class="ai-note">💬 ${esc(h.notes.morning)}</p>` : ""}
    ${horizonStrip(h.horizons)}
    ${h.rituals.map((r) => `<div class="ritual">🕯 ${r.today ? "今天是" : "这一期还没"}「${esc(r.name)}」
      <button class="btn sm" onclick="logRitual(${r.id})">做了</button></div>`).join("")}
    <div id="now-card"><div class="card now rn"><p class="muted small">🧭 看看此刻的天时、地利…</p></div></div>
    <h1 class="ask">你现在感觉怎么样？</h1>
    <p class="small muted" style="margin-top:-6px">说一下，上面的建议会更懂你。不说也可以。</p>
    <div class="feelings">${Object.entries(h.feelings).map(([f, i]) =>
      `<button class="feel ${NOW.feeling === f ? "on" : ""}" data-f="${f}"><span>${i}</span>${f}</button>`).join("")}</div>
    <div class="row minutes"><span class="muted small">有多少时间？</span>${MINUTES.map(([m, label]) =>
      `<button class="chip-btn ${String(NOW.minutes ?? "") === String(m) ? "on" : ""}" data-m="${m}">${label}</button>`).join("")}</div>
    <input id="now-note" value="${esc(NOW.note)}" placeholder="想说点什么也可以（可不填）">
    ${h.echo || h.photos.length ? `<div class="echo">${h.echo ? `✨ ${esc(h.echo)}` : ""}
      ${h.photos.length ? `<div class="photos">${h.photos.map((p) => `<figure><img src="/photo/${p.id}" loading="lazy" alt="">
        <figcaption>${p.years_ago} 年前的今天</figcaption></figure>`).join("")}</div>` : ""}</div>` : ""}
    <p class="small"><a href="#" onclick="drawJunzi(event)">卡住了？抽一张君子卡</a></p><div id="junzi"></div>
    ${morning ? `<div class="quiet"><span class="muted small">昨晚睡了大概：</span>${[5, 6, 7, 8, 9].map((x) => `<button class="chip-btn" data-sleep="${x}">${x}h</button>`).join("")}</div>` : ""}
    <div class="quiet">
      ${anchors.length ? `<p>🌿 今天的节律：${anchors.map(esc).join("；")}</p>` : ""}
      ${h.dates.map((d) => `<p>🎁 ${esc(d.name)}还有 ${d.days_left} 天</p>`).join("")}
      ${h.dated.length ? `<p>⏳ 有期限的：${h.dated.map((t) => `${esc(t.title)}（${t.days_left < 0 ? "日期已过，还要做吗？" : t.days_left === 0 ? "今天" : t.days_left === 1 ? "明天" : "后天"}）`).join("；")}</p>` : ""}
      <p><a href="#pocket">🫧 口袋里有 ${h.pocket_count} 件事，它们会等你 →</a></p>
      <p><a href="#today">今天我需要一点结构 →</a></p>
    </div>
    ${evening ? goodnightForm(h) : ""}`;
  el.querySelectorAll(".feel").forEach((b) => (b.onclick = () => {
    NOW.feeling = b.dataset.f; NOW.seen = []; NOW.note = $("#now-note").value;
    el.querySelectorAll(".feel").forEach((x) => x.classList.toggle("on", x === b));
    ask(true);
  }));
  el.querySelectorAll("[data-m]").forEach((b) => (b.onclick = () => {
    NOW.minutes = b.dataset.m === "" ? null : Number(b.dataset.m); NOW.seen = [];
    el.querySelectorAll("[data-m]").forEach((x) => x.classList.toggle("on", x === b));
    if (NOW.feeling) ask(false);
  }));
  el.querySelectorAll("[data-sleep]").forEach((b) => (b.onclick = async () => {
    await api("/api/goodnight", { sleep: Number(b.dataset.sleep) });
    b.parentElement.innerHTML = '<span class="muted small">记下了。</span>';
  }));
  ask(false);
  const gn = $("#goodnight");
  if (gn) gn.onsubmit = goodnight;
}

async function ask(log) {
  const q = new URLSearchParams({ exclude: NOW.seen.join(",") });
  if (NOW.feeling) q.set("feeling", NOW.feeling);
  if (NOW.minutes) q.set("minutes", NOW.minutes);
  if (NOW.place) q.set("place", NOW.place);
  if (NOW.her !== null) q.set("her", NOW.her ? "1" : "0");
  if (log && NOW.feeling) { q.set("log", "1"); if (NOW.note) q.set("note", NOW.note); }
  const r = await api("/api/right_now?" + q);
  const card = $("#now-card");
  if (!card) return;
  const t = r.tian, s = r.pick;
  const places = Object.entries(r.places).map(([k, i]) =>
    `<button class="chip-btn ${r.place === k ? "on" : ""}" onclick="nowPlace('${k}')">${i} ${k}${r.place === k && r.guessed ? "?" : ""}</button>`).join("");
  const head = `<div class="rn-head"><span>🧭 此刻宜</span><span class="small muted">${esc(t.time)} ${esc(t.shichen)} · ${esc(t.part)}</span></div>`;
  const ctl = `<div class="rn-ctl"><div class="row">${places}
      <button class="chip-btn love ${r.with_her ? "on" : ""}" onclick="nowHer(${!r.with_her})">❤️ 她在身边</button></div>
    <p class="small muted rn-line">${esc(r.line)}　<a href="#moments">丰富选择 →</a></p></div>`;
  if (!s) {
    card.innerHTML = `<div class="card now rn">${head}<div class="sug">🍃 什么都不用做</div>
      <p class="muted">此刻没有特别适合的事。那就好好待着吧。</p>${ctl}</div>`;
    return;
  }
  const icon = { task: "🫧", care: "🌿", block: "🌿", moment: "✨" }[s.kind] || "🫧";
  NOW.cur = s.key; NOW.curTitle = s.title; NOW.curPart = t.part; NOW.curPlace = r.place;
  card.innerHTML = `<div class="card now rn">${head}
    <div class="sug">${icon} ${esc(s.title)}</div>
    ${s.ai ? `<p class="muted">${esc(s.ai)}</p>` : ""}
    <dl class="why">${s.why.map((w) => `<dt>${w.k}</dt><dd>${esc(w.t)}</dd>`).join("")}</dl>
    <div class="row">
      ${s.kind === "task" ? `<button class="btn primary" onclick="nowDone(${s.task_id})">做完了 ✓</button>`
        : s.key === "m:sleep" && $("#goodnight") ? `<button class="btn primary" onclick="$('#goodnight').scrollIntoView({behavior: 'smooth'})">去说晚安 🌙</button>`
        : `<button class="btn primary" onclick="nowOk()">好</button>`}
      <button class="btn" onclick="nowNext()">换一个</button>
      ${s.kind === "task" ? `<button class="btn" onclick="nowSkip(${s.task_id})">现在不想</button>` : ""}
    </div>
    ${r.alts.length ? `<p class="small muted" style="margin:10px 0 0">或者：${r.alts.map((a) => esc(a.title)).join(" · ")}</p>` : ""}
    ${ctl}</div>`;
}
function nowPlace(p) { NOW.place = p; NOW.seen = []; ask(false); }
function nowHer(on) { NOW.her = on; NOW.seen = []; ask(false); }
function logMoment(action) {
  api("/api/moments/log", { key: NOW.cur, title: NOW.curTitle, action, place: NOW.curPlace, feeling: NOW.feeling, part: NOW.curPart }).catch(() => {});
}
function nowNext() { logMoment("next"); NOW.seen.push(NOW.cur); ask(false); }
function nowOk() { logMoment("ok"); $("#now-card").innerHTML = '<div class="card now rn"><p class="muted" style="margin:0">去吧。🌿 <a href="#" onclick="event.preventDefault();ask(false)">回来再看</a></p></div>'; }
async function nowDone(id) { logMoment("done"); await api(`/api/tasks/${id}/done`, {}); toast("✓ 做完了。"); NOW.seen = []; ask(false); }
async function nowSkip(id, key = NOW.cur) { logMoment("not_now");
  const r = await api("/api/now/skip", { task_id: id });
  NOW.seen.push(key);
  if (!r.ask_let_go) {
    // 可选：为什么现在不想？完全可以跳过
    $("#now-card").innerHTML = `<div class="card now"><p class="muted">好。想说说为什么吗？（可以不说）</p>
      <div class="row">${HOME.skip_reasons.map((x) => `<button class="chip-btn" onclick="skipWhy(${id}, '${x}')">${x}</button>`).join("")}
      <button class="btn sm" onclick="ask(false)">跳过，换一个</button></div><div id="skip-why"></div></div>`;
    return;
  }
  if (r.ask_let_go) {
    $("#now-card").innerHTML = `<div class="card now"><div class="sug">这件事你已经跳过 ${r.skips} 次了。</div>
      <p class="muted">它还重要吗？放下不是失败，是选择。</p>
      <div class="row"><button class="btn primary" onclick="letGo(${id}, true)">🍃 放下它</button><button class="btn" onclick="ask(false)">留着，以后再说</button></div></div>`;
  } else ask(false);
}
async function skipWhy(id, reason) {
  const needStep = reason === "太大了" || reason === "不知道从哪开始";
  if (needStep) {
    $("#skip-why").innerHTML = `<p class="small">${reason === "太大了" ? "那就拆小：它的第一小步是什么？" : "写下你能想到的第一个动作，哪怕是\"打开文件\"。"}</p>
      <form class="inline" id="step-form"><input name="step" placeholder="第一小步" required><button class="btn primary">放进口袋</button></form>`;
    $("#step-form").onsubmit = async (e) => {
      e.preventDefault();
      const r = await api("/api/now/skip_reason", { task_id: id, reason, first_step: new FormData(e.target).get("step") });
      toast(r.reply); ask(false);
    };
    return;
  }
  const r = await api("/api/now/skip_reason", { task_id: id, reason });
  toast(r.reply);
  ask(false);
}
async function drawJunzi(e) {
  e.preventDefault();
  const c = await api("/api/junzi");
  $("#junzi").innerHTML = junziCard(c);
}
function junziCard(c) {
  return `<div class="junzi"><div class="junzi-sym">${c.symbol}</div><div class="junzi-img">${esc(c.image)}</div>
    <div class="junzi-act">${esc(c.act)}</div><div class="small muted">${esc(c.plain)}</div></div>`;
}
function horizonStrip(hz) {
  if (hz.ahead.length) {
    return `<div class="horizon">${hz.ahead.slice(0, 2).map((x) => `<a href="#her"><span class="hz-days">${x.days_left === 0 ? "今天" : x.days_left}</span>
      <span class="hz-title">${x.days_left === 0 ? "" : "天后 · "}${esc(x.title)}</span></a>`).join("")}</div>`;
  }
  return hz.empty_soon ? `<p class="small"><a href="#her">✨ 地平线上空了。放一件期待的事？→</a></p>` : "";
}
async function logRitual(id) {
  const note = prompt("怎么样？（可以不写）") ?? "";
  await api(`/api/rituals/${id}/log`, { note });
  toast("🕯");
  render(current);
}

async function letGo(id, thenAsk) {
  await api("/api/now/letgo", { task_id: id });
  toast("🍃 放下了。");
  if (thenAsk) ask(false); else render(current);
}

function goodnightForm() {
  return `<h2>🌙 晚安</h2>
  <form class="card" id="goodnight">
    <p class="muted small">三个问题，都可以不答。</p>
    <label class="small muted">今天有什么值得记住的瞬间？</label>
    <textarea name="moment" rows="2" style="width:100%"></textarea>
    <label class="small muted">她今天怎么样？说了什么？</label>
    <input name="her" style="width:100%">
    <div class="row" style="margin-top:8px"><span class="small muted">和她在一起：</span>
      ${[["", "没见面"], [30, "一会儿"], [180, "一晚上"], [480, "一整天"]].map(([m, l], i) =>
        `<label class="chip-btn"><input type="radio" name="love" value="${m}" ${i === 0 ? "checked" : ""} hidden>${l}</label>`).join("")}</div>
    <button class="btn primary" style="margin-top:10px">晚安</button>
  </form>`;
}
async function goodnight(e) {
  e.preventDefault();
  const f = Object.fromEntries(new FormData(e.target));
  await api("/api/goodnight", { feeling: NOW.feeling, moment: f.moment, her: f.her, love_minutes: f.love ? Number(f.love) : null });
  e.target.outerHTML = '<div class="card"><p>晚安。今天辛苦了。🌙</p></div>';
}

// ------------------------------------------------------------------ 口袋
async function renderPocket(el) {
  const p = await api("/api/pocket");
  const item = (t) => `<li><span>${esc(t.title)}</span>
    <span class="row"><button class="btn sm" onclick="doneTask(${t.id})">✓</button><button class="btn sm" title="放下" onclick="letGo(${t.id})">🍃</button></span></li>`;
  el.innerHTML = `
    <h2>🫧 口袋</h2>
    <p class="muted">这里装着你的杂事。它们会等你，不会追你。想做的时候来拿一件，或者在「此刻」让我帮你挑。</p>
    ${p.dated.length ? `<h3 class="sub">⏳ 有日期的</h3><ul class="pocket">${p.dated.map((t) =>
      item({ ...t, title: `${t.title}（${t.days_left < 0 ? "日期已过，还要做吗？" : t.days_left === 0 ? "今天" : t.due}）` })).join("")}</ul>` : ""}
    ${Object.entries(p.groups).map(([g, items]) => `<details class="card"><summary>${esc(g)} · ${items.length}</summary><ul class="pocket">${items.map(item).join("")}</ul></details>`).join("")}
    <form class="inline card" id="pocket-form"><input name="title" placeholder="放一件事进口袋" required>
      <select name="domain">${META.domains.map((d) => `<option>${esc(d)}</option>`).join("")}</select>
      <select name="energy"><option value="low">不费脑</option><option value="medium" selected>一般</option><option value="high">需要专注</option></select>
      <input name="minutes" type="number" value="30" style="max-width:80px" title="大约几分钟">
      <input name="due" type="date" style="max-width:150px" title="只有真正有期限才填">
      <button class="btn primary">放进去</button></form>
    <p class="small muted">🍃 = 放下。放下不是失败，是选择。</p>`;
  $("#pocket-form").onsubmit = async (e) => {
    e.preventDefault();
    await api("/api/tasks", Object.fromEntries(new FormData(e.target)));
    toast("放进口袋了");
    render("pocket");
  };
}

// ------------------------------------------------------------------ 一封信
async function renderLetter(el) {
  const r = await api("/api/letter");
  el.innerHTML = `
    <div class="card md letter">${md(r.markdown)}</div>
    <div class="row"><button class="btn primary" id="write-letter">${META.llm ? "请它好好写这周的信" : "保存这封信"}</button>
      <a class="small" href="#review">看数据 →</a></div>`;
  $("#write-letter").onclick = async () => {
    toast("写信中…");
    const s = await api("/api/letter", {});
    el.querySelector(".letter").innerHTML = md(s.markdown);
    toast("信已保存到 data/letters/");
  };
}

// ------------------------------------------------------------------ 更多
async function renderMore(el) {
  const ai = await api("/api/ai");
  const last = ai.last;
  const imps = ai.improvements || [];
  el.innerHTML = `
    <div class="card">
      <div class="small muted">🌙 每日梳理（你电脑上的 Claude Code 定时任务）</div>
      ${last ? `<p>${esc(last.day)} · ${last.status === "applied" ? "已完成" : last.status === "undone" ? "已撤销" : "未完成"}</p>
        <details><summary class="small muted">这次改了什么</summary><pre class="small">${esc(last.summary || "")}</pre></details>`
        : `<p class="muted small">还没有运行过。设置方法见 docs/本地部署与每日梳理.md</p>`}
    </div>
    ${imps.length ? `<h2>🛠 系统提升建议</h2>${imps.map((i) => `<div class="card"><b>${esc(i.title)}</b>
      ${i.effort ? `<span class="chip">${esc(i.effort)}</span>` : ""}
      <p class="small">${esc(i.why || "")}</p>
      <details><summary class="small muted">怎么做</summary><p class="small">${esc(i.how || "")}</p></details>
      <div class="row"><button class="btn sm" onclick="markImp(${i.id},'accepted')">想要</button>
      <button class="btn sm ghost" onclick="markImp(${i.id},'declined')">不用</button></div></div>`).join("")}` : ""}
    <div class="card more">
      <a href="#jushi">🧭 人生局势 <span class="muted small">主要矛盾、持久战、选择分析</span></a>
      <a href="#moments">🌿 此刻宜的选择库 <span class="muted small">它会从你的选择里学习</span></a>
      <a href="#memory">🧠 记忆 <span class="muted small">它在后台记着、连着；想找什么时再来</span></a>
      <a href="#today">🗓 今天的结构 <span class="muted small">需要的日子再打开</span></a>
      <a href="#graph">✨ 星图 <span class="muted small">人生各部分怎么连在一起</span></a>
      <a href="#review">📊 数据 <span class="muted small">时间账本、平衡轮、规律</span></a>
      <a href="#system">🤝 交给它的小事 <span class="muted small">菜单、建议、放权</span></a>
      <a href="/shop">📷 器材橱窗 <span class="muted small">给她看的平台雏形</span></a>
      <a href="#" onclick="scanPhotos(event)">🖼 索引照片 <span class="muted small">用于"那年今日"（rules.toml [photos]）</span></a>
    </div>
    <p class="small muted">这个系统的原则：它替你记住，在你需要时帮你做个小决定；其余时候，它安静。你是生活的主体。</p>`;
}

async function markImp(id, status) {
  await api(`/api/improvements/${id}/${status}`, {});
  render("more");
}

// ------------------------------------------------------------------ 天时
function hexSvg(lines, upto = 6) {
  // lines：自下而上的 6/7/8/9；画的时候从上往下
  const rows = [];
  for (let i = 5; i >= 0; i--) {
    const y = (5 - i) * 22 + 4, v = lines[i], shown = i < upto;
    const color = v === 6 || v === 9 ? "var(--accent)" : "var(--fg)";
    const op = shown ? 1 : 0.08;
    rows.push(v === 7 || v === 9
      ? `<rect x="10" y="${y}" width="140" height="12" rx="2" fill="${color}" opacity="${op}"/>`
      : `<rect x="10" y="${y}" width="62" height="12" rx="2" fill="${color}" opacity="${op}"/><rect x="88" y="${y}" width="62" height="12" rx="2" fill="${color}" opacity="${op}"/>`);
    if (shown && (v === 6 || v === 9)) rows.push(`<text x="160" y="${y + 11}" font-size="13" fill="var(--accent)">${v === 9 ? "○" : "×"}</text>`);
  }
  return `<svg viewBox="0 0 180 136" class="hex">${rows.join("")}</svg>`;
}

function readingHtml(r) {
  const rd = r.reading;
  return `<div class="row" style="align-items:flex-start;gap:16px">${hexSvg(r.lines)}
      <div style="flex:1;min-width:180px"><div class="hex-title">${esc(rd.title)}</div>
      ${rd.question ? `<p class="small muted">所问：${esc(rd.question)}</p>` : ""}
      <p class="xiang">${esc(rd.guaci)}</p>
      <p class="xiang">《象》曰：${esc(rd.xiang)}</p><p>${esc(rd.plain)}</p>
      <span class="chip">${esc(rd.stance_text)}</span></div></div>
    <div class="zhuxi"><p class="small muted">${esc(rd.zhuxi.rule)}</p>
      ${rd.zhuxi.main.filter((m) => m.text !== rd.guaci).map((m) => `<p class="xiang"><b>${esc(m.text)}</b>${m.xiang ? `<br><span class="small">《象》曰：${esc(m.xiang)}</span>` : ""}
        ${m.wuying ? `<br><span class="small muted">底本（武英殿本）：${esc(m.wuying)}</span>` : ""}</p>`).join("")}
      ${rd.zhuxi.aux.map((m) => `<p class="xiang small">${esc(m.text)}${m.wuying ? `<br><span class="muted">底本：${esc(m.wuying)}</span>` : ""}</p>`).join("")}</div>
    <p class="small muted">${esc(rd.change)}</p>
    ${rd.trend ? `<p class="small">${esc(rd.trend)}</p>` : ""}
    ${rd.ai ? `<div class="echo">${esc(rd.ai).replace(/\n/g, "<br>")}</div>` : ""}
    ${rd.structure ? structHtml(rd.structure) : ""}
    <p class="small"><b>自问</b><br>${rd.questions.map(esc).join("<br>")}</p>
    <p class="small muted">${esc(rd.note)}</p>`;
}

function structHtml(st) {
  // 卦象解读：内外卦、变爻的处境、互错综、落在各处
  const rel = ["hu", "zong", "cuo"].map((k) => st.related[k]);
  return `<details class="struct"><summary>展开卦象解读：内外卦 · 爻位 · 互错综 · 落在各处</summary>
    <p class="small"><b>内外</b>　${esc(st.summary)}<br><span class="muted">${esc(st.balance)}</span></p>
    <p class="small"><b>${esc(st.lines_title)}</b></p>
    ${st.lines.map((l) => `<p class="small" style="margin:4px 0 8px"><b>${esc(l.name)}</b> <span class="muted">${esc(l.position)}</span><br>${esc(l.text)}</p>`).join("")}
    <p class="small" style="margin-bottom:4px"><b>换三个角度看</b></p>
    <div class="related">${rel.map((x) => `<div><span class="muted">${esc(x.label)}</span> <b>${x.symbol} ${esc(x.full)}</b>
      <div class="muted">${esc(x.meaning)}</div><div>${esc(x.same ? "就是本卦自己：从这个角度看都一样" : x.plain)}</div></div>`).join("")}</div>
    <p class="small" style="margin-bottom:4px"><b>落在各处</b></p>
    <dl class="areas">${Object.entries(st.areas).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
    <p class="small muted">这些都是从六爻的结构推出来的：内卦是你自己，外卦是你的处境；爻有位置、有呼应。它们给你角度，不给结论。</p>
  </details>`;
}

function seasonHtml(t) {
  const sea = t.season, sn = t.sun;
  const lines = sea.hex.bits.map((b) => (b ? 7 : 8));
  return `<div class="card"><div class="season">${hexSvg(lines)}<div style="flex:1;min-width:0">
      <div class="small muted">时令之卦 · ${esc(sea.month)} · 不是起出来的，是这个季节本来的卦</div>
      <div class="hex-title">${sea.hex.symbol} ${esc(sea.hex.full)}</div>
      <p style="margin:4px 0">${esc(sea.text)}</p>
      <p class="xiang small" style="margin:4px 0">《象》曰：${esc(sea.hex.xiang)}</p>
      <p class="small muted yy" style="margin:4px 0">阳 ${sea.yang} · 阴 ${6 - sea.yang}　${esc(sea.next_hex.from)}起转为 ${sea.next_hex.symbol} ${esc(sea.next_hex.name)}</p>
    </div></div>
    <div class="small" style="margin-top:8px">🌾 ${esc(sea.term)}三候</div>
    <div class="hou">${sea.hou.all.map((h, i) => `<span class="${i + 1 === sea.hou.n ? "on" : ""}">${i + 1 === sea.hou.n ? "此候 · " : ""}${esc(h)}</span>`).join("")}</div>
    ${sn ? `<p class="small muted" style="margin:10px 0 0">☀️ 日出 ${sn.rise} · 黄金时刻 ${sn.golden} · 日落 ${sn.set} · 白昼 ${esc(sn.length)}（比昨天${sn.change >= 0 ? "长" : "短"} ${Math.abs(sn.change)} 分钟）</p>` : ""}
    <p class="small muted" style="margin:6px 0 0">🧭 此刻：${esc(t.time)} ${esc(t.shichen)} · ${esc(t.part)}${t.light ? " · " + esc(t.light) : ""}</p>
  </div>`;
}

async function revealCast(el, r) {
  // 一爻一爻地出现：仪式感，也让人慢下来
  for (let k = 1; k <= 6; k++) {
    el.innerHTML = `<div class="row">${hexSvg(r.lines, k)}<span class="muted small">第 ${k} 爻…</span></div>`;
    await new Promise((ok) => setTimeout(ok, 380));
  }
  el.innerHTML = readingHtml(r);
}

async function renderTianshi(el) {
  const d = await api("/api/tianshi");
  if (!HOME.notes) HOME.notes = (await api("/api/ai")).notes || {};
  const dir = { 1: "顺", "-1": "逆", 0: "观" };
  const mom = Object.entries(d.momentum).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  el.innerHTML = `
    <p class="greet">🌿 ${esc(d.term.name)}　${esc(d.term.tip)} <span class="small">（距${esc(d.term.next)} ${d.term.days_to_next} 天）</span></p>
    ${d.weather ? `<p class="muted">${d.weather.icon} ${esc(d.weather.city)} ${esc(d.weather.label)} ${d.weather.tmin}–${d.weather.tmax}°C</p>` : ""}
    ${HOME.notes.shi ? `<p class="ai-note">🧭 ${esc(HOME.notes.shi)}</p>` : ""}
    <p class="small"><a href="#jushi">🧭 看看人生局势：主要矛盾、持久战、选择分析 →</a></p>
    <h2>🌗 时令</h2>
    ${seasonHtml(d.tian)}
    <h2>☯ 今日之卦</h2>
    <div class="card" id="day-cast">${d.today ? readingHtml(d.today) : `
      <p>心里想着今天，静一静，然后起一卦。</p>
      <input id="intention" placeholder="此刻心里想着什么？（可以不写）" style="width:100%;margin-bottom:8px">
      <p class="small muted">三枚铜钱，掷六次。一天只起一次：命不能重抽。</p>
      <button class="btn primary" id="cast-day">起卦</button>`}</div>
    ${d.almanac ? `<p class="small muted">📜 ${esc(d.almanac.lunar)}　宜：${d.almanac.yi.map(esc).join(" ")}　忌：${d.almanac.ji.map(esc).join(" ")}
      <br>（黄历仅作文化参考，不进入任何建议）</p>` : ""}
    <h2>🀄 君子卡</h2>
    <div class="card"><p class="small muted">做设计、剪视频、想事情卡住了，抽一张。六十四条《象传》，每一条都是"在这种处境下，君子怎么做"。</p>
      <div id="junzi-t"></div><button class="btn" onclick="drawJunziT()">抽一张</button></div>
    <h2>🤔 问一事</h2>
    <form class="card" id="ask-form">
      <textarea name="question" rows="2" style="width:100%" placeholder="心里犹豫的一件事，比如：要不要这个月把器材生意做大一点？" required></textarea>
      <button class="btn primary" style="margin-top:8px">起卦</button>
      <div id="ask-result" style="margin-top:12px"></div>
    </form>
    <h2>🌏 天下大势</h2>
    ${mom.length ? `<div class="card">${mom.map(([k, v]) => `<div class="row" style="justify-content:space-between"><span>${esc(k)}</span>
      <span class="small ${v > 0 ? "up" : "down"}">${v > 0 ? "顺势" : "逆势"} ${Math.abs(v)}</span></div>
      <div class="bar"><i style="width:${Math.min(Math.abs(v) / 6 * 100, 100)}%;background:${v > 0 ? "var(--ok)" : "var(--bad)"}"></i></div>`).join("")}</div>` : ""}
    <div class="card">${d.trends.map((t) => `<div class="mem"><div class="row small muted"><span class="chip">${dir[t.direction]}${t.strength}</span>
        <span>${esc(t.domain || "—")}</span><span>${t.observed_at.slice(0, 10)}</span>
        <button class="btn sm" onclick="keepTrend(${t.id})">有用</button><button class="btn sm" onclick="retireTrend(${t.id})">过时了</button></div>
        <div>${esc(t.title)}</div>${t.summary ? `<div class="small muted">${esc(t.summary)}</div>` : ""}</div>`).join("") ||
        '<p class="muted">还没有记录。你观察到的任何趋势都可以记下来：行业冷暖、器材行情、物价、新工具……</p>'}
      <form class="inline" id="trend-form" style="margin-top:10px">
        <input name="title" placeholder="你观察到的势" required>
        <select name="domain"><option value="">领域</option>${META.domains.map((x) => `<option>${esc(x)}</option>`).join("")}</select>
        <select name="direction"><option value="1">对我顺势</option><option value="-1">对我逆势</option><option value="0" selected>只是观察</option></select>
        <select name="strength">${[1, 2, 3, 4, 5].map((n) => `<option ${n === 2 ? "selected" : ""}>${n}</option>`).join("")}</select>
        <button class="btn">记下</button></form>
      <button class="btn sm" id="fetch-trends" style="margin-top:8px">看看外面（新闻源）</button></div>
    ${d.stats.n ? `<h2>📊 起卦记录</h2><div class="card small">
      共 ${d.stats.n} 卦 · 平均变爻 ${d.stats.moving_avg}（随机期望 ${d.stats.moving_expected}）<br>
      ${d.stats.stances.filter((x) => x.seen || x.expected >= 0.5).map((x) => `${esc(x.desc)} ${x.seen}（期望 ${x.expected}）`).join(" · ")}
      <p class="muted">${esc(d.stats.note)}</p></div>` : ""}
    <h2>📜 过去的卦</h2>
    <div class="card">${d.history.map((c) => `<div class="mem"><div class="small muted">${c.day} · ${esc(c.question || "今日之卦")}</div>
        <div>${esc(c.title)}</div>
        ${c.outcome ? `<div class="small">后来：${esc(c.outcome)}</div>` : `<button class="btn sm" onclick="castOutcome(${c.id})">后来怎样了？</button>`}</div>`).join("") ||
        '<p class="muted">还没有起过卦。</p>'}</div>
    <p class="small muted">卦是一面镜子，不是预言；势是风向，不是命令。你标记"有用 / 过时了"，会调整之后从哪些新闻源取多少内容。它们只会让建议轻一点或重一点，从不改变事实。影响程度可在 rules.toml 的 [yi] weight 调整。</p>`;
  const cb = $("#cast-day");
  if (cb) cb.onclick = async () => {
    const r = await api("/api/yi/today", { intention: $("#intention").value });
    await revealCast($("#day-cast"), r);
  };
  $("#ask-form").onsubmit = async (e) => {
    e.preventDefault();
    const q = new FormData(e.target).get("question");
    const box = $("#ask-result");
    box.innerHTML = '<p class="muted small">起卦中…</p>';
    const r = await api("/api/yi/ask", { question: q });
    await revealCast(box, r);
  };
  $("#trend-form").onsubmit = async (e) => { e.preventDefault(); await api("/api/trends", Object.fromEntries(new FormData(e.target))); render("tianshi"); };
  $("#fetch-trends").onclick = async () => {
    toast("去外面看看…");
    const r = await api("/api/trends/fetch", {});
    toast(r.added ? `带回 ${r.added} 条` : "没有新的，或者网络不通");
    render("tianshi");
  };
}
async function drawJunziT() { $("#junzi-t").innerHTML = junziCard(await api("/api/junzi")); }
async function keepTrend(id) { await api(`/api/trends/${id}/keep`, {}); toast("记下了：这个来源更值得看"); render("tianshi"); }
async function retireTrend(id) { await api(`/api/trends/${id}/retire`, {}); render("tianshi"); }
async function castOutcome(id) {
  const o = prompt("后来怎样了？（这是写给自己的）");
  if (o) { await api("/api/yi/outcome", { id, outcome: o }); render("tianshi"); }
}

async function scanPhotos(e) {
  e.preventDefault();
  toast("索引中…");
  const r = await api("/api/photos/scan", {});
  toast(r.folders.length ? `新增 ${r.added} 张，共 ${r.total} 张` : "先在 rules.toml 的 [photos] folders 里填照片文件夹");
}

// ------------------------------------------------------------------ 框架
const RENDER = { now: renderNow, pocket: renderPocket, her: renderHer, tianshi: renderTianshi, memory: renderMemory, gear: renderGear, letter: renderLetter, more: renderMore,
  today: renderToday, graph: renderGraph, review: renderReview, system: renderSystem, jushi: renderJushi, moments: renderMoments };
const TAB_OF = { today: "more", graph: "more", review: "more", system: "more", memory: "more", jushi: "more", moments: "more" };
let current = "now";

async function render(tab) {
  current = tab;
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === (TAB_OF[tab] || tab)));
  document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("on", s.id === tab));
  try {
    await RENDER[tab]($("#" + tab));
  } catch (e) {
    $("#" + tab).innerHTML = `<div class="card">出错了：${esc(e.message)}</div>`;
  }
}

$("#tabs").onclick = (e) => { if (e.target.dataset.tab) location.hash = e.target.dataset.tab; };
window.addEventListener("hashchange", () => render(location.hash.slice(1) in RENDER ? location.hash.slice(1) : "now"));
$("#capture").onsubmit = async (e) => {
  e.preventDefault();
  const input = $("#capture-text");
  if (!input.value.trim()) return;
  const r = await api("/api/capture", { text: input.value });
  input.value = "";
  const parts = [`🧠 记下了`];
  if (r.tasks.length) parts.push(`☐ 任务：${r.tasks.map((t) => t.title).join("；")}`);
  if (r.wishes.length) parts.push(`❤️ 愿望：${r.wishes.map((w) => w.content).join("；")}`);
  if (r.items.length) parts.push(`📷 ${r.items.map((i) => `${i.action === "buy" ? "收" : "出"} ${i.model}`).join("；")}`);
  toast(parts.join("\n"));
  render(current);
};

(async () => {
  META = await api("/api/meta");
  $("#llm").textContent = META.llm ? "Claude" : META.ai_mode === "claude-code" ? "Claude Code" : "每日梳理";
  render(location.hash.slice(1) in RENDER ? location.hash.slice(1) : "now");
})();

// ------------------------------------------------------------------ 人生局势
const OPT = { rev: [["", "可逆吗？"], ["1", "可以回头"], ["0", "很难回头"]], contra: [["0", "对主要矛盾：无关"], ["1", "缓解它"], ["-1", "加剧它"]],
  her: [["0", "对她：无影响"], ["1", "对她好"], ["-1", "对她不好"]], worst: [["", "最坏情况？"], ["1", "承受得起"], ["0", "承受不了"]] };
const sel = (name, opts) => `<select name="${name}">${opts.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select>`;
let JS = null;

async function renderJushi(el) {
  const r = await api("/api/jushi");
  JS = r;
  const m = r.main;
  const bar = (x) => x.ratio === null ? '<span class="small muted">没记录时间</span>'
    : `<div class="bar"><i style="width:${Math.min(x.ratio * 100, 100)}%;background:${x.ratio < 0.5 ? "var(--warn)" : x.ratio > 1.2 ? "var(--bad)" : "var(--ok)"}"></i></div>
       <span class="small muted">${x.hours}/${x.budget}h</span>`;
  el.innerHTML = `<p class="small"><a href="#more">← 更多</a></p>
    <h2>🧭 人生局势</h2>
    <div class="card">${r.summary.map((x) => `<p style="margin:4px 0">${esc(x)}</p>`).join("")}
      <div class="row" style="margin-top:8px"><button class="btn sm" id="js-ai">请 Claude 推演一下</button></div><div id="js-ai-out"></div></div>
    ${m ? `<h2>⚖️ 主要矛盾</h2><div class="card main-contra"><div class="hex-title">${esc(m.title)}</div>
      <p>${esc(m.aspect)}</p>${m.evidence.length ? `<ul class="small muted">${m.evidence.map((e) => `<li>${esc(e)}</li>`).join("")}</ul>` : ""}
      <p><b>下一着：</b>${esc(m.move)}</p>
      <p class="small muted">矛盾论：许多矛盾里，有一个起着决定作用；抓住它，其他的会跟着动。主要矛盾会转化，所以每周重算。</p></div>
      ${r.contradictions.length > 1 ? `<div class="card"><div class="small muted">次要矛盾</div>${r.contradictions.slice(1, 5).map((c) =>
        `<div class="mem"><b>${esc(c.title)}</b><div class="small">${esc(c.aspect)}</div><div class="small muted">一着：${esc(c.move)}</div></div>`).join("")}</div>` : ""}` : ""}
    ${r.gaps.length ? `<h2>🔍 认识与实践</h2><div class="card small">${r.gaps.map((g) => `<p>${esc(g)}</p>`).join("")}
      <p class="muted">实践论：认识从实践中来，也要回到实践里检验。自评和数据对不上的地方，最值得想一想。</p></div>` : ""}
    <h2>🎡 全局</h2>
    <div class="card"><div class="wheel">${r.wheel.map((x) => `<div class="wrow"><span>${esc(x.domain)}${x.role === "main" ? " ·主线" : ""}</span>
      <span>${bar(x)}</span><span class="small ${x.momentum > 0 ? "up" : x.momentum < 0 ? "down" : "muted"}">${x.momentum ? (x.momentum > 0 ? "顺" : "逆") + Math.abs(x.momentum) : "—"}</span>
      <span class="small">${x.self ? x.self + " 分" : ""}</span></div>`).join("")}</div>
      <details><summary class="small">给每个领域打个分（你自己的感觉，1-10）</summary>
      <form id="rate-form" class="rate">${r.wheel.map((x) => `<label class="small">${esc(x.domain)}<input type="number" min="1" max="10" name="${esc(x.domain)}" value="${x.self ?? ""}"></label>`).join("")}
      <button class="btn primary">记下</button></form></details>
      <p class="small muted">投入 = 近 4 周记下的时间 ÷ 预算；势 = 外面的顺逆。数据只是参考，不是评分。</p></div>
    ${r.campaigns.length ? `<h2>🏔 持久战</h2><div class="card">${r.campaigns.map((c) => `<div class="mem"><div class="row" style="justify-content:space-between">
      <b>${esc(c.name)}</b><span class="chip">${esc(c.stage)}</span></div><div class="bar"><i style="width:${c.pct}%;background:var(--accent)"></i></div>
      <div class="small muted">${esc(c.detail)} · ${esc(c.stage_text)}</div></div>`).join("")}
      <p class="small muted">论持久战：长期目标分防御、相持、反攻三个阶段，每个阶段该做的事不一样。积小胜为大胜。</p></div>` : ""}
    ${r.thresholds.length ? `<div class="card small">${r.thresholds.map((x) => `<p>🌱 ${esc(x)}</p>`).join("")}</div>` : ""}
    <h2>🪨 能控制 / 能影响 / 控制不了</h2>
    <div class="card control"><div><b class="small">能控制</b>${r.control.can.map((x) => `<p class="small">${esc(x)}</p>`).join("")}</div>
      <div><b class="small">能影响</b>${r.control.influence.map((x) => `<p class="small">${esc(x)}</p>`).join("")}</div>
      <div><b class="small muted">控制不了</b>${r.control.cannot.map((x) => `<p class="small muted">${esc(x)}</p>`).join("")}</div>
      <p class="small muted" style="grid-column:1/-1">斯多葛：只在第一栏上用力，第二栏尽力而为，第三栏放下。</p></div>
    <h2>🧩 选择分析</h2>
    <form class="card" id="choose-form">
      <textarea name="question" rows="2" style="width:100%" placeholder="一件你在犹豫的事：比如，要不要这个月把器材生意做大？" required></textarea>
      ${[1, 2, 3].map((i) => `<div class="opt"><input name="name${i}" placeholder="选项 ${i}${i === 3 ? "（可不填）" : ""}" ${i < 3 ? "required" : ""}>
        <div class="row">${sel("rev" + i, OPT.rev)}${sel("contra" + i, OPT.contra)}${sel("her" + i, OPT.her)}${sel("worst" + i, OPT.worst)}
        <label class="small"><input type="checkbox" name="ten${i}"> 十年后还在意</label></div></div>`).join("")}
      <button class="btn primary">从各个角度看</button>
      <p class="small muted">矛盾论 · 可逆性 · 最坏情况 · 10/10/10 · 人和 · 持久战 · 天时 · 反演 · 事前验尸 · 基准率。它帮你想清楚，不替你决定。</p>
      <div id="choose-out"></div></form>
    ${r.practice.due.length || r.practice.calibration.length ? `<h2>🔁 实践检验</h2><div class="card small">
      ${r.practice.due.map((d) => `<p>到期回看：${esc(d.question)} → 你选了「${esc(d.choice || "")}」，预测「${esc(d.prediction || "")}」</p>`).join("")}
      ${r.practice.calibration.map((b) => `<p>你说 ${b.confidence} 把握时，命中 ${Math.round(b.hit_rate * 100)}%（${b.n} 次）</p>`).join("")}
      <p class="muted">命令行回看：python3 -m lifeos decide review</p></div>` : ""}
    <h2>☯ 天时</h2><div class="card small"><p>${esc(r.tian.season)}</p>${r.tian.cast ? `<p>今日之卦：${esc(r.tian.cast)}</p>` : ""}
      ${r.tian.momentum.length ? `<p>各领域之势：${r.tian.momentum.map(([k, v]) => `${esc(k)}${v > 0 ? "顺" : "逆"}${Math.abs(v)}`).join("，")}</p>` : ""}</div>
    <h2>🀄 命理</h2><div class="card small">${r.mingli ? r.mingli.lines.map((x) => `<p>${esc(x)}</p>`).join("") + `<p class="muted">${esc(r.mingli.note)}</p>`
      : `<p>填出生时间可以排八字、看流年流月的主题（只存在你的电脑上）。</p>`}
      <form class="inline" id="birth-form"><input type="datetime-local" name="birth" value="${esc((r.birth || "").slice(0, 16))}" required><button class="btn sm">${r.birth ? "修改" : "排盘"}</button></form>
      <p class="muted">命理是文化的镜子，没有经过科学验证，不进入任何建议的计算。</p></div>
    <p class="small muted">这一页把几种看法放在一起：科学（只用你的真实数据）、逻辑推演、斯多葛哲学、矛盾论与实践论、论持久战、周易、命理（只作镜子）。详见 docs/人生局势.md。</p>`;
  $("#js-ai").onclick = async () => {
    $("#js-ai-out").innerHTML = '<p class="small muted">推演中…（本机 claude 可能要一两分钟）</p>';
    const x = await api("/api/jushi/ai", {});
    $("#js-ai-out").innerHTML = x.text ? `<div class="echo">${esc(x.text).replace(/\n/g, "<br>")}</div>`
      : '<p class="small muted">现在没有可用的 Claude（需要 API key，或 [ai] mode = "claude-code"）。每日梳理时它会看局势。</p>';
  };
  $("#rate-form").onsubmit = async (e) => { e.preventDefault(); await api("/api/jushi/rate", { ratings: Object.fromEntries(new FormData(e.target)) }); toast("记下了"); render("jushi"); };
  $("#birth-form").onsubmit = async (e) => { e.preventDefault(); await api("/api/mingli", { birth: new FormData(e.target).get("birth") }); render("jushi"); };
  $("#choose-form").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const tri = (v) => (v === "" ? null : v === "1");
    const options = [1, 2, 3].map((i) => ({ name: f.get("name" + i), reversible: tri(f.get("rev" + i)), contra: Number(f.get("contra" + i)),
      her: Number(f.get("her" + i)), worst_ok: tri(f.get("worst" + i)), ten_years: !!f.get("ten" + i) })).filter((o) => o.name);
    const a = await api("/api/jushi/choose", { question: f.get("question"), options });
    $("#choose-out").innerHTML = `<div style="margin-top:12px">${a.options.map((o, i) => `<div class="mem"><div class="row" style="justify-content:space-between">
        <b>${i === 0 ? "→ " : ""}${esc(o.name)}</b><span class="chip">${o.score > 0 ? "+" : ""}${o.score}</span></div>
        ${o.notes.map(([k, t]) => `<div class="small"><span class="muted">${esc(k)}</span> ${esc(t)}</div>`).join("")}
        ${o.flags.map((t) => `<div class="small" style="color:var(--warn)">⚠️ ${esc(t)}</div>`).join("")}
        <button class="btn sm" type="button" onclick="decideChoice(${a.id}, ${i})">我选这个</button></div>`).join("")}
      <p class="small"><b>再问自己几个问题</b></p>${a.lenses.map((l) => `<p class="small"><span class="muted">${esc(l.name)}</span> ${esc(l.q)}</p>`).join("")}
      <p class="small muted">${esc(a.calibration)}。${esc(a.practice)}</p>
      <p class="small muted">天时：${esc(a.tian)}${a.mingli ? "　" + esc(a.mingli) : ""}</p>
      <p class="small muted">${esc(a.note)}</p></div>`;
    JS.lastChoice = a;
  };
}
async function decideChoice(id, i) {
  const o = JS.lastChoice.options[i];
  const prediction = prompt(`你选「${o.name}」。你预测一个月后会怎样？（写下来，到期回看）`);
  if (prediction === null) return;
  const conf = prompt("你有几成把握？（0-100）", "60");
  await api("/api/jushi/decide", { id, chosen: o.name, prediction, confidence: Math.max(0, Math.min(100, Number(conf) || 60)) / 100, days: 30 });
  toast("记进决策日志了，30 天后回来看看");
}

// ------------------------------------------------------------------ 此刻宜的选择库
async function renderMoments(el) {
  const d = await api("/api/moments");
  const cats = {};
  d.moments.forEach((m) => (cats[m.cat] = cats[m.cat] || []).push(m));
  el.innerHTML = `<p class="small"><a href="#now">← 此刻</a></p><h2>🌿 此刻宜的选择库</h2>
    <p class="small muted">口袋里的事之外，"此刻"还可以做的事。系统按天时、地利、人和从这里挑；常点"好"的会更常出现，常点"换一个"的慢慢沉下去，刚做过的让一让。</p>
    <form class="card" id="moment-form"><div class="row"><input name="title" placeholder="加一个你自己的：比如，去河边坐一会儿" required style="flex:1 1 220px">
      <select name="need">${Object.entries(d.needs).map(([k, v]) => `<option value="${k}" ${k === "any" ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>
      <input name="minutes" type="number" value="15" min="0" style="width:72px"> 分钟 <button class="btn primary">加入</button></div></form>
    ${Object.entries(cats).map(([c, ms]) => `<h2>${esc(c)}</h2><div class="card">${ms.map((m) => `<div class="mem row" style="justify-content:space-between;${m.active ? "" : "opacity:.45"}">
      <span>${esc(m.title)} <span class="small muted">${esc(d.needs[m.need] || "")} · ${m.minutes} 分钟${m.yes || m.no ? ` · 好 ${m.yes} / 换 ${m.no}` : ""}</span></span>
      <button class="btn sm ghost" onclick="toggleMoment('${m.key}', ${m.active ? 0 : 1})">${m.active ? "停用" : "启用"}</button></div>`).join("")}</div>`).join("")}`;
  $("#moment-form").onsubmit = async (e) => { e.preventDefault(); await api("/api/moments", Object.fromEntries(new FormData(e.target))); toast("加进去了"); render("moments"); };
}
async function toggleMoment(key, on) { await api(`/api/moments/${key}/${on ? "on" : "off"}`, {}); render("moments"); }
