/* 报表中心：报表目录、订阅推送、运行记录 */
import { api } from "../api.js";
import { esc, nf, table, toast } from "../core.js";

export async function load() {
  const [defs, runs] = await Promise.all([
    api.get("/reports/definitions"),
    api.get("/reports/runs?limit=12"),
  ]);
  return { defs, runs };
}

export function render(d) {
  const groups = {};
  for (const r of d.defs) (groups[r.category] ||= []).push(r);
  return `
  <div class="grid g-3">
    ${Object.entries(groups).map(([cat, items]) => `
      <div class="card">
        <div class="card-hd"><div class="card-title">${esc(cat)}</div>
          <div class="card-tools"><span class="card-sub">${items.length} 张</span></div></div>
        <div class="card-bd" style="padding:8px 14px 12px">
          ${items.map(r => `<div class="rpt-row">
            <div style="flex:1;min-width:0">
              <div class="rpt-name">${esc(r.name)}</div>
              <div class="small muted">${esc(r.cron || "手动")} · ${esc(r.formats)}</div>
              <div class="small muted">${r.lastRun ? `上次 ${esc(r.lastRun)} · ${nf(r.lastRows)} 行` : "尚未运行"}</div>
            </div>
            <div style="display:flex;flex-direction:column;gap:4px;align-items:flex-end">
              <span class="tag ${r.subscribed ? "g" : "n"}">${r.subscribed ? "已订阅" : "未订阅"}</span>
              <button class="ghost-btn" style="height:24px;font-size:11px"
                data-sub="${esc(r.code)}" data-on="${r.subscribed ? "0" : "1"}">
                ${r.subscribed ? "取消订阅" : "订阅"}</button>
            </div>
          </div>`).join("")}
        </div>
      </div>`).join("")}
  </div>

  <div class="card" style="margin-top:12px">
    <div class="card-hd"><div class="card-title">运行记录</div>
      <div class="card-sub">近 12 次</div>
      <div class="card-tools"><span class="tag g">定时任务正常</span></div></div>
    <div class="card-bd flush">${table(
      ["报表", "期间", "状态", "行数", "耗时", "生成时间"],
      d.runs.map(r => `<tr>
        <td>${esc(r.name)}</td><td>${esc(r.period || "")}</td>
        <td><span class="tag ${r.status === "success" ? "g" : "r"}">${r.status === "success" ? "成功" : "失败"}</span></td>
        <td class="num">${nf(r.row_count)}</td><td class="num">${nf(r.cost_ms)} ms</td>
        <td class="muted">${esc(r.created_at)}</td></tr>`))}</div>
  </div>`;
}

export function mount() {
  document.querySelectorAll("[data-sub]").forEach(b => b.addEventListener("click", async () => {
    try {
      const on = b.dataset.on === "1";
      await api.post("/reports/subscribe", { reportCode: b.dataset.sub, enabled: on, channel: "邮件" });
      toast(on ? "已订阅，将按计划推送" : "已取消订阅", "ok");
      await window.__reloadPage();
    } catch (e) { toast(e.message, "error"); }
  }));
}
