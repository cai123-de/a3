/* 应用内核：状态、格式化、通用组件 */
import { wan, yi, sparkline, C } from "./charts.js";

export const S = {
  user: null,
  menus: [],
  period: null,
  periods: [],
  page: "overview",
  personas: [],
  datasets: {},
};

export const $ = (id) => document.getElementById(id);
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ---------------- 数字格式 ---------------- */
export const nf = (v, d = 0) =>
  (v === null || v === undefined || isNaN(v)) ? "—"
    : Number(v).toLocaleString("zh-CN", { minimumFractionDigits: d, maximumFractionDigits: d });

export function money(v, { sign = false, unit = "元" } = {}) {
  if (v === null || v === undefined || isNaN(v)) return "—";
  const n = Number(v), abs = Math.abs(n);
  const s = sign && n > 0 ? "+" : n < 0 ? "−" : "";
  if (unit === "%") return `${s}${nf(abs, 2)}%`;
  if (abs >= 1e8) return `${s}${nf(abs / 1e8, 2)} 亿`;
  if (abs >= 1e4) return `${s}${nf(abs / 1e4, 0)} 万`;
  return `${s}${nf(abs, 0)}`;
}

export function pct(v, d = 1) {
  if (v === null || v === undefined || isNaN(v)) return "—";
  return `${Number(v).toFixed(d)}%`;
}

export function turnTag(c) {
  if (c.yoy === null && c.value > 0 && c.key === "op") return `<span class="tag g">扭亏</span>`;
  if (c.yoy === null && c.value < 0 && c.key === "op") return `<span class="tag r">转亏</span>`;
  return deltaTag(c.yoy);
}

export function deltaTag(v, { invert = false } = {}) {
  if (v === null || v === undefined || isNaN(v)) return `<span class="flat">—</span>`;
  const up = v > 0;
  const good = invert ? !up : up;
  const cls = Math.abs(v) < 0.05 ? "flat" : good ? "up" : "down";
  const arrow = up ? "▲" : v < 0 ? "▼" : "";
  return `<span class="${cls} num">${arrow}${Math.abs(v).toFixed(1)}%</span>`;
}

export function initials(name) { return (name || "?").slice(0, 1); }

/* ---------------- 图标 ---------------- */
const ICONS = {
  overview: '<path d="M3 13h4v8H3zM10 3h4v18h-4zM17 9h4v12h-4z"/>',
  customers: '<circle cx="9" cy="8" r="3.2"/><path d="M2.8 20a6.2 6.2 0 0 1 12.4 0"/><path d="M16 5.2a3 3 0 0 1 0 5.6M17.5 20a6 6 0 0 0-2.2-4.6"/>',
  ar: '<rect x="2.5" y="5" width="19" height="14" rx="2"/><path d="M2.5 10h19"/><path d="M6 15h3"/>',
  budget: '<path d="M4 19V5M4 19h16"/><rect x="7" y="11" width="3" height="5"/><rect x="12" y="7" width="3" height="9"/><rect x="17" y="13" width="3" height="3"/>',
  semantic: '<circle cx="5.5" cy="5.5" r="2.5"/><circle cx="18.5" cy="5.5" r="2.5"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/><circle cx="12" cy="12" r="2.8"/><path d="M7.4 7.4l2.4 2.4M16.6 7.4l-2.4 2.4M7.4 16.6l2.4-2.4M16.6 16.6l-2.4-2.4"/>',
  dataops: '<ellipse cx="12" cy="5.5" rx="7.5" ry="3"/><path d="M4.5 5.5v13c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3v-13"/><path d="M4.5 12c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3"/>',
  ai: '<path d="M12 2.5 14 8l5.5 2L14 12l-2 5.5L10 12 4.5 10 10 8z"/><path d="M18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
  reports: '<path d="M6 2.5h8l4 4V21H6z"/><path d="M14 2.5V7h4"/><path d="M9 12h6M9 16h6"/>',
  alerts: '<path d="M12 3a5.5 5.5 0 0 0-5.5 5.5c0 4-1.5 5.5-1.5 5.5h14s-1.5-1.5-1.5-5.5A5.5 5.5 0 0 0 12 3z"/><path d="M10 18a2 2 0 0 0 4 0"/>',
  admin: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 1 1-4 0v-.2A1.6 1.6 0 0 0 7 19.4a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.6 1.6 0 0 0 3 14.6H3a2 2 0 1 1 0-4h.2A1.6 1.6 0 0 0 4.6 9a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.6 1.6 0 0 0 9 4.6h.2A2 2 0 1 1 13 4.6V5a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1A1.6 1.6 0 0 0 19.4 11H21a2 2 0 1 1 0 4h-.2a1.6 1.6 0 0 0-1.4 1z"/>',
};

export function icon(id, size = 15) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICONS[id] || ""}</svg>`;
}

/* ---------------- 组件 ---------------- */
export function kpiCard(c) {
  const val = c.unit === "%" ? pct(c.value) : money(c.value);
  return `<div class="kpi" title="${esc(c.definition || "")}">
    <div class="kpi-label">${esc(c.name)}<span class="info" data-info="${esc(c.key)}">i</span></div>
    <div class="kpi-val num">${val}</div>
    <div class="kpi-foot">
      <span class="flat">环比</span> ${deltaTag(c.mom)}
      <span class="flat">同比</span> ${turnTag(c)}
    </div>
    <div class="kpi-spark">${sparkline(c.spark || [], { w: 150, h: 26 })}</div>
  </div>`;
}

export function skeleton() {
  return `<div class="skel">
    <div class="sk-bar" style="width:32%"></div>
    <div class="sk-grid"><div class="sk-card"></div><div class="sk-card"></div><div class="sk-card"></div><div class="sk-card"></div></div>
    <div class="sk-bar" style="width:18%;margin-top:18px"></div>
    <div class="sk-block"></div>
  </div>`;
}

export function blankState(title, desc, action = "") {
  return `<div class="empty" style="padding:56px 20px">
    <div class="st-ico" style="margin:0 auto 12px">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
        <rect x="3" y="4" width="18" height="17" rx="2"/><path d="M3 9h18M8 2v4M16 2v4"/></svg>
    </div>
    <div class="st-t">${esc(title)}</div>
    <div class="st-d">${desc}</div>
    ${action}
  </div>`;
}

export function errorState(err, retry = "location.reload()") {
  const denied = err.code === 40301 || err.code === 40302;
  return `<div class="empty" style="padding:52px 20px">
    <div class="st-ico" style="margin:0 auto 12px;${denied ? "background:#FEF3F2;color:#D92D20" : ""}">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
        <rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg>
    </div>
    <div class="st-t">${denied ? "无权查看该数据" : "加载失败"}</div>
    <div class="st-d">${esc(err.message || "未知错误")}${err.code ? `（错误码 ${err.code}）` : ""}</div>
    <div class="st-note">${denied
      ? "可访问范围由「角色 × 部门 × 职级」三者交集决定，不是黑箱。如需临时查看，请联系财务管理员申请，审批通过后 30 天内有效。本次访问已写入审计日志。"
      : "请稍后重试；若持续失败，请联系数据负责人并提供右侧 requestId。"}</div>
    <div class="st-btns"><button class="primary-btn" onclick="${retry}">重试</button></div>
  </div>`;
}

export function toast(msg, type = "info") {
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.classList.add("on"), 10);
  setTimeout(() => { el.classList.remove("on"); setTimeout(() => el.remove(), 220); }, 2600);
}

/* 弹层 */
export function modal(title, bodyHtml, { footer = "", wide = false } = {}) {
  let ov = $("modal");
  if (!ov) {
    ov = document.createElement("div");
    ov.id = "modal";
    ov.className = "overlay";
    document.body.appendChild(ov);
  }
  ov.innerHTML = `<div class="modal" style="${wide ? "max-width:940px" : ""}" role="dialog" aria-modal="true">
    <div class="modal-hd"><div class="card-title">${title}</div>
      <button class="close-x" onclick="closeModal()" aria-label="关闭">×</button></div>
    <div class="modal-bd">${bodyHtml}</div>
    ${footer ? `<div class="modal-ft">${footer}</div>` : ""}
  </div>`;
  ov.classList.add("on");
}

export function closeModal() {
  const ov = $("modal");
  if (ov) { ov.classList.remove("on"); ov.innerHTML = ""; }
}
window.closeModal = closeModal;

export function table(headers, rows, { empty = "暂无数据", cls = "" } = {}) {
  if (!rows || !rows.length) return `<div class="blank">${empty}</div>`;
  return `<div class="tbl-wrap"><table class="tbl ${cls}">
    <thead><tr>${headers.map(h => `<th>${h}</th>`).join("")}</tr></thead>
    <tbody>${rows.join("")}</tbody></table></div>`;
}

export function scopeChip(user) {
  const depth = { summary: "仅汇总", detail: "可看明细", doc: "可到单据" }[user.depth] || user.depth;
  return `<span class="scope-chip" title="角色决定能做什么，部门决定能看多宽，职级决定能看多深">
    ${esc(user.scopeLabel)} · ${esc(depth)}</span>`;
}

export { wan, yi, C };
