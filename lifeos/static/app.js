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
    <h2>🌙 晚间签到（3 分钟）</h2>
    <form class="card" id="checkin-form">
      <div class="row">
        <label>能量 <input name="energy" type="number" min="1" max="10" style="width:64px"></label>
        <label>心情 <input name="mood" type="number" min="1" max="10" style="width:64px"></label>
        <label>睡眠 <input name="sleep" type="number" step="0.5" style="width:70px">h</label>
        <label>和她 <input name="love_minutes" type="number" style="width:70px">分钟</label>
        <label><input name="exercised" type="checkbox"> 锻炼了</label>
      </div>
      <textarea name="note" rows="2" style="width:100%;margin-top:8px" placeholder="今天最值得记住的事？她提到了什么？"></textarea>
      <button class="btn primary" style="margin-top:8px">完成签到</button>
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
  $("#checkin-form").onsubmit = async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    const num = (k) => (f[k] === "" || f[k] === undefined ? null : Number(f[k]));
    await api("/api/checkin", { energy: num("energy"), mood: num("mood"), sleep: num("sleep"), love_minutes: num("love_minutes"),
      exercised: f.exercised ? 1 : 0, note: f.note || null });
    toast("签到完成，晚安 🌙");
    e.target.reset();
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
  const mems = await api("/api/memories" + (q ? `?q=${encodeURIComponent(q)}` : "?days=60"));
  const pending = mems.filter((m) => m.status === "needs_confirm");
  el.innerHTML = `
    <form class="inline" id="mem-search"><input name="q" value="${esc(q)}" placeholder="检索记忆：冰岛 / 50/1.4 / 她喜欢…"><button class="btn">检索</button></form>
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
  const d = await api("/api/her");
  const statuses = ["想法", "规划中", "进行中", "已实现"];
  el.innerHTML = `
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
  $("#date-form").onsubmit = async (e) => { e.preventDefault(); await api("/api/dates", Object.fromEntries(new FormData(e.target))); render("her"); };
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
    ${a.pending.map((s) => `<div class="card"><span class="chip">${esc(s.category)}</span> ${esc(s.content).slice(0, 300)}<div class="row" style="margin-top:6px">${fbButtons(s.id)}</div></div>`).join("") || '<p class="muted">没有待反馈的建议。</p>'}
    <h2>🍳 本周菜单（🥗 = 轻食，支持她的健康目标）</h2>
    <div class="card">${menu.days.map((d) => `<div>${d.day} ${esc(d.dish)} ${d.light ? "🥗" : ""}</div>`).join("")}
      <p class="small muted">🛒 ${menu.shopping.map(esc).join("、")}</p></div>`;
}


// ------------------------------------------------------------------ 此刻
const NOW = { feeling: null, minutes: null, seen: [], note: "" };
const MINUTES = [[15, "一会儿"], [45, "半小时多"], [120, "一两个小时"], ["", "不确定"]];

async function renderNow(el) {
  const h = await api("/api/home");
  const evening = h.hour >= 20 || h.hour < 3;
  const morning = h.hour >= 5 && h.hour < 11;
  const anchors = h.anchors.filter((a) => !a.includes("💼"));
  el.innerHTML = `
    <p class="greet">${esc(h.greeting)} ${esc(h.term.name)}时节${h.weather ? ` · ${h.weather.icon} ${esc(h.weather.label)} ${h.weather.tmin}–${h.weather.tmax}°C` : ""}</p>
    <p class="small"><a href="#tianshi">${h.cast ? `☯ ${h.cast.symbol} ${esc(h.cast.full)} · ${esc(h.cast.stance)}` : "☯ 今日还未起卦 →"}</a></p>
    <h1 class="ask">你现在感觉怎么样？</h1>
    <div class="feelings">${Object.entries(h.feelings).map(([f, i]) =>
      `<button class="feel ${NOW.feeling === f ? "on" : ""}" data-f="${f}"><span>${i}</span>${f}</button>`).join("")}</div>
    <div class="row minutes"><span class="muted small">有多少时间？</span>${MINUTES.map(([m, label]) =>
      `<button class="chip-btn ${String(NOW.minutes ?? "") === String(m) ? "on" : ""}" data-m="${m}">${label}</button>`).join("")}</div>
    <input id="now-note" value="${esc(NOW.note)}" placeholder="想说点什么也可以（可不填）">
    <div id="now-card">${NOW.feeling ? "" : '<p class="muted small" style="margin-top:14px">点一下你的感受，我给你一个可能性。或者，什么都不点。</p>'}</div>
    ${h.echo ? `<div class="echo">✨ ${esc(h.echo)}</div>` : ""}
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
  if (NOW.feeling) ask(false);
  const gn = $("#goodnight");
  if (gn) gn.onsubmit = goodnight;
}

async function ask(log, decide = false) {
  const q = new URLSearchParams({ feeling: NOW.feeling, exclude: NOW.seen.join(",") });
  if (NOW.minutes) q.set("minutes", NOW.minutes);
  if (log) { q.set("log", "1"); if (NOW.note) q.set("note", NOW.note); }
  if (decide) q.set("decide", "1");
  const s = await api("/api/now?" + q);
  const card = $("#now-card");
  if (s.kind === "none") {
    card.innerHTML = `<div class="card now"><div class="sug">🍃 ${esc(s.title)}</div><p class="muted">${esc(s.reason)}</p></div>`;
    return;
  }
  card.innerHTML = `<div class="card now">
    ${decide ? '<p class="small muted">那就这个吧：</p>' : ""}
    <div class="sug">${s.kind === "care" ? "🌿" : "🫧"} ${esc(s.title)}</div>
    <p class="muted">${esc(s.ai || s.reason)}</p>
    <div class="row">
      ${s.kind === "task" ? `<button class="btn primary" onclick="nowDone(${s.task_id})">做完了 ✓</button>` : `<button class="btn primary" onclick="nowOk()">好</button>`}
      <button class="btn" onclick="nowNext('${s.key}')">换一个</button>
      ${decide ? "" : '<button class="btn" onclick="ask(false, true)">帮我决定</button>'}
      ${s.kind === "task" ? `<button class="btn" onclick="nowSkip(${s.task_id}, '${s.key}')">现在不想</button>` : ""}
    </div>
    <p class="small muted" style="margin-top:10px">或者，什么都不做也很好。</p></div>`;
}
function nowNext(key) { NOW.seen.push(key); ask(false); }
function nowOk() { $("#now-card").innerHTML = '<p class="muted" style="margin-top:14px">去吧。🌿</p>'; }
async function nowDone(id) { await api(`/api/tasks/${id}/done`, {}); toast("✓ 做完了。"); NOW.seen = []; ask(false); }
async function nowSkip(id, key) {
  const r = await api("/api/now/skip", { task_id: id });
  NOW.seen.push(key);
  if (r.ask_let_go) {
    $("#now-card").innerHTML = `<div class="card now"><div class="sug">这件事你已经跳过 ${r.skips} 次了。</div>
      <p class="muted">它还重要吗？放下不是失败，是选择。</p>
      <div class="row"><button class="btn primary" onclick="letGo(${id}, true)">🍃 放下它</button><button class="btn" onclick="ask(false)">留着，以后再说</button></div></div>`;
  } else ask(false);
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
  el.innerHTML = `
    <div class="card more">
      <a href="#today">🗓 今天的结构 <span class="muted small">需要的日子再打开</span></a>
      <a href="#graph">✨ 星图 <span class="muted small">人生各部分怎么连在一起</span></a>
      <a href="#review">📊 数据 <span class="muted small">时间账本、平衡轮、规律</span></a>
      <a href="#system">🤝 交给它的小事 <span class="muted small">菜单、建议、放权</span></a>
      <a href="/shop">📷 器材橱窗 <span class="muted small">给她看的平台雏形</span></a>
    </div>
    <p class="small muted">这个系统的原则：它替你记住，在你需要时帮你做个小决定；其余时候，它安静。你是生活的主体。</p>`;
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
      <p class="xiang">《象》曰：${esc(rd.xiang)}</p><p>${esc(rd.plain)}</p>
      <span class="chip">${esc(rd.stance_text)}</span></div></div>
    <p class="small muted">${esc(rd.change)}</p>
    ${rd.trend ? `<p class="small">${esc(rd.trend)}</p>` : ""}
    ${rd.ai ? `<div class="echo">${esc(rd.ai).replace(/\n/g, "<br>")}</div>` : ""}
    <p class="small"><b>自问</b><br>${rd.questions.map(esc).join("<br>")}</p>
    <p class="small muted">${esc(rd.note)}</p>`;
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
  const dir = { 1: "顺", "-1": "逆", 0: "观" };
  const mom = Object.entries(d.momentum).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  el.innerHTML = `
    <p class="greet">🌿 ${esc(d.term.name)}　${esc(d.term.tip)} <span class="small">（距${esc(d.term.next)} ${d.term.days_to_next} 天）</span></p>
    ${d.weather ? `<p class="muted">${d.weather.icon} ${esc(d.weather.city)} ${esc(d.weather.label)} ${d.weather.tmin}–${d.weather.tmax}°C</p>` : ""}
    <h2>☯ 今日之卦</h2>
    <div class="card" id="day-cast">${d.today ? readingHtml(d.today) : `
      <p>心里想着今天，静一静，然后起一卦。</p>
      <p class="small muted">三枚铜钱，掷六次。一天只起一次：命不能重抽。</p>
      <button class="btn primary" id="cast-day">起卦</button>`}</div>
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
        <button class="btn sm" onclick="retireTrend(${t.id})">过时了</button></div>
        <div>${esc(t.title)}</div>${t.summary ? `<div class="small muted">${esc(t.summary)}</div>` : ""}</div>`).join("") ||
        '<p class="muted">还没有记录。你观察到的任何趋势都可以记下来：行业冷暖、器材行情、物价、新工具……</p>'}
      <form class="inline" id="trend-form" style="margin-top:10px">
        <input name="title" placeholder="你观察到的势" required>
        <select name="domain"><option value="">领域</option>${META.domains.map((x) => `<option>${esc(x)}</option>`).join("")}</select>
        <select name="direction"><option value="1">对我顺势</option><option value="-1">对我逆势</option><option value="0" selected>只是观察</option></select>
        <select name="strength">${[1, 2, 3, 4, 5].map((n) => `<option ${n === 2 ? "selected" : ""}>${n}</option>`).join("")}</select>
        <button class="btn">记下</button></form>
      <button class="btn sm" id="fetch-trends" style="margin-top:8px">看看外面（新闻源）</button></div>
    <h2>📜 过去的卦</h2>
    <div class="card">${d.history.map((c) => `<div class="mem"><div class="small muted">${c.day} · ${esc(c.question || "今日之卦")}</div>
        <div>${esc(c.title)}</div>
        ${c.outcome ? `<div class="small">后来：${esc(c.outcome)}</div>` : `<button class="btn sm" onclick="castOutcome(${c.id})">后来怎样了？</button>`}</div>`).join("") ||
        '<p class="muted">还没有起过卦。</p>'}</div>
    <p class="small muted">卦是一面镜子，不是预言；势是风向，不是命令。它们只会让建议轻一点或重一点，从不改变事实。影响程度可在 rules.toml 的 [yi] weight 调整。</p>`;
  const cb = $("#cast-day");
  if (cb) cb.onclick = async () => { const r = await api("/api/yi/today", {}); await revealCast($("#day-cast"), r); };
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
async function retireTrend(id) { await api(`/api/trends/${id}/retire`, {}); render("tianshi"); }
async function castOutcome(id) {
  const o = prompt("后来怎样了？（这是写给自己的）");
  if (o) { await api("/api/yi/outcome", { id, outcome: o }); render("tianshi"); }
}

// ------------------------------------------------------------------ 框架
const RENDER = { now: renderNow, pocket: renderPocket, her: renderHer, tianshi: renderTianshi, memory: renderMemory, gear: renderGear, letter: renderLetter, more: renderMore,
  today: renderToday, graph: renderGraph, review: renderReview, system: renderSystem };
const TAB_OF = { today: "more", graph: "more", review: "more", system: "more" };
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
  $("#llm").textContent = META.llm ? "Claude" : "规则引擎";
  render(location.hash.slice(1) in RENDER ? location.hash.slice(1) : "now");
})();
