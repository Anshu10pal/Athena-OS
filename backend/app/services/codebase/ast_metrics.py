"""Phase 1 code health: per-file structural metrics from the tree-sitter AST.

Implements the Maintainability inputs defined in docs/code-health-contract.md
(rev 2) -- cyclomatic complexity, nesting depth, boolean-conditional operand
count, function/file NLOC, and broad error handling. Nothing here scores or
weights anything; it only measures. Scoring lives in the health service so
that thresholds and weights can be versioned independently of the analyzer.

Two contract rules are enforced structurally rather than by convention:

- **Unsupported language means N/A, never zero.** `metrics_for` returns None
  for a language with no rule set, and callers must propagate that as N/A. A
  language added later must not silently score 10.0 by having no findings.
- **Nested functions are their own symbols.** A function's complexity stops at
  the boundary of any function defined inside it, so an outer function is not
  charged for its inner closures (and the inner ones are still measured). The
  standard treatment, and it keeps `max` across symbols meaningful.

Comment/blank handling uses the parse tree rather than a `startswith("#")`
heuristic: comment node line spans are collected from the AST, so a `#` inside
a string literal is not mistaken for a comment and a block comment is handled
without a second scanner.
"""
from dataclasses import dataclass, field
from typing import Optional

from app.services.codebase.languages import parser_for_language

# Bumped whenever a rule below changes what a given file would score. Written
# into every snapshot (contract §7) so a trend line can never silently compare
# results from two different analyzers.
ANALYZER_VERSION = 1


@dataclass(frozen=True)
class LanguageRules:
    """Node types that define each metric for one grammar. Kept as data rather
    than branching code so adding a language is a table entry plus fixtures,
    and so the per-language differences are reviewable in one place."""
    function_nodes: frozenset
    # Each occurrence adds 1 to cyclomatic complexity. `else` is deliberately
    # absent: McCabe counts decision points, and an else introduces no new
    # branch beyond the if that owns it.
    decision_nodes: frozenset
    # Boolean operators counted via an operator-text check rather than a node
    # type, because JS uses one `binary_expression` node for both arithmetic
    # and logical operators.
    boolean_operator_nodes: frozenset
    boolean_operators: frozenset
    # Statements that open a new nesting level. Clause nodes (elif/else/case)
    # are excluded -- an elif chain is flat control flow, and counting the
    # clause node would report a 5-branch elif ladder as 5 levels deep.
    nesting_nodes: frozenset
    comment_nodes: frozenset


PYTHON_RULES = LanguageRules(
    function_nodes=frozenset({"function_definition"}),
    decision_nodes=frozenset({
        "if_statement", "elif_clause", "for_statement", "while_statement",
        "except_clause", "conditional_expression", "case_clause", "if_clause",
    }),
    boolean_operator_nodes=frozenset({"boolean_operator"}),
    boolean_operators=frozenset({"and", "or"}),
    nesting_nodes=frozenset({
        "if_statement", "for_statement", "while_statement", "try_statement",
        "with_statement", "match_statement",
    }),
    comment_nodes=frozenset({"comment"}),
)

_JS_DECISION = frozenset({
    "if_statement", "for_statement", "for_in_statement", "while_statement",
    "do_statement", "switch_case", "catch_clause", "ternary_expression",
})
_JS_NESTING = frozenset({
    "if_statement", "for_statement", "for_in_statement", "while_statement",
    "do_statement", "try_statement", "switch_statement",
})
# `switch_default` is deliberately not a decision node (it is the fallthrough,
# not a branch), and optional chaining (`?.`) is not counted at all -- it is a
# null-safety shorthand, not a control-flow branch. Both are pinned by fixtures.
JS_RULES = LanguageRules(
    function_nodes=frozenset({
        "function_declaration", "function_expression", "arrow_function",
        "method_definition", "generator_function_declaration", "function",
    }),
    decision_nodes=_JS_DECISION,
    boolean_operator_nodes=frozenset({"binary_expression"}),
    boolean_operators=frozenset({"&&", "||", "??"}),
    nesting_nodes=_JS_NESTING,
    comment_nodes=frozenset({"comment"}),
)

LANGUAGE_RULES = {
    "python": PYTHON_RULES,
    "javascript": JS_RULES,
    "typescript": JS_RULES,
    "tsx": JS_RULES,
}

SUPPORTED_LANGUAGES = frozenset(LANGUAGE_RULES)


@dataclass
class SymbolMetrics:
    name: str
    line: int
    cyclomatic: int
    nesting: int
    conditional_operands: int
    nloc: int


@dataclass
class FileMetrics:
    language: str
    nloc: int
    function_count: int
    symbols: list = field(default_factory=list)
    broad_handler_count: int = 0

    # Maxima across symbols, with the worst symbol identified. The contract
    # (§2) requires max rather than mean -- one 60-branch function is the
    # risk, and a mean would bury it under trivial accessors.
    max_cyclomatic: int = 0
    max_nesting: int = 0
    max_conditional_operands: int = 0
    max_function_nloc: int = 0
    worst_cyclomatic_symbol: Optional[str] = None
    worst_cyclomatic_line: Optional[int] = None

    # Breadth alongside the maximum, so an explanation can distinguish "one bad
    # function in an otherwise clean file" from "uniformly complex" -- which
    # neither max nor mean conveys alone.
    functions_over_cc_threshold: int = 0
    functions_over_nesting_threshold: int = 0
    functions_over_nloc_threshold: int = 0


# Only used to compute the breach COUNTS above. The scoring thresholds live in
# the health service; these are duplicated here deliberately as reporting
# thresholds, and are the same numbers by intent, not by import, so that
# retuning scoring cannot silently change what an explanation says happened.
CC_REPORT_THRESHOLD = 10
NESTING_REPORT_THRESHOLD = 4
FUNCTION_NLOC_REPORT_THRESHOLD = 60


def _iter_subtree(node, stop_types: frozenset = frozenset()):
    """Depth-first walk, not descending into `stop_types`. Iterative so a
    deeply nested file cannot hit Python's recursion limit."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        for child in reversed(current.children):
            if child.type in stop_types:
                continue
            stack.append(child)


def _is_boolean_operator(node, rules: LanguageRules) -> bool:
    if node.type not in rules.boolean_operator_nodes:
        return False
    operator = node.child_by_field_name("operator")
    if operator is None:
        # tree-sitter-python's boolean_operator is only ever and/or, so the
        # absence of an operator field is not ambiguous there.
        return node.type == "boolean_operator"
    return operator.type in rules.boolean_operators


def _function_metrics(func_node, rules: LanguageRules) -> tuple:
    """(cyclomatic, max_boolean_operands, max_nesting_depth) in ONE traversal.

    Was two separate walks of the same subtree -- `_cyclomatic_and_operands`
    and `_nesting_depth` -- which is half of why `_iter_subtree` was called 35.8
    million times for one health run on apache/superset. They are merged rather
    than optimised individually: neither needs a different traversal ORDER, only
    a different accumulator, and depth is the only one that needs context from
    the path down.

    So this uses an explicit `(node, depth)` stack, which is what `_nesting_depth`
    already did, and computes the decision-point and boolean counts on the same
    visit. `_iter_subtree` is not used here because it carries no depth.

    Semantics preserved exactly, including the three easy ones to lose:

      * the function node ITSELF contributes no decision point and no boolean
        (the old code skipped `node is func_node`);
      * nested functions are not descended into, and are measured on their own;
      * depth counts BLOCK-OPENING nodes only, and the function is depth 0.

    Cyclomatic complexity = 1 + decision points. Boolean operands are counted
    per MAXIMAL expression: `a and b and c` parses as nested boolean_operator
    nodes, so counting each independently would report two 2-operand conditions
    instead of one 3-operand condition.
    """
    complexity = 1
    max_operands = 0
    max_depth = 0
    counted_boolean_nodes = set()

    # (node, depth_of_node). The function root is depth 0 and is not itself
    # counted as a decision point or a boolean.
    stack = [(func_node, 0)]
    while stack:
        node, depth = stack.pop()

        if node is not func_node:
            if node.type in rules.decision_nodes:
                complexity += 1
            if _is_boolean_operator(node, rules):
                complexity += 1
                if node.id not in counted_boolean_nodes:
                    # Walk this maximal boolean expression once, marking its
                    # descendants so they are not re-counted as roots of their
                    # own. Kept as a nested walk deliberately: it has different
                    # semantics from the outer traversal (it marks rather than
                    # measures) and it is bounded by one expression's size, so
                    # folding it in would risk the counting rule for no
                    # meaningful saving.
                    operands = 1
                    for inner in _iter_subtree(node, stop_types=rules.function_nodes):
                        if inner is node:
                            continue
                        if _is_boolean_operator(inner, rules):
                            counted_boolean_nodes.add(inner.id)
                            operands += 1
                    operands += 1  # n operators join n+1 operands
                    max_operands = max(max_operands, operands)

        for child in node.children:
            if child.type in rules.function_nodes:
                continue  # nested function measured on its own
            child_depth = depth + 1 if child.type in rules.nesting_nodes else depth
            if child_depth > max_depth:
                max_depth = child_depth
            stack.append((child, child_depth))

    return complexity, max_operands, max_depth


def _comment_lines(root, rules: LanguageRules) -> set:
    lines = set()
    for node in _iter_subtree(root):
        if node.type in rules.comment_nodes:
            lines.update(range(node.start_point[0], node.end_point[0] + 1))
    return lines


def _nloc(source_bytes: bytes, comment_lines: set, start_row: int = 0,
          end_row: Optional[int] = None) -> int:
    """Non-blank, non-comment lines. Comment spans come from the parse tree, so
    a `#` inside a string literal is never mistaken for a comment."""
    all_lines = source_bytes.split(b"\n")
    last = len(all_lines) - 1 if end_row is None else min(end_row, len(all_lines) - 1)
    count = 0
    for row in range(start_row, last + 1):
        if row in comment_lines:
            continue
        if all_lines[row].strip():
            count += 1
    return count


def _symbol_name(func_node) -> str:
    name_node = func_node.child_by_field_name("name")
    if name_node is not None and name_node.text:
        return name_node.text.decode("utf-8", errors="replace")
    return "<anonymous>"


def _is_python_broad_handler(node) -> bool:
    """One `except_clause`: is it the swallow-everything shape?

    Bare `except:`, or `except Exception`/`except BaseException` whose body is
    only `pass`. A broad except that actually handles or re-raises is not
    counted.

    Split out of the old `_python_broad_handlers(root)` so the decision can be
    made during the single whole-tree pass. The RULE is unchanged -- only the
    traversal moved -- and the metric snapshot over 7,236 files proves it.
    """
    value = node.child_by_field_name("value")
    if value is None:
        # `except:` with no exception type at all.
        has_type = any(
            child.type not in ("except", ":", "block", "comment")
            for child in node.children
        )
        if not has_type:
            return True
        caught = None
    else:
        caught = value.text.decode("utf-8", errors="replace") if value.text else None

    if caught is None:
        caught_text = ""
        for child in node.children:
            if child.type in ("except", ":", "block", "comment"):
                continue
            if child.text:
                caught_text = child.text.decode("utf-8", errors="replace")
                break
    else:
        caught_text = caught

    if caught_text.strip() not in ("Exception", "BaseException"):
        return False
    block = next((c for c in node.children if c.type == "block"), None)
    if block is None:
        return False
    statements = [c for c in block.children if c.type not in ("comment",)]
    return len(statements) == 1 and statements[0].type == "pass_statement"


def _is_js_broad_handler(node) -> bool:
    """`catch` with an empty block. An empty catch discards the error with no
    record that it happened, which is the JS equivalent of `except: pass`."""
    body = node.child_by_field_name("body")
    if body is None:
        return False
    statements = [c for c in body.children if c.type not in ("{", "}", "comment")]
    return not statements


def metrics_for(source_bytes: bytes, language: str) -> Optional[FileMetrics]:
    """None means "this language has no rule set" -- the caller must report
    N/A, never zero (contract §4). Parse failures also return None rather than
    an all-zero record, for the same reason: absence of measurement is not
    evidence of cleanliness."""
    rules = LANGUAGE_RULES.get(language)
    if rules is None:
        return None

    try:
        tree = parser_for_language(language).parse(source_bytes)
    except Exception:
        return None
    root = tree.root_node
    if root is None:
        return None

    # ONE whole-tree walk for three things that used to take three.
    #
    # `_comment_lines`, the function-node scan, and the broad-handler scan each
    # walked the entire tree independently. None of them needs a different
    # traversal order -- each is "find every node of these types, anywhere" --
    # so they are collected on a single visit. Measured on apache/superset,
    # `_iter_subtree` was yielding 35.8 million nodes for one health run, and
    # this is two thirds of the whole-tree share of that.
    #
    # Comments must be complete BEFORE any nloc is computed, which is why this
    # gathers first and measures afterwards rather than doing both in one loop:
    # `_nloc` subtracts comment lines, and a function encountered before a
    # comment inside it would otherwise be measured against an incomplete set.
    comment_lines: set = set()
    function_nodes = []
    broad_handler_count = 0
    handler_type = "except_clause" if language == "python" else "catch_clause"
    is_broad_handler = _is_python_broad_handler if language == "python" else _is_js_broad_handler

    for node in _iter_subtree(root):
        node_type = node.type
        if node_type in rules.comment_nodes:
            comment_lines.update(range(node.start_point[0], node.end_point[0] + 1))
        elif node_type in rules.function_nodes:
            function_nodes.append(node)
        elif node_type == handler_type and is_broad_handler(node):
            broad_handler_count += 1

    file_nloc = _nloc(source_bytes, comment_lines)
    metrics = FileMetrics(language=language, nloc=file_nloc, function_count=0)

    for node in function_nodes:
        complexity, operands, depth = _function_metrics(node, rules)
        func_nloc = _nloc(source_bytes, comment_lines, node.start_point[0], node.end_point[0])
        name = _symbol_name(node)
        line = node.start_point[0] + 1

        metrics.function_count += 1
        metrics.symbols.append(SymbolMetrics(
            name=name, line=line, cyclomatic=complexity,
            nesting=depth, conditional_operands=operands, nloc=func_nloc,
        ))

        if complexity > metrics.max_cyclomatic:
            metrics.max_cyclomatic = complexity
            metrics.worst_cyclomatic_symbol = name
            metrics.worst_cyclomatic_line = line
        metrics.max_nesting = max(metrics.max_nesting, depth)
        metrics.max_conditional_operands = max(metrics.max_conditional_operands, operands)
        metrics.max_function_nloc = max(metrics.max_function_nloc, func_nloc)

        if complexity > CC_REPORT_THRESHOLD:
            metrics.functions_over_cc_threshold += 1
        if depth > NESTING_REPORT_THRESHOLD:
            metrics.functions_over_nesting_threshold += 1
        if func_nloc > FUNCTION_NLOC_REPORT_THRESHOLD:
            metrics.functions_over_nloc_threshold += 1

    metrics.broad_handler_count = broad_handler_count
    return metrics
