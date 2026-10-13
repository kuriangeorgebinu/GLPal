"""One small interface over DeepSeek / OpenAI (OpenAI-compatible API), Anthropic, or a mock.

chat(system, user, image=None) -> str. The mock returns "" so callers use their own
offline fallback, which keeps the whole app usable without any API key.
"""
import base64
import json
import re

import httpx

from . import config

TIMEOUT = httpx.Timeout(60.0, connect=10.0)


class LLMError(RuntimeError):
    pass


def provider() -> str:
    return config.resolved_provider()


def supports_vision() -> bool:
    return provider() in ("openai", "anthropic")


def chat(system: str, user: str, image: bytes | None = None, image_type: str = "image/jpeg",
         max_tokens: int = 900) -> str:
    p = provider()
    if p == "mock":
        return ""
    try:
        if p in ("deepseek", "openai"):
            return _openai_compatible(p, system, user, image, image_type, max_tokens)
        if p == "anthropic":
            return _anthropic(system, user, image, image_type, max_tokens)
    except httpx.HTTPError as e:
        raise LLMError(f"{p} request failed: {type(e).__name__}") from e
    raise LLMError(f"Unknown LLM_PROVIDER '{p}'")


def _openai_compatible(p, system, user, image, image_type, max_tokens) -> str:
    if p == "deepseek":
        key, model, base = config.DEEPSEEK_API_KEY, config.DEEPSEEK_MODEL, config.DEEPSEEK_BASE_URL
    else:
        key, model, base = config.OPENAI_API_KEY, config.OPENAI_MODEL, config.OPENAI_BASE_URL
    if not key:
        raise LLMError(f"No API key set for {p}")
    content = user
    if image is not None and p == "openai":
        b64 = base64.b64encode(image).decode()
        content = [{"type": "text", "text": user},
                   {"type": "image_url", "image_url": {"url": f"data:{image_type};base64,{b64}"}}]
    r = httpx.post(f"{base}/chat/completions", timeout=TIMEOUT,
                   headers={"Authorization": f"Bearer {key}"},
                   json={"model": model, "max_tokens": max_tokens, "temperature": 0.2,
                         "messages": [{"role": "system", "content": system},
                                      {"role": "user", "content": content}]})
    if r.status_code >= 400:
        raise LLMError(f"{p} returned HTTP {r.status_code}")
    return r.json()["choices"][0]["message"]["content"] or ""


def _anthropic(system, user, image, image_type, max_tokens) -> str:
    if not config.ANTHROPIC_API_KEY:
        raise LLMError("No API key set for anthropic")
    content = [{"type": "text", "text": user}]
    if image is not None:
        content.insert(0, {"type": "image", "source": {
            "type": "base64", "media_type": image_type, "data": base64.b64encode(image).decode()}})
    r = httpx.post("https://api.anthropic.com/v1/messages", timeout=TIMEOUT,
                   headers={"x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"},
                   json={"model": config.ANTHROPIC_MODEL, "max_tokens": max_tokens, "system": system,
                         "messages": [{"role": "user", "content": content}]})
    if r.status_code >= 400:
        raise LLMError(f"anthropic returned HTTP {r.status_code}")
    return "".join(b.get("text", "") for b in r.json().get("content", []))


def extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of a model reply (models sometimes wrap it in prose/fences)."""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
