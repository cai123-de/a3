/* 系统管理：用户、角色、职级-数据范围、指标字典、审计日志 */
import { api } from "../api.js";
import { esc, nf, money, table, toast, modal, S } from "../core.js";

export const AD = { tab: "users" };

const TABS = [["users", "用户"], ["roles", "角色"], ["grades", "职级与数据范围"], ["metrics", "指标字典"], ["aikey", "AI 接口"], ["audit", "审计日志"]];

export async function load() {
  const [users, roles, grades, metrics, audit, aikey] = await Promise.all([
    api.get("/admin/users"),
    api.get("/admin/roles"),
    api.get("/admin/grades"),
    api.get("/admin/metrics"),
    api.get("/admin/audit-logs?size=30").catch(() => ({ rows: [], total: 0 })),
    api.get("/admin/ai-key").catch(() => null),
  ]);
  return { users, roles, grades, metrics, audit, aikey };
}

const DEPTH = { summary: "仅汇总", detail: "明细", doc: "到单据" };

export function render(d) {
  return `
  <div class="hstack" style="margin-bottom:12px">
    <div class="seg">${TABS.map(([k, n]) => `<button data-tab="${k}" class="${AD.tab === k ? "on" : ""}">${n}</button>`).join("")}</div>
    <span class="card-sub" style="margin-left:auto">权限 = 角色（能做什么）× 部门（看多宽）× 职级（看多深）</span>
  </div>
  ${AD.tab === "users" ? usersView(d) : ""}
  ${AD.tab === "roles" ? rolesView(d) : ""}
  ${AD.tab === "grades" ? gradesView(d) : ""}
  ${AD.tab === "metrics" ? metricsView(d) : ""}
  ${AD.tab === "aikey" ? aikeyView(d) : ""}
  ${AD.tab === "audit" ? auditView(d) : ""}`;
}

function usersView(d) {
  return `<div class="card"><div class="card-hd"><div class="card-title">账号</div>
    <div class="card-sub">${d.users.length} 个</div>
    <div class="card-tools"><span class="tag n">口令策略：PBKDF2 加盐 · 240,000 轮</span></div></div>
    <div class="card-bd flush">${table(["账号", "姓名", "角色", "部门", "职级", "数据范围", "最近登录", "状态"],
      d.users.map(u => `<tr>
        <td class="code">${esc(u.username)}</td><td>${esc(u.name)}</td>
        <td>${esc(u.role_name)}</td><td class="muted">${esc(u.dept_name || "—")}</td>
        <td><span class="tag n">${esc(u.grade)}</span></td>
        <td class="muted">${DEPTH[u.depth] || u.depth}${u.amount_threshold ? ` · ≤ ${money(u.amount_threshold)}` : ""}</td>
        <td class="muted">${esc(u.last_login_at || "—")}</td>
        <td><span class="tag ${u.status === "active" ? "g" : "n"}">${u.status === "active" ? "启用" : "停用"}</span></td>
      </tr>`))}</div></div>`;
}

function rolesView(d) {
  return `<div class="grid g-2">${d.roles.map(r => `
    <div class="card"><div class="card-hd"><div class="card-title">${esc(r.name)}</div>
      <div class="card-sub code">${esc(r.code)}</div>
      <div class="card-tools"><span class="tag n">${nf(r.users)} 人</span></div></div>
      <div class="card-bd">
        <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px">
          ${(r.perms || []).map(p => `<span class="tag n code" style="font-size:10.5px">${esc(p)}</span>`).join("")}
        </div>
        <div class="small muted">${esc(r.note || "")}</div>
      </div></div>`).join("")}</div>`;
}

function gradesView(d) {
  return `<div class="card"><div class="card-hd"><div class="card-title">职级 → 数据深度映射</div>
    <div class="card-sub">改这里等于改全公司同职级的可见范围，需谨慎</div>
    <div class="card-tools"><span class="tag a">变更记入审计</span></div></div>
    <div class="card-bd flush">${table(["职级", "可见深度", "单笔金额阈值", "敏感字段", "人数", "说明", ""],
      d.grades.map(g => `<tr>
        <td><span class="tag n">${esc(g.grade)}</span></td>
        <td>${DEPTH[g.depth] || g.depth}</td>
        <td class="num">${g.amount_threshold === null ? "不限" : money(g.amount_threshold)}</td>
        <td class="muted">${Object.entries(g.field_mask || {}).map(([k, v]) => `${k}:${v}`).join("、") || "—"}</td>
        <td class="num">${nf(g.users)}</td>
        <td class="muted" style="max-width:240px">${esc(g.note || "")}</td>
        <td><span class="link" data-edit-grade="${esc(g.grade)}">调整</span></td></tr>`))}</div></div>`;
}

function metricsView(d) {
  return `<div class="card"><div class="card-hd"><div class="card-title">指标字典</div>
    <div class="card-sub">${d.metrics.length} 个指标 · AI 与前端共用的唯一口径来源</div></div>
    <div class="card-bd flush">${table(["指标", "口径定义", "单位", "取数视图", "版本", "负责人"],
      d.metrics.map(m => `<tr>
        <td>${esc(m.name)}<div class="small muted code">${esc(m.code)}</div></td>
        <td style="max-width:420px">${esc(m.definition)}</td>
        <td class="muted">${esc(m.unit)}</td>
        <td class="code muted">${esc(m.view_name)}</td>
        <td><span class="tag n">${esc(m.version)}</span></td>
        <td class="muted">${esc(m.owner || "—")}</td></tr>`))}</div></div>`;
}

const EFFORT_LABEL = { none: "关闭思考", low: "低（快速）", high: "标准（官方默认）", max: "最大（深度推理）" };

function aikeyView(d) {
  const k = d.aikey;
  if (!k) return `<div class="card"><div class="card-bd"><div class="blank">无 AI 接口配置权限（仅管理员可见）</div></div></div>`;
  return `<div class="grid g-2">
    <div class="card"><div class="card-hd"><div class="card-title">DeepSeek 接入状态</div>
      <div class="card-sub">AI 分析 / Data Agent 共用</div>
      <div class="card-tools"><span class="tag ${k.enabled ? "g" : "r"}">${k.enabled ? "已启用" : "未配置"}</span></div></div>
      <div class="card-bd">
        <div class="kv"><span>当前密钥</span><div class="code">${esc(k.maskedKey || "—")}</div></div>
        <div class="kv"><span>模型</span><div class="code">${esc(k.model || "—")}</div></div>
        <div class="kv"><span>思考模式</span><div>${esc(EFFORT_LABEL[k.effort] || k.effort)} <span class="muted small">(${esc(k.effort)})</span></div></div>
        <div class="kv"><span>最大输出</span><div>${k.maxTokens ? `${nf(k.maxTokens)} tokens` : `官方默认 <span class="muted small">(思考 64K / max 强度 128K)</span>`}</div></div>
        <div class="kv"><span>端点</span><div class="code muted">${esc(k.baseUrl || "—")}</div></div>
        <div class="kv"><span>超时</span><div>${k.timeoutS}s</div></div>
        <div class="notice small">${esc(k.boundary || "")}</div>
      </div></div>
    <div class="card"><div class="card-hd"><div class="card-title">更新 API Key</div>
      <div class="card-sub">platform.deepseek.com/api_keys 获取</div>
      <div class="card-tools"><span class="tag a">保存即生效 · 免重启</span></div></div>
      <div class="card-bd">
        <div class="kv"><span>新密钥</span><div>
          <input class="f-select" id="aiKeyInput" type="password" placeholder="sk-..." style="width:280px" autocomplete="off"></div></div>
        <div class="hstack" style="gap:8px;margin-top:10px">
          <button class="primary-btn" id="aiKeySave">保存密钥</button>
          <button class="ghost-btn" id="aiKeyClear" ${k.enabled ? "" : "disabled"}>清除密钥</button>
        </div>
        <div class="small muted" style="margin-top:10px">密钥仅保存在服务端 .env 文件，前端只显示掩码；保存与清除均记入审计日志。</div>
      </div></div>
    <div class="card" style="grid-column:1/-1"><div class="card-hd"><div class="card-title">模型推理参数</div>
      <div class="card-sub">按官方文档 create-chat-completion 配置 · 思考模式默认开启</div>
      <div class="card-tools"><span class="tag a">保存即生效 · 免重启</span></div></div>
      <div class="card-bd">
        <div class="kv"><span>思考强度</span><div>
          <select class="f-select" id="aiEffort" style="width:240px">
            ${Object.entries(EFFORT_LABEL).map(([v, n]) =>
              `<option value="${v}" ${k.effort === v ? "selected" : ""}>${n}${v === "high" ? " · 默认" : ""}</option>`).join("")}
          </select></div></div>
        <div class="kv"><span>最大输出 tokens</span><div>
          <input class="f-select" id="aiMaxTokens" type="number" min="0" max="${k.maxTokensLimit}" value="${k.maxTokens || ""}" placeholder="空 = 官方默认（思考 64K）" style="width:240px"></div></div>
        <div class="hstack" style="gap:8px;margin-top:10px">
          <button class="primary-btn" id="aiParamsSave">保存参数</button>
          <span class="small muted">思考强度 none = 关闭思考（回答更快更省）；low/high/max = 开启思考，强度递增。最大输出留空走官方默认（思考 64K / max 强度 128K / 非思考 8K），上限 393,216。</span>
        </div>
      </div></div>
  </div>`;
}

function auditView(d) {
  return `<div class="card"><div class="card-hd"><div class="card-title">审计日志</div>
    <div class="card-sub">共 ${nf(d.audit.total)} 条，显示最近 30 条</div>
    <div class="card-tools"><span class="tag n">登录 / 查询 / 导出 / 拒绝 全留痕</span></div></div>
    <div class="card-bd flush">${table(["时间", "用户", "动作", "对象", "详情"],
      (d.audit.rows || []).map(r => `<tr>
        <td class="muted">${esc(r.created_at)}</td><td>${esc(r.username || "—")}</td>
        <td><span class="tag ${r.action === "deny" ? "r" : r.action === "export" ? "a" : "n"}">${esc(r.action)}</span></td>
        <td class="code">${esc(r.object || "")}</td>
        <td class="muted" style="max-width:480px">${esc(JSON.stringify(r.detail || {}))}</td></tr>`))}</div></div>`;
}

export function mount() {
  const keySave = document.getElementById("aiKeySave");
  if (keySave) {
    keySave.addEventListener("click", async () => {
      const key = document.getElementById("aiKeyInput").value.trim();
      if (!key) { toast("请先粘贴 API Key", "error"); return; }
      try {
        await api.post("/admin/ai-key", { apiKey: key });
        toast("密钥已保存并立即生效", "ok");
        await window.__reloadPage();
      } catch (e) { toast(e.message, "error"); }
    });
    const paramsSave = document.getElementById("aiParamsSave");
    if (paramsSave) paramsSave.addEventListener("click", async () => {
      const mt = document.getElementById("aiMaxTokens").value;
      try {
        await api.put("/admin/ai-key/params", {
          effort: document.getElementById("aiEffort").value,
          maxTokens: mt === "" ? 0 : Number(mt),
        });
        toast("推理参数已保存并立即生效", "ok");
        await window.__reloadPage();
      } catch (e) { toast(e.message, "error"); }
    });
    const keyClear = document.getElementById("aiKeyClear");
    if (keyClear) keyClear.addEventListener("click", async () => {
      try {
        await api.del("/admin/ai-key");
        toast("密钥已清除，AI 将回落规则引擎", "ok");
        await window.__reloadPage();
      } catch (e) { toast(e.message, "error"); }
    });
  }
  document.querySelectorAll("[data-tab]").forEach(b => b.addEventListener("click", async () => {
    AD.tab = b.dataset.tab; await window.__reloadPage();
  }));
  document.querySelectorAll("[data-edit-grade]").forEach(b => b.addEventListener("click", () => {    const g = S.datasets.admin.grades.find(x => x.grade === b.dataset.editGrade);
    modal(`调整职级：${esc(g.grade)}`, `
      <div class="kv"><span>可见深度</span><div>
        <select class="f-select" id="gDepth">
          ${["summary", "detail", "doc"].map(k => `<option value="${k}" ${g.depth === k ? "selected" : ""}>${DEPTH[k]}</option>`).join("")}
        </select></div></div>
      <div class="kv"><span>单笔金额阈值（元，空=不限）</span><div>
        <input class="f-select" id="gAmt" type="number" value="${g.amount_threshold ?? ""}" style="width:180px"></div></div>
      <div class="kv"><span>金额脱敏</span><div>
        <select class="f-select" id="gMask">
          <option value="0" ${g.field_mask?.amount !== "hidden" ? "selected" : ""}>可见</option>
          <option value="1" ${g.field_mask?.amount === "hidden" ? "selected" : ""}>隐藏（***）</option>
        </select></div></div>
      <div class="notice">该职级共 ${nf(g.users)} 人，保存后立即生效；已登录用户的权限在下次请求时按新配置计算。</div>`,
      { footer: `<button class="ghost-btn" onclick="closeModal()">取消</button>
        <button class="primary-btn" id="gSave">保存</button>` });
    document.getElementById("gSave").addEventListener("click", async () => {
      try {
        const amt = document.getElementById("gAmt").value;
        const mask = document.getElementById("gMask").value === "1"
          ? { ...(g.field_mask || {}), amount: "hidden" }
          : Object.fromEntries(Object.entries(g.field_mask || {}).filter(([k]) => k !== "amount"));
        await api.put(`/admin/grades/${encodeURIComponent(g.grade)}`, {
          depth: document.getElementById("gDepth").value,
          amountThreshold: amt === "" ? null : Number(amt),
          fieldMask: mask,
        });
        toast("已保存，立即生效", "ok");
        closeModalGlobal();
        await window.__reloadPage();
      } catch (e) { toast(e.message, "error"); }
    });
  }));
}

function closeModalGlobal() {
  const ov = document.getElementById("modal");
  if (ov) { ov.classList.remove("on"); ov.innerHTML = ""; }
}
