"""Phase 5: comprehension cards -- quality filter, generation, the source seam,
grading dispatch, and conservation on the write path.

Written under the verification bar this phase was given: assert the POPULATION
after a write, not only that the object under test survived. Both persistence
bugs in the previous phase passed tests that checked the intended object and
never counted the table.
"""
import pytest
from fastapi import HTTPException

from app.db.models import ComprehensionCard, Module, Repo
from app.services.codebase import card_generation, card_grading, card_quality
from app.services.codebase.card_persist import ConservationError, _assert_conserved


class TestCardQualityFilter:
    """The filter specified early in the project and never built. It applies to
    BOTH card sources, which is why it is not inside the generator."""

    def test_LOADBEARING_a_card_answerable_from_the_name_is_rejected(self):
        # The real observed case: a barrel importing its own sibling.
        assert card_quality.is_name_guessable(
            "lib/linter/index.js",
            "linter/linter.js",
            ["conf/globals.js", "bin/eslint.js", "docs/.eleventy.js"],
        )

    def test_LOADBEARING_a_card_needing_real_knowledge_is_kept(self):
        # Also real: nothing in the name of bin/eslint.js says it reaches cli.js
        # rather than any other CLI-adjacent file.
        assert not card_quality.is_name_guessable(
            "bin/eslint.js",
            "lib/cli.js",
            ["cli-engine/hash.js", "cli-engine/lint-result-cache.js",
             "formatters/stylish.js"],
        )

    def test_camelCase_and_kebab_case_are_the_same_name(self):
        """`sourceCodeFixer` and `source-code-fixer` are one name in two
        styles; a tokenizer that missed that would pass exactly the cards the
        filter exists to catch."""
        assert card_quality.tokenize("sourceCodeFixer") == \
               card_quality.tokenize("source-code-fixer")

    def test_generic_segments_do_not_count_as_similarity(self):
        """Almost every path contains src/lib/index, so overlap on those says
        nothing about whether the name gives the answer away."""
        assert "src" not in card_quality.tokenize("src/thing.js")
        assert "index" not in card_quality.tokenize("lib/index.js")

    def test_a_free_text_card_is_not_judged_by_this_filter(self):
        """With no distractors there is no "pick the most similar option"
        strategy to defeat, and claiming otherwise would reject every llm card
        sight unseen."""
        assert not card_quality.is_name_guessable("lib/linter.js", "linter.js", [])

    def test_reject_reason_names_the_problem(self):
        assert card_quality.reject_reason("x", "", ["a"]) == "no answer"
        assert "distractors" in card_quality.reject_reason("x", "a", ["a", "b"])
        assert "duplicate" in card_quality.reject_reason("x", "a", ["b", "b"])
        assert card_quality.reject_reason(
            "bin/eslint.js", "lib/cli.js", ["cli-engine/hash.js", "formatters/stylish.js"]
        ) == ""


def _facts(n=8):
    paths = [f"pkg/mod{i}.js" for i in range(n)]
    return {
        "module_title": "pkg",
        "module_paths": paths,
        "owned_paths": paths,
        "other_module_titles": ["other-a", "other-b", "other-c"],
        "imports_by_path": {paths[0]: {paths[1]}, paths[2]: {paths[3]}},
        "importers_by_path": {paths[1]: {paths[0]}},
        "fan_in_ranked": [(p, n - i) for i, p in enumerate(paths)],
        "rank_ordered": paths,
        "layer_by_path": {p: i for i, p in enumerate(paths)},
    }


class TestDeterministicGeneration:
    def test_every_answer_is_among_the_options(self):
        cards, _ = card_generation.generate_deterministic_cards(_facts())
        assert cards
        for c in cards:
            assert c.answer in c.options

    def test_LOADBEARING_generation_is_reproducible(self):
        """No RNG anywhere: a regeneration on unchanged input must produce
        identical cards, or the conservation check could not compare a run
        against its predecessor and mean anything."""
        a, _ = card_generation.generate_deterministic_cards(_facts())
        b, _ = card_generation.generate_deterministic_cards(_facts())
        assert [(c.template, c.question, c.answer, c.options) for c in a] == \
               [(c.template, c.question, c.answer, c.options) for c in b]

    def test_LOADBEARING_the_cap_is_enforced(self):
        cards, _ = card_generation.generate_deterministic_cards(_facts(30), cap=6)
        assert len(cards) <= 6

    def test_LOADBEARING_the_cap_prefers_variety_over_one_template(self):
        """Variety across templates beats coverage within one -- otherwise the
        cap yields the first template's output truncated."""
        cards, _ = card_generation.generate_deterministic_cards(_facts(30), cap=6)
        assert len({c.template for c in cards}) > 1

    def test_distractors_are_not_identical_across_cards(self):
        """The failure found by reading generated cards: every question in a
        module offering the same three wrong options, so a learner scores by
        elimination without knowing anything."""
        facts = _facts(20)
        facts["imports_by_path"] = {
            f"pkg/mod{i}.js": {f"pkg/mod{(i + 1) % 20}.js"} for i in range(10)
        }
        cards, _ = card_generation.generate_deterministic_cards(facts, cap=50)
        import_cards = [c for c in cards if c.template == "which_does_it_import"]
        assert len(import_cards) >= 3
        assert len({tuple(sorted(c.distractors)) for c in import_cards}) > 1

    def test_rejections_are_returned_not_silently_dropped(self):
        """Three cards because three opportunities existed, and three because
        five were rejected, are different situations needing different
        responses -- a bare count cannot tell them apart."""
        facts = _facts(6)
        facts["imports_by_path"] = {"pkg/linter.js": {"pkg/linter-core.js"}}
        facts["module_paths"] = facts["module_paths"] + ["pkg/linter.js", "pkg/linter-core.js"]
        _, rejected = card_generation.generate_deterministic_cards(facts)
        assert isinstance(rejected, list)
        assert all(isinstance(r, tuple) and len(r) == 2 for r in rejected)

    def test_LOADBEARING_a_module_stem_question_is_judged_against_the_module(self):
        """A question whose stem names the MODULE has no file identifier on
        screen to guess from, so the filter must judge it against the module,
        not against `subject_path` -- which for these templates is the ANSWER,
        making the card resemble itself and be rejected every time its answer
        had a distinctive filename.

        Measured before the fix: 6 legitimate cards lost on Athena-OS, 11 on
        eslint, 24 on Superset, with zero cards newly rejected by the fix and
        no effect on the file-stem templates already validated."""
        facts = _facts(12)
        facts["module_title"] = "pkg"
        facts["fan_in_ranked"] = [("pkg/distinctive_name.js", 99)] + [
            (p, 1) for p in facts["module_paths"]]
        cards, rejected = card_generation.generate_deterministic_cards(facts, cap=50)
        templates = {c.template for c in cards}
        assert "most_depended_on" in templates, \
            "a module-stem card must survive the identifier filter"
        assert not [t for t, _ in rejected if t == "most_depended_on"]

    def test_module_stem_templates_declare_their_filter_subject(self):
        """Pinned directly, not only through its symptom: `subject_path` (the
        code link) and `filter_subject` (what a guesser sees) are different
        things, and conflating them was the bug."""
        facts = _facts(12)
        cards, _ = card_generation.generate_deterministic_cards(facts, cap=50)
        for c in cards:
            if c.template in ("most_depended_on", "closest_to_entry", "reading_order"):
                assert c.filter_subject == facts["module_title"]
            else:
                assert c.filter_subject is None

    def test_a_tie_does_not_produce_a_most_depended_on_card(self):
        """Manufacturing a single right answer where the data has a tie would
        make the card wrong, not merely hard."""
        facts = _facts(6)
        facts["fan_in_ranked"] = [(p, 5) for p in facts["module_paths"]]
        cards, _ = card_generation.generate_deterministic_cards(facts, cap=50)
        assert not [c for c in cards if c.template == "most_depended_on"]


class TestTheSourceSeam:
    """The seam is a column, a dispatch table and a raising stub -- not a note."""

    def test_both_sources_are_registered_from_day_one(self):
        assert set(card_generation.GENERATORS) == {
            card_generation.SOURCE_DETERMINISTIC, card_generation.SOURCE_LLM}
        assert set(card_grading.GRADERS) == set(card_generation.GENERATORS)

    def test_LOADBEARING_the_llm_generator_exists_and_raises(self):
        """Exists so wiring it later fills a hole rather than cutting one, and
        raises rather than returning [] so "not built" cannot be mistaken for
        "found nothing to ask"."""
        with pytest.raises(NotImplementedError):
            card_generation.generate_llm_cards(_facts())

    def test_LOADBEARING_the_llm_grader_exists_and_raises(self):
        """Returning Grade(correct=False) would mark every learner wrong on a
        card type nobody built a grader for -- worse than an error, because it
        looks like data."""
        with pytest.raises(NotImplementedError):
            card_grading.grade_llm_card(object(), "anything")

    def test_generated_cards_carry_their_source(self):
        cards, _ = card_generation.generate_cards(_facts())
        assert cards and all(
            c.card_source == card_generation.SOURCE_DETERMINISTIC for c in cards)

    def test_LOADBEARING_a_card_row_cannot_omit_its_source(self):
        """The seam had a Python-side default, which is §17.28's own defect:
        a writer that FORGOT to say what a card was produced a row identical to
        one that meant it, and grading then dispatched on that claim. Omitting
        it must fail at insert rather than silently reading 'deterministic'."""
        import sqlalchemy.exc
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.db.database import Base

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        session = sessionmaker(bind=engine)()
        try:
            session.add(Module(slug="m", title="m", source="codebase", code_repo_id=1))
            session.flush()
            session.add(ComprehensionCard(module_id=1, question="q", answer="a"))
            with pytest.raises(sqlalchemy.exc.IntegrityError):
                session.flush()
        finally:
            session.rollback()
            session.close()
            engine.dispose()

    def test_an_unknown_source_is_refused_by_both_halves(self):
        with pytest.raises(ValueError):
            card_generation.generate_cards(_facts(), card_source="telepathy")

        class Fake:
            card_source = "telepathy"
        with pytest.raises(ValueError):
            card_grading.grade_card(Fake(), "x")


class TestGrading:
    class _Card:
        card_source = card_generation.SOURCE_DETERMINISTIC
        answer = "lib/cli.js"
        rationale = "bin/eslint.js requires ../lib/cli"
        id = 1

    def test_correct_answer_scores_full(self):
        g = card_grading.grade_card(self._Card(), "lib/cli.js")
        assert g.correct and g.score == 100

    def test_whitespace_and_case_are_not_wrong_answers(self):
        g = card_grading.grade_card(self._Card(), "  LIB/CLI.JS ")
        assert g.correct

    def test_a_wrong_answer_is_told_what_was_right(self):
        g = card_grading.grade_card(self._Card(), "conf/globals.js")
        assert not g.correct and g.score == 0
        assert "lib/cli.js" in g.rationale

    def test_LOADBEARING_grading_dispatches_on_the_row_not_the_question(self):
        """A deterministic card that happens to read like prose must still
        grade deterministically."""
        class Prosey(TestGrading._Card):
            question = "Why does the linter separate rule-fixer from source-code-fixer?"
        assert card_grading.grade_card(Prosey(), "lib/cli.js").correct

    def test_a_card_with_no_answer_raises_rather_than_failing_the_learner(self):
        class Empty:
            card_source = card_generation.SOURCE_DETERMINISTIC
            answer = ""
            id = 7
        with pytest.raises(ValueError):
            card_grading.grade_card(Empty(), "anything")


class TestConservation:
    """The bar this phase was given: assert the population, not the survival of
    the thing under test."""

    def test_the_equation_holds_for_a_clean_replace(self):
        _assert_conserved("t", before=10, after=12, created=12, deleted=10)

    def test_LOADBEARING_a_leftover_row_is_caught(self):
        """The exact shape of the stranded-topic bug: the new rows were written
        and the old ones were not removed. Two of three terms right."""
        with pytest.raises(ConservationError) as e:
            _assert_conserved("t", before=10, after=22, created=12, deleted=10)
        assert "discrepancy of 10" in str(e.value)

    def test_the_error_states_the_arithmetic(self):
        with pytest.raises(ConservationError) as e:
            _assert_conserved("comprehension_cards", before=5, after=5, created=3, deleted=0)
        msg = str(e.value)
        assert "comprehension_cards" in msg and "5 before" in msg and "3 created" in msg


class TestCardPersistenceIntegration:
    def _repo_with_module(self, db_session):
        from app.db.models import CodeFile, CodeImport, Resource, Topic
        repo = Repo(host="local", owner="", name="cards-fixture",
                    local_path="/nonexistent", source_kind="local",
                    last_ingested_sha="deadbeef")
        db_session.add(repo)
        db_session.flush()
        module = Module(slug="cards-mod", title="pkg", source="codebase",
                        code_repo_id=repo.id)
        db_session.add(module)
        db_session.flush()
        topic = Topic(module_id=module.id, slug="files-0", title="Files",
                      source="codebase")
        db_session.add(topic)
        db_session.flush()
        files = []
        for i in range(8):
            f = CodeFile(repo_id=repo.id, path=f"pkg/mod{i}.js", language="javascript",
                         content_sha256=f"sha{i}", fan_in=8 - i, seed_eligible=(i == 0))
            db_session.add(f)
            files.append(f)
            db_session.add(Resource(topic_id=topic.id, kind="doc", title=f"mod{i}",
                                    order_index=i, code_repo_id=repo.id,
                                    code_path=f"pkg/mod{i}.js"))
        db_session.flush()
        for i in range(4):
            db_session.add(CodeImport(repo_id=repo.id, from_file_id=files[i].id,
                                      to_file_id=files[i + 1].id,
                                      raw_specifier=f"./mod{i + 1}", resolved=True))
        db_session.commit()
        return repo

    def test_LOADBEARING_regenerating_conserves_the_row_count(self, db_session):
        """Not "the cards survived" -- the table's total, which is the check
        that would have caught both of the previous phase's bugs."""
        from app.services.codebase.card_persist import generate_repo_cards
        repo = self._repo_with_module(db_session)
        first = generate_repo_cards(db_session, repo, commit_sha="deadbeef")
        total_after_first = db_session.query(ComprehensionCard).count()

        second = generate_repo_cards(db_session, repo, commit_sha="deadbeef")
        assert second["conservation"]["holds"]
        assert db_session.query(ComprehensionCard).count() == total_after_first
        assert second["cards_deleted"] == first["cards_created"]

    def test_cards_carry_the_seam_column_and_a_commit_sha(self, db_session):
        from app.services.codebase.card_persist import generate_repo_cards
        repo = self._repo_with_module(db_session)
        generate_repo_cards(db_session, repo, commit_sha="deadbeef")
        rows = db_session.query(ComprehensionCard).filter(
            ComprehensionCard.code_repo_id == repo.id).all()
        assert rows
        assert all(r.card_source == "deterministic" for r in rows)
        assert all(r.code_commit_sha == "deadbeef" for r in rows)
        assert all(r.template for r in rows)

    def test_zero_counters_are_reported_rather_than_omitted(self, db_session):
        """Silence is not evidence: anything that could destroy state reports
        its count whether or not it fired."""
        from app.services.codebase.card_persist import generate_repo_cards
        repo = self._repo_with_module(db_session)
        report = generate_repo_cards(db_session, repo)
        for key in ("cards_deleted", "cards_rejected", "modules_with_no_cards",
                    "rejections_by_reason", "conservation"):
            assert key in report

    def test_refuses_when_the_repo_has_no_modules(self, db_session):
        from app.services.codebase.card_persist import generate_repo_cards
        repo = Repo(host="local", owner="", name="no-modules",
                    local_path="/nonexistent", source_kind="local")
        db_session.add(repo)
        db_session.commit()
        with pytest.raises(ValueError):
            generate_repo_cards(db_session, repo)

    def test_LOADBEARING_another_repos_cards_are_never_touched(self, db_session):
        from app.services.codebase.card_persist import generate_repo_cards
        repo_a = self._repo_with_module(db_session)
        generate_repo_cards(db_session, repo_a)
        other = Module(slug="other-repo-mod", title="other", source="codebase",
                       code_repo_id=4242)
        db_session.add(other)
        db_session.flush()
        db_session.add(ComprehensionCard(module_id=other.id, code_repo_id=4242,
                                         card_source="deterministic",
                                         question="q", answer="a"))
        db_session.commit()

        generate_repo_cards(db_session, repo_a)
        assert db_session.query(ComprehensionCard).filter(
            ComprehensionCard.code_repo_id == 4242).count() == 1


class TestGradeCardEndpoint:
    """The HTTP surface for grading, added when the card UI was built.

    Until then `card_grading.grade_card` was written, tested, and callable only
    from inside the process -- the same built-but-unreachable shape as the cards
    themselves. The frontend grades through this route rather than comparing
    strings locally: `grade_deterministic_card` normalises with
    `" ".join(text.split()).casefold()`, and a browser doing its own match would
    agree until someone changed that normalisation, at which point the two would
    disagree with nothing failing (§17.28).
    """

    def _repo_with_cards(self, db_session):
        from app.db.models import CodeFile, CodeImport, Resource, Topic
        from app.services.codebase.card_persist import generate_repo_cards
        repo = Repo(host="local", owner="", name="grade-fixture",
                    local_path="/nonexistent", source_kind="local",
                    last_ingested_sha="cafe1234")
        db_session.add(repo)
        db_session.flush()
        module = Module(slug="grade-mod", title="pkg", source="codebase",
                        code_repo_id=repo.id)
        db_session.add(module)
        db_session.flush()
        topic = Topic(module_id=module.id, slug="files-0", title="Files", source="codebase")
        db_session.add(topic)
        db_session.flush()
        files = []
        for i in range(8):
            f = CodeFile(repo_id=repo.id, path=f"pkg/mod{i}.js", language="javascript",
                         content_sha256=f"g{i}", fan_in=8 - i, seed_eligible=(i == 0))
            db_session.add(f)
            files.append(f)
            db_session.add(Resource(topic_id=topic.id, kind="doc", title=f"mod{i}",
                                    order_index=i, code_repo_id=repo.id,
                                    code_path=f"pkg/mod{i}.js"))
        db_session.flush()
        for i in range(4):
            db_session.add(CodeImport(repo_id=repo.id, from_file_id=files[i].id,
                                      to_file_id=files[i + 1].id,
                                      raw_specifier=f"./mod{i + 1}", resolved=True))
        db_session.commit()
        generate_repo_cards(db_session, repo, commit_sha="cafe1234")
        card = db_session.query(ComprehensionCard).filter(
            ComprehensionCard.code_repo_id == repo.id).first()
        assert card is not None, "fixture must produce at least one card"
        return repo, card

    def test_LOADBEARING_a_correct_answer_grades_correct(self, db_session):
        from app.api.repos import CardAnswerIn, grade_repo_card
        repo, card = self._repo_with_cards(db_session)
        out = grade_repo_card(repo.id, card.id, CardAnswerIn(response=card.answer),
                              user=None, db=db_session)
        assert out["correct"] is True
        assert out["score"] == 100
        assert out["rationale"]

    def test_LOADBEARING_a_wrong_answer_returns_the_answer_and_rationale(self, db_session):
        """Getting one wrong must TEACH the edge, not just mark it wrong -- the
        rationale names the stored fact the answer came from."""
        from app.api.repos import CardAnswerIn, grade_repo_card
        repo, card = self._repo_with_cards(db_session)
        wrong = next(o for o in card.options if o != card.answer)
        out = grade_repo_card(repo.id, card.id, CardAnswerIn(response=wrong),
                              user=None, db=db_session)
        assert out["correct"] is False
        assert out["score"] == 0
        assert card.answer in out["rationale"] or out["answer"] == card.answer

    def test_LOADBEARING_grading_matches_grade_card_on_whitespace_and_case(self, db_session):
        """The §17.28 guard. This is WHY the browser round-trips instead of
        comparing strings: the normalisation lives in one place, and this pins
        that the endpoint applies it rather than doing its own comparison."""
        from app.api.repos import CardAnswerIn, grade_repo_card
        repo, card = self._repo_with_cards(db_session)
        noisy = f"   {card.answer.upper()}   "
        out = grade_repo_card(repo.id, card.id, CardAnswerIn(response=noisy),
                              user=None, db=db_session)
        assert out["correct"] is True, (
            "the endpoint must normalise like grade_deterministic_card does")

    def test_a_card_from_another_repo_is_not_gradeable_through_this_route(self, db_session):
        from app.api.repos import CardAnswerIn, grade_repo_card
        repo, card = self._repo_with_cards(db_session)
        with pytest.raises(HTTPException) as e:
            grade_repo_card(repo.id + 999, card.id, CardAnswerIn(response=card.answer),
                            user=None, db=db_session)
        assert e.value.status_code == 404

    def test_an_unknown_card_is_404_not_500(self, db_session):
        from app.api.repos import CardAnswerIn, grade_repo_card
        repo, _ = self._repo_with_cards(db_session)
        with pytest.raises(HTTPException) as e:
            grade_repo_card(repo.id, 999_999, CardAnswerIn(response="x"),
                            user=None, db=db_session)
        assert e.value.status_code == 404

    def test_the_llm_seam_reports_501_not_a_crash(self, db_session):
        """A declared-but-unbuilt capability is not a malformed request."""
        from app.api.repos import CardAnswerIn, grade_repo_card
        repo, card = self._repo_with_cards(db_session)
        card.card_source = "llm"
        db_session.commit()
        with pytest.raises(HTTPException) as e:
            grade_repo_card(repo.id, card.id, CardAnswerIn(response="anything"),
                            user=None, db=db_session)
        assert e.value.status_code == 501
