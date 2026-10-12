"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const base = location.pathname.replace(/\/?$/, "/");
  let token = sessionStorage.getItem("nekro-relations-token") || "";
  let report = null, selected = null, busy = false, requestGeneration = 0;
  const text = (tag, value, className) => { const el = document.createElement(tag); el.textContent = value; if (className) el.className = className; return el; };
  const status = (message, error = false) => { $("status").textContent = message; $("status").className = error ? "error" : ""; };
  const formatTime = ts => ts ? new Date(ts * 1000).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }) : "暂无记录";
  function setBusy(value) { busy = value; document.querySelectorAll("#workspace button,#workspace select").forEach(el => { el.disabled = value; }); }
  async function api(path, options = {}) {
    const response = await fetch(base + "api/" + path, { ...options, headers: { "Content-Type": "application/json", "Authorization": "Bearer " + token, ...(options.headers || {}) }, cache: "no-store" });
    if (!response.ok) {
      let data = {}; try { data = await response.json(); } catch (_) {}
      if (response.status === 401 || response.status === 403) showLogin();
      throw new Error(typeof data.detail === "string" ? data.detail : data.message || "请求失败（" + response.status + "）");
    }
    return response;
  }
  function showLogin() { $("login-panel").hidden = false; $("workspace").hidden = true; }
  function logout() { requestGeneration++; token = ""; report = null; selected = null; sessionStorage.removeItem("nekro-relations-token"); showLogin(); status(""); }
  $("logout").addEventListener("click", logout);
  $("login-form").addEventListener("submit", async event => {
    event.preventDefault(); const submit = event.submitter; submit.disabled = true; status("正在验证管理员身份…");
    try {
      const response = await fetch("/api/user/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: $("username").value, password: $("password").value }) });
      const data = await response.json();
      if (!response.ok || !data.access_token) throw new Error(data.message || data.detail || "登录失败，请检查后台账号和密码。");
      token = data.access_token; sessionStorage.setItem("nekro-relations-token", token); $("password").value = "";
      await boot();
    } catch (error) { status(error.message, true); } finally { submit.disabled = false; }
  });
  async function boot() {
    try {
      const { channels } = await (await api("channels")).json();
      $("channel").replaceChildren();
      channels.forEach(c => { const option = text("option", c.name + (c.enabled ? "" : " · 已暂停")); option.value = c.key; $("channel").append(option); });
      $("login-panel").hidden = true; $("workspace").hidden = false;
      if (!channels.length) { status("暂未发现白名单内的 QQ 群聊。请先让机器人接收群消息，并检查插件群白名单。"); return; }
      await load();
    } catch (error) { status(error.message, true); }
  }
  function params() { return { chat_key: $("channel").value, days: Number($("days").value), limit: Number($("limit").value) }; }
  async function load(refresh = false, ai = false) {
    if (busy || !$("channel").value) return;
    const generation = ++requestGeneration; setBusy(true); status(refresh ? "正在从 Nekro Agent 同步历史互动…" : ai ? "正在生成 AI 娱乐点评…" : "正在计算本群互动关系…");
    try {
      const data = await (await api("report", { method: "POST", body: JSON.stringify({ ...params(), refresh, ai }) })).json();
      if (generation !== requestGeneration) return;
      report = data; selected = null; render(); status("");
    } catch (error) { status(error.message, true); } finally { setBusy(false); }
  }
  ["channel", "days", "limit"].forEach(id => $(id).addEventListener("change", () => load()));
  $("refresh").addEventListener("click", () => load(true));
  $("ai").addEventListener("click", () => load(false, true));
  function render() {
    ["messages", "members", "interactions", "pairs"].forEach(key => { $("stat-" + key).textContent = report.meta[key].toLocaleString(); });
    $("graph").innerHTML = report.svg; // Only SVG generated and escaped by the authenticated server, never model/chat HTML.
    $("ranking").replaceChildren();
    report.edges.slice(0, 8).forEach((e, i) => {
      const row = text("div", "", "ranking-row"); row.tabIndex = 0; row.setAttribute("role", "button");
      const names = text("div", name(e.source) + " × " + name(e.target), "rank-names");
      names.append(text("small", `${e.events} 次互动 · ${e.days} 天 · ${e.label}`));
      const score = text("div", e.score, "rank-score"); score.append(text("small", "互动指数"));
      row.append(text("span", String(i + 1).padStart(2, "0"), "rank-number"), names, score);
      row.addEventListener("click", () => showEdge(e)); row.addEventListener("keydown", ev => { if (ev.key === "Enter") showEdge(e); }); $("ranking").append(row);
    });
    if (!report.edges.length) $("ranking").append(text("p", "还没有明确互动记录，先让群聊积累一点时间。", "muted"));
    $("notes").replaceChildren(...report.notes.map(n => text("p", n)));
    $("ai-comment").hidden = !report.ai_comment; $("ai-comment").textContent = report.ai_comment;
    $("warning").hidden = !report.warning; $("warning").textContent = report.warning;
    $("coverage").textContent = `记录覆盖：${formatTime(report.meta.first_message)} 至 ${formatTime(report.meta.last_message)} · 更新时间：${formatTime(report.generated_at)} · ${report.excluded_count} 人退出统计`;
    $("toggle").textContent = report.enabled ? "暂停采集" : "恢复采集";
    $("detail-title").textContent = "点亮一段连接"; $("detail").replaceChildren(text("p", "点击成员查看聊天搭子，点击连线查看互动方向和次数。", "muted"));
    initGraph();
  }
  const name = id => report.members.find(u => u.id === id)?.name || id;
  function metric(value, label) { const el = text("div", "", "detail-stat"); el.append(text("b", value), text("span", label)); return el; }
  function showNode(uid) {
    const member = report.members.find(u => u.id === uid); if (!member) return; selected = uid;
    $("graph").querySelectorAll(".node").forEach(el => el.classList.toggle("selected", el.dataset.id === uid));
    $("detail-title").textContent = member.name; const body = $("detail"); body.replaceChildren(text("p", member.role, "muted"));
    const grid = text("div", "", "detail-stats"); grid.append(metric(member.messages, "发言条数"), metric(member.active_days, "活跃天数"), metric(member.sent, "主动互动"), metric(member.received, "被互动")); body.append(grid, text("h3", "TA 的聊天搭子"));
    const edges = report.edges.filter(e => e.source === uid || e.target === uid).slice(0, 6);
    edges.forEach(e => { const row = text("div", "", "mini-pair"); row.append(text("b", name(e.source === uid ? e.target : e.source)), text("small", `${e.events} 次互动 · ${e.days} 天 · ${e.label}`)); row.addEventListener("click", () => showEdge(e)); body.append(row); });
    if (!edges.length) body.append(text("p", "没有明确互动记录。发言本身不会自动与其他成员连线。", "muted"));
  }
  function showEdge(e) {
    $("detail-title").textContent = name(e.source) + " × " + name(e.target); const body = $("detail"); body.replaceChildren(text("p", e.label, "muted"));
    const grid = text("div", "", "detail-stats"); grid.append(metric(e.events, "明确互动"), metric(e.days, "互动天数"), metric(e.mentions, "@ 互动"), metric(e.replies, "引用回复"));
    body.append(grid, text("p", `${name(e.source)} → ${name(e.target)}：${e.ab} 次`), text("p", `${name(e.target)} → ${name(e.source)}：${e.ba} 次`), text("p", `上一周期 ${e.previous_events} 次，本期变化 ${e.change >= 0 ? "+" : ""}${e.change} 次。记录覆盖不同时，不能直接理解为关系变化。`, "muted"), text("p", "同一条消息对同一人的 @ 与引用只计一次；互动指数对每日重复计分设有上限，并考虑双向程度与发言量。", "fine muted"));
  }
  let resetGraph = () => {};
  function initGraph() {
    const svg = $("graph").querySelector("svg"), content = svg.querySelector("#graph-content"); let zoom = 1, tx = 0, ty = 0, drag = null;
    const point = event => { const p = svg.createSVGPoint(); p.x = event.clientX; p.y = event.clientY; return p.matrixTransform(svg.getScreenCTM().inverse()); };
    const update = () => content.setAttribute("transform", `translate(${tx},${ty}) scale(${zoom})`);
    resetGraph = () => { zoom = 1; tx = ty = 0; update(); };
    svg.addEventListener("wheel", event => { event.preventDefault(); const p = point(event), next = Math.min(3, Math.max(.5, zoom * (event.deltaY < 0 ? 1.12 : .89))); tx = p.x - (p.x - tx) * next / zoom; ty = p.y - (p.y - ty) * next / zoom; zoom = next; update(); }, { passive: false });
    svg.addEventListener("pointerdown", event => { if (event.button !== 0) return; const node = event.target.closest(".node"), p = point(event); drag = { node, x: p.x, y: p.y, tx, ty, moved: false }; svg.setPointerCapture(event.pointerId); });
    svg.addEventListener("pointermove", event => {
      if (!drag) return; const p = point(event); if (Math.hypot(p.x - drag.x, p.y - drag.y) > 3) drag.moved = true;
      if (drag.node && drag.moved) { const x = (p.x - tx) / zoom, y = (p.y - ty) / zoom, uid = drag.node.dataset.id; drag.node.setAttribute("transform", `translate(${x},${y})`); svg.querySelectorAll(".edge").forEach(line => { if (line.dataset.source === uid) { line.setAttribute("x1", x); line.setAttribute("y1", y); } if (line.dataset.target === uid) { line.setAttribute("x2", x); line.setAttribute("y2", y); } }); }
      else if (!drag.node && drag.moved) { tx = drag.tx + p.x - drag.x; ty = drag.ty + p.y - drag.y; update(); }
    });
    svg.addEventListener("pointerup", event => { if (!drag) return; if (!drag.moved) { if (drag.node) showNode(drag.node.dataset.id); else { const hit = document.elementFromPoint(event.clientX, event.clientY)?.closest(".edge"); if (hit) { const e = report.edges.find(e => e.source === hit.dataset.source && e.target === hit.dataset.target); if (e) showEdge(e); } } } drag = null; if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId); });
    svg.addEventListener("pointercancel", () => { drag = null; });
    svg.querySelectorAll(".node").forEach(node => node.addEventListener("keydown", event => { if (event.key === "Enter") showNode(node.dataset.id); }));
  }
  $("reset-view").addEventListener("click", () => { if (report) { $("graph").innerHTML = report.svg; initGraph(); } resetGraph(); });
  async function download(kind) {
    if (busy || !report) return; setBusy(true); status(kind === "image" ? "正在渲染高清 PNG，请稍候…" : "正在导出 SVG…");
    try { const response = await api(kind + "?" + new URLSearchParams(params())); const blob = await response.blob(), url = URL.createObjectURL(blob), a = document.createElement("a"); a.href = url; a.download = "group-relations." + (kind === "image" ? "png" : "svg"); a.click(); setTimeout(() => URL.revokeObjectURL(url), 10000); status(""); } catch (error) { status(error.message, true); } finally { setBusy(false); }
  }
  $("download").addEventListener("click", () => download("image")); $("download-svg").addEventListener("click", () => download("svg"));
  $("toggle").addEventListener("click", async () => { if (!report || busy) return; try { await api("toggle", { method: "POST", body: JSON.stringify({ chat_key: report.chat_key, enabled: !report.enabled }) }); await load(); } catch (error) { status(error.message, true); } });
  $("clear").addEventListener("click", async () => { if (!report || busy) return; const confirmation = prompt("将清空插件内本群的互动数据，并阻止旧历史重新导入。请输入：清空本群"); if (confirmation !== "清空本群") return; try { await api("clear", { method: "POST", body: JSON.stringify({ chat_key: report.chat_key, confirmation }) }); await load(); } catch (error) { status(error.message, true); } });
  if (token) boot(); else showLogin();
})();
