# Troubleshooting

Problems encountered during real builds, in roughly the order they bite you.

## Python and packages

### `mmh3` wheel build fails on Python 3.13
**Symptom:** `error: Microsoft Visual C++ 14.0 or greater is required` while installing `fastembed`.
**Cause:** `fastembed` depends on `mmh3`, and `mmh3 4.1.0` (the version `fastembed 0.5.x` pins) has no Windows wheel for Python 3.13.
**Fix:** Use **Python 3.12**:
```powershell
Remove-Item -Recurse -Force venv
& "C:\Program Files\Python312\python.exe" -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### `piper-phonemize` fails to install
**Symptom:** `No matching distribution found for piper-phonemize`.
**Cause:** No Windows wheels published, period. Building from source requires C++ build tools.
**Fix:** Skip Piper, use Edge-TTS instead — free Microsoft neural voices, dramatically better quality, pure Python:
```powershell
pip install edge-tts faster-whisper
```

### `pydantic_core.ValidationError: Extra inputs are not permitted` on startup
**Cause:** A non-declared env var in `.env` (often `HF_HUB_DISABLE_SYMLINKS_WARNING=1`).
**Fix:** Already baked into `app/core/config.py`:
```python
class Config:
    env_file = ".env"
    env_file_encoding = "utf-8"
    extra = "ignore"          # ← this line
```

## Corporate proxy / SSL

The most common class of failure on managed corporate machines (Prodapt, similar). The proxy intercepts HTTPS to scan traffic, presents its own certificate, and Python doesn't trust it.

### OpenAI client (Gemini/Groq) fails with `CERTIFICATE_VERIFY_FAILED`
**Already fixed in v3+:** `app/core/llm.py` constructs every OpenAI client with `http_client=httpx.Client(verify=False, timeout=60.0)`. If you see this error, you're on an older drop — pull the latest patch.

### Edge-TTS fails with `[SSL: CERTIFICATE_VERIFY_FAILED]`
**Cause:** Edge-TTS uses `aiohttp`'s websocket, which has its **own** SSL context independent of `httpx`.
**Fix:** Patch in `app/api/voice.py`:
```python
import aiohttp, ssl
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE
connector = aiohttp.TCPConnector(ssl=ssl_ctx)
async with aiohttp.ClientSession(connector=connector) as session:
    communicate.session = session
    async for chunk in communicate.stream():
        ...
```
**Worst case:** If the proxy blocks the websocket protocol entirely (not just SSL), Edge-TTS can't work on the corporate network. The frontend's browser-`speechSynthesis` fallback engages automatically, so voice never fully disappears.

### Whisper / FastEmbed model download fails
**Symptom:** `huggingface_hub` retries during first chat or first mic press.
**Cause:** Proxy blocks `huggingface.co` or `cdn-lfs.huggingface.co`.
**Fix:** Whitelist both domains with IT. As a one-time workaround, download the model on a personal network then copy `~/.cache/huggingface/hub` (or `%LOCALAPPDATA%\Temp\fastembed_cache`) into the corporate machine.

### `[WinError 1314] A required privilege is not held` during model download
**Cause:** Hugging Face caching uses symlinks, which Windows requires Developer Mode or admin to create.
**Fix:** It's a warning, not an error — the download still succeeds in degraded mode. Silence the warning safely:
```powershell
# Set as a Windows env var (NOT in .env, pydantic rejects it)
[Environment]::SetEnvironmentVariable("HF_HUB_DISABLE_SYMLINKS_WARNING","1","User")
```

## Node.js / npm

### `node : The term 'node' is not recognized` after installing
**Cause:** PATH update only applies to terminals opened **after** the install.
**Fix:** Quit all PowerShell + VS Code windows, open a fresh PowerShell from Start menu, retry. If still missing:
```powershell
[Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path","User") + ";C:\Program Files\nodejs", "User")
```
Then open another fresh terminal.

### `streamlit : The term 'streamlit' is not recognized` (venv active)
**Cause:** Console scripts not on PATH in this shell.
**Fix:** Use `python -m streamlit run athena_console.py`.

## Frontend

### Blank screen after boot sequence "ATHENA OS" appears
**Likely cause (v3.0 only — fixed in 3.1+):** Race in `BootSequence.tsx` where the lines-render attempted `.replace()` on an undefined array element.
**Fix:** Update to v3.1+ which uses `lines.filter(Boolean)` and `?.` operators.

### `Cannot read properties of undefined (reading 'replace')`
Same root cause as above.

### Hub stations stack at the top instead of orbiting (v3.0 only — fixed in 3.1)
**Cause:** v3.0 added a global `.card { position: relative; }` rule that overrode the `absolute` class on Hub stations.
**Fix:** v3.1+ scopes it: `.card:not(.absolute) { position: relative; }`. Stations also use trigonometric placement now (true ring at any size).

## Behaviour quirks

### Mission count drops below 3
**Cause (v3.0)**: Completion didn't deploy a replacement.
**Fix:** v3.1+ generates one immediately. v3.2+ adds top-up logic — refilling to 3 on every `GET /api/missions/today`.

### Whisper transcript has no fillers ("um"/"uh" missing)
**Cause:** Whisper's default `suppress_tokens` list silently deletes filler tokens before output.
**Fix:** v3.2+ uses `suppress_tokens=[]` to keep them.

### Oratory timer skips / counts 2 seconds in 1 (v3.0–3.1)
**Cause:** React StrictMode + interval double-fire causing tick-based counters to drift.
**Fix:** v3.3+ rebuilt as a timestamp stopwatch: `setElapsed(Math.floor((Date.now() - t0) / 1000))`. Drift-immune by design.

### Athena's voice changes between replies
**Cause (v3.2):** First reply fell back to the browser's default voice before Edge-TTS warmed up; later replies used Edge-TTS.
**Fix:** v3.3+ adds a Settings page voice picker that locks one voice for all replies. Test it with "Test voice" before relying on it.

### Oratory topics repeat
**Fix:** v3.3+ sends your last 12 topics as an avoid-list.

### Chat audio not playing
1. Open browser DevTools → Network → look for `/api/voice/speak` → check status. 501 = server TTS unavailable, fallback should engage.
2. Check Windows volume mixer — browsers sometimes default-mute individual tabs.
3. The browser fallback voice (the last-resort tier) requires no install; if even that fails, check `console.log` for `SpeechSynthesisErrorEvent`.

## Database

### Adding a column without migrations
SQLite-safe `ALTER TABLE` statements run at startup in `main.py` inside a try/except. To add another column later, append to that list — `IF NOT EXISTS` isn't supported by SQLite for ALTER TABLE so the try/except is the idiom:
```python
"ALTER TABLE users ADD COLUMN my_new_field VARCHAR(100) DEFAULT ''",
```

### Lost your password
The schema doesn't include a password-reset flow yet. Quickest unblock:
```python
# In backend/
python -c "
from app.db.database import SessionLocal
from app.db.models import User
from app.core.security import hash_password
db = SessionLocal()
u = db.query(User).filter(User.email == 'you@example.com').first()
u.hashed_password = hash_password('new_temp_password')
db.commit()
print('reset')
"
```
