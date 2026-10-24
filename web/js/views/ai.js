/* AI 分析：语义层问答、六道闸门、取数 SQL、评测集 */
import { api } from "../api.js";
import { esc, money, nf, pct, table, toast, modal, S } from "../core.js";
import { C } from "../charts.js";

export const CHAT = { messages: [], sessionId: null, busy: false };

export async function load() {
  const [suggestions, evalInfo, metrics, status] = await Promise.all([
    api.get("/ai/suggestions"),
    api.get("/ai/eval"),
    api.get("/ai/metrics"),
    api.get("/ai/status").catch(() => ({ enabled: false })),
  ]);
  CHAT.agentMode = !!status.enabled;
  return { suggestions, evalInfo, metrics, agentOn: CHAT.agentMode };
}

const TOOL_LABEL = {
  query_data_dictionary: "查数据字典",
  run_sql: "执行查询",
  explain_sql: "性能验证",
};

function bubble(m) {
  if (m.role === "user") {
    return `<div class="msg u"><div class="bubble">${esc(m.content)}</div></div>`;
  }
  const d = m.data;
  if (!d) return `<div class="msg a"><div class="bubble">${esc(m.content)}</div></div>`;
  const rows = d.rows || [];
  const isList = rows.length > 1;
  const steps = d.steps || [];
  return `<div class="msg a">
    <div class="bubble">
      <div class="small muted" style="margin-bottom:6px">${esc(d.thinking)}</div>
      ${steps.length ? `<div class="agent-steps" style="margin:0 0 10px;padding:8px 10px;background:var(--bg2,#F8FAFC);border-radius:8px">
        ${steps.map(s => `<div style="display:flex;gap:6px;align-items:baseline;padding:2.5px 0;font-size:11.5px">
          <span class="code" style="width:16px;flex:none">${s.i}</span>
          <span class="tag ${s.ok ? "n" : "r"}" style="flex:none">${esc(TOOL_LABEL[s.tool] || s.tool)}</span>
          <span style="flex:1;min-width:0;color:#475467;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(s.summary)}</span>
          <span class="num muted" style="flex:none">${nf(s.ms)}ms</span></div>`).join("")}
      </div>` : ""}
      <div class="ai-answer">${mdLite(d.answer)}</div>
      ${isList && rows[0] && "value" in rows[0] ? `<div style="margin:10px 0">${rows.slice(0, 8).map(r => `
        <div class="legend"><span class="cname" style="width:120px">${esc(r["维度"] ?? r[Object.keys(r).find(k => k !== "value" && k !== "pct")] ?? "")}</span>
          <div class="hbar" style="flex:1"><i style="width:${(Math.abs(r.value) / Math.max(...rows.map(x => Math.abs(x.value || 0)))) * 100}%;background:${C.brand}"></i></div>
          <span class="num" style="width:96px;text-align:right">${r.pct !== undefined ? pct(r.value) : money(r.value)}</span>
        </div>`).join("")}</div>`
        : isList ? `<div style="margin:10px 0;overflow:auto"><table class="tbl" style="font-size:11.5px">
            <thead><tr>${Object.keys(rows[0]).slice(0, 5).map(k => `<th>${esc(k)}</th>`).join("")}</tr></thead>
            <tbody>${rows.slice(0, 6).map(r => `<tr>${Object.keys(rows[0]).slice(0, 5).map(k =>
              `<td class="num">${esc(r[k] ?? "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>` : ""}
      <div class="hstack" style="gap:6px;margin-top:8px;flex-wrap:wrap">
        ${steps.length ? `<span class="tag g">Data Agent</span>` : `<span class="tag n">${esc(d.meta.metric)}</span>`}
        ${d.meta.metricVersion && d.meta.metricVersion !== "—" ? `<span class="tag n">口径 ${esc(d.meta.metricVersion)}</span>` : ""}
        ${d.meta.source && d.meta.source !== "Agent 工具链" ? `<span class="tag n">${esc(d.meta.source)}</span>` : ""}
        <span class="tag n">${nf(d.meta.rowCount)} 行</span>
        <span class="tag n">范围 ${esc(d.meta.scope)}</span>
        ${d.sql ? `<span class="link" onclick="window.__showSql(${m.id})">查看 SQL</span>` : ""}
        <span class="link" onclick="window.__fb(${m.id}, 1)">有用</span>
        <span class="link" onclick="window.__fb(${m.id}, -1)">没用</span>
      </div>
    </div></div>`;
}

function mdLite(t) {
  return esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
}

const GATE_NAMES = [
  ["G1", "身份与数据范围"], ["G2", "指标白名单"], ["G3", "时间范围"],
  ["G4", "行数与明细"], ["G5", "敏感字段"], ["G6", "只读与注入防护"],
];

export function render(d) {
  return `
  <div class="grid" style="grid-template-columns:1.55fr 1fr;gap:12px;align-items:start">
    <div class="card" style="display:flex;flex-direction:column;min-height:520px">
      <div class="card-hd"><div class="card-title">AI 分析</div>
        <div class="card-sub">Data Agent 自主查数 · 六道闸门</div>
        <div class="card-tools"><span class="tag ${d.agentOn ? "g" : "n"}">${d.agentOn ? "Agent 模式 · DeepSeek" : "规则模式 · 未配置 LLM"}</span></div></div>
      <div class="card-bd" id="chatBody" style="flex:1;max-height:520px;overflow:auto">
        ${CHAT.messages.length ? CHAT.messages.map(bubble).join("") : `
          <div class="empty" style="padding:26px 10px">
            <div class="st-t">问一个经营问题</div>
            <div class="st-d">例如「2025年12月各产品线毛利率」「哪个大区收入最高」</div>
          </div>`}
      </div>
      <div class="card-bd" style="border-top:1px solid var(--line2)">
        <div class="chips" style="margin-bottom:8px">
          ${d.suggestions.slice(0, 3).map(q => `<span class="chip" data-q="${esc(q)}">${esc(q)}</span>`).join("")}
        </div>
        <div class="hstack">
          <input id="askInput" class="f-select" style="flex:1;height:34px" placeholder="${d.agentOn ? "用自然语言问任何经营问题，Agent 会自主查数分析" : "输入问题，Enter 发送（仅支持指标字典内的问题）"}">
          <button class="primary-btn" id="askBtn">提问</button>
        </div>
      </div>
    </div>

    <div>
      <div class="card"><div class="card-hd"><div class="card-title">六道安全闸门</div>
        <div class="card-sub">服务端强制执行</div></div>
        <div class="card-bd">
        ${GATE_NAMES.map(([c, n]) => `<div class="gate"><span class="code">${c}</span>
          <div><div style="font-size:12.4px">${n}</div></div>
          <span class="tag g" style="margin-left:auto">通过</span></div>`).join("")}
        <div class="small muted" style="margin-top:8px">
          敏感问题会被拦截并记入审计日志；越权提问不会返回数据，只返回拒绝原因。
        </div>
        </div></div>

      <div class="card" style="margin-top:12px"><div class="card-hd"><div class="card-title">评测集</div>
        <div class="card-sub">上线与回归门槛</div></div>
        <div class="card-bd">
          <div class="kv"><span>题目总数</span><div class="num">${nf(d.evalInfo.total)} 条</div></div>
          <div class="kv"><span>难度分布</span><div>${Object.entries(d.evalInfo.byLevel).map(([k, v]) =>
            `<span class="tag n" style="margin-right:4px">${k} ${v}</span>`).join("")}</div></div>
          <div class="kv"><span>越权试探</span><div class="num">${nf(d.evalInfo.safety)} 条（拦截率要求 100%）</div></div>
          <div class="kv"><span>数值准确率门槛</span><div>总体 ≥ 95%，L1/L2 ≥ 98%</div></div>
          <div class="small muted" style="margin-top:6px">换模型或改提示词后必须全量回归。</div>
        </div></div>

      <div class="card" style="margin-top:12px"><div class="card-hd"><div class="card-title">指标字典</div>
        <div class="card-sub">共 ${d.metrics.length} 个</div></div>
        <div class="card-bd" style="max-height:220px;overflow:auto">
          ${d.metrics.slice(0, 14).map(m => `<div class="legend" style="margin:5px 0">
            <span class="code" style="width:22px">${esc(m.code.slice(0, 2).toUpperCase())}</span>
            <span class="cname">${esc(m.name)}</span>
            <span class="num muted" style="margin-left:auto">${esc(m.version)}</span></div>`).join("")}
        </div></div>
    </div>
  </div>`;
}

export function mount() {
  const input = document.getElementById("askInput");
  const send = async () => {
    const q = (input?.value || "").trim();
    if (!q || CHAT.busy) return;
    input.value = "";
    CHAT.busy = true;
    CHAT.messages.push({ role: "user", content: q });
    redraw();
    try {
      const r = CHAT.agentMode
        ? await api.post("/ai/agent", { question: q, sessionId: CHAT.sessionId })
        : await api.post("/ai/ask", { question: q, sessionId: CHAT.sessionId });
      CHAT.sessionId = r.sessionId;
      CHAT.messages.push({ role: "assistant", content: r.answer, data: r, id: r.messageId });
    } catch (e) {
      CHAT.messages.push({ role: "assistant", content: `⚠️ ${e.message}` });
    } finally {
      CHAT.busy = false;
      redraw();
    }
  };
  document.getElementById("askBtn")?.addEventListener("click", send);
  input?.addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
  document.querySelectorAll("[data-q]").forEach(c => c.addEventListener("click", () => {
    input.value = c.dataset.q; send();
  }));
  input?.focus();

  window.__showSql = (id) => {
    const m = CHAT.messages.find(x => x.id === id)?.data;
    if (!m) return;
    modalSql(m);
  };
  window.__fb = async (id, v) => {
    try { await api.post("/ai/feedback", { message: id, value: v }); toast("已记录反馈", "ok"); }
    catch (e) { toast(e.message, "error"); }
  };
}

function redraw() {
  const body = document.getElementById("chatBody");
  if (!body) return;
  body.innerHTML = CHAT.messages.length
    ? CHAT.messages.map(bubble).join("") +
      (CHAT.busy ? `<div class="msg"><div class="bubble muted">${CHAT.agentMode ? "Data Agent 正在查字典 → 写 SQL → 取数分析…" : "正在按语义层解析…"}</div></div>` : "")
    : "";
  body.scrollTop = body.scrollHeight;
}

function modalSql(m) {
  modal("取数 SQL", `
      <pre class="code" style="white-space:pre-wrap">${esc(m.sql)}</pre>
      <div class="card-sub" style="margin:10px 0 6px">闸门执行结果</div>
      ${m.gates.map(g => `<div class="gate"><span class="code">${g.code}</span>
        <div><div style="font-size:12.2px">${esc(g.name)}</div>
        <div class="small muted">${esc(g.detail || g.note)}</div></div>
        <span class="tag ${g.passed ? "g" : "r"}" style="margin-left:auto">${g.passed ? "通过" : "拦截"}</span></div>`).join("")}
      <div class="small muted" style="margin-top:10px">
        引擎：${esc(m.meta.engine)}；指标 ${esc(m.meta.metric)}（${esc(m.meta.metricVersion)}）；
        数据源 ${esc(m.meta.source)}。
      </div>`, { wide: true });
}
