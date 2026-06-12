"""LLM router: Gemini free tier (primary) -> Groq free tier (fallback).

Both expose OpenAI-compatible endpoints, so one SDK covers both.
Fallback triggers on rate limits (429), auth issues, or transient errors.
"""
import json
import logging
from typing import Generator, Optional

import httpx
from openai import OpenAI

from app.core.config import settings

logger = logging.getLogger("athena.llm")

PROVIDERS = [
    {
        "name": "gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key": settings.GEMINI_API_KEY,
        "model": "gemini-2.5-flash",
    },
    {
        "name": "groq",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key": settings.GROQ_API_KEY,
        "model": "llama-3.3-70b-versatile",
    },
]

# Fast lane for short internal calls (intent detection, scoring). Groq first: low latency.
FAST_ORDER = ["groq", "gemini"]


def _clients():
    return {
        p["name"]: (
            OpenAI(
                base_url=p["base_url"],
                api_key=p["api_key"],
                http_client=httpx.Client(verify=False, timeout=60.0),
            ),
            p["model"],
        )
        for p in PROVIDERS
        if p["api_key"]
    }


def chat(
    messages: list[dict],
    json_mode: bool = False,
    temperature: float = 0.7,
    fast: bool = False,
    max_tokens: Optional[int] = None,
) -> str:
    """Non-streaming completion with automatic provider fallback."""
    clients = _clients()
    if not clients:
        raise RuntimeError("No LLM API keys configured. Copy .env.example to .env and add keys.")
    order = FAST_ORDER if fast else [p["name"] for p in PROVIDERS]
    last_err: Exception = RuntimeError("No provider available")
    for name in order:
        if name not in clients:
            continue
        client, model = clients[name]
        try:
            kwargs: dict = {"model": model, "messages": messages, "temperature": temperature}
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            if max_tokens:
                kwargs["max_tokens"] = max_tokens
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except Exception as e:  # rate limit / transient -> try next provider
            logger.warning("Provider %s failed (%s); falling back.", name, e)
            last_err = e
    raise last_err


def chat_stream(messages: list[dict], temperature: float = 0.7) -> Generator[str, None, None]:
    """Streaming completion with fallback. Yields text deltas."""
    clients = _clients()
    if not clients:
        raise RuntimeError("No LLM API keys configured. Copy .env.example to .env and add keys.")
    last_err: Exception = RuntimeError("No provider available")
    for p in PROVIDERS:
        if p["name"] not in clients:
            continue
        client, model = clients[p["name"]]
        try:
            stream = client.chat.completions.create(
                model=model, messages=messages, temperature=temperature, stream=True
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield delta
            return
        except Exception as e:
            logger.warning("Provider %s stream failed (%s); falling back.", p["name"], e)
            last_err = e
    raise last_err


def chat_json(messages: list[dict], fast: bool = True, retries: int = 2) -> dict:
    """JSON completion with parse-repair retry."""
    for attempt in range(retries + 1):
        raw = chat(messages, json_mode=True, temperature=0.2, fast=fast)
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            if attempt == retries:
                raise
            messages = messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "That was not valid JSON. Respond again with ONLY valid JSON."},
            ]
    return {}
