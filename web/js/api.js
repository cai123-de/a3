/* API 客户端：统一信封解析、令牌续期、错误码转异常 */

const ACCESS = "fin.access";
const REFRESH = "fin.refresh";

export class ApiError extends Error {
  constructor(code, message, detail, status) {
    super(message || "请求失败");
    this.code = code;
    this.detail = detail;
    this.status = status;
  }
}

export const session = {
  get token() { return localStorage.getItem(ACCESS) || ""; },
  get refreshToken() { return localStorage.getItem(REFRESH) || ""; },
  save(data) {
    if (data.accessToken) localStorage.setItem(ACCESS, data.accessToken);
    if (data.refreshToken) localStorage.setItem(REFRESH, data.refreshToken);
  },
  clear() { localStorage.removeItem(ACCESS); localStorage.removeItem(REFRESH); },
};

let refreshing = null;

async function refresh() {
  if (!session.refreshToken) return false;
  if (!refreshing) {
    refreshing = fetch("/api/v1/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refreshToken: session.refreshToken }),
    }).then(async r => {
      const j = await r.json().catch(() => ({}));
      if (r.ok && j.code === 0) { session.save(j.data); return true; }
      return false;
    }).finally(() => { refreshing = null; });
  }
  return refreshing;
}

async function request(path, { method = "GET", body, retry = true, raw = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (session.token) headers.Authorization = `Bearer ${session.token}`;
  let res, json;
  try {
    res = await fetch(`/api/v1${path}`, {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e) {
    throw new ApiError(-1, "无法连接服务器，请确认服务已启动", null, 0);
  }

  if (res.status === 401 && retry && await refresh()) {
    return request(path, { method, body, retry: false, raw });
  }
  try { json = await res.json(); } catch { json = { code: 50000, message: `服务返回异常（HTTP ${res.status}）` }; }

  if (!res.ok || json.code !== 0) {
    if (json.code === 40101) {
      session.clear();
      window.dispatchEvent(new CustomEvent("auth:expired"));
    }
    throw new ApiError(json.code, json.message, json.detail, res.status);
  }
  return raw ? json : json.data;
}

export const api = {
  get: (p) => request(p),
  post: (p, body) => request(p, { method: "POST", body }),
  put: (p, body) => request(p, { method: "PUT", body }),
  del: (p) => request(p, { method: "DELETE" }),
  envelope: (p) => request(p, { raw: true }),
};

export async function login(username, password) {
  const data = await request("/auth/login", { method: "POST", body: { username, password }, retry: false });
  session.save(data);
  return data;
}

export async function logout() {
  try { await api.post("/auth/logout"); } catch { /* 忽略 */ }
  session.clear();
}

export async function me() { return api.get("/auth/me"); }

export async function demoAccounts() { return api.get("/auth/demo-accounts"); }
