/* 应收与回款：账龄结构、逾期清单、催收派单 */
import { api } from "../api.js";
import { S, esc, money, pct, nf, table, toast, blankState } from "../core.js";
import { agingBar, donut, C } from "../charts.js";

export const AR = { page: 1, size: 12, minDays: 0 };

export async function load() {
  const end = S.period;
  const [aging, overdue, collection] = await Promise.all([
    api.get(`/ar/aging?period=${end}`),
    api.get(`/ar/overdue?period=${end}&page=${AR.page}&size=${AR.size}&min_days=${AR.minDays}`),
    api.get(`/ar/collection?period=${end}`).catch(() => ({ byMonth: [], methods: [] })),
  ]);
  return { aging, overdue, collection };
}

export function render(d) {
  const a = d.aging, o = d.overdue;
  const bucketColor = { "未到期": "#9BD9C7", "0-30 天": "#F5C26B", "31-60 天": "#E9963F", "61-90 天": "#E4663C", "90+ 天": C.red };
  const pages = Math.max(1, Math.ceil(o.total / AR.size));
  return `
  <div class="grid g-kpi" style="grid-template-columns:repeat(4,1fr)">
    <div class="kpi"><div class="kpi-label">期末应收余额</div>
      <div class="kpi-val num">${money(a.total)}</div>
      <div class="kpi-foot muted">账龄桶合计口径</div></div>
    <div class="kpi"><div class="kpi-label">逾期应收</div>
      <div class="kpi-val num" style="color:${C.red}">${money(a.overdueTotal)}</div>
      <div class="kpi-foot muted">占应收 ${pct(a.overdueTotal / (a.total || 1) * 100)}</div></div>
    <div class="kpi"><div class="kpi-label">90 天以上</div>
      <div class="kpi-val num">${money(a.over90)}</div>
      <div class="kpi-foot muted">建议重点催收</div></div>
    <div class="kpi"><div class="kpi-label">当月回款率</div>
      <div class="kpi-val num">${pct(a.collectionRate)}</div>
      <div class="kpi-foot muted">开票 ${money(a.billing)} · 回款 ${money(a.collection)}</div></div>
  </div>

  <div class="card">
    <div class="card-hd"><div class="card-title">账龄结构</div>
      <div class="card-sub">${esc(a.period)}</div>
      <div class="card-tools"><span class="scope-chip">${esc(a.scope)}</span></div></div>
    <div class="card-bd">
      ${agingBar(a.buckets)}
      <div class="grid g-2" style="margin-top:14px;gap:14px">
        <div>
          ${a.buckets.map(b => `<div class="legend" style="margin:8px 0">
            <span class="dot" style="background:${bucketColor[b.bucket] || C.ink3}"></span>
            <span class="cname" style="width:78px">${esc(b.bucket)}</span>
            <span class="num" style="width:72px;text-align:right">${nf(b.invoices)} 张</span>
            <span class="num" style="margin-left:auto">${money(b.balance)}</span>
            <span class="num muted" style="width:52px;text-align:right">${pct(b.ratio)}</span>
          </div>`).join("")}
          <div class="notice" style="margin-top:10px">${esc(a.note)}</div>
        </div>
        <div>
          ${donut(a.buckets.map(b => ({ name: b.bucket, value: b.balance, color: bucketColor[b.bucket] })),
            { size: 168, thick: 24, center: money(a.total), centerSub: "应收余额" })}
          <div class="small muted" style="margin-top:6px">按大区分布</div>
          ${a.regions.map(r => `<div class="legend" style="margin:5px 0">
            <span class="cname">${esc(r.region)}</span>
            <span class="num" style="margin-left:auto">${money(r.balance)}</span>
            <span class="num" style="width:70px;text-align:right;color:${C.red}">90+ ${money(r.over90)}</span>
          </div>`).join("")}
        </div>
      </div>
    </div>
  </div>

  <div class="card" style="margin-top:12px">
    <div class="card-hd"><div class="card-title">逾期发票清单</div>
      <div class="card-sub">共 ${o.total} 张 · 未收合计 ${money(o.unpaidTotal)}</div>
      <div class="card-tools">
        <select class="f-select" data-min-days>
          <option value="0" ${AR.minDays === 0 ? "selected" : ""}>全部逾期</option>
          <option value="30" ${AR.minDays === 30 ? "selected" : ""}>逾期 30 天以上</option>
          <option value="90" ${AR.minDays === 90 ? "selected" : ""}>逾期 90 天以上</option>
        </select>
        <button class="ghost-btn" data-batch>批量派单</button>
      </div></div>
    <div class="card-bd flush">
      ${o.rows.length ? `<div class="tbl-wrap"><table class="tbl">
        <thead><tr><th style="width:30px"><input type="checkbox" data-check-all></th>
          <th>客户</th><th>类型</th><th>开票日</th><th>应收日</th>
          <th class="num">开票金额</th><th class="num">未收</th><th class="num">逾期天数</th><th>状态</th></tr></thead>
        <tbody>${o.rows.map(r => `<tr>
          <td><input type="checkbox" data-inv="${esc(r.invoice_id)}"></td>
          <td>${esc(r.customer)}</td><td class="muted">${esc(r.type)}</td>
          <td>${esc(r.invoice_date)}</td><td>${esc(r.due_date)}</td>
          <td class="num">${money(r.amount)}</td>
          <td class="num">${money(r.unpaid)}</td>
          <td class="num">${r.overdue_days > 90 ? `<span class="tag r">${r.overdue_days}</span>` : r.overdue_days}</td>
          <td class="muted">${esc(r.status)}</td></tr>`).join("")}</tbody></table></div>`
        : blankState("没有逾期发票", "当前筛选条件下所有发票均已收回或未到期")}
      <div class="hstack" style="padding:10px 14px;border-top:1px solid var(--line2)">
        <span class="card-sub">第 ${o.page} / ${pages} 页</span>
        <div style="margin-left:auto;display:flex;gap:6px">
          <button class="ghost-btn" data-page="prev" ${o.page <= 1 ? "disabled" : ""}>上一页</button>
          <button class="ghost-btn" data-page="next" ${o.page >= pages ? "disabled" : ""}>下一页</button>
        </div>
      </div>
    </div>
  </div>`;
}

export async function mount() {
  document.querySelector("[data-min-days]")?.addEventListener("change", async (e) => {
    AR.minDays = Number(e.target.value); AR.page = 1;
    await window.__reloadPage();
  });
  document.querySelectorAll("[data-page]").forEach(b => b.addEventListener("click", async () => {
    AR.page += b.dataset.page === "next" ? 1 : -1;
    await window.__reloadPage();
  }));
  document.querySelector("[data-check-all]")?.addEventListener("change", (e) => {
    document.querySelectorAll("[data-inv]").forEach(c => { c.checked = e.target.checked; });
  });
  document.querySelector("[data-batch]")?.addEventListener("click", async () => {
    const ids = [...document.querySelectorAll("[data-inv]:checked")].map(c => c.dataset.inv);
    if (!ids.length) return toast("请先勾选发票", "warn");
    try {
      const r = await api.post("/ar/collection-task", { invoiceIds: ids, note: "列表批量派单" });
      toast(`已生成 ${r.created} 条催收任务`, "ok");
    } catch (e) { toast(e.message, "error"); }
  });
}
