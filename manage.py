"""初始化与运维脚本。

用法：
    python manage.py init        # 建应用表 + 参考数据 + 演示账号 + 预警
    python manage.py reset-demo  # 只重置演示数据（账号、预警、预算草稿）
    python manage.py check       # 连通性与结构自检
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from server import db  # noqa: E402
from server.config import settings  # noqa: E402
from server.security import hash_password  # noqa: E402

DEMO_PASSWORD = "Fin@2026"

USERS = [
    # username, name, title, role, dept, grade, email
    ("chenjing", "陈静", "首席财务官", "cfo", "HQ", "专家", "chenjing@example.com"),
    ("lizhe", "李哲", "财务 BP（华东）", "fin_bp", "FIN-BP", "高级", "lizhe@example.com"),
    ("wanglin", "王琳", "销售主管（华东）", "sales_mgr", "SALES-E", "主管", "wanglin@example.com"),
    ("zhangchen", "张晨", "客户成功主管（华东）", "cs_mgr", "CS-E", "主管", "zhangchen@example.com"),
    ("zhoumin", "周敏", "会计（应收）", "accountant", "FIN", "初级", "zhoumin@example.com"),
    ("wanglei", "王磊", "IT 运维", "admin", "HQ", "专家", "wanglei@example.com"),
]


def run_sql_file(path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    with db.get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql)
    print(f"  执行 {path.name} 完成")


def seed_users() -> None:
    with db.get_conn() as conn:
        conn.autocommit = False
        cur = conn.cursor()
        for username, name, title, role, dept, grade, email in USERS:
            pwd_hash, salt = hash_password(DEMO_PASSWORD)
            cur.execute(
                """INSERT INTO app.sys_user(username, name, title, password_hash, password_salt,
                                            role_code, dept_code, grade, email)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (username) DO UPDATE SET
                     name=EXCLUDED.name, title=EXCLUDED.title, role_code=EXCLUDED.role_code,
                     dept_code=EXCLUDED.dept_code, grade=EXCLUDED.grade, email=EXCLUDED.email""",
                (username, name, title, pwd_hash, salt, role, dept, grade, email))
        cur.execute(
            """INSERT INTO app.sys_data_scope(user_id, scope_type, scope_value, effect, reason)
               SELECT u.id, 'customer', 'C00012', 'deny', '竞对关联方，禁止查看'
               FROM app.sys_user u WHERE u.username = 'wanglin'
                 AND NOT EXISTS (SELECT 1 FROM app.sys_data_scope s WHERE s.user_id = u.id)""")
        cur.execute(
            """INSERT INTO app.sys_data_scope(user_id, scope_type, scope_value, effect, expire_at, reason)
               SELECT u.id, 'customer', 'C00003', 'allow', CURRENT_DATE + 90, '跨大区协作：总部战略客户'
               FROM app.sys_user u WHERE u.username = 'wanglin'
                 AND NOT EXISTS (SELECT 1 FROM app.sys_data_scope s
                                 WHERE s.user_id = u.id AND s.scope_value = 'C00003')""")
        conn.commit()
    print(f"  演示账号 {len(USERS)} 个已写入（统一口令 {DEMO_PASSWORD}）")


def seed_alerts() -> None:
    """按真实数据生成预警，阈值来自 sys_alert_rule 的口径说明。"""
    db.execute("DELETE FROM app.sys_alert")
    latest = db.scalar('SELECT max("月份") FROM "V_月度经营总览"')
    prev = db.scalar('SELECT max("月份") FROM "V_月度经营总览" WHERE "月份" < %s', (latest,))

    # 1) 90+ 天应收
    over90 = db.query_one(
        """SELECT COALESCE(SUM("应收余额"),0) AS v, COALESCE(SUM("发票数"),0) AS n
           FROM "V_应收账龄结构" WHERE "月份" = %s AND "账龄桶" = '90+ 天'""", (latest,))
    db.execute(
        """INSERT INTO app.sys_alert(rule_code, level, title, detail, metric_code, period, amount, owner)
           VALUES ('AR_OVERDUE_90','high',%s,%s,'ar_balance',%s,%s,'周敏')""",
        (f"90 天以上应收 {float(over90['v']) / 1e8:.2f} 亿元，涉及 {int(over90['n'])} 张发票",
         "账龄 90+ 天余额超过 800 万阈值，建议本周完成催收派单并复核坏账准备。",
         latest, over90["v"]))

    # 2) 逾期占比
    ar = db.query_one(
        """SELECT "逾期应收余额","期末应收余额" FROM "V_月度经营总览" WHERE "月份" = %s""", (latest,))
    rate = float(ar["逾期应收余额"] or 0) / float(ar["期末应收余额"] or 1) * 100
    db.execute(
        """INSERT INTO app.sys_alert(rule_code, level, title, detail, metric_code, period, amount, owner)
           VALUES ('AR_OVERDUE_RATE','mid',%s,%s,'ar_overdue',%s,%s,'周敏')""",
        (f"逾期应收占比 {rate:.1f}%，超过 25% 阈值",
         "账龄结构在恶化，需区分「服务发票里程碑口径」与真实逾期后再考核。",
         latest, ar["逾期应收余额"]))

    # 3) 毛利率环比
    gm = db.query(
        """SELECT "月份","毛利率%" FROM "V_月度经营总览" WHERE "月份" IN (%s,%s) ORDER BY 1""",
        (prev, latest))
    if len(gm) == 2:
        diff = float(gm[1]["毛利率%"]) - float(gm[0]["毛利率%"])
        if diff < -2:
            db.execute(
                """INSERT INTO app.sys_alert(rule_code, level, title, detail, metric_code, period, amount)
                   VALUES ('GM_DROP','high',%s,%s,'gross_margin',%s,%s)""",
                (f"毛利率环比下降 {abs(diff):.1f} 个百分点",
                 f"{prev} {float(gm[0]['毛利率%']):.2f}% → {latest} {float(gm[1]['毛利率%']):.2f}%，需拆解成本结构。",
                 latest, diff))

    # 4) 预算超支科目（年初预算口径）
    over = db.query(
        """SELECT "科目类别", SUM("实际金额") AS actual, SUM("预算金额") AS budget
           FROM "V_费用预算执行" WHERE "月份" = %s AND "预算版本" = '年初预算'
           GROUP BY 1 HAVING SUM("实际金额") > SUM("预算金额") * 1.02 ORDER BY 2 DESC LIMIT 3""",
        (latest,))
    for r in over:
        db.execute(
            """INSERT INTO app.sys_alert(rule_code, level, title, detail, metric_code, period, amount)
               VALUES ('BUDGET_OVER','mid',%s,%s,'budget_exec',%s,%s)""",
            (f"{r['科目类别']} 预算超支",
             f"实际 {float(r['actual']) / 1e4:,.0f} 万 vs 预算 {float(r['budget']) / 1e4:,.0f} 万，"
             f"执行率 {float(r['actual']) / float(r['budget'] or 1) * 100:.1f}%。",
             latest, float(r["actual"]) - float(r["budget"])))

    # 5) 90 天内到期续约
    ren = db.query_one(
        """SELECT count(*) AS n, COALESCE(SUM("月经常性收入MRR" * 12),0) AS arr
           FROM "fact_subscription"
           WHERE "合同状态" = '激活' AND "订阅截止日期" BETWEEN %s AND %s""",
        (date(2025, 12, 1), date(2026, 2, 28)))
    if ren and ren["n"]:
        db.execute(
            """INSERT INTO app.sys_alert(rule_code, level, title, detail, metric_code, period, amount, owner)
               VALUES ('RENEWAL_30','high',%s,%s,'arr',%s,%s,'张晨')""",
            (f"{int(ren['n'])} 份合同将在 90 天内到期，ARR {float(ren['arr']) / 1e8:.2f} 亿",
             "其中部分为自动续约，需逐单确认续约意向，避免静默流失。",
             latest, ren["arr"]))

    # 6) 高价值低健康
    low = db.query_one(
        """SELECT count(*) AS n FROM "V_客户360视图"
           WHERE "当前ARR" > 5000000 AND "健康度等级" = '预警'""")
    if low and low["n"]:
        db.execute(
            """INSERT INTO app.sys_alert(rule_code, level, title, detail, metric_code, period, amount, owner)
               VALUES ('HEALTH_LOW','mid',%s,%s,'health_score',%s,%s,'张晨')""",
            (f"{int(low['n'])} 个高价值客户健康度处于预警",
             "建议客户成功在本周内完成回访，并在客户 360 中记录跟进结果。",
             latest, None))
    print("  预警已按真实数据重建")


def seed_budget_draft() -> None:
    """2026 年度预算草稿：财务部按 2025 实际 × 1.08 生成，供编制页演示。"""
    year = "2025"
    rows = db.query(
        """SELECT "一级科目名称", SUM("费用金额") AS amt
           FROM "V_期间费用结构" WHERE "月份" LIKE %s GROUP BY 1 ORDER BY 2 DESC LIMIT 6""",
        (year + "-%",))
    header = db.query_one(
        """SELECT id FROM app.bud_header WHERE version='2026年度预算' AND unit_code='FIN'""")
    if not header:
        header = db.execute_returning(
            """INSERT INTO app.bud_header(version, period_year, unit_type, unit_code, status, total_amount)
               VALUES ('2026年度预算', 2026, 'dept', 'FIN', 'draft', 0) RETURNING id""")
    hid = header["id"]
    db.execute("DELETE FROM app.bud_line WHERE header_id = %s", (hid,))
    lines = []
    for r in rows:
        for m in range(1, 13):
            amt = round(float(r["amt"] or 0) / 12 * 1.08, 2)
            lines.append((hid, r["一级科目名称"], r["一级科目名称"], f"2026-{m:02d}", amt))
    db.execute_many(
        """INSERT INTO app.bud_line(header_id, subject, subject_name, month, draft_amount)
           VALUES (%s,%s,%s,%s,%s)""", lines)
    total = sum(l[4] for l in lines)
    db.execute("UPDATE app.bud_header SET total_amount=%s WHERE id=%s", (total, hid))
    print(f"  2026 预算草稿：{len(lines)} 行，合计 {total / 1e4:,.0f} 万元")


def seed_reports() -> None:
    db.execute("DELETE FROM app.rpt_run")
    defs = db.query("SELECT code FROM app.rpt_definition ORDER BY code")
    for i, d in enumerate(defs):
        for k in range(2):
            ts = datetime.now() - timedelta(days=i * 2 + k)
            db.execute(
                """INSERT INTO app.rpt_run(report_code, period, status, row_count, cost_ms, file_name, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (d["code"], "2025-12", "success" if (i + k) % 7 else "failed",
                 1200 + i * 130, 700 + i * 90, f"{d['code']}_2025-12.xlsx", ts))
    subs = db.query("SELECT username, id FROM app.sys_user WHERE username IN ('chenjing','lizhe')")
    for s in subs:
        for code in ("RPT_MONTHLY", "RPT_AR_AGING"):
            db.execute(
                """INSERT INTO app.rpt_subscription(user_id, report_code, cron, channel)
                   SELECT %s,%s,'每月 5 日 09:00','邮件'
                   WHERE NOT EXISTS (SELECT 1 FROM app.rpt_subscription
                                     WHERE user_id=%s AND report_code=%s)""",
                (s["id"], code, s["id"], code))
    print("  报表运行记录与订阅已生成")


def check() -> None:
    info = db.healthcheck()
    print(f"  数据库 {info['db']} · PostgreSQL {info['ver']} · {info['tables']} 表 / {info['views']} 视图")
    for t in ("app.sys_user", "app.meta_metric", "app.meta_drill_map", "app.sys_alert"):
        n = db.scalar(f"SELECT count(*) FROM {t}")
        print(f"  {t}: {n} 行")


def init() -> None:
    print("1/6 建表结构")
    run_sql_file(settings.sql_dir / "01_schema.sql")
    print("2/6 写入参考数据")
    run_sql_file(settings.sql_dir / "02_seed.sql")
    print("3/6 演示账号")
    seed_users()
    print("4/6 预算草稿")
    seed_budget_draft()
    print("5/6 预警与报表")
    seed_alerts()
    seed_reports()
    print("6/6 自检")
    check()
    print(f"\n完成。访问 http://127.0.0.1:8000  账号 chenjing / {DEMO_PASSWORD}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "init"
    if cmd == "init":
        init()
    elif cmd == "reset-demo":
        seed_users(); seed_alerts(); seed_budget_draft(); seed_reports()
    elif cmd == "check":
        check()
    else:
        print(__doc__)
