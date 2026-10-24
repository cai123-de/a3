/* 客户分析：分层、健康度、Top 客户、客户 360、续约日历 */
import { api } from "../api.js";
import { S, esc, money, pct, nf, table, modal, toast } from "../core.js";
import { donut, hbars, C } from "../charts.js";

export async function load() {
  const [summary, renewals] = await Promise.all([
    api.get("/customer/summary"),
    api.get(`/customer/renewal-calendar?months=6`).catch(() => ({ rows: [], totalArr: 0 })),
  ]);
  return { summary, renewals };
}

export function render(d) {
  const s = d.summary;
  const tierTotal = s.tiers.reduce((a, t) => a + t.arr, 0) || 1;
  const healthColors = { healthy: C.brand, watch: C.amber, risk: C.red };
  return `
  <div class="grid g-kpi" style="grid-template-columns:repeat(4,1fr)">
    <div class="kpi"><div class="kpi-label">在服客户</div>
      <div class="kpi-val num">${nf(s.tiers.reduce((a, t) => a + t.customers, 0))}</div>
      <div class="kpi-foot muted">范围：${esc(s.scope)}</div></div>
    <div class="kpi"><div class="kpi-label">客户 ARR</div>
      <div class="kpi-val num">${money(s.totalArr)}</div>
      <div class="kpi-foot muted">月末在服合同年化</div></div>
    <div class="kpi"><div class="kpi-label">Top10 集中度</div>
      <div class="kpi-val num">${pct(s.top.slice(0, 10).reduce((a, c) => a + (c["当前ARR"] || 0), 0) / (s.totalArr || 1) * 100)}</div>
      <div class="kpi-foot muted">前十大客户 ARR 占比</div></div>
    <div class="kpi"><div class="kpi-label">未来 6 个月待续约</div>
      <div class="kpi-val num">${money(d.renewals.totalArr || 0)}</div>
      <div class="kpi-foot muted">${nf(d.renewals.count || 0)} 份合同</div></div>
  </div>

  <div class="grid g-3">
    <div class="card"><div class="card-hd"><div class="card-title">客户分层</div></div>
      <div class="card-bd">${s.tiers.map(t => `
        <div class="legend" style="margin:7px 0">
          <span class="cname" style="width:64px">${esc(t.tier)}</span>
          <div class="hbar" style="flex:1"><i style="width:${(t.arr / tierTotal * 100).toFixed(1)}%;background:${C.brand}"></i></div>
          <span class="num" style="width:44px;text-align:right">${nf(t.customers)}</span>
          <span class="num muted" style="width:74px;text-align:right">${money(t.arr)}</span>
        </div>`).join("")}
        <div class="small muted" style="margin-top:8px">柱：ARR 占比；右侧依次为客户数、ARR</div>
      </div></div>

    <div class="card"><div class="card-hd"><div class="card-title">健康度分布</div>
      <div class="card-sub">${esc(S.period)}</div></div>
      <div class="card-bd" style="display:flex;gap:12px;align-items:center">
        ${s.health.length ? donut(s.health.map(h => ({ name: h.level, value: h.customers,
            color: healthColors[h.level] || C.ink3 })), { size: 150, thick: 22,
            center: nf(s.health.reduce((a, h) => a + h.customers, 0)), centerSub: "名客户" }) : `<div class="blank">暂无</div>`}
        <div style="flex:1">${s.health.map(h => `<div class="legend"><span class="dot"
          style="background:${healthColors[h.level] || C.ink3}"></span>
          <span class="cname">${esc(h.level)}</span>
          <span class="num" style="margin-left:auto">${nf(h.customers)}</span></div>`).join("")}</div>
      </div></div>

    <div class="card"><div class="card-hd"><div class="card-title">行业分布</div></div>
      <div class="card-bd">${hbars(s.industries.slice(0, 6).map(i => ({ name: i.name, value: i.arr })))}</div></div>
  </div>

  <div class="card" style="margin-top:12px">
    <div class="card-hd"><div class="card-title">重点客户</div>
      <div class="card-sub">按当前 ARR 排序，点击查看 360</div>
      <div class="card-tools">${s.folded ? `<span class="tag a">${s.folded.count} 笔大额已折叠</span>` : ""}</div></div>
    <div class="card-bd flush">${table(
      ["客户", "分层", "大区", "行业", "当前 ARR", "累计收入", "毛利率", "应收余额", "健康度", ""],
      s.top.map(c => `<tr data-customer="${esc(c["客户ID"])}" style="cursor:pointer">
        <td>${c.masked ? `<span class="lock">已脱敏</span>` : esc(c["客户名称"])}</td>
        <td><span class="tag n">${esc(c.tier)}</span></td>
        <td class="muted">${esc(c.region)}</td><td class="muted">${esc(c.industry)}</td>
        <td class="num">${money(c["当前ARR"])}</td><td class="num">${money(c["累计确认收入"])}</td>
        <td class="num">${pct(c.margin)}</td><td class="num">${money(c.ar)}</td>
        <td><span class="tag ${c.health === "healthy" ? "g" : c.health === "risk" ? "r" : "a"}">${esc(c.health || "—")}</span></td>
        <td class="link">360 ›</td></tr>`))}</div>
  </div>

  <div class="card" style="margin-top:12px">
    <div class="card-hd"><div class="card-title">续约日历（未来 6 个月）</div>
      <div class="card-tools"><span class="card-sub">合计 ${money(d.renewals.totalArr || 0)}</span></div></div>
    <div class="card-bd flush">${table(
      ["客户", "大区", "产品", "到期日", "MRR", "ARR"],
      (d.renewals.rows || []).slice(0, 12).map(r => `<tr>
        <td>${esc(r["客户名称"])}</td><td class="muted">${esc(r.region)}</td>
        <td class="muted">${esc(r["产品ID"])}</td><td>${esc(r.end_date)}</td>
        <td class="num">${nf(r.mrr)}</td><td class="num">${money(r.arr)}</td></tr>`),
      { empty: "未来 6 个月没有到期合同" })}</div>
  </div>`;
}

export function mount() {
  document.querySelectorAll("[data-customer]").forEach(el => el.addEventListener("click", async () => {
    try {
      const r = await api.get(`/customer/${el.dataset.customer}/360`);
      const c = r.customer;
      modal(esc(c["客户名称"]), `
        <div class="grid g-3" style="gap:10px;margin-bottom:12px">
          <div><div class="card-sub">当前 ARR</div><div class="num" style="font-size:17px;font-weight:600">${money(c["当前ARR"])}</div></div>
          <div><div class="card-sub">累计收入</div><div class="num" style="font-size:17px;font-weight:600">${money(c["累计确认收入"])}</div></div>
          <div><div class="card-sub">累计毛利率</div><div class="num" style="font-size:17px;font-weight:600">${pct(c["累计毛利率%"])}</div></div>
        </div>
        <div class="kv"><span>分层 / 大区</span><div>${esc(c["客户分层"])} · ${esc(c["所在大区"])}</div></div>
        <div class="kv"><span>行业 / 规模</span><div>${esc(c["行业"])} · ${esc(c["企业规模"])}</div></div>
        <div class="kv"><span>首次签约</span><div>${esc(c["首次签约日期"])}</div></div>
        <div class="kv"><span>最新应收</span><div class="num">${money(c["最新应收余额"])}</div></div>
        <div class="kv"><span>健康度</span><div>${esc(c["健康度等级"] || "—")}（${nf(c["健康度得分"], 0)} 分）</div></div>
        <div class="kv"><span>工单 / 平均工时</span><div>${nf(c["累计工单数"])} 个 · ${nf(c["平均处理工时"], 1)} 小时</div></div>
        <div class="card-sub" style="margin:14px 0 6px">最近合同</div>
        ${table(["产品", "起", "止", "MRR", "状态"], r.contracts.map(x => `<tr>
          <td>${esc(x["产品ID"])}</td><td>${esc(x["订阅起始日期"])}</td><td>${esc(x["订阅截止日期"])}</td>
          <td class="num">${nf(x["月经常性收入MRR"])}</td><td>${esc(x["合同状态"])}</td></tr>`), { empty: "无合同" })}
        <div class="small muted" style="margin-top:10px">数据范围：${esc(r.scope)}${r.amountMasked ? " · 金额已脱敏" : ""}</div>`,
        { wide: true });
    } catch (err) { toast(err.message, "error"); }
  }));
}
