"""Lazy per-module topic generation (Phase 4).

Triggered the moment someone opens a module page that has no topics yet (seeded
or otherwise), then cached permanently as real Topic/Resource rows -- generation
never runs again for that module regardless of which roadmap led here.

The LLM must never emit a URL: video IDs and article slugs are exactly what these
models invent most confidently, and a study guide full of 404s is worse than an
empty one. Enforced here in code, not just asked for in the prompt.
"""
import json

from sqlalchemy.orm import Session

from app.agents import prompts
from app.core.llm import chat_json
from app.db.models import Module, Resource, Topic
from app.services.content_hub import slugify


def _contains_url(obj) -> bool:
    if isinstance(obj, str):
        return "http" in obj.lower()
    if isinstance(obj, dict):
        return any(_contains_url(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_contains_url(v) for v in obj)
    return False


def generate_topics_for_module(module: Module) -> list[dict]:
    messages = [
        {
            "role": "system",
            "content": prompts.MODULE_TOPIC_GENERATOR.format(title=module.title, summary=module.summary or module.title),
        },
        {"role": "user", "content": "Generate the topics JSON now."},
    ]
    for attempt in range(2):
        data = chat_json(messages, fast=False)
        topics = data.get("topics", [])
        if topics and not _contains_url(topics):
            return topics
        messages = messages + [
            {"role": "assistant", "content": json.dumps(data)},
            {
                "role": "user",
                "content": "That response contained a URL or link, which is forbidden. Respond again with "
                "ONLY JSON, using natural-language search queries instead of any link or video ID.",
            },
        ]
    raise ValueError("Could not generate topics without a fabricated link -- try again")


def ensure_topics(db: Session, module: Module) -> None:
    """No-op if the module already has topics, seeded or previously generated."""
    if db.query(Topic).filter(Topic.module_id == module.id).count() > 0:
        return
    topics = generate_topics_for_module(module)
    for i, t in enumerate(topics):
        title = t.get("title") or f"Topic {i + 1}"
        topic = Topic(
            module_id=module.id,
            slug=slugify(title),
            title=title,
            blurb=t.get("blurb", ""),
            order_index=i,
            estimated_minutes=t.get("estimated_minutes") or 15,
            source="generated",
        )
        db.add(topic)
        db.flush()
        for j, r in enumerate((t.get("resources") or [])[:2]):
            kind = r.get("kind", "article")
            db.add(
                Resource(
                    topic_id=topic.id,
                    kind=kind,
                    status="intent",
                    title=r.get("title") or f"{kind.title()}: {title}",
                    search_query=r.get("search_query", title),
                    source_hint="generated",
                    order_index=j,
                )
            )
    db.commit()
