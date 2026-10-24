/* 预警中心：规则、预警闭环 */
import { api } from "../api.js";
import { esc, money, nf, table, toast, S } from "../core.js";
import { C } from "../charts.js";

export const A = { status: "", level: "" };

export async function load() {
  const qs = new URLSearchParams();
  if (A.status) qs.set("status", A.status);
  if (A.level) qs.set("level", A.level);
  const [list, rules] = await Promise.all([
    api.get(`/alerts${qs.toString() ? "?" + qs : ""}`),
    api.get("/alerts/rules"),
  ]);
  return { list, rules };
}

export function render(d) {
  const { rows, stats } = d.list;
  return `
  <div class="grid g-kpi" style="grid-template-columns:repeat(4,1fr)">
    <div class="kpi"><div class="kpi-label">待处理</div><div class="kpi-val num">${nf(stats.open)}</div>
      <div class="kpi-foot muted">open</div></div>
    <div class="kpi"><div class="kpi-label">处理中</div><div class="kpi-val num">${nf(stats.ack)}</div>
      <div class="kpi-foot muted">已确认未关闭</div></div>
    <div class="kpi"><div class="kpi-label">高优先级</div>
      <div class="kpi-val num" style="color:${C.red}">${nf(stats.high)}</div>
      <div class="kpi-foot muted">未关闭的 high</div></div>
    <div class="kpi"><div class="kpi-label">已关闭</div><div class="kpi-val num">${nf(stats.closed)}</div>
      <div class="kpi-foot muted">含历史</div></div>
  </div>

  <div class="hstack" style="margin-bottom:10px">
    <div class="seg">
      ${[["", "全部"], ["open", "待处理"], ["ack", "处理中"], ["closed", "已关闭"]]
        .map(([k, n]) => `<button data-status="${k}" class="${A.status === k ? "on" : ""}">${n}</button>`).join("")}
    </div>
    <div class="seg">
      ${[["", "全部级别"], ["high", "高"], ["mid", "中"], ["low", "低"]]
        .map(([k, n]) => `<button data-level="${k}" class="${A.level === k ? "on" : ""}">${n}</button>`).join("")}
    </div>
    <span class="card-sub" style="margin-left:auto">共 ${rows.length} 条</span>
  </div>

  <div class="card"><div class="card-bd" style="padding:4px 14px">
    ${rows.length ? rows.map(a => `
      <div class="alert-row">
        <span class="dot ${a.level === "high" ? "r" : a.level === "mid" ? "a" : "g"}"></span>
        <div style="flex:1;min-width:0">
          <div class="alert-t">${esc(a.title)}</div>
          <div class="alert-m">${esc(a.detail || "")}</div>
          <div class="small muted">${esc(a.rule_code)} · ${esc(a.period || "")} · ${esc(a.owner || "未指派")}
            · ${esc(a.created_at)}</div>
        </div>
        <div style="text-align:right;min-width:100px">
          <div class="num" style="font-weight:600">${a.amount ? money(a.amount) : "—"}</div>
          <span class="tag ${a.status === "open" ? "a" : a.status === "ack" ? "b" : "n"}">
            ${a.status === "open" ? "待处理" : a.status === "ack" ? "处理中" : "已关闭"}</span>
        </div>
        <div style="display:flex;gap:4px;margin-left:8px">
          ${a.status === "open" ? `<button class="ghost-btn" style="height:24px;font-size:11px" data-ack="${a.id}">确认</button>` : ""}
          ${a.status !== "closed" ? `<button class="primary-btn" style="height:24px;font-size:11px" data-close="${a.id}">关闭</button>` : ""}
        </div>
      </div>`).join("") : `<div class="blank" style="padding:40px">当前筛选下没有预警</div>`}
  </div></div>

  <div class="card" style="margin-top:12px">
    <div class="card-hd"><div class="card-title">预警规则</div>
      <div class="card-sub">阈值可在配置中心调整，改动需审批</div></div>
    <div class="card-bd flush">${table(["规则", "类别", "口径", "级别", "通知渠道", "负责人", "状态"],
      d.rules.map(r => `<tr>
        <td>${esc(r.name)}<div class="small muted">${esc(r.code)}</div></td>
        <td class="muted">${esc(r.category)}</td><td>${esc(r.expr)}</td>
        <td><span class="tag ${r.level === "high" ? "r" : r.level === "mid" ? "a" : "n"}">
          ${r.level === "high" ? "高" : r.level === "mid" ? "中" : "低"}</span></td>
        <td class="muted">${esc(r.channel)}</td><td class="muted">${esc(r.owner_role || "—")}</td>
        <td><span class="tag ${r.enabled ? "g" : "n"}">${r.enabled ? "启用" : "停用"}</span></td></tr>`))}</div>
  </div>`;
}

export function mount() {
  document.querySelectorAll("[data-status]").forEach(b => b.addEventListener("click", async () => {
    A.status = b.dataset.status; await window.__reloadPage();
  }));
  document.querySelectorAll("[data-level]").forEach(b => b.addEventListener("click", async () => {
    A.level = b.dataset.level; await window.__reloadPage();
  }));
  const handle = async (id, action) => {
    try {
      await api.post(`/alerts/${id}/handle`, { action, note: `${S.user.name} 于 ${S.period} 处理` });
      toast(action === "close" ? "已关闭" : "已确认", "ok");
      await window.__reloadPage();
    } catch (e) { toast(e.message, "error"); }
  };
  document.querySelectorAll("[data-ack]").forEach(b => b.addEventListener("click", () => handle(b.dataset.ack, "ack")));
  document.querySelectorAll("[data-close]").forEach(b => b.addEventListener("click", () => handle(b.dataset.close, "close")));
}
