"""Acceptance criterion: no LLM response containing a URL ever reaches the
database. generate_topics_for_module / ensure_topics (app/services/topics.py)
must reject a fabricated link, not pass it through.
"""
from unittest.mock import patch

import pytest

from app.db.models import Module, Resource, Topic
from app.services.topics import _contains_url, ensure_topics, generate_topics_for_module

FABRICATED_URL_RESPONSE = {
    "topics": [
        {
            "title": "Intro to Foo",
            "blurb": "Getting started",
            "estimated_minutes": 15,
            "resources": [
                {"kind": "video", "search_query": "check out https://youtube.com/watch?v=fake123"},
                {"kind": "article", "search_query": "foo basics guide"},
            ],
        }
    ]
}

CLEAN_RESPONSE = {
    "topics": [
        {
            "title": "Intro to Foo",
            "blurb": "Getting started",
            "estimated_minutes": 15,
            "resources": [
                {"kind": "video", "search_query": "foo explained for beginners"},
                {"kind": "article", "search_query": "foo basics guide"},
            ],
        }
    ]
}


class TestContainsUrl:
    def test_detects_url_in_nested_resource(self):
        assert _contains_url(FABRICATED_URL_RESPONSE["topics"]) is True

    def test_clean_response_has_no_url(self):
        assert _contains_url(CLEAN_RESPONSE["topics"]) is False

    def test_case_insensitive(self):
        assert _contains_url([{"q": "Visit HTTP://example.com"}]) is True

    def test_empty_and_non_string_values(self):
        assert _contains_url({"a": None, "b": 5, "c": []}) is False


def test_fabricated_url_is_rejected_after_one_retry_then_fails_loudly():
    module = Module(slug="git", title="Git", kind="tool", summary="Version control")
    with patch("app.services.topics.chat_json", return_value=FABRICATED_URL_RESPONSE) as mocked:
        with pytest.raises(ValueError, match="fabricated link"):
            generate_topics_for_module(module)
    # One corrective retry, then fail loudly -- not a silent pass-through, not infinite retries.
    assert mocked.call_count == 2


def test_clean_response_on_retry_is_accepted():
    module = Module(slug="git", title="Git", kind="tool", summary="Version control")
    with patch("app.services.topics.chat_json", side_effect=[FABRICATED_URL_RESPONSE, CLEAN_RESPONSE]) as mocked:
        topics = generate_topics_for_module(module)
    assert mocked.call_count == 2
    assert topics == CLEAN_RESPONSE["topics"]


def test_fabricated_url_never_reaches_the_database(db_session):
    module = Module(slug="test-module", title="Test Module", kind="skill", source="generated")
    db_session.add(module)
    db_session.commit()
    db_session.refresh(module)

    with patch("app.services.topics.chat_json", return_value=FABRICATED_URL_RESPONSE):
        with pytest.raises(ValueError):
            ensure_topics(db_session, module)

    assert db_session.query(Topic).filter(Topic.module_id == module.id).count() == 0
    assert db_session.query(Resource).count() == 0


def test_clean_topics_do_reach_the_database(db_session):
    module = Module(slug="test-module-2", title="Test Module 2", kind="skill", source="generated")
    db_session.add(module)
    db_session.commit()
    db_session.refresh(module)

    with patch("app.services.topics.chat_json", return_value=CLEAN_RESPONSE):
        ensure_topics(db_session, module)

    topics = db_session.query(Topic).filter(Topic.module_id == module.id).all()
    assert len(topics) == 1
    assert topics[0].title == "Intro to Foo"
    resources = db_session.query(Resource).filter(Resource.topic_id == topics[0].id).all()
    assert len(resources) == 2
    assert all("http" not in (r.search_query or "").lower() for r in resources)
