/* 数据管理：数据资产盘点、表关系地图、期间管理 */
import { api } from "../api.js";
import { esc, nf, table } from "../core.js";

let ASSETS = [];

export async function load() {
  const [assets, relations, periods] = await Promise.all([
    api.get("/dataops/assets"),
    api.get("/dataops/relations"),
    api.get("/dataops/periods"),
  ]);
  return { assets, relations, periods };
}

export function render(d) {
  ASSETS = d.assets.tables.concat(d.assets.views);
  const s = d.assets.summary;
  const open = d.periods.rows.filter(p => p.status === "open").length;
  return `
  <div class="grid g-4">
    <div class="card"><div class="card-bd" style="padding:14px">
      <div class="kpi-label">数据表</div><div class="kpi-val num">${nf(s.tables)} <span class="small muted" style="font-size:12px">张</span></div>
      <div class="small muted" style="margin-top:6px">明细表 + 维表，勾稽基座</div></div></div>
    <div class="card"><div class="card-bd" style="padding:14px">
      <div class="kpi-label">分析视图</div><div class="kpi-val num">${nf(s.views)} <span class="small muted" style="font-size:12px">个</span></div>
      <div class="small muted" style="margin-top:6px">V_ 指标视图 + sem_ 语义视图</div></div></div>
    <div class="card"><div class="card-bd" style="padding:14px">
      <div class="kpi-label">总行数（表）</div><div class="kpi-val num">${nf(s.rows_total)}</div>
      <div class="small muted" style="margin-top:6px">pg_class 精确 count，非估算</div></div></div>
    <div class="card"><div class="card-bd" style="padding:14px">
      <div class="kpi-label">期间状态</div><div class="kpi-val num">${nf(d.periods.rows.length)} 期 · ${open} 期开放</div>
      <div class="small muted" style="margin-top:6px">最新期间 ${esc(d.periods.latest || "—")}</div></div></div>
  </div>

  <div class="card" style="margin-top:12px">
    <div class="card-hd"><div class="card-title">数据资产</div>
      <div class="card-sub" id="assetCount"></div>
      <div class="card-tools" style="display:flex;gap:8px;align-items:center">
        <div id="assetTabs" style="display:flex;gap:6px">
          <button class="ghost-btn asset-tab" data-f="all" style="height:26px;font-size:11px">全部</button>
          <button class="ghost-btn asset-tab" data-f="table" style="height:26px;font-size:11px">表</button>
          <button class="ghost-btn asset-tab" data-f="view" style="height:26px;font-size:11px">视图</button>
        </div>
        <input class="f-input" id="assetSearch" placeholder="搜索表名 / 注释…" style="width:180px;height:26px;font-size:12px">
      </div></div>
    <div class="card-bd flush"><div id="assetTbl"></div></div>
  </div>

  <div class="grid" style="grid-template-columns:3fr 2fr;gap:12px;margin-top:12px">
    <div class="card">
      <div class="card-hd"><div class="card-title">表关系地图</div>
        <div class="card-sub">${d.relations.length} 条关系 · 来自 sem_relation</div></div>
      <div class="card-bd flush">${table(
        ["源表.字段", "方向", "目标表.字段", "基数", "说明"],
        d.relations.map(r => `<tr>
          <td><code class="small">${esc(r.from_table)}.${esc(r.from_col)}</code></td>
          <td class="muted">→</td>
          <td><code class="small">${esc(r.to_table)}.${esc(r.to_col)}</code></td>
          <td><span class="tag n">${esc(r.cardinality || "n:1")}</span></td>
          <td class="small muted">${esc(r.note || "—")}</td></tr>`))}</div>
    </div>
    <div class="card">
      <div class="card-hd"><div class="card-title">期间管理</div>
        <div class="card-sub">fin_period · 关账状态</div></div>
      <div class="card-bd flush" style="max-height:420px;overflow:auto">${table(
        ["期间", "状态", "关账时间", "操作人"],
        d.periods.rows.slice(0, 24).map(p => `<tr>
          <td><b>${esc(p.period)}</b></td>
          <td><span class="tag ${p.status === "closed" ? "g" : p.status === "open" ? "a" : "n"}">${
            p.status === "closed" ? "已关账" : p.status === "open" ? "开放中" : esc(p.status)}</span></td>
          <td class="muted small">${esc(p.closed_at || "—")}</td>
          <td class="muted small">${esc(p.closed_by || "—")}</td></tr>`),
        { empty: "无期间数据" })}</div>
    </div>
  </div>`;
}

export function mount() {
  const assets = ASSETS;
  let filter = "all";
  const paint = () => {
    const q = (document.getElementById("assetSearch")?.value || "").trim().toLowerCase();
    const rows = assets.filter(a =>
      (filter === "all" || a.kind === filter) &&
      (!q || [a.name, a.comment].some(x => (x || "").toLowerCase().includes(q))));
    document.getElementById("assetCount").textContent = `${rows.length} 项`;
    document.getElementById("assetTbl").innerHTML = rows.length ? table(
      ["名称", "类型", "行数", "注释"],
      rows.map(a => `<tr>
        <td><code>${esc(a.name)}</code></td>
        <td><span class="tag ${a.kind === "table" ? "n" : "a"}">${a.kind === "table" ? "表" : "视图"}</span></td>
        <td class="num">${a.rows === null ? "—" : nf(a.rows)}</td>
        <td class="small muted">${esc(a.comment || "—")}</td></tr>`)) : `<div class="blank">无匹配资产</div>`;
  };
  document.querySelectorAll(".asset-tab").forEach(b => b.addEventListener("click", () => {
    filter = b.dataset.f;
    document.querySelectorAll(".asset-tab").forEach(x =>
      x.style.background = x === b ? "var(--bg3, #1F2937)" : "");
    paint();
  }));
  document.getElementById("assetSearch")?.addEventListener("input", paint);
  paint();
}
