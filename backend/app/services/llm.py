"""Provider-agnostic LLM client (Anthropic / OpenAI / Gemini) over plain HTTPS.

Every agent calls `complete_json`; if no provider is configured or a call fails, it returns
None and the agent falls back to its deterministic rule engine. This keeps the demo
working without a key, and acts as a guardrail: LLM output is always schema-checked.
"""
import base64
import json
import logging
import re

import httpx

from ..core.config import settings

log = logging.getLogger("llm")

DEFAULT_MODELS = {"anthropic": "claude-sonnet-4-5", "openai": "gpt-4o-mini", "gemini": "gemini-2.0-flash"}


def provider() -> str:
    p = settings.LLM_PROVIDER.lower()
    key = {"anthropic": settings.ANTHROPIC_API_KEY, "openai": settings.OPENAI_API_KEY,
           "gemini": settings.GEMINI_API_KEY}.get(p, "")
    return p if key else "none"


def enabled() -> bool:
    return provider() != "none"


def _model() -> str:
    return settings.LLM_MODEL or DEFAULT_MODELS.get(provider(), "")


def complete(system: str, prompt: str, image: tuple[bytes, str] | None = None, max_tokens: int = 1200) -> str | None:
    p = provider()
    if p == "none":
        return None
    try:
        with httpx.Client(timeout=settings.LLM_TIMEOUT) as c:
            if p == "anthropic":
                content = [{"type": "text", "text": prompt}]
                if image:
                    content.insert(0, {"type": "image", "source": {"type": "base64", "media_type": image[1],
                                                                    "data": base64.b64encode(image[0]).decode()}})
                r = c.post("https://api.anthropic.com/v1/messages",
                           headers={"x-api-key": settings.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"},
                           json={"model": _model(), "max_tokens": max_tokens, "system": system,
                                 "messages": [{"role": "user", "content": content}]})
                r.raise_for_status()
                return "".join(b.get("text", "") for b in r.json()["content"])
            if p == "openai":
                content = [{"type": "text", "text": prompt}]
                if image:
                    content.append({"type": "image_url", "image_url": {
                        "url": f"data:{image[1]};base64,{base64.b64encode(image[0]).decode()}"}})
                r = c.post("https://api.openai.com/v1/chat/completions",
                           headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                           json={"model": _model(), "max_tokens": max_tokens,
                                 "messages": [{"role": "system", "content": system},
                                              {"role": "user", "content": content}]})
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
            if p == "gemini":
                parts = [{"text": prompt}]
                if image:
                    parts.append({"inline_data": {"mime_type": image[1], "data": base64.b64encode(image[0]).decode()}})
                r = c.post(f"https://generativelanguage.googleapis.com/v1beta/models/{_model()}:generateContent",
                           params={"key": settings.GEMINI_API_KEY},
                           json={"system_instruction": {"parts": [{"text": system}]},
                                 "contents": [{"role": "user", "parts": parts}],
                                 "generationConfig": {"maxOutputTokens": max_tokens}})
                r.raise_for_status()
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:  # network, quota, schema — fall back silently
        log.warning("LLM call failed (%s): %s", p, e)
    return None


def complete_json(system: str, prompt: str, image=None, required: list[str] | None = None) -> dict | None:
    text = complete(system + "\nRespond with a single JSON object only, no prose.", prompt, image)
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if required and not all(k in data for k in required):
        return None
    return data
