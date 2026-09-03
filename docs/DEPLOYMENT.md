# Deployment notes

ATHENA OS is designed local-first. These notes are for when you eventually want a hosted instance.

## Render (recommended for parity with your other projects)

### Backend (Web Service)
- Runtime: pin to **Python 3.12** in `runtime.txt`:
  ```
  python-3.12.x
  ```
- Build command: `pip install -r requirements.txt && bash scripts/fetch_models.sh`
  - **The second half is not optional.** `fetch_models.sh` downloads every model
    weight — Kokoro TTS, the Piper fallback voice, faster-whisper, and
    FastEmbed's `bge-small-en-v1.5` — into `backend/models/`, verifying each
    against a pinned SHA256 before trusting it.
  - It runs at **build**, which is the point: the runtime is offline-enforced
    (`MODELS_OFFLINE` defaults on), so a missing weight fails the build loudly
    rather than triggering a ~316 MB download on some user's first request. That
    closes `arena-known-issues.md` KI-2 and `voice-known-issues.md` VKI-4.
  - Weights land inside the **project directory** deliberately. Render's docs
    confirm the build filesystem carries into the runtime and that the runtime
    filesystem is otherwise ephemeral, but do **not** document whether
    build-time writes outside it (`~/.cache`, `/tmp`) survive — and FastEmbed's
    own default was `/tmp/fastembed_cache`, which is cleared under a running
    service.
  - On the free tier this matters more than once-per-deploy: the ephemeral
    filesystem is restored to its post-build state on every cold start, so a
    *runtime* fetch is re-paid after every spin-down.
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Environment variables (Dashboard → Environment):
  - `GEMINI_API_KEY`
  - `GROQ_API_KEY`
  - `SECRET_KEY` (a long random string — different from your local dev one)
  - `DATABASE_URL` — for production, point to **Render Postgres** instead of SQLite
- Persistent disk: **mount one at `/opt/render/project/src/qdrant_data`** so vector memory survives deploys

#### Codebase agent on a managed host

- **Private repositories need a per-host token env var.** A managed host has no
  keyring backend, so the developer-machine credential store is unavailable
  there. Set `ATHENA_GIT_TOKEN_<HOST>` — host uppercased with every
  non-alphanumeric character replaced by `_`:

  | Repo host | Variable |
  |---|---|
  | `github.com` | `ATHENA_GIT_TOKEN_GITHUB_COM` |
  | `gitlab.com` | `ATHENA_GIT_TOKEN_GITLAB_COM` |
  | `git.corp.example.co.uk` | `ATHENA_GIT_TOKEN_GIT_CORP_EXAMPLE_CO_UK` |

  There is intentionally no generic `ATHENA_GIT_TOKEN`: a single variable would
  be offered to whatever host the submitted URL names, so one mistyped or
  hostile URL would disclose the token to a third party. Public repos need no
  variable at all.

- **Persistent disk for the clone cache.** `REPO_CLONE_ROOT` defaults under the
  app data root, which on Render is ephemeral — without a mounted disk every
  redeploy re-clones every registered repo.

### Frontend (Static Site)
- Build command: `npm install && npm run build`
- Publish directory: `frontend/dist`
- Rewrite rule: `/* → /index.html` (SPA fallback)
- Set the backend URL in `frontend/src/lib/api.ts` to your Render backend URL

### Things to change before production
1. **Re-enable SSL verification** in `app/core/llm.py` — the `verify=False` was a corporate-proxy workaround, you don't want it on the public internet
2. **Move JWT from sessionStorage to httpOnly cookie** to defend against XSS
3. **Rate-limit the free-tier LLM calls per-user** — one user can blow your Gemini quota for everyone (slowapi or your own counter on `user_id`)
4. **Validate file uploads** in `/presentation/analyze` and `/oratory/analyze` — size cap, mime check, virus scan
5. **CORS allowlist** — restrict to your frontend URL
6. **Add HTTPS redirect** middleware
7. **Logging** — Render captures stdout but consider structured logs

## Docker (optional, for self-hosting)

**The buildpack path above is the single supported deployment shape.** Worth
stating plainly, because it was not: an instruction to "bake model weights into
the Docker image" was carried across four separate filed items — a voice
migration hard constraint, KI-2, VKI-4, and a phase go-ahead — before anyone
checked that this project has no Dockerfile and deliberately does not want one.
See `decisions.md`, the unresolved-premise defect class.

If you do containerize, the equivalent of the build command above is a `RUN`
step invoking `scripts/fetch_models.sh`, with `MODELS_OFFLINE` left on.

A `Dockerfile` and `docker-compose.yml` aren't included by default because the project deliberately avoids Docker dependence. If you want to containerize:

```dockerfile
# backend/Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```yaml
# docker-compose.yml
services:
  backend:
    build: ./backend
    ports: ["8000:8000"]
    environment:
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - GROQ_API_KEY=${GROQ_API_KEY}
      - SECRET_KEY=${SECRET_KEY}
    volumes:
      - ./data:/app/qdrant_data
      - ./athena.db:/app/athena.db
  frontend:
    build: ./frontend
    ports: ["5173:80"]
```

## Cost ceiling

At free tiers, the entire stack costs **$0/month** at modest usage:
- Gemini free: ~1,500 req/day
- Groq free: ~14,400 req/day
- Render free tier: backend + static site
- Render Postgres free tier: 1GB
- GitHub: free for the community content repo

Hitting the ceiling typically means a successful product, not a problem.
