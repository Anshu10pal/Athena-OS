# Reading list for eslint/eslint (lib/, as of 2026-08-07, `main` branch)
#
# Transcribed from eslint/eslint's own
# docs/src/contribute/architecture/index.md. Full provenance, the two
# verified doc/code discrepancies, and how lib/rules/ (294 files, not
# ranked here) is handled separately are in
# external-validation-eslint.md, not in this file -- this file follows
# scripts/validate_ranking.py's documented minimal format strictly:
# comments and blank lines only, one path per line otherwise.
#
# Note, 2026-08-17: re-verified against a full, unscoped eslint/eslint
# clone (1,447 files) in external-validation-eslint.md's Round 5 -- all 30
# paths below still exist unchanged. The ground truth is not stale; the
# corpus it was compared against in Rounds 1-4 was a stripped fixture.
1. api.js
2. cli.js
3. cli-engine/formatters/html.js
4. cli-engine/formatters/json-with-metadata.js
5. cli-engine/formatters/json.js
6. cli-engine/formatters/stylish.js
7. cli-engine/hash.js
8. cli-engine/lint-result-cache.js
9. linter/apply-disable-directives.js
10. linter/code-path-analysis/code-path-analyzer.js
11. linter/code-path-analysis/code-path-segment.js
12. linter/code-path-analysis/code-path-state.js
13. linter/code-path-analysis/code-path.js
14. linter/code-path-analysis/debug-helpers.js
15. linter/code-path-analysis/fork-context.js
16. linter/code-path-analysis/id-generator.js
17. linter/esquery.js
18. linter/file-context.js
19. linter/file-report.js
20. linter/index.js
21. linter/interpolate.js
22. linter/linter.js
23. linter/rule-fixer.js
24. linter/timing.js
25. linter/vfile.js
26. rule-tester/index.js
27. rule-tester/rule-tester.js
28. linter/source-code-fixer.js
29. linter/source-code-traverser.js
30. linter/source-code-visitor.js
