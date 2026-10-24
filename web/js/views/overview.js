/* 经营驾驶舱：KPI、四级利润表、下钻、趋势、结构 */
import { api } from "../api.js";
import {
  S, $, esc, money, pct, nf, deltaTag, kpiCard, table, modal, toast, wan,
} from "../core.js";
import { trendChart, waterfall, donut, hbars, agingBar, C } from "../charts.js";

const expanded = new Set(["revenue"]);

export async function load() {
  const p = S.period;
  const [kpi, statement, charts, alerts] = await Promise.all([
    api.get(`/overview/kpi?period=${p}`),
    api.get(`/overview/statement?period=${p}&level=4`),
    api.get(`/overview/charts?period=${p}&months=24`),
    api.get(`/overview/alerts?limit=3`),
  ]);
  return { kpi, statement, charts, alerts };
}

function flatten(nodes, depth = 0, out = []) {
  for (const n of nodes) {
    out.push({ ...n, depth });
    if (n.children?.length && expanded.has(n.key)) flatten(n.children, depth + 1, out);
  }
  return out;
}

function profitTable(data) {
  const rows = flatten(data.rows);
  const rev = data.summary.revenue || 1;
  return `<div class="pt-wrap">
    <table class="pt">
      <thead><tr><th style="width:44%">项目</th><th class="num">本期金额（万元）</th>
        <th class="num">占收入</th><th class="num">操作</th></tr></thead>
      <tbody>
      ${rows.map(n => {
        const kids = n.children?.length;
        const open = expanded.has(n.key);
        const strong = n.level <= 1 || n.key === "gross" || n.key === "op";
        return `<tr class="${n.level <= 1 ? "lv1" : "lv" + Math.min(n.level, 4)} ${strong ? "strong" : ""}"
            data-key="${n.key}">
          <td><span style="display:inline-block;width:${(n.depth) * 16}px"></span>
            ${kids ? `<span class="caret ${open ? "open" : ""}" data-toggle="${n.key}">▸</span>` : `<span style="display:inline-block;width:14px"></span>`}
            <span class="pt-name">${esc(n.label)}</span>
            ${n.note ? `<span class="card-sub" style="margin-left:6px">${esc(n.note)}</span>` : ""}
          </td>
          <td class="num">${n.value < 0 ? "−" : ""}${nf(Math.abs(n.value) / 1e4, 2)}</td>
          <td class="num muted">${pct(n.value / rev * 100)}</td>
          <td class="num">${n.drill ? `<span class="link" data-drill="${n.key}" data-path="${n.drill.path}" data-dim="${n.drill.dim}">下钻</span>` : ""}</td>
        </tr>`;
      }).join("")}
      </tbody>
    </table>
    <div class="small muted" style="padding:8px 14px 10px">
      子项合计 = 父项 ${data.checkPassed ? '<span class="tag g">已校验</span>' : '<span class="tag r">存在差异</span>'}
      · 口径：管理会计（订阅收入按服务期摊销；营业成本只含订阅 COGS，期间费用单列）
    </div>
  </div>`;
}

export function render(d) {
  const { kpi, statement, charts, alerts } = d;
  const expTotal = charts.expense.reduce((s, x) => s + x.value, 0);
  return `
  <div class="grid g-kpi">${kpi.cards.map(kpiCard).join("")}</div>

  <div class="grid g-main">
    <div class="card">
      <div class="card-hd">
        <div class="card-title">利润表（管理会计口径）</div>
        <div class="card-sub">点击 ▸ 逐级展开，最细可到单据</div>
        <div class="card-tools"><span class="tag ${statement.checkPassed ? "g" : "r"}">
          ${statement.checkPassed ? "勾稽通过" : "勾稽异常"}</span></div>
      </div>
      <div class="card-bd flush">${profitTable(statement)}</div>
    </div>

    <div class="card">
      <div class="card-hd"><div class="card-title">预警</div>
        <div class="card-tools"><span class="link" data-go="alerts">全部 ›</span></div></div>
      <div class="card-bd" style="padding:6px 14px 10px">
        ${alerts.length ? alerts.map(a => `
          <div class="alert-item">
            <span class="dot ${a.level === "high" ? "r" : a.level === "mid" ? "a" : "g"}"></span>
            <div><div class="alert-t">${esc(a.title)}</div>
              <div class="alert-m">${esc(a.detail || "")}</div></div>
            <div class="alert-v num">${a.amount ? money(a.amount) : ""}</div>
          </div>`).join("") : `<div class="blank">暂无未处理预警</div>`}
      </div>
    </div>
  </div>

  <div class="grid g-2">
    <div class="card">
      <div class="card-hd"><div class="card-title">收入与毛利率（近 24 个月）</div>
        <div class="card-sub">柱：营业收入；线：毛利率</div></div>
      <div class="card-bd">${trendChart(charts.trend)}</div>
    </div>
    <div class="card">
      <div class="card-hd"><div class="card-title">收入 → 利润</div><div class="card-sub">${S.period}</div></div>
      <div class="card-bd">${waterfall(charts.waterfall.map(w => ({ ...w })))}</div>
    </div>
  </div>

  <div class="grid g-3">
    <div class="card">
      <div class="card-hd"><div class="card-title">期间费用结构</div>
        <div class="card-tools"><span class="card-sub">合计 ${money(expTotal)}</span></div></div>
      <div class="card-bd" style="display:flex;gap:14px;align-items:center">
        ${donut(charts.expense.map(e => ({ value: e.value, name: e.name })), { center: wan(expTotal) })}
        <div style="flex:1">${charts.expense.map((e, i) => `
          <div class="legend"><span class="dot" style="background:${[C.brand, "#4FBFA0", C.blue, C.purple, C.amber][i % 5]}"></span>
            <span class="cname">${esc(e.name)}</span>
            <span class="num" style="margin-left:auto">${(e.value / expTotal * 100).toFixed(1)}%</span></div>`).join("")}
        </div>
      </div>
    </div>
    <div class="card">
      <div class="card-hd"><div class="card-title">应收账龄</div>
        <div class="card-tools"><span class="link" data-go="ar">明细 ›</span></div></div>
      <div class="card-bd">
        ${agingBar(charts.aging.map(a => ({ bucket: a.bucket, balance: a.amount })))}
        <div style="margin-top:10px">${charts.aging.map(a => `
          <div class="legend"><span class="dot" style="background:${{ "未到期": "#9BD9C7", "0-30 天": "#F5C26B", "31-60 天": "#E9963F", "61-90 天": "#E4663C", "90+ 天": C.red }[a.bucket]}"></span>
            <span class="cname">${esc(a.bucket)}</span>
            <span class="num" style="margin-left:auto">${money(a.amount)}</span></div>`).join("")}</div>
      </div>
    </div>
    <div class="card">
      <div class="card-hd"><div class="card-title">大区收入</div><div class="card-sub">订阅 + 服务</div></div>
      <div class="card-bd">${hbars(charts.regions.map(r => ({ name: r.name, value: r.total })))}</div>
    </div>
  </div>

  <div class="card" style="margin-top:12px">
    <div class="card-hd"><div class="card-title">产品线收入与毛利</div>
      <div class="card-sub">按订阅收入排序</div>
      <div class="card-tools"><span class="card-sub">ARR ${money(charts.arr.arr)} · 在服客户 ${nf(charts.arr.customers)} · 合同 ${nf(charts.arr.contracts)}</span></div></div>
    <div class="card-bd flush">${table(
      ["产品", "产品线", "订阅收入", "毛利", "毛利率", "占比"],
      charts.products.map(p => `<tr>
        <td>${esc(p.name)}</td><td class="muted">${esc(p.line)}</td>
        <td class="num">${money(p.revenue)}</td><td class="num">${money(p.gross)}</td>
        <td class="num">${p.margin < 60 ? `<span class="tag r">${pct(p.margin)}</span>` : pct(p.margin)}</td>
        <td class="num muted">${pct(p.revenue / (charts.products.reduce((s, x) => s + x.revenue, 0) || 1) * 100)}</td>
      </tr>`))}</div>
  </div>`;
}

/* ---------- 事件 ---------- */
export function mount() {
  document.querySelectorAll("[data-toggle]").forEach(el => el.addEventListener("click", () => {
    const k = el.dataset.toggle;
    expanded.has(k) ? expanded.delete(k) : expanded.add(k);
    const d = S.datasets.overview;
    $("view").innerHTML = render(d);
    mount();
  }));

  document.querySelectorAll("[data-info]").forEach(el => el.addEventListener("click", () => {
    const c = S.datasets.overview.kpi.cards.find(x => x.key === el.dataset.info);
    modal(esc(c.name), `<div class="kv"><span>指标口径</span><div>${esc(c.definition || "—")}</div></div>
      <div class="kv"><span>口径版本</span><div>${esc(c.metricVersion)}</div></div>
      <div class="kv"><span>取数视图</span><div>由指标字典 meta_metric 映射，禁止前端硬编码</div></div>
      <div class="kv"><span>本期值</span><div class="num">${c.unit === "%" ? pct(c.value) : money(c.value)}</div></div>`);
  }));

  document.querySelectorAll("[data-drill]").forEach(el => el.addEventListener("click", () => {
    openDrill(el.dataset.path, el.dataset.dim);
  }));
}

async function openDrill(path, dim) {
  try {
    const r = await api.get(`/overview/drill?path=${encodeURIComponent(path)}&dim=${dim}&period=${S.period}&size=50`);
    const dims = (r.dims || []).map(x => `<option value="${x.dim}" ${x.dim === dim ? "selected" : ""}>${x.label}</option>`).join("");
    modal(`下钻 · ${esc(r.node.label)}`, `
      <div class="hstack" style="margin-bottom:10px">
        <span class="card-sub">维度</span>
        <select class="f-select" onchange="window.__drill('${esc(path)}', this.value)">${dims}</select>
        <span class="card-sub" style="margin-left:auto">范围：${esc(r.scope)} · 共 ${r.total} 项</span>
      </div>
      ${r.folded ? `<div class="notice">${esc(r.folded.hint)}（合计 ${money(r.folded.amount)}）</div>` : ""}
      ${table(r.columns, r.rows.map(row => `<tr>${r.columns.map(c => {
        const v = row[c];
        return `<td class="${typeof v === "number" ? "num" : ""}">${typeof v === "number" ? nf(v, 2) : esc(v ?? "")}</td>`;
      }).join("")}</tr>`))}
      <div class="small muted" style="margin-top:10px;line-height:1.8">
        子项合计 ${money(r.subtotal)} · 父项 ${money(r.parentTotal)}
        ${r.checkPassed ? '<span class="tag g">勾稽通过</span>' : '<span class="tag r">存在差异</span>'}
        <br>数据源：${esc(r.node.view)}
      </div>`, { wide: true });
  } catch (err) { toast(err.message, "error"); }
}

window.__drill = openDrill;
