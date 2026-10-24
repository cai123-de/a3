"""DeepSeek 大模型客户端（OpenAI 兼容格式，标准库实现零新增依赖）。

接口规范（api-docs.deepseek.com/zh-cn）：
- 端点：POST {base_url}/chat/completions
- 认证：Authorization: Bearer <DEEPSEEK_API_KEY>
- 模型：deepseek-flash（默认）/ deepseek-v4-pro
- JSON 输出：response_format = {"type": "json_object"}（提示词中须包含「JSON」字样）

安全边界（Data Agent 框架 L1）：本模块只做「意图解析」的文本进出，
不接触 SQL、不接触业务数据、不做任何算术——取数与闸门全部在语义层服务端。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from ..config import settings


class LLMError(Exception):
    """DeepSeek 调用失败（网络/鉴权/格式）。"""


def available() -> bool:
    return bool(settings.llm_api_key)


def chat_msg(messages: list[dict], *, tools: list[dict] | None = None,
             temperature: float = 0.1, json_mode: bool = False,
             timeout: int | None = None) -> tuple[dict, dict]:
    """调用 chat/completions，返回 (assistant_message, usage)。

    tools 传 OpenAI 格式工具定义时启用 function calling；
    assistant_message 形如 {"role":"assistant","content":...,"tool_calls":[...]}。
    json_mode=True 时启用 JSON 输出（提示词须含「JSON」字样，DeepSeek 官方要求）。
    """
    if not available():
        raise LLMError("未配置 DEEPSEEK_API_KEY")
    body: dict = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    # 思考模式（官方文档）：reasoning_effort 同时控制开关与强度；
    # none=关闭思考；low/high/max 开启，默认 high。思考模式下 temperature 不生效（官方说明）。
    effort = settings.llm_effort if settings.llm_effort in ("none", "low", "high", "max") else "high"
    body["thinking"] = {"type": "disabled" if effort == "none" else "enabled"}
    body["reasoning_effort"] = effort
    # max_tokens：0 表示不传，走官方默认（思考 64K / max 强度 128K / 非思考 8K）
    if settings.llm_max_tokens and settings.llm_max_tokens > 0:
        body["max_tokens"] = min(int(settings.llm_max_tokens), 393216)
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    req = urllib.request.Request(
        settings.llm_base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + settings.llm_api_key},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout or settings.llm_timeout_s) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "ignore")
        raise LLMError(f"DeepSeek HTTP {e.code}：{detail}") from e
    except Exception as e:  # noqa: BLE001
        raise LLMError(f"DeepSeek 调用失败：{e}") from e
    cost = (time.perf_counter() - t0) * 1000
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"DeepSeek 响应格式异常：{str(data)[:200]}") from e
    usage = data.get("usage") or {}
    print(f"[llm] {settings.llm_model} {cost:.0f}ms "
          f"tokens={usage.get('total_tokens', '?')}", flush=True)
    return message, usage


def chat(messages: list[dict], *, temperature: float = 0.1,
         json_mode: bool = True, timeout: int | None = None) -> str:
    """调用 DeepSeek chat/completions，返回助手回复文本。"""
    message, _ = chat_msg(messages, temperature=temperature, json_mode=json_mode,
                          timeout=timeout)
    return message.get("content") or ""
