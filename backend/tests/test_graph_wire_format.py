"""Item 5: the ONE layer the direct-call convention cannot reach.

Every other endpoint test in this suite calls the route function directly. That
is fast, it needs no server, and it proves the FILTERING logic -- but it bypasses
FastAPI's request parsing entirely, so it says nothing about whether a client can
reach the endpoint at all. An audit of every route parameter whose direct-call
value differs from its wire value found 11, of which 2 had genuinely diverged:
`Query(None)` is a truthy MARKER object, so a direct call took the filtering
branch on every unfiltered request and died on `in` against a non-iterable.

Which layer covers what:

    direct route call (test_repos_api.py)   the filtering logic, the SQL, the
                                            aggregation, the error messages
    TestClient (this file)                  query-string parsing: repeated
                                            values, scalar coercion, and
                                            FastAPI's own 422 -- which fires
                                            BEFORE the handler and is therefore
                                            unreachable from a direct call

Deliberately narrow. This is not a second copy of the endpoint's test suite; it
covers the three things only the wire can show. Anything about what the endpoint
COMPUTES belongs in the direct-call tests, where it is cheaper.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.core.security import get_current_user, require_write_access
from app.db import models  # noqa: F401
from app.db.database import Base, get_db
from app.db.models import CodeFile, CodeFileRank, Repo
from app.main import app


@pytest.fixture()
def wire_client():
    """A TestClient over a throwaway in-memory database, with auth stubbed.

    Auth is overridden rather than exercised: a real token would add a login
    round trip to every test here and prove nothing about query parsing, which
    is the only thing this file is for.
    """
    # StaticPool: `sqlite:///:memory:` gives every CONNECTION its own private
    # database, so the request handler's session would open an empty one and
    # report "no such table: repos" while the fixture's own session saw the rows
    # it had just inserted. StaticPool holds a single connection and hands it to
    # everyone, which is what makes the seeded data visible to the app.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    repo = Repo(host="github.com", owner="acme", name="wire", source_kind="local",
                local_path=".", default_branch="main")
    session.add(repo)
    session.flush()
    # Three languages and two segments, so a multi-value filter has something to
    # distinguish and a single-value read of it produces a DIFFERENT answer.
    rows = [
        ("backend/a.py", "python"),
        ("backend/b.py", "python"),
        ("frontend/c.ts", "typescript"),
        ("frontend/d.tsx", "tsx"),
        ("setup.py", "python"),
    ]
    for i, (path, lang) in enumerate(rows, start=1):
        f = CodeFile(repo_id=repo.id, path=path, language=lang, content_sha256=str(i) * 64)
        session.add(f)
        session.flush()
        session.add(CodeFileRank(repo_id=repo.id, file_id=f.id, scorer="legacy",
                                 rank=i, score=1.0 / i))
    session.commit()
    repo_id = repo.id

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: None
    app.dependency_overrides[require_write_access] = lambda: None
    try:
        with TestClient(app) as client:
            yield client, repo_id
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


class TestRepeatedValues:
    """The class of bug that actually occurred."""

    def test_LOADBEARING_three_repeated_languages_are_all_parsed(self, wire_client):
        client, repo_id = wire_client
        r = client.get(f"/api/repos/{repo_id}/graph",
                       params=[("level", "file"), ("languages", "python"),
                               ("languages", "typescript"), ("languages", "tsx")])
        assert r.status_code == 200, r.text
        body = r.json()

        # Echoed in order, all three -- not the first, not the last.
        assert body["filters"]["languages"] == ["python", "typescript", "tsx"]

        # And the RESULT differs from every single-value request. Three values,
        # because a two-value test passes on an implementation that reads only
        # the last one.
        totals = {}
        for lang in ("python", "typescript", "tsx"):
            single = client.get(f"/api/repos/{repo_id}/graph",
                                params=[("level", "file"), ("languages", lang)])
            totals[lang] = single.json()["total_nodes_before_cap"]
            assert body["total_nodes_before_cap"] != totals[lang], (
                f"the three-language result equals the {lang}-only result"
            )
        assert body["total_nodes_before_cap"] == sum(totals.values())

    def test_LOADBEARING_repeated_segments_are_all_parsed(self, wire_client):
        client, repo_id = wire_client
        r = client.get(f"/api/repos/{repo_id}/graph",
                       params=[("level", "file"), ("segments", "backend"),
                               ("segments", "frontend")])
        assert r.status_code == 200
        assert r.json()["filters"]["segments"] == ["backend", "frontend"]
        assert r.json()["total_nodes_before_cap"] == 4

    def test_a_root_segment_survives_url_encoding(self, wire_client):
        """"(root)" is what topLevelSegment returns for a file with no "/", and
        the parentheses go through percent-encoding on the way here."""
        client, repo_id = wire_client
        r = client.get(f"/api/repos/{repo_id}/graph",
                       params=[("level", "file"), ("segments", "(root)")])
        assert r.status_code == 200
        assert [n["path"] for n in r.json()["nodes"]] == ["setup.py"]

    def test_absent_repeated_params_mean_unfiltered(self, wire_client):
        """The marker-default bug: Query(None) is truthy, so omitting the param
        took the filtering branch. Over the wire FastAPI substitutes None, which
        is why the direct-call tests could not see it."""
        client, repo_id = wire_client
        r = client.get(f"/api/repos/{repo_id}/graph", params={"level": "file"})
        assert r.status_code == 200
        assert r.json()["filters_active"] is False
        assert r.json()["total_nodes_before_cap"] == 5


class TestScalarCoercion:
    @pytest.mark.parametrize("raw,expected", [("true", True), ("1", True),
                                              ("false", False), ("0", False)])
    def test_hide_noise_accepts_the_forms_a_client_sends(self, wire_client, raw, expected):
        client, repo_id = wire_client
        r = client.get(f"/api/repos/{repo_id}/graph",
                       params={"level": "file", "hide_noise": raw})
        assert r.status_code == 200
        assert r.json()["filters"]["hide_noise"] is expected

    def test_limit_is_coerced_from_a_string(self, wire_client):
        client, repo_id = wire_client
        r = client.get(f"/api/repos/{repo_id}/graph", params={"level": "file", "limit": "2"})
        assert r.status_code == 200
        assert len(r.json()["nodes"]) == 2


class TestValidationFailuresOnlyTheWireCanShow:
    """FastAPI validates and rejects BEFORE the handler runs, so these status
    codes are unreachable from a direct call -- the function is never entered."""

    def test_a_non_numeric_scalar_is_422_not_500(self, wire_client):
        client, repo_id = wire_client
        r = client.get(f"/api/repos/{repo_id}/graph",
                       params={"level": "file", "limit": "not-a-number"})
        assert r.status_code == 422

    def test_a_non_boolean_hide_noise_is_422(self, wire_client):
        client, repo_id = wire_client
        r = client.get(f"/api/repos/{repo_id}/graph",
                       params={"level": "file", "hide_noise": "maybe"})
        assert r.status_code == 422

    def test_the_handlers_own_validation_still_returns_400(self, wire_client):
        """Distinguishes the two layers: a well-typed but out-of-range value
        reaches the handler and gets its 400, rather than FastAPI's 422."""
        client, repo_id = wire_client
        r = client.get(f"/api/repos/{repo_id}/graph",
                       params={"level": "file", "scorer": "nonsense"})
        assert r.status_code == 400

