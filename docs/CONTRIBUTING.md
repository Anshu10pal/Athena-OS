# Contributing

There are two contribution surfaces:

## 1. Code (this repo)

Standard flow — fork, branch, commit, PR. Coding conventions:

- **Python:** type hints, `pydantic` schemas for IO, kept SQLAlchemy 2.0 style (`Mapped[...]`)
- **TypeScript:** strict mode on, prefer explicit prop types, no `any` unless interfacing with untyped libs
- **CSS:** Tailwind utilities + the `.card` / `.btn-brass` / `.input` patterns in `index.css`. Brass `#D4B36A` on graphite `#0B0E14` — never deviate from the palette without discussion
- **Effects rule:** every animation must respond to a real signal (mic amplitude, token stream, XP event), never decorate
- **Verify before PR:** `cd backend && python -m py_compile app/**/*.py` and `cd frontend && npm run build` must pass clean

When adding a new agent: drop a system prompt in `app/agents/prompts.py`, a routing rule in `commander.py`, and an API endpoint. Mirror existing patterns.

When adding a new page: add to `App.tsx` routes, `Layout.tsx` nav, and `CommandPalette.tsx` commands. The trio always moves together.

## 2. Study content (athena-content repo)

The community resource layer lives in a **separate** public repo: `Anshu10pal/athena-content`.

### Suggesting a resource (no clone needed)

The easiest path is built into the app: open any node dossier → "+ suggest a resource" → a pre-filled GitHub issue opens. Submit, done.

### Direct PR

For batch additions, clone `athena-content` and add JSON files under `resources/`:

```json
{
  "topic": "transformers",
  "resources": [
    {
      "title": "Attention is all you need (original paper)",
      "url": "https://arxiv.org/abs/1706.03762",
      "type": "article",
      "note": "The 2017 paper that started it all",
      "added_by": "yourname"
    }
  ]
}
```

### Rules (borrowed from roadmap.sh)

- File name = slugified topic (`Deep Learning` → `deep-learning.json`)
- Max **8 links per topic**
- Required per link: `title`, `url`, `type`, `note`, `added_by`
- Types: `official` / `article` / `video` / `course` / `opensource`
- No self-promotion, no paywalled-only content, no link shorteners
- URL must work — test before submitting

Merged PRs become visible to all ATHENA users on their next 24h cache refresh.
