"""Roadmap generation as a LangGraph workflow: generate -> validate/repair."""
from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.agents import prompts
from app.core.llm import chat_json


class RoadmapState(TypedDict):
    target_role: str
    current_skills: list[str]
    draft: dict
    final: dict


def generate_node(state: RoadmapState) -> dict:
    draft = chat_json(
        [
            {
                "role": "system",
                "content": prompts.ROADMAP_GENERATOR.format(
                    target_role=state["target_role"],
                    current_skills=", ".join(state["current_skills"]) or "nothing yet",
                ),
            },
            {"role": "user", "content": "Generate the roadmap JSON now."},
        ],
        fast=False,
    )
    return {"draft": draft}


def validate_node(state: RoadmapState) -> dict:
    import json

    fixed = chat_json(
        [
            {"role": "system", "content": prompts.ROADMAP_VALIDATOR},
            {"role": "user", "content": json.dumps(state["draft"])},
        ],
        fast=True,
    )
    # Stamp node states: first node available, rest locked.
    nodes = fixed.get("nodes", [])
    for i, node in enumerate(nodes):
        node["status"] = "available" if i == 0 else "locked"
    fixed["nodes"] = nodes
    return {"final": fixed}


_graph = StateGraph(RoadmapState)
_graph.add_node("generate", generate_node)
_graph.add_node("validate", validate_node)
_graph.set_entry_point("generate")
_graph.add_edge("generate", "validate")
_graph.add_edge("validate", END)
roadmap_workflow = _graph.compile()


def generate_roadmap(target_role: str, current_skills: list[str]) -> dict:
    result = roadmap_workflow.invoke(
        {"target_role": target_role, "current_skills": current_skills, "draft": {}, "final": {}}
    )
    return result["final"]


def generate_sub_roadmap(target_role: str, node: dict) -> dict:
    """Expand one node into a granular sub-roadmap (drill-down)."""
    from app.agents import prompts as _p

    draft = chat_json(
        [
            {
                "role": "system",
                "content": _p.SUB_ROADMAP_GENERATOR.format(
                    target_role=target_role,
                    node_title=node["title"],
                    node_description=node.get("description", ""),
                    skills=", ".join(node.get("skills", [])),
                ),
            },
            {"role": "user", "content": "Generate the sub-roadmap JSON now."},
        ],
        fast=False,
    )
    result = roadmap_workflow.invoke({"target_role": target_role, "current_skills": [], "draft": draft, "final": {}})
    # invoke runs generate again; we want validate-only on our draft -> call validate directly
    validated = validate_node({"target_role": target_role, "current_skills": [], "draft": draft, "final": {}})
    return validated["final"]
