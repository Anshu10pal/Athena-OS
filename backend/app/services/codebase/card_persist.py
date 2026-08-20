"""Phase 5: building card facts from the graph, and writing cards.

Reads only what earlier phases already computed -- resolved `CodeImport`
edges, subsystem membership, `CodeFile.fan_in`, ranks, BFS layers -- so a card
never asserts anything the database cannot be asked to confirm.

**Conservation is checked here, not only in tests.** Both bugs in the
persistence work were invisible to green tests and visible in one number, and
the pattern was the same: the assertion covered the object under test and
never counted the table. So every write returns rows-before, rows-after and
the delta, and `_assert_conserved` raises if they disagree -- a write that
quietly leaves a duplicate behind fails at the point it happens rather than
being noticed later by someone reading a total.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import (
    CodeFile, CodeFileRank, CodeImport, ComprehensionCard, Module, Repo, Resource,
    Topic,
)
from app.services.codebase import card_generation
from app.services.codebase.ordering import compute_layers


class ConservationError(AssertionError):
    """A write did not conserve the row count it claimed to.

    An AssertionError subclass rather than a plain one so a caller can catch
    exactly this and report it, without swallowing unrelated assertion
    failures from libraries.
    """


def _assert_conserved(label: str, before: int, after: int, created: int,
                      deleted: int) -> None:
    """after == before + created - deleted, or raise saying by how much.

    The equation is stated rather than checking any two of the three terms:
    both bugs this pattern exists for had two terms right and the third wrong,
    which is exactly the shape a partial check misses.

    LIMITATION, stated so "conservation holds" is not read as more than it is:
    **this checks COUNTS, not content.** A write that replaced N rows with N
    different rows -- wrong questions, wrong answers, wrong module -- satisfies
    it exactly. It catches the leak (rows left behind, rows lost) that the two
    persistence bugs were, and it cannot catch a corruption that preserves
    cardinality. Content correctness is the separate job of the per-card
    assertions in the test suite, and nothing here substitutes for them.
    """
    expected = before + created - deleted
    if after != expected:
        raise ConservationError(
            f"{label}: expected {expected} rows "
            f"({before} before + {created} created - {deleted} deleted) "
            f"but found {after}, a discrepancy of {after - expected}"
        )


def build_module_facts(db: Session, repo: Repo, module: Module,
                       all_module_titles: list) -> dict:
    """Everything the deterministic templates need for one module, read from
    stored facts. No parsing, no filesystem, no LLM."""
    # The module's files, via its resources' code_path -- the same membership
    # roadmap_persist writes, so a card and a reading list cannot disagree
    # about what is in the module.
    member_paths = sorted({
        p for (p,) in db.query(Resource.code_path)
        .join(Topic, Resource.topic_id == Topic.id)
        .filter(Topic.module_id == module.id, Resource.code_path.isnot(None))
        .all()
    })
    if not member_paths:
        return {}

    member_set = set(member_paths)
    files = db.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()
    id_by_path = {f.path: f.id for f in files}
    path_by_id = {f.id: f.path for f in files}
    fan_in_by_path = {f.path: (f.fan_in or 0) for f in files}

    member_ids = {id_by_path[p] for p in member_paths if p in id_by_path}
    imports_by_path: dict = {}
    importers_by_path: dict = {}
    for from_id, to_id in db.query(CodeImport.from_file_id, CodeImport.to_file_id).filter(
        CodeImport.repo_id == repo.id, CodeImport.to_file_id.isnot(None)
    ).all():
        a, b = path_by_id.get(from_id), path_by_id.get(to_id)
        if a is None or b is None:
            continue
        if from_id in member_ids and b in member_set:
            imports_by_path.setdefault(a, set()).add(b)
        if to_id in member_ids and a in member_set:
            importers_by_path.setdefault(b, set()).add(a)

    rank_by_path = {}
    for file_id, rank in db.query(CodeFileRank.file_id, CodeFileRank.rank).filter(
        CodeFileRank.repo_id == repo.id, CodeFileRank.scorer == "legacy"
    ).all():
        p = path_by_id.get(file_id)
        if p in member_set:
            rank_by_path[p] = rank

    return {
        "module_title": module.title,
        "module_paths": member_paths,
        "owned_paths": member_paths,
        "other_module_titles": [t for t in all_module_titles if t != module.title],
        "imports_by_path": imports_by_path,
        "importers_by_path": importers_by_path,
        "fan_in_ranked": sorted(
            ((p, fan_in_by_path.get(p, 0)) for p in member_paths),
            key=lambda t: (-t[1], t[0]),
        ),
        "rank_ordered": [
            p for p in sorted(rank_by_path, key=lambda p: rank_by_path[p])
        ],
        "layer_by_path": {},   # filled by the caller, which has the graph
    }


def generate_repo_cards(db: Session, repo: Repo, *,
                        card_source: str = card_generation.SOURCE_DETERMINISTIC,
                        cap: int = card_generation.MAX_CARDS_PER_MODULE,
                        commit_sha: Optional[str] = None) -> dict:
    """Regenerate this repo's comprehension cards.

    Scoped exactly like roadmap persistence: only rows whose module is a
    `codebase` module of THIS repo are ever touched. Cards carry no user state,
    so they are replaced wholesale -- which is what makes the conservation
    equation exact rather than approximate.
    """
    modules = db.query(Module).filter(
        Module.source == "codebase", Module.code_repo_id == repo.id,
        Module.code_orphaned_at.is_(None),
    ).order_by(Module.id).all()
    if not modules:
        raise ValueError(
            f"repo {repo.id} has no codebase modules -- write its roadmap first. "
            "Generating cards for nothing would report success over an empty set."
        )

    # Layers once for the repo, not per module: it is a property of the whole
    # graph and recomputing it per module would also risk two modules
    # disagreeing about a file's depth.
    from app.api.repos import _build_graph
    file_by_id = {f.id: f for f in db.query(CodeFile).filter(
        CodeFile.repo_id == repo.id).all()}
    graph = _build_graph(db, repo, file_by_id)
    entry_ids = {fid for fid, f in file_by_id.items() if f.seed_eligible}
    layer_by_file_id = compute_layers(graph, entry_ids)
    layer_by_path = {
        file_by_id[fid].path: depth
        for fid, depth in layer_by_file_id.items() if fid in file_by_id
    }

    module_ids = [m.id for m in modules]
    total_before = db.query(ComprehensionCard).count()
    deleted = db.query(ComprehensionCard).filter(
        ComprehensionCard.module_id.in_(module_ids)).count()
    db.query(ComprehensionCard).filter(
        ComprehensionCard.module_id.in_(module_ids)).delete(synchronize_session=False)
    db.flush()

    titles = [m.title for m in modules]
    created = 0
    rejected_total = 0
    rejections_by_reason: dict = {}
    by_template: dict = {}
    modules_with_no_cards = []

    for module in modules:
        facts = build_module_facts(db, repo, module, titles)
        if not facts:
            modules_with_no_cards.append(module.slug)
            continue
        facts["layer_by_path"] = {
            p: layer_by_path.get(p) for p in facts["module_paths"]
        }
        cards, rejected = card_generation.generate_cards(
            facts, card_source=card_source, cap=cap)
        for template, reason in rejected:
            rejected_total += 1
            rejections_by_reason[reason] = rejections_by_reason.get(reason, 0) + 1
        if not cards:
            modules_with_no_cards.append(module.slug)
        for card in cards:
            db.add(ComprehensionCard(
                module_id=module.id, code_repo_id=repo.id,
                card_source=card.card_source, template=card.template,
                question=card.question, options=card.options, answer=card.answer,
                rationale=card.rationale, subject_path=card.subject_path,
                code_commit_sha=commit_sha, order_index=card.order_index,
            ))
            created += 1
            by_template[card.template] = by_template.get(card.template, 0) + 1

    db.flush()
    total_after = db.query(ComprehensionCard).count()
    _assert_conserved("comprehension_cards", total_before, total_after, created, deleted)
    db.commit()

    return {
        "repo_id": repo.id,
        "card_source": card_source,
        "cap_per_module": cap,
        "modules_considered": len(modules),
        # Reported even when empty: a module that produced no cards is a
        # finding, not a gap in the output.
        "modules_with_no_cards": modules_with_no_cards,
        "cards_created": created,
        "cards_deleted": deleted,
        "cards_by_template": by_template,
        # Reported even when zero -- "nothing was rejected" and "rejection was
        # never checked" must not look alike.
        "cards_rejected": rejected_total,
        "rejections_by_reason": rejections_by_reason,
        "conservation": {
            "rows_before": total_before,
            "rows_after": total_after,
            "expected": total_before + created - deleted,
            "holds": total_after == total_before + created - deleted,
        },
    }
