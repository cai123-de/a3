/* 预算管理：版本、执行、量价结构归因、滚动预测、编制草稿 */
import { api } from "../api.js";
import { S, esc, money, pct, nf, table, toast } from "../core.js";
import { waterfall, hbars, C } from "../charts.js";

export const B = { version: "年初预算", year: 2026 };

export async function load() {
  const p = S.period;
  const [versions, exec, variance, forecast] = await Promise.all([
    api.get("/budget/versions"),
    api.get(`/budget/execution?period=${p}&version=${encodeURIComponent(B.version)}`),
    api.get(`/budget/variance?period=${p}&version=${encodeURIComponent(B.version)}`),
    api.get(`/budget/forecast?period=${p}&version=${encodeURIComponent(B.version)}`).catch(e => ({ error: e.message })),
  ]);
  let draft = null;
  try { draft = await api.get(`/budget/draft?year=${B.year}`); } catch { /* 无权限时忽略 */ }
  return { versions, exec, variance, forecast, draft };
}

export function render(d) {
  const { exec, variance, forecast, draft } = d;
  const v = variance.revenue.total;
  const bridge = [
    { name: "预算收入", value: v.budget, kind: "subtotal" },
    { name: "量差", value: v.volume, kind: "in" },
    { name: "价差", value: v.price, kind: "in" },
    { name: "结构差", value: v.structure, kind: "in" },
    { name: "实际收入", value: v.actual, kind: "total" },
  ];
  const statusMap = { draft: ["草稿", "n"], submitted: ["已提交", "a"], approved: ["已批复", "g"],
    issued: ["已下达", "g"], returned: ["已退回", "r"] };
  return `
  <div class="hstack" style="margin-bottom:12px">
    <div class="seg">${d.versions.map(x => `<button data-version="${esc(x.version)}"
      class="${x.version === B.version ? "on" : ""}">${esc(x.version)}</button>`).join("")}</div>
    <span class="card-sub">三条预算线口径不同，不叠加</span>
    <span class="tag n" style="margin-left:auto">当前期间 ${esc(S.period)}</span>
  </div>

  <div class="grid g-main">
    <div class="card">
      <div class="card-hd"><div class="card-title">预算执行</div>
        <div class="card-sub">${esc(B.version)} · ${esc(S.period)}</div>
        <div class="card-tools"><span class="tag ${exec.lines[0]?.rate >= 100 ? "g" : "a"}">
          收入达成 ${pct(exec.lines[0]?.rate)}</span></div></div>
      <div class="card-bd flush">${table(
        ["预算线", "预算（万）", "实际（万）", "差异（万）", "执行率", "在途占用", "状态"],
        exec.lines.map(l => `<tr class="${l.name.startsWith("　") ? "sub" : ""}">
          <td>${esc(l.name)}</td>
          <td class="num">${nf(l.budget / 1e4, 0)}</td>
          <td class="num">${nf(l.actual / 1e4, 0)}</td>
          <td class="num" style="color:${(l.kind === "revenue" ? l.diff < 0 : l.diff > 0) ? C.red : C.green}">
            ${l.diff >= 0 ? "+" : "−"}${nf(Math.abs(l.diff) / 1e4, 0)}</td>
          <td class="num"><span class="tag ${l.rate > 102 ? "r" : l.rate > 100 ? "a" : "g"}">${pct(l.rate)}</span></td>
          <td class="num muted">${l.transit ? nf(l.transit / 1e4) : "—"}</td>
          <td>${l.kind === "revenue"
            ? `<span class="tag ${l.rate >= 100 ? "g" : "a"}">${l.rate >= 100 ? "达成" : "未达成"}</span>`
            : `<span class="tag ${l.rate > 100 ? "a" : "g"}">${l.rate > 100 ? "超支" : "节约"}</span>`}</td>
        </tr>`))}</div>
    </div>

    <div class="card">
      <div class="card-hd"><div class="card-title">滚动预测</div>
        <div class="card-sub">YTD 实际 + 剩余月预测</div></div>
      <div class="card-bd">
        ${forecast.error ? `<div class="blank">${esc(forecast.error)}</div>` : `
        <div class="kv"><span>年初预算</span><div class="num">${money(forecast.yearBudget)}</div></div>
        <div class="kv"><span>YTD 实际</span><div class="num">${money(forecast.ytdActual)}</div></div>
        <div class="kv"><span>剩余月预算</span><div class="num">${money(forecast.remainingBudget)}</div></div>
        <div class="kv"><span>修正系数</span><div class="num">${nf(forecast.factor, 3)}
          <span class="muted">（近 3 月执行偏差自动 ${nf(forecast.autoFactor, 3)}）</span></div></div>
        <div class="kv"><span>全年预测</span><div class="num" style="font-weight:600">${money(forecast.forecast)}</div></div>
        <div class="kv"><span>预计差异</span><div class="num" style="color:${forecast.gap > 0 ? C.red : C.green}">
          ${money(forecast.gap, { sign: true })}（${pct(forecast.gapRate)}）</div></div>
        <div class="small muted" style="margin-top:8px">${esc(forecast.note)}</div>`}
      </div>
    </div>
  </div>

  <div class="card" style="margin-top:12px">
    <div class="card-hd"><div class="card-title">收入差异三因素分解</div>
      <div class="card-sub">量差 + 价差 + 结构差 = 总差异</div>
      <div class="card-tools"><span class="tag ${v.diff >= 0 ? "g" : "r"}">总差异 ${money(v.diff, { sign: true })}</span></div></div>
    <div class="card-bd">
      ${waterfall(bridge)}
      <div class="grid g-3" style="margin-top:6px">
        <div class="kv"><span>量差（客户数变化）</span><div class="num">${money(v.volume, { sign: true })}</div></div>
        <div class="kv"><span>价差（ARPA 变化）</span><div class="num">${money(v.price, { sign: true })}</div></div>
        <div class="kv"><span>结构差（产品组合）</span><div class="num">${money(v.structure, { sign: true })}</div></div>
      </div>
      <div class="small muted" style="margin-top:6px">
        校验：三项合计 ${money(v.volume + v.price + v.structure, { sign: true })} = 总差异 ${money(v.diff, { sign: true })}
        <span class="tag g">通过</span>
      </div>
    </div>
  </div>

  <div class="grid g-2" style="margin-top:12px">
    <div class="card"><div class="card-hd"><div class="card-title">产品收入差异</div></div>
      <div class="card-bd flush">${table(["产品", "预算", "实际", "差异", "量差", "价差"],
        variance.revenue.items.slice(0, 8).map(i => `<tr>
          <td>${esc(i.product)}</td><td class="num">${money(i.budget)}</td>
          <td class="num">${money(i.actual)}</td>
          <td class="num" style="color:${i.diff < 0 ? C.red : C.green}">${money(i.diff, { sign: true })}</td>
          <td class="num muted">${money(i.volume, { sign: true })}</td>
          <td class="num muted">${money(i.price, { sign: true })}</td></tr>`))}</div></div>

    <div class="card"><div class="card-hd"><div class="card-title">费用预算执行</div>
      <div class="card-sub">按科目类别</div></div>
      <div class="card-bd">
        ${variance.expense.items.length ? hbars(variance.expense.items.map(i => ({
          name: `${i.category} ${i.rate.toFixed(0)}%`, value: i.actual,
          color: i.rate > 100 ? C.amber : C.brand }))) : `<div class="blank">无预算数据</div>`}
        <div class="small muted" style="margin-top:8px">${esc(variance.expense.note)}</div>
      </div></div>
  </div>

  <div class="card" style="margin-top:12px">
    <div class="card-hd"><div class="card-title">${B.year} 年度预算编制</div>
      <div class="card-sub">草稿状态 · 两上两下流程</div>
      <div class="card-tools">
        ${draft?.header ? `<span class="tag ${statusMap[draft.header.status]?.[1] || "n"}">
          ${statusMap[draft.header.status]?.[0] || draft.header.status}</span>
          <button class="ghost-btn" data-submit="${draft.header.id}">提交审批</button>` : ""}
      </div></div>
    <div class="card-bd flush">
      ${draft?.header
        ? table(["科目", "1 月", "2 月", "3 月", "…", "合计"],
          groupDraft(draft.lines).map(g => `<tr>
            <td>${esc(g.name)}</td>${g.months.slice(0, 3).map(m => `<td class="num">${nf(m / 1e4, 1)}</td>`).join("")}
            <td class="muted">…</td><td class="num">${nf(g.total / 1e4, 1)}</td></tr>`))
        : `<div class="blank" style="padding:24px">当前部门没有编制草稿，或你的角色没有编制权限</div>`}
      <div class="small muted" style="padding:10px 14px">
        可用余额 = 批复预算 − 已发生 − 在途占用；下达后该版本冻结，修改须走调整单。
      </div>
    </div>
  </div>`;
}

function groupDraft(lines) {
  const map = new Map();
  for (const l of lines) {
    if (!map.has(l.subject)) map.set(l.subject, { name: l.subjectName || l.subject, months: Array(12).fill(0), total: 0 });
    const g = map.get(l.subject);
    const idx = Number(l.month.slice(5, 7)) - 1;
    if (idx >= 0 && idx < 12) g.months[idx] = l.draft;
    g.total += l.draft;
  }
  return [...map.values()];
}

export async function mount() {
  document.querySelectorAll("[data-version]").forEach(b => b.addEventListener("click", async () => {
    B.version = b.dataset.version;
    await window.__reloadPage();
  }));
  document.querySelector("[data-submit]")?.addEventListener("click", async (e) => {
    try {
      const r = await api.post("/budget/submit", { headerId: Number(e.target.dataset.submit), comment: "部门提交" });
      toast(`已提交，状态：${r.status}`, "ok");
      await window.__reloadPage();
    } catch (err) { toast(err.message, "error"); }
  });
}
