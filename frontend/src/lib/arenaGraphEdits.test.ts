import { describe, expect, it } from "vitest";
import {
  ArenaGraphT,
  MAX_CHILDREN_PER_PARENT,
  SkillNodeT,
  applyEdits,
  canReparent,
  emptyEditSet,
  flatten,
  hasEdits,
  nodeCount,
  stageAddition,
  stageDelete,
  stageUpdate,
  structureWarnings,
  unstageDelete,
} from "./arenaGraphEdits";

function node(id: number, name: string, parentId: number | null = null): SkillNodeT {
  return {
    id,
    parent_id: parentId,
    canonical_name: name,
    jd_weight: 0.5,
    target_tier: "working",
    surface_forms: [name],
    merge_evidence: [],
    source_spans: [],
    weight_signals: {},
    weight_explanation: "section_base +0.60",
    extraction_source: "llm_extraction",
    user_edited: false,
    children: [],
  };
}

function graph(): ArenaGraphT {
  const dataParent = { ...node(1, "Data Engineering"), children: [node(2, "Python", 1), node(3, "SQL", 1)] };
  const opsParent = { ...node(4, "Platform Operations"), children: [node(5, "Kubernetes", 4)] };
  return {
    id: 99,
    title: "Senior Data Engineer",
    jd_text: "...",
    extractor_version: "a1",
    graph_confirmed_at: null,
    extraction_metadata: {},
    parents: [dataParent, opsParent],
    merge_suggestions: [],
  };
}

describe("flatten", () => {
  it("returns parents and children", () => {
    expect(flatten(graph()).map((n) => n.id).sort()).toEqual([1, 2, 3, 4, 5]);
  });
});

describe("staging", () => {
  it("starts empty", () => {
    const edits = emptyEditSet();
    expect(hasEdits(edits)).toBe(false);
  });

  it("collapses repeated updates on one node, last write per field", () => {
    // Without collapsing, four renames send four updates for one id and the
    // result depends on array ordering that nothing guarantees.
    let edits = emptyEditSet();
    edits = stageUpdate(edits, { id: 2, canonical_name: "Py" });
    edits = stageUpdate(edits, { id: 2, canonical_name: "Python 3" });
    edits = stageUpdate(edits, { id: 2, jd_weight: 0.9 });
    expect(edits.updates).toHaveLength(1);
    expect(edits.updates[0]).toEqual({ id: 2, canonical_name: "Python 3", jd_weight: 0.9 });
  });

  it("keeps updates for different nodes separate", () => {
    let edits = emptyEditSet();
    edits = stageUpdate(edits, { id: 2, canonical_name: "A" });
    edits = stageUpdate(edits, { id: 3, canonical_name: "B" });
    expect(edits.updates).toHaveLength(2);
  });

  it("drops a pending update when the node is deleted", () => {
    // Sending an update AND a delete for one id is a contradiction; which wins
    // would depend on the server's iteration order rather than the user's intent.
    let edits = emptyEditSet();
    edits = stageUpdate(edits, { id: 2, canonical_name: "Renamed" });
    edits = stageDelete(edits, 2);
    expect(edits.updates).toHaveLength(0);
    expect(edits.deletes).toEqual([2]);
  });

  it("does not duplicate a delete", () => {
    let edits = stageDelete(emptyEditSet(), 2);
    edits = stageDelete(edits, 2);
    expect(edits.deletes).toEqual([2]);
  });

  it("can unstage a delete", () => {
    let edits = stageDelete(emptyEditSet(), 2);
    edits = unstageDelete(edits, 2);
    expect(hasEdits(edits)).toBe(false);
  });
});

describe("canReparent", () => {
  it("allows promotion to top level", () => {
    expect(canReparent(graph(), 2, 0)).toEqual({ ok: true });
  });

  it("allows moving a child to another parent", () => {
    expect(canReparent(graph(), 2, 4)).toEqual({ ok: true });
  });

  it("refuses self-parenting with a reason", () => {
    const result = canReparent(graph(), 2, 2);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toMatch(/own parent/i);
  });

  it("refuses a third level", () => {
    // Node 5 is a child; nothing may be parented under it.
    const result = canReparent(graph(), 2, 5);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toMatch(/two levels/i);
  });

  it("refuses moving a non-empty parent under another parent", () => {
    // That would carry its children to depth 3.
    const result = canReparent(graph(), 1, 4);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toMatch(/skills under it/i);
  });

  it("refuses exceeding the child cap and names the group", () => {
    const g = graph();
    g.parents[1].children = Array.from({ length: MAX_CHILDREN_PER_PARENT }, (_, i) =>
      node(100 + i, `Skill ${i}`, 4),
    );
    const result = canReparent(g, 2, 4);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toContain("Platform Operations");
  });

  it("refuses an unknown parent", () => {
    const result = canReparent(graph(), 2, 12345);
    expect(result.ok).toBe(false);
  });
});

describe("applyEdits", () => {
  it("applies a rename optimistically and marks the node edited", () => {
    const edits = stageUpdate(emptyEditSet(), { id: 2, canonical_name: "Python 3" });
    const applied = applyEdits(graph(), edits);
    const renamed = flatten(applied).find((n) => n.id === 2)!;
    expect(renamed.canonical_name).toBe("Python 3");
    expect(renamed.user_edited).toBe(true);
  });

  it("re-parents children when a parent is deleted, never cascades", () => {
    // Mirrors what the server does. Showing a cascade the server will not
    // perform would teach the user the wrong thing about a destructive action.
    const edits = stageDelete(emptyEditSet(), 1);
    const applied = applyEdits(graph(), edits);
    const ids = flatten(applied).map((n) => n.id).sort();
    expect(ids).not.toContain(1);
    expect(ids).toContain(2);
    expect(ids).toContain(3);
    for (const orphan of applied.parents.filter((p) => [2, 3].includes(p.id))) {
      expect(orphan.parent_id).toBeNull();
    }
  });

  it("deletes a child without touching its siblings", () => {
    const applied = applyEdits(graph(), stageDelete(emptyEditSet(), 2));
    const ids = flatten(applied).map((n) => n.id);
    expect(ids).not.toContain(2);
    expect(ids).toContain(3);
  });

  it("promotes a child to top level on parent_id 0", () => {
    const edits = stageUpdate(emptyEditSet(), { id: 2, parent_id: 0 });
    const applied = applyEdits(graph(), edits);
    const promoted = applied.parents.find((p) => p.id === 2);
    expect(promoted).toBeDefined();
    expect(promoted!.parent_id).toBeNull();
    expect(applied.parents.find((p) => p.id === 1)!.children).toHaveLength(1);
  });

  it("shows additions with a negative id so they never collide with real ones", () => {
    const edits = stageAddition(emptyEditSet(), { canonical_name: "Rust" });
    const applied = applyEdits(graph(), edits);
    const added = applied.parents.find((p) => p.canonical_name === "Rust")!;
    expect(added.id).toBeLessThan(0);
    expect(added.extraction_source).toBe("user_added");
  });

  it("leaves the graph untouched when there are no edits", () => {
    const g = graph();
    expect(applyEdits(g, emptyEditSet())).toEqual(g);
  });
});

describe("nodeCount", () => {
  it("reflects pending deletes and additions", () => {
    expect(nodeCount(graph(), emptyEditSet())).toBe(5);
    expect(nodeCount(graph(), stageDelete(emptyEditSet(), 2))).toBe(4);
    expect(nodeCount(graph(), stageAddition(emptyEditSet(), { canonical_name: "Rust" }))).toBe(6);
  });
});

describe("structureWarnings", () => {
  it("says nothing about a small graph", () => {
    // A short JD honestly yielding few groups is a correct result. Pushing the
    // user to add groups the JD does not support is how a graph acquires
    // invented skills, so this must NOT warn.
    const g = graph();
    g.parents = [g.parents[0]];
    expect(structureWarnings(g, emptyEditSet())).toEqual([]);
  });

  it("warns when a parent exceeds the child cap", () => {
    const g = graph();
    g.parents[0].children = Array.from({ length: MAX_CHILDREN_PER_PARENT + 1 }, (_, i) =>
      node(200 + i, `Skill ${i}`, 1),
    );
    const warnings = structureWarnings(g, emptyEditSet());
    expect(warnings.some((w) => w.level === "warn" && w.message.includes("Data Engineering"))).toBe(true);
  });

  it("warns on an empty graph", () => {
    const g = graph();
    const edits = [1, 2, 3, 4, 5].reduce((acc, id) => stageDelete(acc, id), emptyEditSet());
    expect(structureWarnings(g, edits).some((w) => /empty/i.test(w.message))).toBe(true);
  });
});
