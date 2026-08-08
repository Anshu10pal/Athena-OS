"""Phase B: parse a repo and build its code_files/code_symbols/code_imports.

Zero LLM calls -- every step here is deterministic local computation.

Re-ingest caching: a file whose content_sha256 is unchanged is never
re-parsed (no tree-sitter call). Import RESOLUTION, however, reruns for
every import row on every ingest -- including rows belonging to unchanged
files -- because resolving a specifier only needs the current full file set
(a cheap dict lookup), and a newly-added file can resolve an import that a
previous ingest left unresolved. Rerunning resolution is not re-parsing, so
this stays compliant with "re-ingesting an unchanged repo re-parses zero
files."
"""
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import CodeFile, CodeImport, CodeSymbol, Repo, utcnow
from app.services.codebase import (
    edge_weights, extract_js, extract_python, git_ops, js_root_discovery, node_priors, registry,
    repo_lock, resolve_imports, root_discovery,
)
from app.services.codebase.discovery import discover_files
from app.services.codebase.languages import language_for_path

BLIND_SPOTS = [
    "Dynamic import(...) is never resolved, even with a literal string argument.",
    "Decorator-registered routes, dependency injection, and monkeypatching create no static edge in any language.",
    "package.json workspaces are detected as boundaries (for cross_root flagging) but a bare specifier "
    'naming a sibling workspace package BY ITS DECLARED NAME (e.g. import "@myorg/ui-lib", not a relative '
    "path) is not resolved to that package's files -- that needs each workspace's own package.json `name` "
    "cross-referenced against bare specifiers, which is closer to Phase E3's dependency-classification work "
    "than root discovery.",
    "Python absolute-import root discovery (Phase E2.1) is evidence-based -- marker files and structural "
    "signals (a package's __init__.py parent, a directory holding a module matching an unresolved bare "
    "specifier), scored against real unresolved specifiers, not assumed. A genuinely unusual layout with "
    "none of that evidence still falls back to repo-root/src/ only, same as before Phase E2.",
    "Webpack/Vite custom aliases outside tsconfig.json/jsconfig.json compilerOptions.paths are not read.",
    "Default imports resolve to their target file but not to a specific default-exported symbol.",
    "Module-level variables/constants (e.g. `settings = Settings()`) are not extracted as symbols -- "
    "importing one resolves to the file but not to a specific symbol.",
]


class RootPromotionCollapseError(RuntimeError):
    """Phase F7's second, better-grounded hypothesis for the incident
    ResolutionRateCollapseError (ranking.py) was built to catch downstream:
    stage 2's root_discovery.promote_roots(scores) returning empty --
    evidence pool empty, thresholds not cleared, whatever the trigger --
    silently collapses resolution to the bare ["", "src"] fallback for
    every unresolved absolute Python import, with no exception anywhere in
    the loop. Deterministic under a condition that wasn't being varied,
    which is exactly why a tight ingest-verify-ingest reproduction loop
    never reproduced it. Raised here, at ingest time, before the commit
    that would persist the collapsed state -- catching it one step
    upstream of ranking.py's tripwire, which can only ever see the
    aftermath."""


@dataclass
class IngestReport:
    repo_id: int
    files_total: int
    files_parsed: int
    files_skipped_unchanged: int
    files_deleted: int
    symbols_total: int
    imports_total: int
    imports_resolved: int
    # Phase E2.3: promoted_python_roots/python_cross_root_edges only ever
    # reflect stage 2 (rows stage 1 left unresolved); js_configs_found/
    # js_cross_root_edges cover every JS/TS row, since config discovery
    # needs no unresolved-row evidence to run.
    promoted_python_roots: list = field(default_factory=list)
    python_cross_root_edges: int = 0
    js_configs_found: int = 0
    js_cross_root_edges: int = 0
    blind_spots: list = field(default_factory=lambda: list(BLIND_SPOTS))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _repo_root(repo: Repo) -> Path:
    root = Path(repo.local_path)
    return root / repo.source_root if repo.source_root else root


def ingest_repo(
    db: Session, repo: Repo, on_progress: Optional[Callable[[str, int, int, str], None]] = None
) -> IngestReport:
    """on_progress(stage, current, total, message), called at stage transitions
    and once per file during parsing. Callers decide how often to persist it
    (e.g. throttled) -- this function just calls it, it never skips calls
    itself, so a caller that wants every file need only pass a fast callback.

    Holds this repo's advisory lock (repo_lock.py) for the whole call --
    ingest re-resolves every import row in place across two stages; a rank
    read landing in that window must never happen."""
    with repo_lock.repo_lock(repo.id, "ingest"):
        return _ingest_repo_locked(db, repo, on_progress)


def _ingest_repo_locked(
    db: Session, repo: Repo, on_progress: Optional[Callable[[str, int, int, str], None]]
) -> IngestReport:
    if on_progress is None:
        on_progress = lambda *a: None  # noqa: E731

    root = _repo_root(repo)
    if not root.is_dir():
        raise ValueError(f"Repo root does not exist: {root}")

    on_progress("discovering", 0, 0, "Discovering files")
    extra_excludes = registry.protected_data_exclusion_patterns(root)
    rel_paths = discover_files(root, settings.REPO_MAX_FILES, extra_excludes=extra_excludes)  # raises TooManyFilesError, not truncated
    all_paths = {p.as_posix() for p in rel_paths}
    total_files = len(rel_paths)

    files_by_path: dict[str, CodeFile] = {
        f.path: f for f in db.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()
    }
    symbol_index: dict[str, dict[str, int]] = {}
    seen_paths: set = set()
    files_parsed = 0
    files_skipped = 0

    for i, rel in enumerate(rel_paths):
        posix_path = rel.as_posix()
        on_progress("parsing", i + 1, total_files, posix_path)
        seen_paths.add(posix_path)
        language = language_for_path(rel)
        try:
            data = (root / rel).read_bytes()
        except OSError:
            continue
        sha = _sha256(data)

        existing = files_by_path.get(posix_path)
        if existing is not None and existing.content_sha256 == sha:
            files_skipped += 1
            syms = (
                db.query(CodeSymbol)
                .filter(CodeSymbol.file_id == existing.id, CodeSymbol.parent_symbol_id.is_(None))
                .all()
            )
            symbol_index[posix_path] = {s.name: s.id for s in syms}
            continue

        try:
            if language == "python":
                raw_symbols, raw_imports = extract_python.extract(data)
            else:
                raw_symbols, raw_imports = extract_js.extract(data, language)
        except Exception:
            continue  # one unparseable file must not abort the whole ingest

        source_text = data.decode("utf-8", errors="replace")
        # Phase F2: file-local prior category only -- never "entry" here,
        # that's graph-dependent and handled solely by ranking.py's
        # write-back (see node_priors.py's module docstring).
        prior_category, prior_source = node_priors.classify_file_local_category(
            path=posix_path, source_text=source_text,
            symbol_count=len(raw_symbols),
            reexport_count=sum(1 for ri in raw_imports if ri.is_reexport),
        )

        if existing is not None:
            db.query(CodeSymbol).filter(CodeSymbol.file_id == existing.id).delete()
            db.query(CodeImport).filter(CodeImport.from_file_id == existing.id).delete()
            existing.content_sha256 = sha
            existing.size_bytes = len(data)
            existing.line_count = data.count(b"\n") + 1
            existing.language = language
            existing.last_parsed_at = utcnow()
            existing.prior_category = prior_category
            existing.prior_source = prior_source
            code_file = existing
        else:
            code_file = CodeFile(
                repo_id=repo.id, path=posix_path, language=language,
                content_sha256=sha, size_bytes=len(data), line_count=data.count(b"\n") + 1,
                prior_category=prior_category, prior_source=prior_source,
            )
            db.add(code_file)
        db.flush()
        files_by_path[posix_path] = code_file

        name_to_id: dict[str, int] = {}
        name_to_class_id: dict[str, int] = {}
        for rs in raw_symbols:
            parent_id = name_to_class_id.get(rs.parent_name) if rs.parent_name else None
            sym = CodeSymbol(
                file_id=code_file.id, parent_symbol_id=parent_id, name=rs.name, kind=rs.kind,
                signature=rs.signature, docstring=rs.docstring,
                line_start=rs.line_start, line_end=rs.line_end,
            )
            db.add(sym)
            db.flush()
            if rs.kind == "class":
                name_to_class_id[rs.name] = sym.id
            if rs.parent_name is None:
                name_to_id[rs.name] = sym.id
        symbol_index[posix_path] = name_to_id

        # Phase F1: kind is classified once here, from the raw source text
        # already in memory (decoded above for Phase F2's prior
        # classification too) -- not in the later resolution pass, since
        # it's independent of whether the import resolves internally. The
        # whole file's import-block boundary (not just this one row's own
        # line) is used so occurrence counting never trivially counts an
        # import's own declaration, and so two imports sharing a
        # locally-bound name are both measured against the same "body"
        # window (see edge_weights.py).
        import_block_end_line = max((r.line_number for r in raw_imports), default=0)

        for ri in raw_imports:
            if ri.imported_names:
                names = ri.imported_names
                locals_for_names = ri.local_names if len(ri.local_names) == len(names) else [None] * len(names)
            else:
                names = [None]
                locals_for_names = [ri.local_names[0] if ri.local_names else None]

            for name, local_name in zip(names, locals_for_names):
                kind = edge_weights.classify_edge(
                    source_text=source_text,
                    local_name=local_name,
                    original_name=name,
                    import_block_end_line=import_block_end_line,
                    from_file_path=posix_path,
                    is_reexport=ri.is_reexport,
                )
                db.add(CodeImport(
                    repo_id=repo.id, from_file_id=code_file.id, raw_specifier=ri.raw_specifier,
                    imported_names=[name] if name else [], to_file_id=None, to_symbol_id=None,
                    resolved=False, line_number=ri.line_number, kind=kind,
                ))
        files_parsed += 1

    on_progress("cleanup", total_files, total_files, "Removing deleted files")
    files_deleted = 0
    for path, cf in list(files_by_path.items()):
        if path not in seen_paths:
            db.query(CodeSymbol).filter(CodeSymbol.file_id == cf.id).delete()
            db.query(CodeImport).filter(
                (CodeImport.from_file_id == cf.id) | (CodeImport.to_file_id == cf.id)
            ).delete()
            db.delete(cf)
            del files_by_path[path]
            files_deleted += 1
    db.flush()

    # ---- resolution pass: every row, every ingest (see module docstring) ----
    # Stage 1: one honest resolution attempt per row with whatever context
    # is immediately available -- Python's pre-Phase-E2 defaults ("", "src"
    # fallback); JS/TS's nearest GOVERNING tsconfig/jsconfig (Phase E2.2,
    # exclusive, no cascading -- see js_root_discovery.config_for_file).
    # Stage 2 (below, Python only) picks up whatever stage 1 couldn't
    # resolve and applies Phase E2.1's evidence-based root discovery.
    on_progress("resolving", 0, 0, "Resolving imports")
    id_to_file = {cf.id: cf for cf in files_by_path.values()}
    all_rows = db.query(CodeImport).filter(CodeImport.repo_id == repo.id).all()
    imports_resolved = 0

    js_configs = js_root_discovery.find_ts_configs(root)
    workspace_dirs = js_root_discovery.find_package_json_workspace_dirs(root)
    js_config = js_root_discovery.load_js_root_discovery_config()
    js_cross_root_edges = 0

    unresolved_python_rows = []  # (row, from_file, name) -- stage 2 candidates
    for row in all_rows:
        from_file = id_to_file.get(row.from_file_id)
        if from_file is None:
            continue
        name = row.imported_names[0] if row.imported_names else None
        to_path: Optional[str] = None
        is_submodule = False
        cross_root_kind: Optional[str] = None

        if from_file.language == "python":
            to_path, is_submodule = resolve_imports.resolve_python_import(
                row.raw_specifier, name, from_file.path, all_paths
            )
            if to_path is None and not row.raw_specifier.startswith("."):
                unresolved_python_rows.append((row, from_file, name))
        else:
            governing_config = js_root_discovery.config_for_file(from_file.path, js_configs)
            to_path = resolve_imports.resolve_js_module(
                row.raw_specifier, from_file.path, all_paths,
                path_aliases=(governing_config["paths"] if governing_config else {}),
                extension_probe_order=js_config["extension_probe_order"],
                try_index_resolution=js_config["try_index_resolution"],
            )
            if to_path is not None:
                from_ws = js_root_discovery.workspace_of(from_file.path, workspace_dirs)
                to_ws = js_root_discovery.workspace_of(to_path, workspace_dirs)
                if from_ws != to_ws:
                    cross_root_kind = "workspace_boundary"
                    js_cross_root_edges += 1

        to_file = files_by_path.get(to_path) if to_path else None
        row.to_file_id = to_file.id if to_file else None
        row.resolved = to_file is not None
        row.to_symbol_id = None
        row.cross_root_kind = cross_root_kind if to_file is not None else None
        if to_file is not None and not is_submodule and name and name not in ("default", "*"):
            row.to_symbol_id = symbol_index.get(to_path, {}).get(name)
        if row.resolved:
            imports_resolved += 1

    # Stage 2 (Python only): evidence-based root discovery, scored against
    # exactly the rows stage 1 couldn't resolve. Free short-circuit first --
    # a stdlib specifier can never resolve internally regardless of root
    # (root_discovery.py's own scoring denominator excludes it the same
    # way), so it's skipped before any per-root probing, at zero cost.
    promoted_python_roots: list = []
    python_cross_root_edges = 0
    if unresolved_python_rows:
        evidence_rows = [
            {"from_file": from_file.path, "raw_specifier": row.raw_specifier, "name": name}
            for row, from_file, name in unresolved_python_rows
        ]
        partition = root_discovery.partition_unresolved_specifiers(evidence_rows)
        not_yet_classified = partition["not_yet_classified"]
        stdlib_keys = {(r["raw_specifier"], r["from_file"]) for r in partition["stdlib"]}

        python_files = {f.path for f in files_by_path.values() if f.language == "python"}
        candidate_roots = (
            root_discovery.find_marker_candidate_roots(root)
            | root_discovery.find_structural_candidate_roots(
                python_files, [r["raw_specifier"] for r in not_yet_classified]
            )
        )
        scores = root_discovery.score_candidate_roots(candidate_roots, not_yet_classified, all_paths)
        promoted = root_discovery.promote_roots(scores)
        promoted_python_roots = sorted(promoted)

        if repo.last_promoted_python_roots and not promoted_python_roots:
            raise RootPromotionCollapseError(
                f"Repo {repo.id} ({repo.host}/{repo.owner}/{repo.name}): Python root promotion returned "
                f"EMPTY this ingest, but the previous ingest promoted {repo.last_promoted_python_roots} -- "
                "refusing to commit a resolution pass that would silently fall back to [\"\", \"src\"] for "
                f"every one of this ingest's {len(unresolved_python_rows)} unresolved absolute Python "
                "imports. If this repo genuinely lost the structure that justified those roots (e.g. a "
                "large deletion), clear repo.last_promoted_python_roots to accept the new baseline; "
                "otherwise this points at a real bug in root_discovery.promote_roots."
            )

        for row, from_file, name in unresolved_python_rows:
            if (row.raw_specifier, from_file.path) in stdlib_keys:
                continue  # cannot resolve internally by definition -- never probed

            nearest = root_discovery.nearest_promoted_root(from_file.path, promoted)
            ordered_roots = ([nearest] if nearest is not None else [])
            ordered_roots += sorted(promoted - {nearest}, key=root_discovery.root_depth, reverse=True)
            ordered_roots += ["", "src"]
            seen: set = set()
            deduped_roots = [r for r in ordered_roots if not (r in seen or seen.add(r))]

            winning_root, to_path, is_submodule = None, None, False
            for candidate_root in deduped_roots:
                attempt_path, attempt_is_submodule = resolve_imports.resolve_python_import(
                    row.raw_specifier, name, from_file.path, all_paths, roots=[candidate_root]
                )
                if attempt_path:
                    winning_root, to_path, is_submodule = candidate_root, attempt_path, attempt_is_submodule
                    break

            to_file = files_by_path.get(to_path) if to_path else None
            if to_file is None:
                continue  # stays unresolved -- a real gap or an unclassified third-party specifier

            row.to_file_id = to_file.id
            row.resolved = True
            row.cross_root_kind = "root_fallback" if winning_root != nearest else None
            if not is_submodule and name and name not in ("default", "*"):
                row.to_symbol_id = symbol_index.get(to_path, {}).get(name)
            imports_resolved += 1
            if row.cross_root_kind is not None:
                python_cross_root_edges += 1

    # Unconditional, every ingest -- the Phase F7 incident was invisible
    # precisely because nothing surfaced what root promotion actually did
    # on a given run. Printed rather than gated behind on_progress, so it
    # shows up in server logs even when nothing is watching progress events.
    if unresolved_python_rows:
        print(f"[ingest] repo {repo.id}: Python root promotion ran, promoted={promoted_python_roots}")
    else:
        print(f"[ingest] repo {repo.id}: Python root promotion skipped (no unresolved absolute imports needing it)")
    repo.last_promoted_python_roots = promoted_python_roots

    repo.last_ingested_sha = git_ops.get_head_sha(repo.local_path)
    repo.last_ingested_at = utcnow()
    repo.file_count = len(rel_paths)
    db.commit()

    symbols_total = (
        db.query(CodeSymbol).join(CodeFile, CodeSymbol.file_id == CodeFile.id)
        .filter(CodeFile.repo_id == repo.id).count()
    )
    on_progress("ingest_done", total_files, total_files, "Ingest complete")

    return IngestReport(
        repo_id=repo.id,
        files_total=len(rel_paths),
        files_parsed=files_parsed,
        files_skipped_unchanged=files_skipped,
        files_deleted=files_deleted,
        symbols_total=symbols_total,
        imports_total=len(all_rows),
        imports_resolved=imports_resolved,
        promoted_python_roots=promoted_python_roots,
        python_cross_root_edges=python_cross_root_edges,
        js_configs_found=len(js_configs),
        js_cross_root_edges=js_cross_root_edges,
    )
