-- =============================================================
-- 财务管理系统 · 应用层表结构（schema: app）
-- 数据层仍沿用「实例三 / 文件夹」schema 的 25 张表与 19 个视图，不在此重复创建
-- 执行：psql -f sql/01_schema.sql  或  python manage.py init
-- =============================================================

CREATE SCHEMA IF NOT EXISTS app;

-- -------------------------------------------------------------
-- 1. 组织 / 角色 / 职级（三维权限模型的三个维度）
-- -------------------------------------------------------------
DROP TABLE IF EXISTS app.sys_user CASCADE;
DROP TABLE IF EXISTS app.sys_dept CASCADE;
DROP TABLE IF EXISTS app.sys_role CASCADE;
DROP TABLE IF EXISTS app.sys_grade_scope CASCADE;
DROP TABLE IF EXISTS app.sys_data_scope CASCADE;
DROP TABLE IF EXISTS app.sys_login_log CASCADE;

CREATE TABLE app.sys_dept (
    code        VARCHAR(32) PRIMARY KEY,
    name        VARCHAR(64) NOT NULL,
    parent_code VARCHAR(32),
    region      VARCHAR(32),          -- 映射到 dim_customer.所在大区，NULL 表示不限
    kind        VARCHAR(16) NOT NULL DEFAULT 'dept',   -- dept / region / cost_center
    sort_no     SMALLINT NOT NULL DEFAULT 0
);
COMMENT ON TABLE app.sys_dept IS '组织树：部门、大区、成本中心，用于数据权限的「宽度」';

CREATE TABLE app.sys_role (
    code       VARCHAR(32) PRIMARY KEY,
    name       VARCHAR(64) NOT NULL,
    level      SMALLINT NOT NULL DEFAULT 10,   -- 数值越小权限越大，仅用于排序展示
    perms      JSONB NOT NULL DEFAULT '[]'::jsonb,  -- 功能权限码列表，支持 * 通配
    note       TEXT
);
COMMENT ON TABLE app.sys_role IS '角色：决定「能做什么」（功能权限）';

CREATE TABLE app.sys_grade_scope (
    grade            VARCHAR(16) PRIMARY KEY,   -- 与 dim_employee.职级 取值一致
    rank             SMALLINT NOT NULL,         -- 0 最高
    depth            VARCHAR(16) NOT NULL,      -- summary 只看汇总 / detail 可看明细 / doc 可到单据
    amount_threshold NUMERIC(18,2),             -- 单笔可见金额阈值，NULL 表示不限
    field_mask       JSONB NOT NULL DEFAULT '{}'::jsonb,  -- 字段脱敏规则
    note             TEXT
);
COMMENT ON TABLE app.sys_grade_scope IS '职级：决定「能看多深」——可见深度、单笔金额阈值、敏感字段脱敏';

CREATE TABLE app.sys_user (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(32) NOT NULL UNIQUE,
    name          VARCHAR(32) NOT NULL,
    title         VARCHAR(64),
    password_hash VARCHAR(128) NOT NULL,
    password_salt VARCHAR(64) NOT NULL,
    role_code     VARCHAR(32) NOT NULL REFERENCES app.sys_role(code),
    dept_code     VARCHAR(32) REFERENCES app.sys_dept(code),
    grade         VARCHAR(16) NOT NULL REFERENCES app.sys_grade_scope(grade),
    email         VARCHAR(96),
    status        VARCHAR(12) NOT NULL DEFAULT 'active',   -- active / disabled
    must_change_pwd BOOLEAN NOT NULL DEFAULT FALSE,
    last_login_at TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE app.sys_user IS '用户：角色 + 部门 + 职级 三者共同决定可见数据';

CREATE TABLE app.sys_data_scope (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES app.sys_user(id) ON DELETE CASCADE,
    scope_type VARCHAR(16) NOT NULL,   -- customer / region / project / dept
    scope_value VARCHAR(64) NOT NULL,
    effect     VARCHAR(8) NOT NULL DEFAULT 'allow',  -- allow / deny（deny 优先级最高）
    expire_at  DATE,
    reason     TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_data_scope_user ON app.sys_data_scope(user_id, effect);
COMMENT ON TABLE app.sys_data_scope IS '数据权限例外：显式授权（跨部门协作、代管）与黑名单（deny）';

CREATE TABLE app.sys_login_log (
    id         BIGSERIAL PRIMARY KEY,
    username   VARCHAR(32),
    ok         BOOLEAN NOT NULL,
    ip         VARCHAR(64),
    ua         VARCHAR(200),
    reason     VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -------------------------------------------------------------
-- 2. 指标字典 / 下钻映射 / 口径版本（语义层）
-- -------------------------------------------------------------
DROP TABLE IF EXISTS app.meta_metric CASCADE;
DROP TABLE IF EXISTS app.meta_metric_version CASCADE;
DROP TABLE IF EXISTS app.meta_drill_map CASCADE;

CREATE TABLE app.meta_metric (
    code         VARCHAR(48) PRIMARY KEY,
    name         VARCHAR(64) NOT NULL,
    alias        TEXT NOT NULL DEFAULT '',       -- 同义词，供 AI 实体识别，逗号分隔
    definition   TEXT NOT NULL,                  -- 口径说明（展示在 ⓘ 与 AI 回答的 meta 里）
    unit         VARCHAR(16) NOT NULL DEFAULT '元',
    view_name    VARCHAR(64) NOT NULL,
    expr         TEXT NOT NULL,                  -- 取值表达式（字段或聚合式）
    default_dim  VARCHAR(32),
    version      VARCHAR(12) NOT NULL DEFAULT 'v1.0',
    owner        VARCHAR(32),
    is_active    BOOLEAN NOT NULL DEFAULT TRUE
);
COMMENT ON TABLE app.meta_metric IS '指标字典：AI 与前端共用的唯一口径来源，禁止在代码里硬编码口径';

CREATE TABLE app.meta_metric_version (
    id           SERIAL PRIMARY KEY,
    metric_code  VARCHAR(48) NOT NULL REFERENCES app.meta_metric(code) ON DELETE CASCADE,
    version      VARCHAR(12) NOT NULL,
    definition   TEXT NOT NULL,
    effective_from DATE NOT NULL,
    effective_to   DATE,
    change_reason  TEXT,
    approved_by    VARCHAR(32),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (metric_code, version)
);

CREATE TABLE app.meta_drill_map (
    id          SERIAL PRIMARY KEY,
    parent_path VARCHAR(64) NOT NULL,   -- 父节点路径，如 revenue.subscription
    dim         VARCHAR(32) NOT NULL,   -- 下钻维度：product / region / customer / month / account ...
    label       VARCHAR(64) NOT NULL,   -- 维度中文名，前端展示
    view_name   VARCHAR(64) NOT NULL,
    group_cols  TEXT NOT NULL,          -- 逗号分隔的分组列
    amount_expr TEXT NOT NULL,          -- 金额表达式
    extra_where TEXT,                   -- 追加过滤，支持 :period :region :user 占位
    sort_no     SMALLINT NOT NULL DEFAULT 0,
    UNIQUE (parent_path, dim)
);
COMMENT ON TABLE app.meta_drill_map IS '下钻映射：新增一层下钻是配置工作，不是开发工作';

-- -------------------------------------------------------------
-- 3. 期间与关账
-- -------------------------------------------------------------
DROP TABLE IF EXISTS app.fin_period CASCADE;
CREATE TABLE app.fin_period (
    period    VARCHAR(7) PRIMARY KEY,   -- YYYY-MM
    status    VARCHAR(12) NOT NULL DEFAULT 'open',  -- open / closing / closed
    closed_at TIMESTAMPTZ,
    closed_by VARCHAR(32),
    note      TEXT
);

-- -------------------------------------------------------------
-- 4. 预警
-- -------------------------------------------------------------
DROP TABLE IF EXISTS app.sys_alert_rule CASCADE;
DROP TABLE IF EXISTS app.sys_alert CASCADE;

CREATE TABLE app.sys_alert_rule (
    code       VARCHAR(32) PRIMARY KEY,
    name       VARCHAR(96) NOT NULL,
    category   VARCHAR(24) NOT NULL,
    expr       TEXT NOT NULL,            -- 规则说明（阈值、窗口）
    level      VARCHAR(8) NOT NULL,      -- high / mid / low
    channel    VARCHAR(48) NOT NULL DEFAULT '站内',
    owner_role VARCHAR(32),
    enabled    BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE app.sys_alert (
    id          SERIAL PRIMARY KEY,
    rule_code   VARCHAR(32) REFERENCES app.sys_alert_rule(code),
    level       VARCHAR(8) NOT NULL,
    title       VARCHAR(128) NOT NULL,
    detail      TEXT,
    metric_code VARCHAR(48),
    period      VARCHAR(7),
    object_id   VARCHAR(64),             -- 关联客户 / 产品 / 科目
    amount      NUMERIC(18,2),
    status      VARCHAR(16) NOT NULL DEFAULT 'open',  -- open / ack / closed
    owner       VARCHAR(32),
    handle_note TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at   TIMESTAMPTZ
);
CREATE INDEX idx_alert_status ON app.sys_alert(status, level, created_at DESC);

-- -------------------------------------------------------------
-- 5. 审计与安全
-- -------------------------------------------------------------
DROP TABLE IF EXISTS app.ops_audit_log CASCADE;
CREATE TABLE app.ops_audit_log (
    id         BIGSERIAL PRIMARY KEY,
    user_id    INTEGER,
    username   VARCHAR(32),
    action     VARCHAR(48) NOT NULL,     -- login / view / export / query / deny / update
    object     VARCHAR(96),
    detail     JSONB,
    ip         VARCHAR(64),
    request_id VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_time ON app.ops_audit_log(created_at DESC);
CREATE INDEX idx_audit_user ON app.ops_audit_log(username, created_at DESC);

-- -------------------------------------------------------------
-- 6. 报表中心
-- -------------------------------------------------------------
DROP TABLE IF EXISTS app.rpt_definition CASCADE;
DROP TABLE IF EXISTS app.rpt_run CASCADE;
DROP TABLE IF EXISTS app.rpt_subscription CASCADE;

CREATE TABLE app.rpt_definition (
    code      VARCHAR(32) PRIMARY KEY,
    name      VARCHAR(96) NOT NULL,
    category  VARCHAR(24) NOT NULL,
    owner     VARCHAR(32),
    cron      VARCHAR(32),
    formats   VARCHAR(64) NOT NULL DEFAULT 'xlsx,pdf',
    note      TEXT
);

CREATE TABLE app.rpt_run (
    id          BIGSERIAL PRIMARY KEY,
    report_code VARCHAR(32) NOT NULL REFERENCES app.rpt_definition(code),
    period      VARCHAR(7),
    status      VARCHAR(16) NOT NULL,     -- success / failed / running
    row_count   INTEGER,
    cost_ms     INTEGER,
    file_name   VARCHAR(128),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_rpt_run_time ON app.rpt_run(created_at DESC);

CREATE TABLE app.rpt_subscription (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES app.sys_user(id) ON DELETE CASCADE,
    report_code VARCHAR(32) NOT NULL REFERENCES app.rpt_definition(code),
    cron        VARCHAR(32) NOT NULL,
    channel     VARCHAR(32) NOT NULL DEFAULT '邮件',
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, report_code)
);

-- -------------------------------------------------------------
-- 7. 预算编制（二期写操作，本期先落表 + 审批流）
-- -------------------------------------------------------------
DROP TABLE IF EXISTS app.bud_line CASCADE;
DROP TABLE IF EXISTS app.bud_header CASCADE;
DROP TABLE IF EXISTS app.bud_adjust CASCADE;
DROP TABLE IF EXISTS app.bud_forecast CASCADE;
DROP TABLE IF EXISTS app.wf_task CASCADE;
DROP TABLE IF EXISTS app.wf_flow CASCADE;

CREATE TABLE app.bud_header (
    id           SERIAL PRIMARY KEY,
    version      VARCHAR(24) NOT NULL,     -- 年初预算 / Q1调整 ...
    period_year  SMALLINT NOT NULL,
    unit_type    VARCHAR(16) NOT NULL,      -- dept / region / product
    unit_code    VARCHAR(32) NOT NULL,
    status       VARCHAR(16) NOT NULL DEFAULT 'draft',  -- draft / submitted / balancing / approved / issued / adjusting
    round_no     SMALLINT NOT NULL DEFAULT 1,
    submitted_by INTEGER REFERENCES app.sys_user(id),
    submitted_at TIMESTAMPTZ,
    total_amount NUMERIC(18,2),
    UNIQUE (version, period_year, unit_type, unit_code)
);

CREATE TABLE app.bud_line (
    id          BIGSERIAL PRIMARY KEY,
    header_id   INTEGER NOT NULL REFERENCES app.bud_header(id) ON DELETE CASCADE,
    subject     VARCHAR(48) NOT NULL,       -- 科目ID / 产品ID / 收入类型
    subject_name VARCHAR(96),
    month       VARCHAR(7) NOT NULL,
    draft_amount NUMERIC(18,2) NOT NULL DEFAULT 0,   -- 申报
    approved_amount NUMERIC(18,2),                   -- 批复
    adjust_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    note        VARCHAR(200)
);
CREATE INDEX idx_bud_line_header ON app.bud_line(header_id, month);

CREATE TABLE app.bud_adjust (
    id          SERIAL PRIMARY KEY,
    doc_no      VARCHAR(32) NOT NULL UNIQUE,
    header_id   INTEGER NOT NULL REFERENCES app.bud_header(id),
    kind        VARCHAR(16) NOT NULL,     -- increase / decrease / transfer
    from_subject VARCHAR(48),
    to_subject   VARCHAR(48),
    amount       NUMERIC(18,2) NOT NULL,
    reason       TEXT,
    status       VARCHAR(16) NOT NULL DEFAULT 'pending',
    created_by   INTEGER REFERENCES app.sys_user(id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_at  TIMESTAMPTZ
);

CREATE TABLE app.bud_forecast (
    id          SERIAL PRIMARY KEY,
    version     VARCHAR(24) NOT NULL,
    subject     VARCHAR(48) NOT NULL,
    month       VARCHAR(7) NOT NULL,
    forecast_amount NUMERIC(18,2) NOT NULL,
    factor      NUMERIC(6,4) NOT NULL DEFAULT 1.0,
    updated_by  INTEGER REFERENCES app.sys_user(id),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (version, subject, month)
);

CREATE TABLE app.wf_flow (
    code       VARCHAR(32) PRIMARY KEY,
    name       VARCHAR(96) NOT NULL,
    doc_type   VARCHAR(32) NOT NULL,
    nodes      JSONB NOT NULL,          -- [{node,role,threshold}]
    note       TEXT
);

CREATE TABLE app.wf_task (
    id          BIGSERIAL PRIMARY KEY,
    flow_code   VARCHAR(32) NOT NULL REFERENCES app.wf_flow(code),
    doc_type    VARCHAR(32) NOT NULL,
    doc_id      INTEGER NOT NULL,
    node        VARCHAR(32) NOT NULL,
    approver_id INTEGER REFERENCES app.sys_user(id),
    action      VARCHAR(16),            -- approve / reject / pending
    comment     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    acted_at    TIMESTAMPTZ
);
CREATE INDEX idx_wf_task_approver ON app.wf_task(approver_id, action);

-- -------------------------------------------------------------
-- 8. AI 会话与评测集
-- -------------------------------------------------------------
DROP TABLE IF EXISTS app.ai_message CASCADE;
DROP TABLE IF EXISTS app.ai_session CASCADE;
DROP TABLE IF EXISTS app.ai_eval_case CASCADE;

CREATE TABLE app.ai_session (
    id         VARCHAR(32) PRIMARY KEY,
    user_id    INTEGER REFERENCES app.sys_user(id),
    title      VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE app.ai_message (
    id         BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(32) NOT NULL REFERENCES app.ai_session(id) ON DELETE CASCADE,
    role       VARCHAR(12) NOT NULL,     -- user / assistant
    content    TEXT NOT NULL,
    meta       JSONB,                    -- thinking / sql / metric / rows / gates
    feedback   SMALLINT,                 -- 1 有用 / -1 没用
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_ai_msg_session ON app.ai_message(session_id, created_at);

CREATE TABLE app.ai_eval_case (
    id        SERIAL PRIMARY KEY,
    question  VARCHAR(200) NOT NULL,
    metric_code VARCHAR(48),
    dims      VARCHAR(96),
    period    VARCHAR(16),
    expected  NUMERIC(18,4),
    tolerance NUMERIC(6,4) NOT NULL DEFAULT 0.005,
    level     VARCHAR(4) NOT NULL DEFAULT 'L1',
    safety    BOOLEAN NOT NULL DEFAULT FALSE,
    note      TEXT
);
