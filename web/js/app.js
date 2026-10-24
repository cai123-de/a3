/* 应用入口：登录、导航、路由、数据加载、全局状态 */
window.__FIN_VER = "1.4.1"; /* 版本哨兵：index.html 内联脚本据此检测旧模块并自动刷新 */
import { api, login, logout, me, session, demoAccounts, ApiError } from "./api.js";
import { S, $, esc, icon, toast, skeleton, errorState, scopeChip, money, nf } from "./core.js";
import * as overview from "./views/overview.js";
import * as customers from "./views/customers.js";
import * as ar from "./views/ar.js";
import * as budget from "./views/budget.js";
import * as ai from "./views/ai.js";
import * as reports from "./views/reports.js";
import * as alerts from "./views/alerts.js";
import * as admin from "./views/admin.js";
import * as semantic from "./views/semantic.js";
import * as dataops from "./views/dataops.js";

const VIEWS = { overview, customers, ar, budget, semantic, ai, reports, alerts, dataops, admin };
const TITLES = {
  overview: "经营驾驶舱", customers: "客户分析", ar: "应收与回款", budget: "预算管理",
  semantic: "语义模型", ai: "AI 分析", reports: "报表中心", alerts: "预警中心",
  dataops: "数据管理", admin: "系统管理",
};
const SUBTITLES = {
  overview: "管理层每日入口 · 任何数字 4 步内到单据",
  customers: "客户旅程 · 健康度 · 续约",
  ar: "账龄 · 逾期 · 催收闭环",
  budget: "三条预算线 · 差异归因 · 滚动预测",
  semantic: "指标字典 · 口径版本 · 下钻映射 · sem 视图",
  ai: "语义层问答 · 六道闸门",
  reports: "定时生成 · 订阅推送",
  alerts: "规则触发 · 处理闭环",
  dataops: "数据资产 · 关系地图 · 期间管理",
  admin: "账号 · 角色 · 职级 · 审计",
};

/* ---------------- 启动 ---------------- */
async function boot() {
  bindGlobalEvents();
  // 开发环境便捷入口：?demo=chenjing 自动以演示账号登录（仅本地联调/截图使用）
  const demo = new URLSearchParams(location.search).get("demo");
  if (!session.token && demo) {
    try {
      const data = await login(demo, "Fin@2026");
      applyUser(data.user, data.menus);
      await startApp();
      return;
    } catch (e) { console.warn("demo login failed", e); }
  }
  if (session.token) {
    try {
      const data = await me();
      applyUser(data.user, data.menus);
      await startApp();
      return;
    } catch (e) {
      session.clear();
    }
  }
  showLogin();
}

function applyUser(user, menus) {
  S.user = user;
  S.menus = menus || [];
}

async function startApp() {
  $("login")?.classList.add("hide");
  $("app").hidden = false;
  renderSidebar();
  await loadPeriods();
  renderTopbar();
  const hash = location.hash.replace("#", "");
  await go(VIEWS[hash] ? hash : (S.menus[0]?.id || "overview"));
}

/* ---------------- 登录 ---------------- */
async function showLogin() {
  $("app").hidden = true;
  const box = $("login");
  box.classList.remove("hide");
  let demos = [];
  try { demos = await demoAccounts(); } catch { /* 服务未初始化时忽略 */ }
  box.innerHTML = `
  <div class="login-card">
    <div class="login-l">
      <div class="brand" style="padding:0 0 18px">
        <div class="brand-mark">财</div>
        <div><div class="brand-t">财务管理系统</div><div class="brand-s">FIN SUITE</div></div>
      </div>
      <h1>管理会计口径的<br>经营分析平台</h1>
      <p class="login-desc">25 张数据表 · 19 个分析视图 · 31 个指标口径<br>
        三维数据权限（角色 × 部门 × 职级）· 语义层 AI 问答</p>
      <ul class="login-points">
        <li>任何数字 4 步内下钻到单据</li>
        <li>超阈值金额折叠而非隐藏，合计始终对得上</li>
        <li>AI 走指标白名单，拒绝裸 Text-to-SQL</li>
      </ul>
      <div class="login-meta">数据截至 ${esc(S.period || "2025-12")} · 实例三 / 文件夹</div>
    </div>
    <div class="login-r">
      <div class="login-title">登录</div>
      <form id="loginForm">
        <label class="f-label">账号</label>
        <input class="f-input" name="username" autocomplete="username" placeholder="如 chenjing" required>
        <label class="f-label" style="margin-top:12px">口令</label>
        <input class="f-input" name="password" type="password" autocomplete="current-password" placeholder="Fin@2026" required>
        <div id="loginErr" class="login-err"></div>
        <button class="primary-btn login-btn" type="submit">登录</button>
      </form>
      <div class="login-demos">
        <div class="f-label" style="margin-bottom:6px">演示账号（点击填充）</div>
        ${demos.map(d => `<button class="demo-item" data-u="${esc(d.username)}">
          <span class="avatar" style="width:26px;height:26px;font-size:11px">${esc(d.name.slice(0, 1))}</span>
          <span style="flex:1;text-align:left">
            <b>${esc(d.name)}</b><span class="muted"> · ${esc(d.role_name)}</span>
            <div class="small muted">${esc(d.dept_name || "")} · ${esc(d.grade)}</div>
          </span>
        </button>`).join("")}
        <div class="small muted" style="margin-top:8px">统一口令 Fin@2026（开发环境初始值，生产环境首次登录强制改密）</div>
      </div>
    </div>
  </div>`;

  box.querySelectorAll("[data-u]").forEach(b => b.addEventListener("click", () => {
    box.querySelector('[name="username"]').value = b.dataset.u;
    box.querySelector('[name="password"]').value = "Fin@2026";
    box.querySelector('[name="password"]').focus();
  }));

  $("loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const btn = e.target.querySelector("button[type=submit]");
    btn.disabled = true; btn.textContent = "登录中…";
    $("loginErr").textContent = "";
    try {
      const data = await login(fd.get("username"), fd.get("password"));
      applyUser(data.user, data.menus);
      await startApp();
    } catch (err) {
      $("loginErr").textContent = err.message || "登录失败";
      btn.disabled = false; btn.textContent = "登录";
    }
  });
}

/* ---------------- 侧栏 / 顶栏 ---------------- */
function renderSidebar() {
  const nav = S.menus.map(m => `<div class="nav-item ${S.page === m.id ? "active" : ""}" data-go="${m.id}">
    ${icon(m.id)}<span>${esc(m.name)}</span></div>`).join("");
  $("navBox").innerHTML = `<div class="nav-label">业务</div>${nav}`;
  $("sideUser").innerHTML = `
    <div class="avatar">${esc(S.user.name.slice(0, 1))}</div>
    <div style="min-width:0">
      <div style="color:#E4E7EC;font-size:12.5px">${esc(S.user.name)}</div>
      <div style="color:#667085;font-size:10.5px">${esc(S.user.roleName)} · ${esc(S.user.grade)}</div>
    </div>`;
  $("navBox").querySelectorAll("[data-go]").forEach(el => el.addEventListener("click", () => go(el.dataset.go)));
}

function renderTopbar() {
  $("crumb").innerHTML = `<b>${esc(TITLES[S.page] || "")}</b>
    <span class="muted">/ ${esc(SUBTITLES[S.page] || "")}</span>`;
  $("topRight").innerHTML = `
    <button class="fresh" id="qualityBtn" title="查看数据质量体检">
      <span class="dot"></span><span>数据截至 ${esc(S.period)}</span>
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#98A2B3" stroke-width="2.6"><path d="m6 9 6 6 6-6"/></svg>
    </button>
    <select class="f-select" id="periodSel" title="切换期间">
      ${S.periods.slice(0, 24).map(p => `<option value="${p}" ${p === S.period ? "selected" : ""}>${p}</option>`).join("")}
    </select>
    ${scopeChip(S.user)}
    <div class="persona-btn" id="userBtn">
      <div class="avatar" style="width:26px;height:26px;font-size:11px">${esc(S.user.name.slice(0, 1))}</div>
      <div class="persona-meta"><b>${esc(S.user.name)}</b><span>${esc(S.user.title || S.user.roleName)}</span></div>
    </div>`;
  $("periodSel").addEventListener("change", async (e) => {
    S.period = e.target.value;
    renderTopbar();
    await go(S.page);
  });
  $("qualityBtn").addEventListener("click", toggleQuality);
  $("userBtn").addEventListener("click", showUserMenu);
}

function showUserMenu() {
  import("./core.js").then(({ modal }) => {
    const u = S.user;
    modal("当前身份与权限", `
      <div class="kv"><span>姓名</span><div>${esc(u.name)} · ${esc(u.title || "")}</div></div>
      <div class="kv"><span>角色</span><div>${esc(u.roleName)}（功能权限）</div></div>
      <div class="kv"><span>部门</span><div>${esc(u.dept?.name || "—")}（数据宽度：${esc(u.scopeLabel)}）</div></div>
      <div class="kv"><span>职级</span><div>${esc(u.grade)}（数据深度：${{ summary: "仅汇总", detail: "可看明细", doc: "可到单据" }[u.depth]}）</div></div>
      <div class="kv"><span>单笔阈值</span><div>${u.amountThreshold === null ? "不限" : "≤ " + money(u.amountThreshold)}</div></div>
      <div class="kv"><span>字段脱敏</span><div>${Object.entries(u.fieldMask || {}).map(([k, v]) => `${k}: ${v}`).join("、") || "无"}</div></div>
      <div class="kv"><span>有效期</span><div>8 小时，到期自动失效</div></div>
      <div class="notice">越权访问会被拒绝并记入审计日志，可在「系统管理 → 审计日志」查看。</div>`,
      { footer: `<button class="ghost-btn" id="logoutBtn">退出登录</button>` });
    document.getElementById("logoutBtn").addEventListener("click", async () => {
      await logout();
      session.clear();
      location.reload();
    });
  });
}

/* ---------------- 路由 ---------------- */
async function go(page, force = false) {
  if (!VIEWS[page]) page = "overview";
  S.page = page;
  document.querySelectorAll("[data-go]").forEach(el =>
    el.classList.toggle("active", el.dataset.go === page));
  if (location.hash !== "#" + page) history.replaceState(null, "", "#" + page);
  renderTopbar();
  const view = $("view");
  view.innerHTML = skeleton();
  try {
    const data = await VIEWS[page].load();
    S.datasets[page] = data;
    view.innerHTML = VIEWS[page].render(data);
    VIEWS[page].mount?.();
  } catch (err) {
    view.innerHTML = errorState(err instanceof ApiError ? err : new ApiError(-1, err.message));
  }
}

window.__reloadPage = () => go(S.page, true);
window.go = go;

/* ---------------- 数据质量体检 ---------------- */
async function toggleQuality() {
  let panel = document.getElementById("qpanel");
  if (!panel) {
    panel = document.createElement("div");
    panel.id = "qpanel";
    document.body.appendChild(panel);
    panel.addEventListener("click", (e) => e.stopPropagation());
  }
  if (panel.classList.contains("on")) { panel.classList.remove("on"); return; }
  panel.innerHTML = `<div class="qp-hd"><span>数据质量体检</span><span class="muted">加载中…</span></div>`;
  panel.classList.add("on");
  try {
    const q = await api.get("/overview/quality");
    const ok = q.items.filter(i => i.s === "ok").length;
    panel.innerHTML = `
      <div class="qp-hd"><span>数据质量体检</span>
        <span class="tag ${ok === q.items.length ? "g" : "a"}">${ok}/${q.items.length}</span></div>
      <div class="qp-sub">数据截至 ${esc(q.at)}　ETL 完成 ${esc(q.etlAt)}</div>
      ${q.items.map(i => `<div class="qp-row">
        <span class="qp-dot ${i.s === "ok" ? "" : "warn"}"></span>
        <div><div class="qp-k">${esc(i.k)}</div><div class="qp-v">${esc(i.v)}</div>
        <div class="qp-n">${esc(i.note)}</div></div></div>`).join("")}
      <div class="qp-ft">四方勾稽：订阅收入、营业成本、应收余额、期间费用四项视图合计与明细表逐项比对，
        差异容差 1 元。勾稽不通过时页面应挂黄色横幅并禁用导出——<b>宁可不显示，也不显示错的数</b>。</div>`;
  } catch (e) {
    panel.innerHTML = `<div class="qp-hd"><span>数据质量体检</span></div>
      <div class="qp-row"><div class="qp-n">${esc(e.message)}</div></div>`;
  }
}

/* ---------------- 全局 ---------------- */
function bindGlobalEvents() {
  window.addEventListener("auth:expired", () => {
    toast("登录已过期，请重新登录", "warn");
    setTimeout(() => location.reload(), 800);
  });
  document.addEventListener("click", (e) => {
    const panel = document.getElementById("qpanel");
    if (panel && panel.classList.contains("on") &&
        !panel.contains(e.target) && e.target.id !== "qualityBtn") {
      panel.classList.remove("on");
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") window.closeModal?.();
  });
  window.addEventListener("hashchange", () => {
    const p = location.hash.replace("#", "");
    if (VIEWS[p] && p !== S.page) go(p);
  });
}

/* ---------------- 期间 ---------------- */
async function loadPeriods() {
  try {
    const r = await api.get("/overview/periods");
    S.periods = r.periods;
    S.period = r.latest;
  } catch {
    S.periods = ["2025-12"];
    S.period = "2025-12";
  }
}

boot().catch(e => { console.error(e); });
