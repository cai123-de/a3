/* 语义模型：指标字典、sem 语义视图、口径版本沿革、下钻映射、长表取数预览 */
import { api } from "../api.js";
import { esc, nf, table, modal, toast } from "../core.js";
import { sparkline } from "../charts.js";

const LAYER_TAG = { "关系层": "a", "字典层": "g", "指标层": "n" };
let METRICS = [];

export async function load() {
  const [metrics, semViews, drills] = await Promise.all([
    api.get("/semantic/metrics"),
    api.get("/semantic/views"),
    api.get("/semantic/drills"),
  ]);
  return { metrics, semViews, drills };
}

export function render(d) {
  METRICS = d.metrics;
  return `
  <div class="grid g-4">
    ${d.semViews.map(v => `
      <div class="card">
        <div class="card-hd"><div class="card-title" style="font-size:13px">${esc(v.name)}</div>
          <div class="card-tools"><span class="tag ${LAYER_TAG[v.layer] || "n"}">${esc(v.layer)}</span></div></div>
        <div class="card-bd" style="padding:10px 14px 14px">
          <div class="small" style="line-height:1.55">${esc(v.desc)}</div>
          <div class="small muted" style="margin-top:8px">行数：<b class="num">${v.rows === null ? "—" : nf(v.rows)}</b></div>
        </div>
      </div>`).join("")}
  </div>

  <div class="card" style="margin-top:12px">
    <div class="card-hd"><div class="card-title">指标字典</div>
      <div class="card-sub">${d.metrics.length} 个指标 · 点击查看口径版本与下钻</div>
      <div class="card-tools">
        <input class="f-input" id="semSearch" placeholder="搜索编码 / 名称 / 别名…" style="width:200px;height:28px;font-size:12px">
      </div></div>
    <div class="card-bd flush"><div id="semTbl">${metricTable(d.metrics)}</div></div>
  </div>

  <div class="card" style="margin-top:12px">
    <div class="card-hd"><div class="card-title">下钻映射</div>
      <div class="card-sub">${d.drills.length} 条路径 · parent_path 树，AI 问答与前端下钻共用</div></div>
    <div class="card-bd flush">${table(
      ["父路径", "维度", "标签", "来源视图", "分组字段", "金额表达式"],
      d.drills.map(x => `<tr>
        <td><code>${esc(x.parent_path)}</code></td>
        <td><span class="tag n">${esc(x.dim)}</span></td>
        <td>${esc(x.label)}</td>
        <td class="muted">${esc(x.view_name || "—")}</td>
        <td class="muted small">${esc(x.group_cols || "—")}</td>
        <td class="small muted"><code>${esc(x.amount_expr || "—")}</code></td></tr>`))}</div>
  </div>`;
}

function metricTable(rows) {
  if (!rows.length) return `<div class="blank">无匹配指标</div>`;
  return table(
    ["编码", "名称", "单位", "口径版本", "生效起", "来源视图", "责任人", "状态"],
    rows.map(m => `<tr data-metric="${esc(m.code)}" style="cursor:pointer">
      <td><code>${esc(m.code)}</code></td>
      <td><b>${esc(m.name)}</b><div class="small muted">${esc(m.aliases || "")}</div></td>
      <td>${esc(m.unit)}</td>
      <td><span class="tag ${m.caliber_version >= "v1.3" ? "g" : "n"}">${esc(m.caliber_version || "v1.0")}</span></td>
      <td class="muted">${esc(m.caliber_effective_from || "—")}</td>
      <td class="muted small">${esc(m.source_view || "—")}</td>
      <td class="muted">${esc(m.owner || "—")}</td>
      <td><span class="tag ${m.is_active ? "g" : "r"}">${m.is_active ? "在用" : "停用"}</span></td></tr>`));
}

export function mount() {
  const all = METRICS;
  document.getElementById("semSearch")?.addEventListener("input", (e) => {
    const q = e.target.value.trim().toLowerCase();
    const rows = all.filter(m => !q ||
      [m.code, m.name, m.aliases, m.source_view].some(x => (x || "").toLowerCase().includes(q)));
    document.getElementById("semTbl").innerHTML = metricTable(rows);
    bindRows();
  });
  bindRows();
}

function bindRows() {
  document.querySelectorAll("[data-metric]").forEach(tr =>
    tr.addEventListener("click", () => showDetail(tr.dataset.metric)));
}

async function showDetail(code) {
  let m;
  try { m = await api.get(`/semantic/metrics/${encodeURIComponent(code)}`); }
  catch (e) { toast(e.message, "error"); return; }
  modal(`指标详情 · ${esc(m.name)}`, `
    <div class="kv"><span>编码</span><div><code>${esc(m.code)}</code>　${(m.aliases || "").split(/[、,，]/).filter(Boolean).map(a => `<span class="tag n">${esc(a)}</span>`).join(" ")}</div></div>
    <div class="kv"><span>口径定义</span><div style="line-height:1.6">${esc(m.definition)}</div></div>
    <div class="kv"><span>取数表达式</span><div><code class="small">${esc(m.expr || "—")}</code></div></div>
    <div class="kv"><span>来源视图 / 默认维度</span><div>${esc(m.source_view || "—")} · ${esc(m.default_dim || "—")} · 单位 ${esc(m.unit)} · 责任人 ${esc(m.owner || "—")}</div></div>
    <div class="kv"><span>当前版本</span><div><span class="tag g">${esc(m.caliber_version)}</span> ${m.is_active ? `<span class="tag g">在用</span>` : `<span class="tag r">停用</span>`}</div></div>

    <div class="card-title" style="margin:14px 0 6px">版本沿革</div>
    ${(m.versions || []).map((v, i) => `
      <div class="qp-row" style="align-items:flex-start">
        <span class="qp-dot ${i === 0 ? "" : "warn"}"></span>
        <div><div class="qp-k"><span class="tag ${i === 0 ? "g" : "n"}">${esc(v.version)}</span>
          ${esc(v.effective_from || "—")} ~ ${esc(v.effective_to || "至今")}　${esc(v.approved_by || "")} 审批</div>
        <div class="qp-v">${esc(v.definition)}</div>
        <div class="qp-n">变更原因：${esc(v.change_reason || "—")}</div></div>
      </div>`).join("")}

    <div class="card-title" style="margin:14px 0 6px">下钻路径（${(m.drills || []).length}）</div>
    ${(m.drills || []).map(x => `
      <div class="kv"><span>${esc(x.dim)}</span>
        <div>${esc(x.label)} <span class="muted small">· ${esc(x.view_name || "")} · 按 ${esc(x.group_cols || "")} 分组</span></div></div>`).join("") || `<div class="blank">无下钻</div>`}

    <div class="card-title" style="margin:14px 0 6px">取数预览 <span class="muted small">（sem_metric_long 统一取数模板）</span></div>
    <div id="valBox"><button class="ghost-btn" id="loadVals">加载近 12 期序列</button></div>`,
    { wide: true, footer: `<button class="ghost-btn" onclick="closeModal()">关闭</button>` });

  document.getElementById("loadVals")?.addEventListener("click", async (e) => {
    e.target.disabled = true; e.target.textContent = "加载中…";
    try {
      const v = await api.get(`/semantic/values?code=${encodeURIComponent(code)}`);
      const vals = v.rows.map(r => r.value);
      const unit = v.rows[0]?.unit || "";
      document.getElementById("valBox").innerHTML = `
        <div style="margin:4px 0 8px">${sparkline(vals, { w: 860, h: 56 })}</div>
        ${table(["期间", "指标", "数值", "单位"],
          v.rows.map(r => `<tr><td>${esc(r.period)}</td><td>${esc(r.metric_name)}</td>
            <td class="num">${nf(r.value, 2)}</td><td class="muted">${esc(unit)}</td></tr>`))}`;
    } catch (err) { toast(err.message, "error"); }
  });
}
