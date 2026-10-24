# 财务管理系统（FIN SUITE）

基于《财务管理系统开发文档 V1.2》落地的全栈工程：FastAPI + PostgreSQL + 原生 ES Module 前端（零构建）。
数据源为「实例三库 · `文件夹` schema」中的 25 张中文业务表与 19 个 `V_` 前缀分析视图（详见项目根目录 `数据字典.md` / `数据导入说明.md`）。

---

## 零、下次查看：双击启动

日常查看无需敲任何命令，直接双击 **`启动系统.bat`**：

1. 双击后脚本自动完成：端口检查 → Python 定位 → 依赖校验（缺了自动装）→ 数据库自检 → 启动服务 → 4 秒后打开浏览器
2. 默认以 CFO「陈静」身份进入经营驾驶舱（`?demo=chenjing#overview`）
3. **关闭黑色命令行窗口即停止服务**

| 需求 | 做法 |
|---|---|
| 换端口（默认 8021 被占用时） | 命令行执行 `set FS_PORT=8030`，再运行 `启动系统.bat` |
| 只检查环境是否就绪 | `启动系统.bat --check` |
| 不自动打开浏览器 | `启动系统.bat --no-browser` |
| 开发调试（改代码自动重载） | `python run.py --port 8021 --reload` |

脚本会依次尝试三个 Python 来源：项目内 `.venv` → 本机 WorkBuddy 自带运行环境 → 系统 PATH。

---

## 一、快速启动

### 0. 前置条件

- Python 3.13+，依赖：`fastapi`、`uvicorn`、`psycopg2-binary`、`pydantic`（已列在 `requirements.txt`）
- PostgreSQL 17，已完成业务数据导入（`导入实例三.py`）与应用表初始化（`sql/01_schema.sql` + `sql/02_seed.sql`）
- 应用库表使用独立 schema `app`（与业务数据 schema `文件夹` 分离）

### 1. 初始化（首次）

```bash
# ① 建应用表（sys_* / meta_* / fin_* / rpt_* / bud_* / wf_* / ai_* 共 25 张）
python manage.py init

# ② 写入种子数据（6 账号、31 指标、20 下钻映射、6 预警规则、8 报表定义、12 AI 评测集）
#    init 已自动执行 02_seed.sql；如需重置演示数据：
python manage.py reset-demo

# ③ 环境自检（连接池 / 关键表 / 视图可达性）
python manage.py check
```

数据库连接等配置可用环境变量覆盖（见 `server/config.py`）：

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `FS_DB_HOST` | `127.0.0.1` | PostgreSQL 主机 |
| `FS_DB_PORT` | `5432` | 端口 |
| `FS_DB_NAME` | 实例三库 | 库名 |
| `FS_DB_USER` / `FS_DB_PWD` | — | 连接凭据 |
| `FS_JWT_SECRET` | 内置开发密钥 | **生产必须更换** |
| `FS_API_PREFIX` | `/api/v1` | API 前缀 |
| `FS_PORT` | `8021` | 服务端口 |

### 2. 启动

```bash
python run.py --port 8021          # 开发启动
python run.py --port 8021 --reload # 热重载
```

浏览器打开 `http://127.0.0.1:8021`。

### 3. 演示账号（统一口令 `Fin@2026`）

| 登录名 | 角色 | 部门 | 职级 | 体验要点 |
|---|---|---|---|---|
| `chenjing` | cfo | 总部 | 专家 | 全量数据 + 全功能，可看成本/职级映射 |
| `lizhe` | fin_bp | 财务BP组 | 高级 | 预算编制、滚动预测、预警规则维护 |
| `wanglin` | sales_mgr | 华东销售 | 主管 | 数据收敛到华东、金额阈值 200 万 |
| `zhangchen` | cs_mgr | 华南客服 | 主管 | 客户成功视角、续约/健康度 |
| `zhoumin` | accountant | 财务共享 | 初级 | depth=summary、金额隐藏、客户名脱敏 |
| `wanglei` | admin | 总部 | 专家 | 系统管理全权 |

便捷登录：`http://127.0.0.1:8021/?demo=chenjing#overview`

---

## 二、目录结构

```
finance-system/
├── 启动系统.bat              # ★ 双击即用：环境自检 + 启动 + 打开浏览器
├── requirements.txt          # 运行依赖
├── run.py                    # 启动脚本（命令行）
├── manage.py                 # init / reset-demo / check 运维命令
├── sql/
│   ├── 01_schema.sql         # app schema 25 张应用表
│   └── 02_seed.sql           # 种子数据（账号/指标/下钻/预警/报表/审批流/评测集）
├── server/
│   ├── main.py               # FastAPI 入口：lifespan 自检、request_id、静态托管
│   ├── config.py             # 环境变量配置
│   ├── db.py                 # 连接池 + 只读事务 + 中文列名 % 转义（_prepare）
│   ├── security.py           # PBKDF2 口令哈希 + HMAC-SHA256 JWT
│   ├── permissions.py        # 三维权限引擎（角色×部门×职级）
│   ├── response.py / deps.py # 统一响应信封 / 认证依赖
│   ├── services/
│   │   ├── common.py         # 期间解析/切换/状态/数据版本
│   │   ├── statement.py      # 利润表树 + 勾稽校验 + KPI 卡
│   │   ├── drill.py          # 配置驱动下钻（group_names/group_cols）
│   │   └── ai_engine.py      # AI 问数：语义解析 + 六道闸门
│   └── routers/              # 12 个路由模块，61 个端点
├── web/                      # 前端（无构建，直接静态托管）
│   ├── index.html
│   ├── css/app.css
│   └── js/
│       ├── app.js            # 路由/登录/骨架
│       ├── api.js            # fetch 封装 + 自动 refresh
│       ├── core.js           # 状态/格式化/弹层/表格组件
│       ├── charts.js         # 手写 SVG：趋势/瀑布/环形/条形/账龄
│       └── views/            # 10 个页面模块
└── tests/smoke.py            # 50 项 HTTP 冒烟测试
```

---

## 三、接口清单（前缀 `/api/v1`）

### 认证 `/auth`
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/auth/login` | 登录，返回 accessToken/refreshToken |
| POST | `/auth/refresh` | 刷新令牌 |
| GET | `/auth/me` | 当前用户 + 权限/数据范围 |
| POST | `/auth/logout` | 登出（审计） |
| GET | `/auth/demo-accounts` | 演示账号列表 |

### 经营驾驶舱 `/overview`
`GET /overview/kpi`（8 张 KPI 卡含环比/同比/spark）· `GET /overview/statement`（利润表树+勾稽校验）· `GET /overview/statement/drill`（逐级下钻）· `GET /overview/charts` · `GET /overview/alerts` · `GET /overview/quality`（数据质量体检）

### 客户分析 `/customer`
`GET /customer/profile`（分层/健康度/行业分布）· `GET /customer/top`（重点客户 360）· `GET /customer/{id}/detail`

### 应收与回款 `/ar`
`GET /ar/overview` · `GET /ar/aging`（账龄桶）· `GET /ar/overdue`（逾期清单，分页）· `GET /ar/renewal-calendar`（续约日历，以数据期末为基准）· `POST /ar/assign`（批量派单）

### 成本 `/cost`
`GET /cost/structure` · `GET /cost/center`

### 预算 `/budget`
`GET /budget/versions` · `GET /budget/detail`（三因素差异）· `POST /budget/draft`（草稿提交）· `GET /budget/forecast` · `POST /budget/forecast` · `GET /budget/lines` · `POST /budget/submit` · `GET /budget/adjustments` · `POST /budget/adjustments`

### AI 分析 `/ai`
`POST /ai/ask`（六道闸门问数）· `GET /ai/sessions` · `GET /ai/sessions/{id}/messages` · `GET /ai/suggest` · `GET /ai/eval-cases` · `POST /ai/eval-run`

### 报表 `/reports`
`GET /reports` · `GET /reports/runs` · `POST /reports/{id}/run` · `POST /reports/{id}/subscribe`

### 预警 `/alerts`
`GET /alerts` · `POST /alerts/{id}/ack`（确认/关闭）· `GET|PUT /alerts/rules`

### 系统管理 `/admin`
用户 CRUD ×2、角色、部门、职级映射（depth/amount_threshold/field_mask）、数据范围、审计日志，共 9 端点。

**统一响应信封**：`{code, message, data, meta, requestId}`；错误码：`40001` 参数错误 / `40101` 未认证 / `40301` 无权限 / `40302` 超金额阈值 / `50001` 指标未命中 / `50002` 建议问法。

---

## 四、核心设计说明

### 1. 三维权限模型

```
角色（能做什么）  ×  部门（能看多宽）  ×  职级（能看多深）
  sys_role          sys_data_scope       sys_grade_scope
```

- **部门维度**：`sys_data_scope` 沿组织树向上找 region，SQL 层注入 `region_sql`
- **职级维度**：`depth`（doc 单据 / detail 明细 / summary 汇总）、`amount_threshold`（超阈值折叠 `fold_by_threshold` 而非隐藏）、`field_mask`（salary hidden / customer_name mask / amount hidden）
- **角色覆盖**：`ROLE_DEPTH_OVERRIDE`（cfo/admin 强制 doc，fin_bp 不限制）
- 所有拒绝均写 `ops_audit_log`（含 403 审计）

### 2. 语义层

- `meta_metric`：31 条指标字典（名称→口径 SQL/维度/单位），AI 问数与图表共用同一套口径
- `meta_drill_map`：20 条下钻映射（视图、分组列、指标列）
- `meta_metric_version`：口径版本化，口径变更留痕

### 3. AI 六道闸门

`G1 数据范围`（注入 region/depth）→ `G2 指标白名单`（只允许命中 meta_metric）→ `G3 时间范围`（期间解析到 fin_period）→ `G4 行数上限` → `G5 敏感字段`（按 field_mask）→ `G6 只读与注入防护`（仅 SELECT、白名单列名）。
当前为规则引擎实现，接口预留 LLM 替换点（`ai_engine.find_metric/find_period`）。问数会话落库 `ai_session`/`ai_message`，评测集 `ai_eval_case` 支持 `POST /ai/eval-run` 回归。

### 4. 数据访问层要点

- 连接池默认只读事务，写操作显式提交流程，杜绝误写业务库
- `_prepare()` 处理中文列名中的 `%` 与占位符冲突（哨兵替换方案）
- 金额表达式非聚合时自动包 `SUM()`，避免 GROUP BY 报错

### 5. 前端

- 原生 ES Module，无构建工具；`charts.js` 手写 SVG 图表（趋势双轴/瀑布/环形/条形/账龄）
- 环比/同比异常处理：经营利润扭亏时同比置空，显示「扭亏/转亏」标签（`turnTag`）
- 续约日历以「数据期末次月 1 日」为基准，避免演示数据停在 2025-12 时永远为空

---

## 五、测试

```bash
python tests/smoke.py
```

48 项冒烟测试覆盖 7 组：认证（含 40101）、经营驾驶舱（KPI/利润表勾稽/下钻/质量）、客户与应收、AI 语义层（六道闸门/未命中建议）、三维权限（华东收敛/阈值/脱敏/40301/审计）、预警与审计、语义模型与数据管理（指标字典 31 条/版本沿革/下钻映射/长表取数/资产盘点/关系地图/期间管理/越权拒绝）。
当前结果：**50 通过 / 0 失败**。

## 十二、Data Agent 模式（自主查数计算分析）

在 DeepSeek 意图解析之上的升级（框架 L2：Agent Loop + 工具调用）。入口：`POST /api/v1/ai/agent`，前端 AI 分析页在配置 LLM 后自动切换。

**三个通用工具**（`server/services/agent.py`）：

1. **query_data_dictionary** — 数据字典查询：`objects`（全部表/视图+行数+注释）、`columns`（指定对象字段明细）、`metrics`（31 条指标字典）。LLM 写 SQL 前自主查阅，不再依赖预注入。
2. **run_sql** — 自由只读查询：单条 SELECT/WITH，安全防线层层强制——SELECT-only 关键词黑名单 → FROM/JOIN 对象白名单（数据字典内）→ 敏感列（薪酬/个人信息）非 CFO 拒绝 → `BEGIN READ ONLY` 只读事务 → statement_timeout 8s → 强制 LIMIT ≤200 → 返回 LLM 最多 40 行。
3. **explain_sql** — 性能验证：EXPLAIN ANALYZE 返回计划/执行耗时、成本、实际行数，<200ms 良好 / <1s 可接受 / 否则建议优化。

**Agent Loop**：最多 6 次工具调用、总预算 60s，超限强制汇总收尾；每次回答返回完整工具执行轨迹（步骤、耗时、结果摘要），前端时间线可视化。

**实测能力**（规则引擎做不到的）：
- 口语理解：「上个季度赚了多少钱」→ 经营利润；
- 自主探查：先查字典确认字段再写 SQL，不猜列名；
- 归因分析：「为什么毛利率比上月下降」→ 自主对比两月数据，定位到客户成功成本 +39.9%、技术支持成本 +41.5% 贡献 77% 成本增量；
- 越权透明处理：部门受限用户查大区对象被 G1 拦截后，Agent 如实说明限制并改用可查口径回答。

**安全设计**：LLM 只能通过三工具触达数据库；六道闸门全部下沉到工具层强制执行，无法被提示词绕过；所有工具调用记入审计日志（action=ai/agent）。

## 十一、DeepSeek 大模型接入（AI 分析）

按官方文档（https://api-docs.deepseek.com/zh-cn/）接入，OpenAI 兼容格式：

- **配置**：项目根目录复制 `.env.example` 为 `.env`，填入 `DEEPSEEK_API_KEY=sk-xxx`（在 platform.deepseek.com/api_keys 申请），重启服务即生效；也可用同名环境变量。默认模型 `deepseek-flash`，可用 `DEEPSEEK_MODEL` 覆盖（如 `deepseek-v4-pro`）。
- **安全边界**（Data Agent 框架 L1）：LLM **只做意图解析**——从问句识别「指标 / 维度 / 期间」并输出 JSON；输出经白名单严格校验（metric_code 必须在 31 条指标字典内、dim 必须在维度计划内），**不生成 SQL、不接触数据、不做算术**。取数与六道闸门全部在服务端语义层执行。
- **降级策略**：未配置密钥、网络失败、LLM 返回不合法时自动回落语义层规则引擎，问答永不停摆；回答里的「引擎」标签会注明当前用的是 DeepSeek 还是规则兜底。
- **状态查询**：`GET /api/v1/ai/status` 返回 enabled / model / baseUrl（不回传密钥）。
- 客户端实现：`server/services/llm.py`（标准库 urllib，零新增依赖）；意图解析：`server/services/ai_engine.py::llm_intent`。

---

## 六、与原型的关系

`../prototype/index.html`（v0.95）为静态单文件原型，仅用于需求评审。
本工程是其产品化落地：10 个页面全部对接真实 API，权限、闸门、预算工作流、AI 问数均为真实实现。

## 七、后续路线（见开发文档 V1.2 第 13 章）

1. AI 规则引擎 → LLM 路由替换（保留六道闸门）
2. 报表引擎对接真实导出（当前为定义+运行记录）
3. 审批流 `wf_flow/wf_task` 接入预算提交节点
4. WebSocket 实时预警推送
5. 生产部署：HTTPS、FS_JWT_SECRET 更换、连接池参数调优
