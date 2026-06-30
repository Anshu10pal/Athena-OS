"""Commander Agent — intent detection + routing for the chat pipeline.

Chat uses a streaming-friendly route() (intent -> memory retrieval -> agent prompt),
while multi-step workflows (roadmap generation) use a LangGraph graph
(see app/agents/roadmap_graph.py).
"""
import json

from app.agents import prompts
from app.core.llm import chat_json
from app.services.vector_store import search_memory


def detect_intent(message: str) -> str:
    """Instant keyword-based routing. Kept off the LLM critical path so streaming
    starts immediately — the agent badge is cosmetic, so a heuristic is plenty."""
    m = message.lower()
    if any(w in m for w in ("interview", "hiring", "recruiter", "screening round")):
        return "interview"
    if any(w in m for w in ("present", "deck", "slide", "pitch")):
        return "presentation"
    if any(w in m for w in ("remember", "recall", "what did i", "last time", "previously", "my notes", "from the vault", "we discussed")):
        return "memory"
    if any(w in m for w in ("research", "compare", "trade-off", "tradeoff", " vs ", "versus", "deep dive", "pros and cons")):
        return "research"
    if any(w in m for w in ("explain", "teach", "learn", "how do", "how does", "what is", "what are", "why does", "concept", "understand", "difference between")):
        return "learn"
    return "general"


def build_context(user, message: str) -> tuple[str, str]:
    """Returns (profile_str, memories_str)."""
    profile = {
        "name": user.name,
        "experience_level": user.experience_level,
        "current_role": user.current_role,
        "target_role": user.target_role,
        "learning_goals": user.learning_goals,
        "skills": user.skills,
    }
    memories = search_memory(user.id, message, limit=4)
    mem_str = "\n".join(f"- [{m['kind']}] {m['text'][:300]}" for m in memories) or "None yet."
    return json.dumps(profile), mem_str


def route(user, message: str) -> dict:
    """Pick the agent and build its system prompt. The chat endpoint streams the reply.

    Intent detection and memory retrieval are independent -> run them in parallel.
    """
    intent = detect_intent(message)  # instant heuristic
    profile_str, mem_str = build_context(user, message)

    if intent == "learn":
        system = prompts.LEARNING.format(profile=profile_str, memories=mem_str)
    elif intent == "research":
        system = prompts.RESEARCH.format(profile=profile_str)
    elif intent == "memory":
        system = (
            "You are the Memory Agent of ATHENA OS. Answer the user's question using ONLY "
            f"these retrieved memories from their past sessions:\n{mem_str}\n"
            "If the memories don't cover it, say so honestly."
        )
    elif intent == "interview":
        system = (
            prompts.GENERAL.format(profile=profile_str, memories=mem_str)
            + "\nThe user wants interview practice — give a brief tip, then point them to the "
            "Interview Arena page for a full scored voice interview."
        )
    elif intent == "presentation":
        system = (
            prompts.GENERAL.format(profile=profile_str, memories=mem_str)
            + "\nThe user is asking about presentations — help conversationally, and mention the "
            "Presentation Arena page for full deck analysis with speaker notes."
        )
    else:
        system = prompts.GENERAL.format(profile=profile_str, memories=mem_str)

    return {"intent": intent, "system": system}
