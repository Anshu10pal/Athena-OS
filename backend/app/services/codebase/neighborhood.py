"""Phase 6 checkpoint 2: a file's dependency neighbourhood.

**What this is for.** Not an export. When Claude Code is about to work on one
file, this hands it the connected set directly, so it reads what matters instead
of grepping around to discover what is connected and then reading that. The
graph is a targeting map for reads.

**Reads through the 1a boundary and nothing else.** Same rule as the emitter,
same canary: stub `read_repo_graph` and no real data may survive.

**Sufficiency is the correctness bar, not cheapness.** A neighbourhood that is
small but incomplete is worse than useless -- the agent reads the files it names,
discovers something was missing, and reads more anyway, having paid for the
query on top. So the rule for the DIRECT neighbourhood -- the part sufficiency depends on --
is: **a path is never dropped.** (The opt-in second hop is the one bounded part,
and it reports its own truncation rather than reading as "nothing further out".)

That rule survives contact with hubs because of a measurement, not an
assumption. On apache/superset the worst hub, `superset/__init__.py`, has 515
importers, and listing every one of their paths costs 7,458 tokens -- 1.3% of
the 560,768 it would cost to read the top-100 files. Paths are cheap; the
per-neighbour METADATA (cluster, rank, crossing flag) is what scales. So the
bound applies to enrichment only: past `MAX_ENRICHED` neighbours, ranked best
first, the remainder still appear as bare paths with an exact total. Nothing is
hidden, and `enriched + len(additional_paths) == total` is asserted by a test
rather than promised by this comment.

**Known cost, stated rather than left to be discovered.** Each call reads the
whole repo graph through the boundary. On superset that is real work per query.
Caching belongs to whatever puts this behind an interface (checkpoint 4), not
here; `graph=` lets a batch caller read once and query many times meanwhile.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.services.codebase.graph_read import RepoGraphT, read_repo_graph

# How many neighbours carry full metadata. Beyond this, paths still travel --
# see the module docstring for the measurement that makes that affordable.
MAX_ENRICHED = 25

# Second-hop is a path-only, deduplicated frontier. It answers "what is one step
# further out" without paying to describe any of it, because a file two hops
# away is context for deciding what to read, not something being changed.
MAX_SECOND_HOP = 200

_SCORER = "legacy"

# The query budget. Graphify's default is 2,000; ours is 9,000, and the
# difference is a measurement rather than a preference.
#
# A budget bounds TOKENS, but the payload of a hub neighbourhood is PATHS. At
# 2,000 the two worst hubs measured on apache/superset -- `superset/__init__.py`
# at 8,452 tok (524 importers) and `superset/utils/core.py` at 5,954 (346) --
# cannot fit even after everything else is stripped, and the only way to reach
# the number is to drop dependents. Checkpoint 2 established that a dropped
# dependent is invisible to the consumer, so that is the one thing this query
# must never do.
#
# 9,000 clears the worst measured hub with headroom, so the cap is MET for real
# files and the cost is flat -- and `_apply_budget` still refuses rather than
# cuts if some future mega-hub exceeds even this. That is the integrity of
# never-cut with the presentation of a flat, always-met number; the alternative
# (cut paths to hit 2,000) was rejected outright.
#
# OPT-IN: `budget_tokens` still defaults to None, so no existing caller changes
# behaviour. This constant is what a caller passes when it wants the flat cost.
DEFAULT_BUDGET_TOKENS = 9000

# ~3.6 characters per token on path-shaped text, calibrated against tiktoken
# cl100k on this repo's own path corpus. Deliberately an ESTIMATE and not
# tiktoken: making the service layer depend on a tokenizer to answer a
# structural question would be a real dependency bought for an approximation
# the caller can override anyway.
_CHARS_PER_TOKEN = 3.6


def _estimate_tokens(obj) -> int:
    import json
    return int(len(json.dumps(obj, separators=(",", ":"))) / _CHARS_PER_TOKEN)


def _apply_budget(result: dict, budget: int, count) -> dict:
    """Shrink the result to fit `budget`, cheapest-information-first.

    The ORDER is the whole design. Second-hop goes first (it is a convenience),
    then per-neighbour METADATA (recoverable by asking again), and only then --
    if the budget still cannot be met -- the direct path set, which is NOT
    recoverable and whose loss is a hidden dependency. That last step is
    recorded as `sufficiency_sacrificed`, because a consumer must be able to
    tell "this is bounded" from "this is bounded AND incomplete".
    """
    result["budget"] = {"limit": budget, "applied": False}
    if count(result) <= budget:
        return result

    result["budget"]["applied"] = True
    dropped = []

    if "second_hop" in result:
        del result["second_hop"]
        dropped.append("second_hop")
        if count(result) <= budget:
            result["budget"]["dropped"] = dropped
            return result

    for side in ("importers", "imports"):
        blk = result[side]
        if blk["files"]:
            # Keep the paths, drop the descriptions -- same rule as the hub
            # bound: metadata scales, paths are the answer.
            blk["additional_paths"] = sorted(
                set(blk.get("additional_paths", [])) | {f["p"] for f in blk["files"]})
            blk["files"] = []
            blk["enriched"] = 0
            blk["truncated_metadata"] = True
            dropped.append(f"{side}.metadata")
        if count(result) <= budget:
            result["budget"]["dropped"] = dropped
            return result

    # Everything cheap is gone and the budget is still exceeded. What remains is
    # the path set itself, and cutting it hides real dependents.
    result["budget"]["dropped"] = dropped
    result["budget"]["sufficiency_sacrificed"] = True
    result["budget"]["shortfall_tokens"] = count(result) - budget
    result["budget"]["note"] = (
        "The direct path set alone exceeds the budget. Paths were NOT cut: a "
        "dropped dependent is invisible to the consumer and this query's "
        "correctness bar is sufficiency, not size. Raise the budget or accept "
        "an over-budget result.")
    return result


def _rank(node) -> Optional[int]:
    for r in node.ranks:
        if r.scorer == _SCORER:
            return r.rank
    return None


def _sort_key(node):
    # Best rank first; unranked last rather than first -- an absent rank is not
    # rank 0, and sorting it to the front would push real neighbours out of the
    # enriched window.
    return (_rank(node) is None, _rank(node) or 0, node.path)


def _describe(node, home_cluster: Optional[str]) -> dict:
    d = {"p": node.path}
    rank = _rank(node)
    if rank is not None:
        d["rank"] = rank
    cluster = node.clusters.get("modularity")
    if cluster:
        d["cluster"] = cluster
    if node.fan_in:
        d["fan_in"] = node.fan_in
    # THE BOUNDARY-CROSSING SIGNAL. Only meaningful when both ends are
    # clustered; a missing flag means "cannot tell", never "does not cross".
    if home_cluster and cluster:
        d["crosses"] = cluster != home_cluster
    return d


def _bounded(nodes, home_cluster, max_enriched) -> dict:
    """Enrich the best `max_enriched`, keep every remaining PATH, state the
    exact total. The count is never an estimate and the set is never cut."""
    ordered = sorted(nodes, key=_sort_key)
    head, tail = ordered[:max_enriched], ordered[max_enriched:]
    out = {
        "total": len(ordered),
        "enriched": len(head),
        "files": [_describe(n, home_cluster) for n in head],
    }
    if tail:
        out["additional_paths"] = [n.path for n in tail]
        out["truncated_metadata"] = True
    return out


def read_neighborhood(
    db: Session,
    repo_id: int,
    path: str,
    *,
    second_hop: bool = False,
    max_enriched: int = MAX_ENRICHED,
    budget_tokens: Optional[int] = None,
    count_tokens=None,
    graph: Optional[RepoGraphT] = None,
) -> dict:
    """The minimal set an agent needs to understand and safely change `path`.

    `second_hop` is off by default and bounded when on: widening is a decision
    the caller makes explicitly, not a cost it absorbs by accident.
    """
    if graph is None:
        graph = read_repo_graph(db, repo_id, include_symbols=False)

    by_path = {n.path: n for n in graph.nodes}
    target = by_path.get(path)
    if target is None:
        # Distinguished from "a file with no neighbours", which is a fact about
        # the repo rather than a caller error.
        raise ValueError(f"{path!r} is not a file in repo {repo_id}")

    home = target.clusters.get("modularity")

    import_paths, unresolved, importer_paths = set(), [], set()
    for e in graph.edges:
        if e.from_path == path:
            if e.is_resolved:
                import_paths.add(e.to_path)
            else:
                # An agent editing X needs to know about a dependency the
                # resolver could not pin -- that is precisely the case where it
                # cannot find the file by looking.
                unresolved.append({"spec": e.raw_specifier, "line": e.line_number})
        if e.is_resolved and e.to_path == path and e.from_path != path:
            importer_paths.add(e.from_path)

    imports = _bounded([by_path[p] for p in import_paths if p in by_path],
                       home, max_enriched)
    imports["unresolved"] = unresolved
    importers = _bounded([by_path[p] for p in importer_paths if p in by_path],
                         home, max_enriched)

    def _crossing(paths):
        inside = outside = unknown = 0
        for p in paths:
            c = by_path[p].clusters.get("modularity") if p in by_path else None
            if not home or not c:
                unknown += 1
            elif c == home:
                inside += 1
            else:
                outside += 1
        return {"same_subsystem": inside, "other_subsystems": outside,
                "unknown": unknown}

    result = {
        "repo": graph.repo_label,
        "repo_id": graph.repo_id,
        # PART OF SUFFICIENCY, not a feature bolted on. The bar for this query
        # is that a consumer can tell whether the answer is enough to act on,
        # and an answer computed against a snapshot the working tree has moved
        # past is NOT enough -- the blast radius may name files that changed and
        # omit files that appeared. Without the sha in the result the consumer
        # cannot detect that, and an undetectably-stale answer is the same
        # §17.25 failure as an undetectably-partial one. It travels IN the
        # result rather than beside it because a caller holding the dict must be
        # able to check currency (against `git rev-parse HEAD`) without a
        # second call it might not know to make.
        "snapshot": {
            "last_ingested_sha": graph.last_ingested_sha,
            # Already ISO 8601 -- the boundary normalises it, so this does
            # not need to know what driver produced it.
            "last_ingested_at": graph.last_ingested_at,
        },
        "file": {
            "p": target.path,
            "lang": target.language,
            "rank": _rank(target),
            "cluster": home,
            "fan_in": target.fan_in,
            "fan_out": target.fan_out,
            "entry_point": target.seed_eligible,
            # Present only when the file really is in a cycle -- 1a already
            # normalised one-member SCCs away, so this never over-claims.
            "in_cycle": bool(target.scc_id),
        },
        "imports": imports,
        "importers": importers,
        # A change that stays inside its subsystem is safer than one that
        # ripples across. Reported as counts so the shape of the risk is
        # visible without reading every entry.
        "blast_radius": {
            "importers": _crossing(importer_paths),
            "imports": _crossing(import_paths),
        },
    }

    if second_hop:
        first = import_paths | importer_paths | {path}
        out_hop, in_hop = set(), set()
        for e in graph.edges:
            if not e.is_resolved:
                continue
            if e.from_path in import_paths and e.to_path not in first:
                out_hop.add(e.to_path)
            if e.to_path in importer_paths and e.from_path not in first:
                in_hop.add(e.from_path)
        def _frontier(paths):
            # The one place a PATH may be dropped, and it says so. The direct
            # neighbourhood is what sufficiency depends on and is never cut;
            # the second hop is an opt-in frontier for deciding where to look
            # next, so it is bounded -- but the total is exact and `truncated`
            # is explicit, because a silently-short frontier would read as
            # "there is nothing further out" (§17.25).
            ordered = sorted(paths)
            return {
                "total": len(ordered),
                "paths": ordered[:MAX_SECOND_HOP],
                "truncated": len(ordered) > MAX_SECOND_HOP,
            }

        result["second_hop"] = {
            "imports_of_imports": _frontier(out_hop),
            "importers_of_importers": _frontier(in_hop),
        }

    if budget_tokens is not None:
        result = _apply_budget(result, budget_tokens,
                               count_tokens or _estimate_tokens)
    return result
