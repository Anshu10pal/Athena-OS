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
        # Was `llama-3.3-70b-versatile` until 2026-09-03. Groq DECOMMISSIONED
        # that model: it 404s with `model_not_found`, and this key's /models
        # listing carries no llama-3.3-* chat model at all. Because Groq is
        # FIRST in both FAST_ORDER and STREAM_ORDER, every fast-lane and
        # streaming call had been paying a failed round trip and falling through
        # to Gemini -- so the app had effectively ONE provider, and the fallback
        # that exists to survive a Gemini quota exhaustion was itself dead. Found
        # when it turned a Gemini 429 into a hard failure mid measurement run.
        # See docs/arena-known-issues.md KI-4.
        #
        # `openai/gpt-oss-120b` is the closest replacement IN KIND -- a large
        # general-purpose model, preserving the intent of the original 70B
        # choice, at 131,072 context (the old model had ~128k).
        #
        # QUALIFIED against what this module actually needs, rather than "does it
        # respond" -- which would certify the wrong property. A model failing any
        # of these degrades SILENTLY to Gemini, the exact shape this change
        # exists to end:
        #   1. non-empty message.content    (chat() returns `content or ""`)
        #   2. response_format json_object  (chat_json depends on it)
        #   3. stream=True delta.content    (chat_stream depends on it)
        #   4. non-empty content at max_tokens=200
        #      (briefing.py:49 is a fast-lane call with a small cap; a reasoning
        #       model can spend that budget thinking and return an empty string,
        #       which propagates as SUCCESS -- no exception, no fallback, no log,
        #       and a blank briefing on screen)
        # All four verified through this module with the Gemini key BLANKED, so
        # no fallback could mask a fault. Streaming passed 3/3 attempts.
        #
        # REJECTED on measurement, recorded so they are not retried blind:
        #   openai/gpt-oss-20b   yields ZERO content deltas when streaming
        #   qwen/qwen3.6-27b     leaks chain-of-thought into `content`
        #                        ("<think>\nHere's a thinking process...", 163
        #                        output tokens to answer "capital of France")
        #
        # RUNNER-UP `qwen/qwen3.8-27b` passed everything and is materially
        # leaner: 0.24s vs 0.79s on a realistic JSON task, 56 vs 202 output
        # tokens on the same prompt. That token economy matters against the
        # measured 8,000 TPM ceiling, so it is the better pick IF the fast lane
        # is ever split from the streaming lane. Not chosen now because one model
        # serves both here, and 27B would downgrade user-facing chat.
        "model": "openai/gpt-oss-120b",
    },
]

# Fast lane for short internal calls (intent detection, scoring). Groq first: low latency.
FAST_ORDER = ["groq", "gemini"]
# Chat streaming: Groq first for far lower time-to-first-token; Gemini as quality fallback.
STREAM_ORDER = ["groq", "gemini"]


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
    order = [n for n in STREAM_ORDER if n in clients] or list(clients.keys())
    for name in order:
        client, model = clients[name]
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
            logger.warning("Provider %s stream failed (%s); falling back.", name, e)
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
