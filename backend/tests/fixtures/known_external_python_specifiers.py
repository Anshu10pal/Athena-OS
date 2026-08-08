"""Hand-verified ground truth for Phase E3's third-party dependency
classifier (not yet built).

While validating Phase E2.1's root discovery against the two live
structural test cases (repo 1 = github.com/Anshu10pal/Athena-OS, repo 2 =
github.com/Anshu10pal/AFDE_Jan26_Anshuman_Pal_LMS), every non-stdlib,
non-relative Python specifier left unexplained by the correctly-promoted
`backend/` root was manually inspected. Every single one is a genuine
third-party dependency -- zero were a real internal resolution gap
(root_discovery.py explained 100% of the non-stdlib, could-be-internal
pool once sys.stdlib_module_names was excluded from the denominator).

When Phase E3's requirements.txt/pyproject.toml-parsing classifier lands,
it should classify exactly these specifiers (by first dotted component) as
third-party on the corresponding repo, and nothing else -- a mismatch
against this list is a real regression in E3's classifier to investigate,
not a sign this ground truth is wrong. Re-verify by hand (same method:
run scripts/discover_roots.py, inspect every non-stdlib entry in
"still unexplained") if either repo's dependencies change materially.
"""

# repo 1: github.com/Anshu10pal/Athena-OS
REPO_1_KNOWN_EXTERNAL_SPECIFIERS = [
    "alembic",
    "alembic.config",
    "bcrypt",
    "edge_tts",
    "fastapi",
    "fastapi.middleware.cors",
    "fastapi.responses",
    "fastapi.security",
    "fastapi.staticfiles",
    "faster_whisper",
    "httpx",
    "jwt",
    "keyring",
    "langgraph.graph",
    "networkx",
    "numpy",
    "openai",
    "openwakeword.model",
    "pathspec",
    "piper",
    "platformdirs",
    "pptx",
    "pydantic",
    "pydantic_settings",
    "pygit2",
    "pypdf",
    "pytest",
    "qdrant_client",
    "requests",
    "sounddevice",
    "sqlalchemy",
    "sqlalchemy.orm",
    "sqlalchemy.orm.attributes",
    "streamlit",
    "tree_sitter",
    "tree_sitter_javascript",
    "tree_sitter_python",
    "tree_sitter_typescript",
    "uvicorn",
    "yaml",
]

# repo 2: github.com/Anshu10pal/AFDE_Jan26_Anshuman_Pal_LMS
REPO_2_KNOWN_EXTERNAL_SPECIFIERS = [
    "dotenv",
    "fastapi",
    "fastapi.middleware.cors",
    "fastapi.security",
    "jose",
    "passlib.context",
    "pydantic",
    "sqlalchemy",
    "sqlalchemy.ext.declarative",
    "sqlalchemy.orm",
]
