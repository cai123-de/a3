-- =============================================================
-- 语义层轻量原生方案：sem_* 视图套件
-- 前提：应用内轻量原生方案（不引入外部语义引擎）
-- 组成：
--   1) sem_relation      表关系字典（ER 关系 + 业务链路，VALUES 视图）
--   2) sem_metric_dict   指标字典（meta_metric + 最新口径版本，跨 app schema）
--   3) sem_metric_wide   月度指标宽表（18 指标 + 3 个环比，1 行 = 1 月）
--   4) sem_metric_long   月度指标长表（period/metric_code/value，AI·BI 友好）
-- 约定：period 统一 'YYYY-MM' 文本；金额元；比率%；可重复执行
-- =============================================================

-- -------------------------------------------------------------
-- 1) 表关系字典：25 张表 + 19 视图的关联地图（人工维护的元数据）
--    供 AI agent 规划 JOIN、BI 建模、新人理解数据血缘
-- -------------------------------------------------------------
CREATE OR REPLACE VIEW "文件夹".sem_relation AS
SELECT * FROM (VALUES
    -- ===== 维度 → 事实（直接外键，摘自数据字典 ER 图）=====
    ('dim_date',           '日期键',     'fact_subscription',     '订阅起始日期', '1:N', '日期维度'),
    ('dim_customer',       '客户ID',     'fact_subscription',     '客户ID',       '1:N', '客户主数据'),
    ('dim_customer',       '客户ID',     'fact_billing',          '客户ID',       '1:N', '客户主数据'),
    ('dim_customer',       '客户ID',     'fact_payment',          '客户ID',       '1:N', '客户主数据'),
    ('dim_customer',       '客户ID',     'fact_ar_aging',         '客户ID',       '1:N', '客户主数据'),
    ('dim_customer',       '客户ID',     'fact_opportunity',      '客户ID',       '1:N', '已赢机会才有客户ID（潜在客户为空）'),
    ('dim_customer',       '客户ID',     'fact_addon_service',    '客户ID',       '1:N', '客户主数据'),
    ('dim_customer',       '客户ID',     'fact_customer_health',  '客户ID',       '1:N', '客户主数据'),
    ('dim_customer',       '客户ID',     'fact_support_ticket',   '客户ID',       '1:N', '客户主数据'),
    ('dim_customer',       '客户ID',     'fact_usage',            '客户ID',       '1:N', '客户主数据'),
    ('dim_customer',       '客户ID',     'fact_cogs',             '客户ID',       '1:N', '客户主数据'),
    ('dim_product',        '产品ID',     'fact_subscription',     '产品ID',       '1:N', '订阅类产品 P0001-P0009'),
    ('dim_product',        '产品ID',     'fact_billing',          '产品ID',       '1:N', '产品维度'),
    ('dim_product',        '产品ID',     'fact_revenue',          '产品ID',       '1:N', '产品维度'),
    ('dim_product',        '产品ID',     'fact_usage',            '产品ID',       '1:N', '产品维度'),
    ('dim_product',        '产品ID',     'fact_addon_service',    '产品ID',       '1:N', '服务类产品 P0010-P0015'),
    ('dim_product',        '产品ID',     'fact_opportunity',      '产品ID',       '1:N', '产品维度'),
    ('dim_product',        '产品ID',     'fact_customer_health',  '产品ID',       '1:N', '产品维度'),
    ('dim_product',        '产品ID',     'fact_support_ticket',   '产品ID',       '1:N', '产品维度'),
    ('dim_product',        '产品ID',     'fact_cogs',             '产品ID',       '1:N', '产品维度'),
    ('dim_product',        '产品ID',     'fact_revenue_budget',   '产品ID',       '1:N', '收入预算'),
    ('dim_product',        '产品ID',     'fact_cost_budget',      '产品ID',       '1:N', '成本预算'),
    ('dim_employee',       '员工ID',     'fact_subscription',     '员工ID',       '1:N', '销售业绩归属'),
    ('dim_employee',       '员工ID',     'fact_billing',          '员工ID',       '1:N', '销售归属'),
    ('dim_employee',       '员工ID',     'fact_revenue',          '员工ID',       '1:N', '销售归属'),
    ('dim_employee',       '员工ID',     'fact_opportunity',      '员工ID',       '1:N', '销售归属'),
    ('dim_employee',       '员工ID',     'fact_addon_service',    '员工ID',       '1:N', '销售归属'),
    ('dim_employee',       '员工ID',     'fact_employee_payroll', '员工ID',       '1:N', '薪酬发放'),
    ('dim_employee',       '员工ID',     'fact_service_timesheet','员工ID',       '1:N', '服务工时'),
    ('dim_employee',       '员工ID',     'fact_support_ticket',   '处理人ID',     '1:N', '工单处理人'),
    ('dim_account',        '科目ID',     'fact_expense',          '科目ID',       '1:N', '费用科目（二级）'),
    ('dim_account',        '科目ID',     'fact_budget',           '科目ID',       '1:N', '费用预算'),
    ('dim_cost_center',    '成本中心ID', 'fact_expense',          '成本中心ID',   '1:N', '费用组织'),
    ('dim_cost_center',    '成本中心ID', 'dim_employee',          '成本中心ID',   '1:N', '员工归属成本中心'),
    ('dim_project',        '项目ID',     'fact_expense',          '项目ID',       '1:N', '研发项目（可空）'),
    -- ===== 事实 → 事实（业务链路，无直接外键，JOIN 需按规则）=====
    ('fact_revenue',       '订阅ID',     'fact_subscription',     '订阅ID',       'N:1', '摊销明细归属订阅合同'),
    ('fact_payment',       '开票ID',     'fact_billing',          '开票ID',       'N:1', '一张发票可拆多笔收款'),
    ('fact_opportunity',   '实际成交金额','fact_subscription',    '合同金额ACV',  '1:1', '已赢机会金额 = 订阅ACV（业务链路）'),
    ('fact_subscription',  '订阅ID',     'fact_billing',          '业务ID',       '1:N', '⚠️ 业务ID为多态外键：按开票类型分别JOIN订阅/服务/一次性'),
    ('fact_addon_service', '订单ID',     'fact_billing',          '业务ID',       '1:N', '⚠️ 多态外键（同上，服务类型分支）'),
    ('fact_cloud_billing', '账单月份+服务类别', 'fact_cogs',      '成本月份+成本类型', '分摊', '云账单按月份+服务类别分摊进COGS（非外键，分摊规则见数据导入说明）')
) AS t(from_table, from_col, to_table, to_col, cardinality, note);

COMMENT ON VIEW "文件夹".sem_relation IS
'sem|表关系字典：25 表 + 关键业务链路的 JOIN 地图。from_table.from_col → to_table.to_col，cardinality 为基数，note 含业务含义与多态外键警示。供 AI 规划 JOIN / BI 建模 / 血缘查阅';

-- -------------------------------------------------------------
-- 2) 指标字典视图：meta_metric + 最新口径版本信息（跨 app schema）
-- -------------------------------------------------------------
CREATE OR REPLACE VIEW "文件夹".sem_metric_dict AS
SELECT m.code                                   AS metric_code,
       m.name                                   AS metric_name,
       m.alias                                  AS aliases,
       m.definition                             AS definition,
       m.unit                                   AS unit,
       m.view_name                              AS source_view,
       m.expr                                   AS expr,
       m.default_dim                            AS default_dim,
       m.version                                AS caliber_version,
       m.owner                                  AS owner,
       m.is_active                              AS is_active,
       lv.effective_from                        AS caliber_effective_from,
       lv.change_reason                         AS last_change_reason,
       lv.approved_by                           AS last_approved_by
FROM   app.meta_metric m
LEFT JOIN LATERAL (
    SELECT mv.effective_from, mv.change_reason, mv.approved_by
    FROM   app.meta_metric_version mv
    WHERE  mv.metric_code = m.code
    ORDER  BY mv.effective_from DESC NULLS LAST
    LIMIT  1
) lv ON TRUE;

COMMENT ON VIEW "文件夹".sem_metric_dict IS
'sem|指标字典：31 条指标的编码/别名/口径定义/单位/取数表达式/版本/责任人，附最新口径版本的生效时间与审批信息。AI 问数白名单与 BI 建模的元数据源';

-- -------------------------------------------------------------
-- 3) 月度指标宽表：经营总览 15 列 ⨝ ARR 结构 4 列 + 核心环比
--    1 行 = 1 个月；对齐口径 v1.2（服务收入 v1.3 切换后自动生效）
-- -------------------------------------------------------------
CREATE OR REPLACE VIEW "文件夹".sem_metric_wide AS
SELECT o."月份"                                                          AS period,
       o."订阅收入", o."服务订单金额", o."营业收入合计",
       o."营业成本合计", o."托管成本", o."客户成功成本", o."技术支持成本",
       o."毛利", o."毛利率%", o."期间费用", o."经营利润(估)",
       o."开票金额", o."收款金额", o."期末应收余额", o."逾期应收余额",
       o."DSO天数(按30天)", o."新签合同数",
       a."ARR", a."MRR", a."在服客户数", a."在服合同数",
       ROUND((o."营业收入合计" - LAG(o."营业收入合计") OVER w)
             / NULLIF(LAG(o."营业收入合计") OVER w, 0) * 100, 2)          AS "营业收入环比%",
       ROUND((o."毛利" - LAG(o."毛利") OVER w)
             / NULLIF(LAG(o."毛利") OVER w, 0) * 100, 2)                  AS "毛利环比%",
       ROUND((a."ARR" - LAG(a."ARR") OVER w)
             / NULLIF(LAG(a."ARR") OVER w, 0) * 100, 2)                   AS "ARR环比%"
FROM   "文件夹"."V_月度经营总览" o
LEFT JOIN "文件夹"."V_月度ARR与合同结构" a ON a."月份" = o."月份"
WINDOW w AS (ORDER BY o."月份");

COMMENT ON VIEW "文件夹".sem_metric_wide IS
'sem|月度指标宽表：18 项核心指标（收入/成本/毛利/费用/利润/开票/回款/应收/逾期/DSO/新签/ARR/MRR/在服客户/在服合同）+ 营业收入/毛利/ARR 三个环比，1 行 = 1 个月。人工对数与报表直连的首选';

-- -------------------------------------------------------------
-- 4) 月度指标长表：period / metric_code / value 统一长表
--    AI·BI 友好：查任意指标都是同一条 SQL 模板
-- -------------------------------------------------------------
CREATE OR REPLACE VIEW "文件夹".sem_metric_long AS
SELECT "月份"::TEXT AS period, 'revenue'                AS metric_code, '营业收入'      AS metric_name, '元' AS unit, "营业收入合计"::NUMERIC(18,2)   AS value FROM "文件夹"."V_月度经营总览"
UNION ALL SELECT "月份", 'subscription_revenue', '订阅收入',      '元', "订阅收入"::NUMERIC(18,2)       FROM "文件夹"."V_月度经营总览"
UNION ALL SELECT "月份", 'service_revenue',      '服务订单收入',   '元', "服务订单金额"::NUMERIC(18,2)   FROM "文件夹"."V_月度经营总览"
UNION ALL SELECT "月份", 'cogs',                 '营业成本',       '元', "营业成本合计"::NUMERIC(18,2)   FROM "文件夹"."V_月度经营总览"
UNION ALL SELECT "月份", 'gross_profit',         '毛利',           '元', "毛利"::NUMERIC(18,2)           FROM "文件夹"."V_月度经营总览"
UNION ALL SELECT "月份", 'gross_margin',         '毛利率',         '%',  "毛利率%"::NUMERIC(18,2)        FROM "文件夹"."V_月度经营总览"
UNION ALL SELECT "月份", 'opex',                 '期间费用',       '元', "期间费用"::NUMERIC(18,2)       FROM "文件夹"."V_月度经营总览"
UNION ALL SELECT "月份", 'op_profit',            '经营利润',       '元', "经营利润(估)"::NUMERIC(18,2)   FROM "文件夹"."V_月度经营总览"
UNION ALL SELECT "月份", 'billing',              '开票额',         '元', "开票金额"::NUMERIC(18,2)       FROM "文件夹"."V_月度经营总览"
UNION ALL SELECT "月份", 'collection',           '回款额',         '元', "收款金额"::NUMERIC(18,2)       FROM "文件夹"."V_月度经营总览"
UNION ALL SELECT "月份", 'ar_balance',           '期末应收余额',   '元', "期末应收余额"::NUMERIC(18,2)   FROM "文件夹"."V_月度经营总览"
UNION ALL SELECT "月份", 'ar_overdue',           '逾期应收余额',   '元', "逾期应收余额"::NUMERIC(18,2)   FROM "文件夹"."V_月度经营总览"
UNION ALL SELECT "月份", 'dso',                  'DSO',            '天', "DSO天数(按30天)"::NUMERIC(18,2) FROM "文件夹"."V_月度经营总览"
UNION ALL SELECT "月份", 'new_contracts',        '新签合同数',     '个', "新签合同数"::NUMERIC(18,2)     FROM "文件夹"."V_月度经营总览"
UNION ALL SELECT "月份", 'arr',                  'ARR',            '元', "ARR"::NUMERIC(18,2)            FROM "文件夹"."V_月度ARR与合同结构"
UNION ALL SELECT "月份", 'mrr',                  'MRR',            '元', "MRR"::NUMERIC(18,2)            FROM "文件夹"."V_月度ARR与合同结构"
UNION ALL SELECT "月份", 'active_customers',     '在服客户数',     '个', "在服客户数"::NUMERIC(18,2)     FROM "文件夹"."V_月度ARR与合同结构"
UNION ALL SELECT "月份", 'active_contracts',     '在服合同数',     '个', "在服合同数"::NUMERIC(18,2)     FROM "文件夹"."V_月度ARR与合同结构";

COMMENT ON VIEW "文件夹".sem_metric_long IS
'sem|月度指标长表：18 项核心指标的 EAV 长表（period/metric_code/metric_name/unit/value），metric_code 与 app.meta_metric 及口径卡 MC 编号一一对应。AI 取数与 BI 通用查询的首选：SELECT * WHERE metric_code=? AND period BETWEEN ? AND ?';
