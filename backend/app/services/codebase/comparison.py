"""Phase F5: compare scorers and signals against EACH OTHER, not against
ground truth -- scripts/validate_ranking.py already does the ground-truth
comparison against a hand-authored answer key, a different question this
module doesn't touch. Every function here is pure and DB-agnostic: callers
(rank_repo* in ranking.py, scripts/compare_scorers.py) pass in the
score/signal dicts already computed elsewhere.

No scipy anywhere in this module, same constraint as the rest of this
codebase's stats (see ranking.py's _pagerank docstring) -- everything below
is a small, direct implementation of its formula.
"""


def kendall_tau(scores_a: dict, scores_b: dict) -> tuple:
    """Tau-b over the common key set: pairwise concordant/discordant/tied
    counting, O(n^2) -- fine at repo scale (hundreds of files, not
    millions). Returns (tau, n_common); tau is None when n_common < 2, or
    when one side has zero variance across the common set (every pair tied
    on that side makes concordance undefined, not 0).

    Callers comparing two scorers restricted to a subgraph (e.g. Phase F5's
    frontend-only validation) MUST pre-filter scores_a/scores_b to that
    subgraph's file ids before calling this -- passing whole-repo dicts
    when only a subgraph was validated would let an unrelated, unvalidated
    part of the graph dominate the result."""
    common = sorted(set(scores_a) & set(scores_b))
    n = len(common)
    if n < 2:
        return None, n
    a = [scores_a[key] for key in common]
    b = [scores_b[key] for key in common]
    concordant = discordant = tied_a_only = tied_b_only = 0
    for i in range(n):
        for j in range(i + 1, n):
            da = a[i] - a[j]
            db = b[i] - b[j]
            if da == 0 and db == 0:
                continue  # tied on both -- contributes to neither side's denominator
            elif da == 0:
                tied_a_only += 1
            elif db == 0:
                tied_b_only += 1
            elif (da > 0) == (db > 0):
                concordant += 1
            else:
                discordant += 1
    denom = ((concordant + discordant + tied_a_only) * (concordant + discordant + tied_b_only)) ** 0.5
    if denom == 0:
        return None, n
    return (concordant - discordant) / denom, n


def pearson_correlation(values_a: dict, values_b: dict) -> tuple:
    """Returns (r, n_common); None when n_common < 2 or either side has zero
    variance across the common set -- correlation is undefined there, not 0
    (a real case on this repo: distinct_authors takes only values 1 and 2,
    and can end up with no variance at all on a small subgraph)."""
    common = sorted(set(values_a) & set(values_b))
    n = len(common)
    if n < 2:
        return None, n
    a = [values_a[key] for key in common]
    b = [values_b[key] for key in common]
    mean_a, mean_b = sum(a) / n, sum(b) / n
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    var_a = sum((x - mean_a) ** 2 for x in a)
    var_b = sum((y - mean_b) ** 2 for y in b)
    if var_a == 0 or var_b == 0:
        return None, n
    return cov / (var_a * var_b) ** 0.5, n


def signal_correlation_matrix(signal_values: dict, threshold: float = 0.8) -> dict:
    """signal_values: {signal_name: {file_id: raw_value}}. Returns every
    unordered pair's (r, n) plus a `redundant` list of pairs with |r| above
    threshold -- two signals that move together this closely are mostly
    re-tuning the same thing twice under the legacy scorer, and under RRF
    contribute two near-identical rank terms instead of one independent one."""
    names = sorted(signal_values.keys())
    pairs = {}
    redundant = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            name_a, name_b = names[i], names[j]
            r, n = pearson_correlation(signal_values[name_a], signal_values[name_b])
            pairs[(name_a, name_b)] = {"r": r, "n": n}
            if r is not None and abs(r) > threshold:
                redundant.append((name_a, name_b, r))
    return {"pairs": pairs, "redundant": redundant}


def spearman_on_intersection(order_a: list, order_b: list, top_n: int) -> tuple:
    """Spearman rank correlation over the intersection of two top_n lists --
    "for items both consider important, do we agree on their relative
    order?" Says nothing about items only one list considers important;
    that's a separate enter/leave comparison, not this function's job.

    Same formula and rationale as scripts/validate_ranking.py's function of
    the same name -- reimplemented here rather than imported, since
    scripts/ is a one-off CLI entry point, not a package other app code
    should depend on. Ranks used are the common items' RELATIVE order
    within each top_n (re-indexed 0..n-1), NOT their absolute position in
    the original list: using absolute position is a real bug that was
    caught and fixed in validate_ranking.py -- a small common set scattered
    near opposite ends of two lists produces a rho outside [-1, 1] when
    raw position gaps aren't bounded by n once most of the list isn't
    shared."""
    top_a, top_b = order_a[:top_n], order_b[:top_n]
    common = set(top_a) & set(top_b)
    n = len(common)
    if n < 2:
        return None, n
    a_order = [item for item in top_a if item in common]
    b_order = [item for item in top_b if item in common]
    a_rank = {item: i for i, item in enumerate(a_order)}
    b_rank = {item: i for i, item in enumerate(b_order)}
    d_sq_sum = sum((a_rank[item] - b_rank[item]) ** 2 for item in common)
    rho = 1 - (6 * d_sq_sum) / (n * (n**2 - 1))
    return rho, n


def top_n_ablation_report(baseline_scores: dict, ablated_scores_by_signal: dict, top_n: int = 20) -> dict:
    """Scorer-agnostic: doesn't care whether baseline/ablated scores came
    from the legacy weighted sum with one weight zeroed, or RRF with one
    signal dropped from the fusion entirely -- both are "recompute the
    score without this one signal's influence," and this function only
    ever compares the resulting top_n sets/orders.

    No renormalization on the caller's side, and none needed here: scaling
    every REMAINING weight (or, for RRF, every remaining signal's
    contribution) by the same constant so they "sum back to 1" is a single
    positive multiplier applied identically to every file's ablated score.
    A uniform positive scalar cannot change relative order or top_n
    membership -- so renormalizing would be pointless extra computation for
    a question (which files enter/leave the top_n, and does their order
    among survivors change) that a global rescale can't affect either way.

    Returns {signal_name: {left_top_n, entered_top_n, spearman, n_common}}."""
    baseline_order = [key for key, _ in sorted(baseline_scores.items(), key=lambda kv: -kv[1])][:top_n]
    report = {}
    for signal_name, ablated_scores in ablated_scores_by_signal.items():
        ablated_order = [key for key, _ in sorted(ablated_scores.items(), key=lambda kv: -kv[1])][:top_n]
        left_top_n = [key for key in baseline_order if key not in ablated_order]
        entered_top_n = [key for key in ablated_order if key not in baseline_order]
        rho, n_common = spearman_on_intersection(baseline_order, ablated_order, top_n)
        report[signal_name] = {
            "left_top_n": left_top_n,
            "entered_top_n": entered_top_n,
            "spearman": rho,
            "n_common": n_common,
        }
    return report
