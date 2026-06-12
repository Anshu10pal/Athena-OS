"""ATHENA OS — Streamlit test console (interim UI until Node.js is installed).

This is a thin client over the same FastAPI backend the React app uses.
Run the backend first (python run.py), then:

    pip install streamlit requests
    streamlit run athena_console.py
"""
import json

import requests
import streamlit as st

API = "http://127.0.0.1:8000"

st.set_page_config(page_title="ATHENA OS Console", page_icon="🦉", layout="wide")

if "token" not in st.session_state:
    st.session_state.token = None
if "chat" not in st.session_state:
    st.session_state.chat = []
if "interview" not in st.session_state:
    st.session_state.interview = None


def auth_headers():
    return {"Authorization": f"Bearer {st.session_state.token}"}


def api_get(path):
    r = requests.get(f"{API}{path}", headers=auth_headers(), timeout=120)
    r.raise_for_status()
    return r.json()


def api_post(path, payload=None):
    r = requests.post(f"{API}{path}", json=payload or {}, headers=auth_headers(), timeout=180)
    r.raise_for_status()
    return r.json()


# ---------------- Auth gate ----------------
if not st.session_state.token:
    st.title("🦉 ATHENA OS — Console")
    st.caption("Interim Streamlit UI · the React frontend takes over once Node.js is installed")
    tab_login, tab_register = st.tabs(["Sign in", "Create account"])

    with tab_login:
        email = st.text_input("Email", key="li_email")
        password = st.text_input("Password", type="password", key="li_pass")
        if st.button("Sign in", type="primary"):
            r = requests.post(f"{API}/api/auth/login", data={"username": email, "password": password}, timeout=30)
            if r.ok:
                st.session_state.token = r.json()["access_token"]
                st.rerun()
            else:
                st.error(r.json().get("detail", "Login failed"))

    with tab_register:
        name = st.text_input("Name", key="rg_name")
        email_r = st.text_input("Email", key="rg_email")
        password_r = st.text_input("Password", type="password", key="rg_pass")
        if st.button("Create account", type="primary"):
            r = requests.post(
                f"{API}/api/auth/register",
                json={"name": name, "email": email_r, "password": password_r},
                timeout=30,
            )
            if r.ok:
                st.session_state.token = r.json()["access_token"]
                st.rerun()
            else:
                st.error(r.json().get("detail", "Registration failed"))
    st.stop()

# ---------------- Authenticated app ----------------
me = api_get("/api/auth/me")
with st.sidebar:
    st.title("🦉 ATHENA OS")
    st.write(f"**{me['name']}**")
    st.caption(f"🔥 {me['streak']} day streak · ✨ {me['xp']} XP")
    page = st.radio("Navigate", ["Dashboard", "Chat", "Roadmap", "Interview Arena", "Presentation Arena", "Knowledge Vault"])
    if st.button("Sign out"):
        st.session_state.token = None
        st.rerun()

# ---------------- Dashboard ----------------
if page == "Dashboard":
    st.header("Dashboard")
    dash = api_get("/api/analytics/dashboard")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Level", dash["level"])
    c2.metric("Roadmap", f"{dash['roadmap_progress']}%", dash.get("roadmap_title") or "")
    c3.metric("Interview readiness", f"{dash['interview_readiness']}/100")
    c4.metric("Missions done", dash["missions_completed"])

    st.subheader("Today's missions")
    missions = api_get("/api/missions/today")
    if not missions:
        st.info("No missions yet — generate a roadmap first, then revisit.")
    for m in missions:
        col_a, col_b = st.columns([5, 1])
        done = m["status"] == "completed"
        col_a.write(("~~" + m["objective"] + "~~") if done else m["objective"])
        col_a.caption(f"{m['difficulty']} · +{m['xp_reward']} XP")
        if not done and col_b.button("Complete", key=f"m{m['id']}"):
            api_post(f"/api/missions/{m['id']}/complete")
            st.rerun()

    st.subheader("Digital twin")
    for k, v in dash["digital_twin"].items():
        st.progress(min(100, int(v)) / 100, text=f"{k.replace('_', ' ').title()} — {v}")

# ---------------- Chat ----------------
elif page == "Chat":
    st.header("Talk to Athena")
    for msg in st.session_state.chat:
        with st.chat_message(msg["role"]):
            if msg.get("intent"):
                st.caption(f"{msg['intent']} agent")
            st.write(msg["content"])

    prompt = st.chat_input("Ask Athena anything…")
    if prompt:
        st.session_state.chat.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)
        history = [{"role": m["role"], "content": m["content"]} for m in st.session_state.chat[:-1]]
        with st.chat_message("assistant"):
            placeholder = st.empty()
            full, intent = "", None
            with requests.post(
                f"{API}/api/chat/stream",
                json={"message": prompt, "history": history[-10:]},
                headers=auth_headers(),
                stream=True,
                timeout=300,
            ) as r:
                for line in r.iter_lines():
                    if not line or not line.startswith(b"data: "):
                        continue
                    evt = json.loads(line[6:])
                    if evt["type"] == "meta":
                        intent = evt["intent"]
                    elif evt["type"] == "token":
                        full += evt["text"]
                        placeholder.write(full + "▌")
                    elif evt["type"] == "error":
                        full = f"Something went wrong: {evt['message']}"
            placeholder.write(full)
        st.session_state.chat.append({"role": "assistant", "content": full, "intent": intent})

# ---------------- Roadmap ----------------
elif page == "Roadmap":
    st.header("Roadmap engine")
    role = st.text_input("Target role", placeholder="AI Architect")
    if st.button("Generate roadmap", type="primary") and role.strip():
        with st.spinner("Athena is charting your path (LangGraph: generate → validate)…"):
            api_post("/api/roadmap/generate", {"target_role": role})
        st.rerun()

    maps = api_get("/api/roadmap")
    if maps:
        rm = maps[0]
        st.subheader(rm["title"])
        icons = {"locked": "🔒", "available": "🟡", "in_progress": "▶️", "completed": "✅"}
        for node in rm["nodes"]:
            with st.expander(f"{icons.get(node['status'], '')} {node['title']}", expanded=node["status"] in ("available", "in_progress")):
                st.write(node["description"])
                if node.get("skills"):
                    st.caption(" · ".join(node["skills"]))
                if node["status"] == "available" and st.button("Start", key=f"s{node['id']}"):
                    requests.patch(f"{API}/api/roadmap/{rm['id']}/node", json={"node_id": node["id"], "status": "in_progress"}, headers=auth_headers(), timeout=30)
                    st.rerun()
                if node["status"] == "in_progress" and st.button("Mark complete (+150 XP)", key=f"c{node['id']}"):
                    requests.patch(f"{API}/api/roadmap/{rm['id']}/node", json={"node_id": node["id"], "status": "completed"}, headers=auth_headers(), timeout=30)
                    st.rerun()

# ---------------- Interview ----------------
elif page == "Interview Arena":
    st.header("Interview Arena")
    sess = st.session_state.interview
    if sess is None:
        role = st.selectbox("Track", ["AI Engineer", "ML Engineer", "Data Scientist", "Architect", "Product Manager", "Behavioral"])
        if st.button("Start interview", type="primary"):
            with st.spinner("Preparing your interviewer…"):
                st.session_state.interview = api_post("/api/interview/start", {"role": role})
            st.rerun()
    elif sess.get("finished"):
        scores = sess["scores"]
        st.success("Interview complete — +200 XP")
        for k in ["communication", "technical_accuracy", "confidence", "depth", "leadership"]:
            st.progress((scores.get(k, 0)) / 10, text=f"{k.replace('_', ' ').title()} — {scores.get(k, 0)}/10")
        st.write(scores.get("feedback", ""))
        col_s, col_i = st.columns(2)
        col_s.write("**Strengths**")
        for s in scores.get("strengths", []):
            col_s.write(f"- {s}")
        col_i.write("**Improve next**")
        for s in scores.get("improvements", []):
            col_i.write(f"- {s}")
        if st.button("New interview"):
            st.session_state.interview = None
            st.rerun()
    else:
        st.caption(f"Question {sess['question_number']} of {sess['total']}")
        st.write(f"**{sess['question']}**")
        answer = st.text_area("Your answer", key=f"ans{sess['question_number']}")
        if st.button("Submit answer", type="primary") and answer.strip():
            with st.spinner("Evaluating…"):
                st.session_state.interview = api_post("/api/interview/answer", {"session_id": sess["session_id"], "answer": answer})
            st.rerun()

# ---------------- Presentation ----------------
elif page == "Presentation Arena":
    st.header("Presentation Arena")
    up = st.file_uploader("Upload a deck", type=["pptx", "pdf"])
    if up and st.button("Analyze", type="primary"):
        with st.spinner("Athena is reviewing your deck…"):
            r = requests.post(
                f"{API}/api/presentation/analyze",
                files={"file": (up.name, up.getvalue())},
                headers=auth_headers(),
                timeout=300,
            )
        if r.ok:
            res = r.json()
            st.metric("Overall", f"{res.get('overall_score', '—')}/10")
            st.write(res.get("executive_summary", ""))
            c1, c2, c3 = st.columns(3)
            c1.info(f"**Storytelling**\n\n{res.get('storytelling', '')}")
            c2.info(f"**Business impact**\n\n{res.get('business_impact', '')}")
            c3.info(f"**Technical depth**\n\n{res.get('technical_depth', '')}")
            st.subheader("Slide-by-slide")
            for s in res.get("slide_feedback", []):
                st.write(f"**S{s['slide']}** — {s['feedback']}")
            st.subheader("Speaker notes")
            for s in res.get("speaker_notes", []):
                st.write(f"**S{s['slide']}** — {s['notes']}")
        else:
            st.error(r.json().get("detail", "Analysis failed"))

# ---------------- Vault ----------------
elif page == "Knowledge Vault":
    st.header("Knowledge Vault")
    q = st.text_input("Semantic search", placeholder='What did I learn about LangGraph?')
    if q:
        hits = api_get(f"/api/vault/search?q={requests.utils.quote(q)}")
        if not hits:
            st.info("Nothing in memory yet for that.")
        for h in hits:
            st.write(h["text"])
            st.caption(f"{h.get('kind', '')} · relevance {h.get('score', 0):.2f}")
            st.divider()

    with st.form("note"):
        st.subheader("Save a note")
        title = st.text_input("Title")
        content = st.text_area("What did you learn?")
        if st.form_submit_button("Save to vault") and title.strip() and content.strip():
            api_post("/api/vault/notes", {"title": title, "content": content})
            st.success("Saved.")

    st.subheader("Recent entries")
    for e in api_get("/api/vault/entries")[:20]:
        st.write(f"**{e['title']}**  `{e['kind']}`")
        st.caption(e["content"][:200])