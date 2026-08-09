"""Phase 1 code health: AST golden tests.

Contract §15 requires these before the analyzer is trusted. Every expected
number below is hand-derived from the source in the test, not captured from a
run -- a snapshot test would happily freeze a wrong count and then defend it.

Cyclomatic complexity here is McCabe's: 1 + one per decision point, where a
decision point is if/elif/loop/except/case/ternary/boolean-operator. `else` is
never a decision point (it adds no branch the `if` did not already create).
"""
import pytest

from app.services.codebase.ast_metrics import (
    LANGUAGE_RULES,
    SUPPORTED_LANGUAGES,
    metrics_for,
)


def cc(source: str, language: str = "python") -> int:
    m = metrics_for(source.encode(), language)
    assert m is not None
    return m.max_cyclomatic


def only_symbol(source: str, language: str = "python"):
    m = metrics_for(source.encode(), language)
    assert m is not None
    assert len(m.symbols) == 1, f"expected exactly one function, got {[s.name for s in m.symbols]}"
    return m.symbols[0]


class TestLanguageCoverage:
    def test_supported_set_matches_the_contract(self):
        assert SUPPORTED_LANGUAGES == {"python", "javascript", "typescript", "tsx"}

    def test_unsupported_language_returns_none_not_a_clean_record(self):
        # The whole N/A discipline rests on this: a language with no rules must
        # not come back as a file with zero findings.
        assert metrics_for(b"SELECT 1;", "sql") is None
        assert metrics_for(b"x", "go") is None

    def test_every_supported_language_has_rules(self):
        for language in SUPPORTED_LANGUAGES:
            assert language in LANGUAGE_RULES


class TestPythonCyclomatic:
    def test_straight_line_function_is_one(self):
        assert cc("def f():\n    return 1\n") == 1

    def test_single_if_is_two(self):
        assert cc("def f(a):\n    if a:\n        return 1\n    return 0\n") == 2

    def test_else_adds_nothing(self):
        # 1 + if = 2. The else branch is not an independent decision.
        assert cc("def f(a):\n    if a:\n        return 1\n    else:\n        return 0\n") == 2

    def test_elif_chain_counts_each_elif(self):
        # 1 + if + elif + elif = 4 (the trailing else adds nothing).
        src = (
            "def f(a):\n"
            "    if a == 1:\n        return 1\n"
            "    elif a == 2:\n        return 2\n"
            "    elif a == 3:\n        return 3\n"
            "    else:\n        return 0\n"
        )
        assert cc(src) == 4

    def test_loops_count(self):
        # 1 + for + while = 3
        assert cc("def f(xs):\n    for x in xs:\n        pass\n    while True:\n        break\n") == 3

    def test_boolean_operators_each_count(self):
        # 1 + if + (and, or) = 4
        assert cc("def f(a, b, c):\n    if a and b or c:\n        return 1\n    return 0\n") == 4

    def test_ternary_counts(self):
        assert cc("def f(a):\n    return 1 if a else 0\n") == 2

    def test_comprehension_filter_counts(self):
        # 1 + the comprehension's `if` = 2. The `for` clause of a comprehension
        # is not a for_statement node, so it is not double counted.
        assert cc("def f(xs):\n    return [x for x in xs if x]\n") == 2

    def test_except_clauses_count_each(self):
        # 1 + two except clauses = 3
        src = (
            "def f():\n"
            "    try:\n        g()\n"
            "    except ValueError:\n        pass\n"
            "    except KeyError:\n        pass\n"
        )
        assert cc(src) == 3

    def test_match_case_counts_each_case(self):
        # 1 + two case clauses = 3
        src = (
            "def f(a):\n"
            "    match a:\n"
            "        case 1:\n            return 1\n"
            "        case _:\n            return 0\n"
        )
        assert cc(src) == 3

    def test_nested_function_is_measured_separately_not_folded_into_parent(self):
        src = (
            "def outer(a):\n"
            "    def inner(b):\n"
            "        if b:\n            return 1\n"
            "        return 0\n"
            "    if a:\n        return inner(a)\n"
            "    return 0\n"
        )
        m = metrics_for(src.encode(), "python")
        by_name = {s.name: s.cyclomatic for s in m.symbols}
        assert by_name == {"outer": 2, "inner": 2}


class TestPythonNesting:
    def test_flat_function_is_zero(self):
        assert only_symbol("def f():\n    return 1\n").nesting == 0

    def test_single_if_is_one(self):
        assert only_symbol("def f(a):\n    if a:\n        return 1\n").nesting == 1

    def test_nested_blocks_accumulate(self):
        src = (
            "def f(xs):\n"
            "    for x in xs:\n"
            "        if x:\n"
            "            while x:\n"
            "                x -= 1\n"
        )
        assert only_symbol(src).nesting == 3

    def test_elif_ladder_is_not_treated_as_deep_nesting(self):
        # The specific trap this rule exists for: an elif chain is flat control
        # flow. Counting the clause node would report depth 3 here instead of 1.
        src = (
            "def f(a):\n"
            "    if a == 1:\n        return 1\n"
            "    elif a == 2:\n        return 2\n"
            "    elif a == 3:\n        return 3\n"
        )
        assert only_symbol(src).nesting == 1


class TestPythonConditionalOperands:
    def test_simple_condition_has_no_boolean_operands_recorded(self):
        assert only_symbol("def f(a):\n    if a:\n        pass\n").conditional_operands == 0

    def test_two_operands(self):
        assert only_symbol("def f(a, b):\n    if a and b:\n        pass\n").conditional_operands == 2

    def test_chained_operators_count_as_one_expression_not_several(self):
        # `a and b and c and d` is ONE 4-operand condition, not three 2-operand
        # ones -- the parse nests boolean_operator nodes, so counting each node
        # as its own expression would understate the real condition.
        src = "def f(a, b, c, d):\n    if a and b and c and d:\n        pass\n"
        assert only_symbol(src).conditional_operands == 4


class TestPythonBroadErrorHandling:
    def test_bare_except_is_a_finding(self):
        src = "def f():\n    try:\n        g()\n    except:\n        pass\n"
        assert metrics_for(src.encode(), "python").broad_handler_count == 1

    def test_except_exception_with_only_pass_is_a_finding(self):
        src = "def f():\n    try:\n        g()\n    except Exception:\n        pass\n"
        assert metrics_for(src.encode(), "python").broad_handler_count == 1

    def test_broad_except_that_actually_handles_is_not_a_finding(self):
        # Catching broadly and doing something real (log, re-raise) is a
        # legitimate pattern; only the silent swallow is flagged.
        src = "def f():\n    try:\n        g()\n    except Exception as e:\n        log(e)\n"
        assert metrics_for(src.encode(), "python").broad_handler_count == 0

    def test_narrow_except_with_pass_is_not_a_finding(self):
        src = "def f():\n    try:\n        g()\n    except KeyError:\n        pass\n"
        assert metrics_for(src.encode(), "python").broad_handler_count == 0


class TestJavaScriptCyclomatic:
    def test_straight_line_is_one(self):
        assert cc("function f() { return 1; }", "javascript") == 1

    def test_else_if_counts_as_two_ifs(self):
        # JS `else if` really is a nested if_statement, unlike Python's elif
        # clause -- 1 + if + if = 3.
        src = "function f(a) { if (a === 1) { return 1; } else if (a === 2) { return 2; } return 0; }"
        assert cc(src, "javascript") == 3

    def test_loops_count(self):
        src = "function f(xs) { for (const x of xs) {} while (true) { break; } }"
        assert cc(src, "javascript") == 3

    def test_logical_operators_count_including_nullish(self):
        # 1 + if + (&&, ||, ??) = 5.
        # Parenthesised deliberately: mixing `??` with `&&`/`||` unparenthesised
        # is a SyntaxError in real JavaScript. tree-sitter parses it anyway
        # (has_error=False, same count), so an unparenthesised fixture would
        # pass while testing source no engine would accept.
        src = "function f(a, b, c, d) { if ((a && b) || (c ?? d)) { return 1; } return 0; }"
        assert cc(src, "javascript") == 5

    def test_optional_chaining_is_not_a_branch(self):
        # `?.` is null-safety shorthand, not control flow. If this ever starts
        # counting, every modern TS file inflates at once.
        assert cc("function f(a) { return a?.b?.c; }", "javascript") == 1

    def test_ternary_counts(self):
        assert cc("function f(a) { return a ? 1 : 0; }", "javascript") == 2

    def test_switch_cases_count_but_default_does_not(self):
        # 1 + two `case` = 3; `default` is the fallthrough, not a branch.
        src = (
            "function f(a) { switch (a) { case 1: return 1; case 2: return 2; "
            "default: return 0; } }"
        )
        assert cc(src, "javascript") == 3

    def test_catch_counts(self):
        assert cc("function f() { try { g(); } catch (e) { h(e); } }", "javascript") == 2

    def test_arrow_function_is_measured(self):
        m = metrics_for(b"const f = (a) => a ? 1 : 0;", "javascript")
        assert m.function_count == 1
        assert m.symbols[0].cyclomatic == 2


class TestTypeScriptAndTsx:
    def test_typescript_annotations_do_not_change_complexity(self):
        src = "function f(a: number, b: string): number { if (a) { return 1; } return 0; }"
        assert cc(src, "typescript") == 2

    def test_tsx_jsx_logical_render_counts_as_a_branch(self):
        # `{cond && <X/>}` is a real conditional render -- 1 + && = 2.
        src = "const C = (p: {x: boolean}) => <div>{p.x && <span/>}</div>;"
        assert cc(src, "tsx") == 2

    def test_tsx_ternary_render_counts(self):
        src = "const C = (p: {x: boolean}) => <div>{p.x ? <a/> : <b/>}</div>;"
        assert cc(src, "tsx") == 2


class TestJavaScriptBroadErrorHandling:
    def test_empty_catch_is_a_finding(self):
        assert metrics_for(b"function f() { try { g(); } catch (e) {} }", "javascript").broad_handler_count == 1

    def test_catch_that_does_something_is_not(self):
        src = b"function f() { try { g(); } catch (e) { log(e); } }"
        assert metrics_for(src, "javascript").broad_handler_count == 0


class TestNloc:
    def test_blank_lines_are_not_counted(self):
        m = metrics_for(b"def f():\n\n\n    return 1\n", "python")
        assert m.nloc == 2

    def test_comment_lines_are_not_counted(self):
        m = metrics_for(b"# a comment\ndef f():\n    return 1\n", "python")
        assert m.nloc == 2

    def test_a_hash_inside_a_string_is_not_treated_as_a_comment(self):
        # The reason comment spans come from the parse tree rather than a
        # startswith("#") scan.
        m = metrics_for(b'def f():\n    return "# not a comment"\n', "python")
        assert m.nloc == 2

    def test_js_block_comments_are_not_counted(self):
        m = metrics_for(b"/* one\n   two */\nfunction f() { return 1; }", "javascript")
        assert m.nloc == 1


class TestBreadthReporting:
    def test_records_how_many_functions_breach_and_which_is_worst(self):
        # One deliberately complex function among simple ones: the contract
        # requires both the max AND the breach count, so an explanation can
        # separate "one bad function" from "uniformly bad".
        complex_fn = "def bad(a):\n" + "".join(
            f"    if a == {i}:\n        return {i}\n" for i in range(12)
        )
        simple = "def ok():\n    return 1\n"
        m = metrics_for((complex_fn + simple).encode(), "python")
        assert m.function_count == 2
        assert m.max_cyclomatic == 13  # 1 + 12 ifs
        assert m.worst_cyclomatic_symbol == "bad"
        assert m.functions_over_cc_threshold == 1

    def test_file_with_no_functions_reports_zero_functions(self):
        # Not an error, and not a finding -- the caller reports the Complexity
        # category as N/A for such a file (contract §5.1).
        m = metrics_for(b"X = 1\nY = 2\n", "python")
        assert m.function_count == 0
        assert m.max_cyclomatic == 0
        assert m.nloc == 2


class TestFixturesAreValidSource:
    """tree-sitter recovers from syntax errors instead of failing, so a golden
    test can pass while asserting counts over source no real compiler would
    accept. These pin the representative fixtures as genuinely parseable."""

    @pytest.mark.parametrize("language,source", [
        ("python", "def f(a):\n    match a:\n        case 1:\n            return 1\n"),
        ("javascript", "function f(a) { switch (a) { case 1: return 1; default: return 0; } }"),
        ("javascript", "function f(a, b, c, d) { if ((a && b) || (c ?? d)) { return 1; } return 0; }"),
        ("javascript", "const f = (a) => a ? 1 : 0;"),
        ("typescript", "function f(a: number, b: string): number { if (a) { return 1; } return 0; }"),
        ("tsx", "const C = (p: {x: boolean}) => <div>{p.x && <span/>}</div>;"),
        ("tsx", "const C = (p: {x: boolean}) => <div>{p.x ? <a/> : <b/>}</div>;"),
    ])
    def test_fixture_parses_without_error_recovery(self, language, source):
        from app.services.codebase.languages import parser_for_language
        tree = parser_for_language(language).parse(source.encode())
        assert not tree.root_node.has_error, f"{language} fixture relies on error recovery: {source!r}"


class TestRobustness:
    def test_syntactically_broken_source_does_not_raise(self):
        # tree-sitter recovers from errors rather than failing, so this should
        # produce a record instead of taking down an ingest.
        m = metrics_for(b"def f(:\n    return\n", "python")
        assert m is not None

    def test_empty_file(self):
        m = metrics_for(b"", "python")
        assert m is not None
        assert m.nloc == 0
        assert m.function_count == 0
