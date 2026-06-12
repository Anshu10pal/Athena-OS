"""GitHub-backed community study resources.

Reads resources/{slug}.json from the public athena-content repo (main branch),
caches in SQLite for 24h, serves from cache when offline.
"""
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from app.db.models import ResourceCache

CONTENT_REPO = "Anshu10pal/athena-content"
RAW_BASE = f"https://raw.githubusercontent.com/{CONTENT_REPO}/main/resources"
CACHE_TTL_HOURS = 24


def slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:100]


def get_community_resources(db: Session, topic_title: str) -> list[dict]:
    slug = slugify(topic_title)
    row = db.query(ResourceCache).filter(ResourceCache.slug == slug).first()
    fresh = row and row.fetched_at and (
        datetime.now(timezone.utc) - row.fetched_at.replace(tzinfo=timezone.utc)
    ) < timedelta(hours=CACHE_TTL_HOURS)
    if fresh:
        return (row.payload or {}).get("resources", [])
    try:
        resp = httpx.get(f"{RAW_BASE}/{slug}.json", timeout=8.0, verify=False)
        payload = resp.json() if resp.status_code == 200 else {"resources": []}
    except Exception:
        return (row.payload or {}).get("resources", []) if row else []
    if row:
        row.payload = payload
        row.fetched_at = datetime.now(timezone.utc)
    else:
        db.add(ResourceCache(slug=slug, payload=payload))
    db.commit()
    return payload.get("resources", [])


def suggest_url(topic_title: str) -> str:
    slug = slugify(topic_title)
    title = f"[Resource] {slug}: ".replace(" ", "%20")
    body = (
        f"**Topic slug**: {slug}%0A%0A**Title**: %0A%0A**URL**: %0A%0A"
        "**Type** (official / article / video / course / opensource): %0A%0A"
        "**Why it's good (one line)**: %0A%0A**Suggested by** (GitHub username): "
    ).replace(" ", "%20")
    return f"https://github.com/{CONTENT_REPO}/issues/new?labels=resource&title={title}&body={body}"


def generated_links(title: str, skills: list[str]) -> list[dict]:
    """Hallucination-proof study links: search URLs only, can never 404."""
    import urllib.parse

    q = urllib.parse.quote(title)
    links = [
        {"title": f"GeeksforGeeks: {title}", "url": f"https://www.geeksforgeeks.org/?s={q}", "type": "article", "source": "search"},
        {"title": f"YouTube: {title} explained", "url": f"https://www.youtube.com/results?search_query={q}+explained", "type": "video", "source": "search"},
    ]
    if skills:
        sq = urllib.parse.quote(skills[0])
        links.append({"title": f"Official docs: {skills[0]}", "url": f"https://duckduckgo.com/?q={sq}+official+documentation", "type": "official", "source": "search"})
    return links
