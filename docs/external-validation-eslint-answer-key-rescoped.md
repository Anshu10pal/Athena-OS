# Reading list for eslint/eslint (bin/ + lib/, source_root=None, 398 files)
#
# Identical content to external-validation-eslint-answer-key.md, every
# path prefixed with lib/ -- CodeFile.path is relative to source_root, and
# this companion file exists only because the rescoped run (source_root
# changed from "lib" to None, to bring bin/eslint.js into ingestion scope
# and fix cli.js's false near-zero fan_in) changed what that base is.
# Same reason this file, not the original, must be used with
# scripts/validate_ranking.py against the rescoped run -- see
# external-validation-eslint.md's "Round 2" section for why the two runs
# exist and are reported side by side, on their own denominators (393
# files vs. 398).
#
# Note, 2026-08-17: "398 files" here was a stripped bin/+lib/ fixture, not
# eslint/eslint. Round 5 (external-validation-eslint.md) re-verified these
# 30 paths directly against a full, unscoped clone (1,447 files) -- all 30
# still exist at these exact paths, so the ground truth below is UNCHANGED
# and still valid to use. Only the denominator/corpus this list gets
# compared against has changed.
1. lib/api.js
2. lib/cli.js
3. lib/cli-engine/formatters/html.js
4. lib/cli-engine/formatters/json-with-metadata.js
5. lib/cli-engine/formatters/json.js
6. lib/cli-engine/formatters/stylish.js
7. lib/cli-engine/hash.js
8. lib/cli-engine/lint-result-cache.js
9. lib/linter/apply-disable-directives.js
10. lib/linter/code-path-analysis/code-path-analyzer.js
11. lib/linter/code-path-analysis/code-path-segment.js
12. lib/linter/code-path-analysis/code-path-state.js
13. lib/linter/code-path-analysis/code-path.js
14. lib/linter/code-path-analysis/debug-helpers.js
15. lib/linter/code-path-analysis/fork-context.js
16. lib/linter/code-path-analysis/id-generator.js
17. lib/linter/esquery.js
18. lib/linter/file-context.js
19. lib/linter/file-report.js
20. lib/linter/index.js
21. lib/linter/interpolate.js
22. lib/linter/linter.js
23. lib/linter/rule-fixer.js
24. lib/linter/timing.js
25. lib/linter/vfile.js
26. lib/rule-tester/index.js
27. lib/rule-tester/rule-tester.js
28. lib/linter/source-code-fixer.js
29. lib/linter/source-code-traverser.js
30. lib/linter/source-code-visitor.js
