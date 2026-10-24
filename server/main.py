"""FastAPI 应用入口。

启动：
    uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload
或：
    python run.py
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .config import settings
from .response import ApiError, error_response, ok
from .routers import admin, ai, alerts, ar, auth, budget, cost, customer, dataops, overview, reports, semantic

logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("fin.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_pool()
    try:
        info = db.healthcheck()
        log.info("数据库就绪：%s / %s 表 / %s 视图", info["db"], info["tables"], info["views"])
        n = db.scalar("SELECT count(*) FROM app.sys_user")
        log.info("应用账号 %s 个", n)
    except Exception as exc:  # noqa: BLE001
        log.error("数据库自检失败：%s（请先执行 python manage.py init）", exc)
    yield
    db.close_pool()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="SaaS 财务管理系统 · 管理会计口径 · 三维数据权限 · 语义层 AI",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.debug else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    request.state.request_id = rid
    start = time.perf_counter()
    response = await call_next(request)
    cost = (time.perf_counter() - start) * 1000
    response.headers["x-request-id"] = rid
    response.headers["x-response-time"] = f"{cost:.1f}ms"
    if request.url.path.startswith("/api"):
        log.info("%s %s %.0fms", request.method, request.url.path, cost)
    else:
        # 静态资源（前端单页）禁止启发式缓存：浏览器每次须带 ETag 回源校验，
        # 避免改版后旧 JS 模块（如 VIEWS 注册表）滞留导致新菜单点不开。
        # 入口 HTML 用 no-store 彻底禁存，保证版本号参数改动立即可见。
        p = request.url.path
        response.headers["Cache-Control"] = "no-store" if p == "/" or p.endswith(".html") else "no-cache"
    return response


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return error_response(exc.code, exc.message, exc.detail,
                          getattr(request.state, "request_id", None))


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return error_response(40001, "参数校验失败", exc.errors(),
                          getattr(request.state, "request_id", None))


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    log.exception("未处理异常：%s", exc)
    msg = str(exc) if settings.debug else "服务内部错误"
    code = 50001 if "timeout" in msg.lower() or "超时" in msg else 50000
    return error_response(code, msg, None, getattr(request.state, "request_id", None))


@app.get("/healthz", tags=["运维"])
def healthz():
    try:
        info = db.healthcheck()
        return ok({"status": "ok", **info})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={"status": "down", "error": str(exc)})


@app.get("/api/v1", tags=["运维"])
def api_root():
    return ok({
        "name": settings.app_name,
        "version": "1.0.0",
        "docs": "/api/docs",
        "modules": ["auth", "overview", "customer", "ar", "cost", "budget", "semantic", "ai",
                    "reports", "alerts", "dataops", "admin"],
    })


for r in (auth.router, overview.router, customer.router, ar.router, cost.router,
          budget.router, ai.router, reports.router, alerts.router, admin.router,
          semantic.router, dataops.router):
    app.include_router(r, prefix=settings.api_prefix)

# 静态资源：前端单页应用（放在最后，避免吞掉 /api 路由）
if settings.web_dir.exists():
    app.mount("/", StaticFiles(directory=str(settings.web_dir), html=True), name="web")
