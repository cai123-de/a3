"""数据库访问层：连接池 + 统一定义 search_path + 只读保护。"""
from __future__ import annotations

import contextlib
import logging
import re
from typing import Any, Iterable, Sequence

import psycopg2
import psycopg2.extras
from psycopg2 import pool as pg_pool

from .config import settings

log = logging.getLogger("fin.db")

_pool: pg_pool.ThreadedConnectionPool | None = None


_QUOTED = re.compile(r'"([^"]*)"')
_SENTINEL = "\x00PH\x00"


def _prepare(sql: str, params: Sequence[Any] | None) -> str:
    """psycopg2 会把 SQL 里的 % 当作占位符；中文列名含 %（如 "毛利率%"）时需转义。

    做法：先把 %s 占位符替换成哨兵，再把所有双引号内的 % 变成 %%，最后还原占位符。
    这样不会误伤跨引号的片段，也不会影响字符串字面量里的 %。
    """
    if not params:
        return sql
    tmp = sql.replace("%s", _SENTINEL)
    tmp = _QUOTED.sub(lambda m: '"' + m.group(1).replace("%", "%%") + '"', tmp)
    return tmp.replace(_SENTINEL, "%s")


def _dsn() -> str:
    s = settings
    return (
        f"host={s.db_host} port={s.db_port} user={s.db_user} "
        f"password={s.db_password} dbname={s.db_name} "
        f"client_encoding=UTF8 application_name=fin-suite"
    )


def init_pool() -> None:
    global _pool
    if _pool is None:
        _pool = pg_pool.ThreadedConnectionPool(settings.pool_min, settings.pool_max, dsn=_dsn())
        log.info("数据库连接池已建立 %s:%s/%s", settings.db_host, settings.db_port, settings.db_name)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


@contextlib.contextmanager
def get_conn():
    if _pool is None:
        init_pool()
    assert _pool is not None
    conn = _pool.getconn()
    try:
        yield conn
    finally:
        _pool.putconn(conn)


@contextlib.contextmanager
def cursor(commit: bool = False):
    """默认只读事务：数据查询走这里；写入请显式 commit=True。"""
    with get_conn() as conn:
        conn.autocommit = commit
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute("SET statement_timeout = %s", (settings.statement_timeout_ms,))
            cur.execute(
                'SET search_path TO "%s", %s, public'
                % (settings.data_schema, settings.app_schema)
            )
            yield cur
            if commit:
                conn.commit()
        except Exception:
            if not commit:
                conn.rollback()
            raise
        finally:
            cur.close()


def query(sql: str, params: Sequence[Any] | None = None) -> list[dict]:
    params = params or None          # 空列表会被 psycopg2 当作「需要格式化」，中文列名含 % 时报错
    with cursor() as cur:
        cur.execute(_prepare(sql, params), params)
        return [dict(r) for r in cur.fetchall()]


def query_one(sql: str, params: Sequence[Any] | None = None) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def scalar(sql: str, params: Sequence[Any] | None = None) -> Any:
    row = query_one(sql, params)
    if not row:
        return None
    return next(iter(row.values()))


def execute(sql: str, params: Sequence[Any] | None = None) -> int:
    params = params or None
    with cursor(commit=True) as cur:
        cur.execute(_prepare(sql, params), params)
        return cur.rowcount


def execute_returning(sql: str, params: Sequence[Any] | None = None) -> dict | None:
    params = params or None
    with cursor(commit=True) as cur:
        cur.execute(_prepare(sql, params), params)
        if cur.description is None:
            return None
        row = cur.fetchone()
        return dict(row) if row else None


def execute_many(sql: str, rows: Iterable[Sequence[Any]]) -> int:
    with cursor(commit=True) as cur:
        cur.executemany(sql, list(rows))
        return cur.rowcount


def healthcheck() -> dict:
    row = query_one(
        "SELECT current_database() AS db, current_setting('server_version') AS ver, now() AS ts"
    )
    tables = query_one(
        """SELECT count(*) FILTER (WHERE relkind='r') AS tables,
                  count(*) FILTER (WHERE relkind='v') AS views
           FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname = %s""",
        (settings.data_schema,),
    )
    return {**(row or {}), **(tables or {})}
