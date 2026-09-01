/**
 * Pure edit reducer for the skill-graph confirmation screen.
 *
 * Extracted from the page component and kept side-effect-free so it is
 * unit-testable, matching this project's `lib/*.ts` + `lib/*.test.ts`
 * convention (17 such pairs already). Graph editing has enough invariants --
 * two levels deep, a child cap, no self-parenting, no orphaned skills -- that
 * testing them through a rendered component would be slower and would test the
 * rendering instead.
 *
 * The reducer builds a PENDING edit set. Nothing here talks to the network; the
 * page sends the accumulated set as one PATCH. That means the user can rename
 * three nodes, reparent one and delete another, see the result, and still
 * abandon the whole thing -- which matters because this screen is the
 * component's only validation path and a user who is afraid to experiment on it
 * will not validate anything.
 */

export type TargetTier = "expert" | "proficient" | "working" | "awareness";

export const TARGET_TIERS: TargetTier[] = ["expert", "proficient", "working", "awareness"];

/** Kept in sync with config/arena_extraction.yaml `max_children_per_parent`.
 *  Duplicated deliberately rather than fetched: the server re-validates every
 *  edit anyway, so this copy exists only to disable a control before the user
 *  clicks it. A drift makes the UI slightly pessimistic, never wrong. */
export const MAX_CHILDREN_PER_PARENT = 8;

export interface MergeEvidence {
  surface: string;
  method: string;
  score: number;
}

export interface SourceSpan {
  span: string;
  offset: number;
  section: string;
}

export interface SkillNodeT {
  id: number;
  parent_id: number | null;
  canonical_name: string;
  jd_weight: number;
  target_tier: TargetTier;
  surface_forms: string[];
  merge_evidence: MergeEvidence[];
  source_spans: SourceSpan[];
  weight_signals: Record<string, any>;
  weight_explanation: string;
  extraction_source: "llm_extraction" | "cluster_parent" | "user_added";
  user_edited: boolean;
  children?: SkillNodeT[];
}

export interface MergeSuggestionT {
  id: number;
  left_node_id: number;
  right_node_id: number;
  left_name: string;
  right_name: string;
  enriched_cosine: number;
  bare_cosine: number;
  status: "pending" | "accepted" | "rejected";
}

export interface ArenaGraphT {
  id: number;
  title: string;
  jd_text: string;
  extractor_version: string;
  graph_confirmed_at: string | null;
  extraction_metadata: Record<string, any>;
  parents: SkillNodeT[];
  merge_suggestions: MergeSuggestionT[];
  cached?: boolean;
}

export interface NodeUpdate {
  id: number;
  canonical_name?: string;
  jd_weight?: number;
  target_tier?: TargetTier;
  /** 0 means "promote to top level" — a sentinel, because `undefined` already
   *  means "leave the parent alone" and the two are different instructions. */
  parent_id?: number;
}

export interface NodeAddition {
  canonical_name: string;
  parent_id?: number | null;
  jd_weight?: number;
  target_tier?: TargetTier;
}

export interface EditSet {
  updates: NodeUpdate[];
  additions: NodeAddition[];
  deletes: number[];
}

export const emptyEditSet = (): EditSet => ({ updates: [], additions: [], deletes: [] });

export const hasEdits = (edits: EditSet): boolean =>
  edits.updates.length > 0 || edits.additions.length > 0 || edits.deletes.length > 0;

/** Flatten a graph to a lookup, parents and children alike. */
export function flatten(graph: ArenaGraphT): SkillNodeT[] {
  const out: SkillNodeT[] = [];
  for (const parent of graph.parents) {
    out.push(parent);
    for (const child of parent.children ?? []) out.push(child);
  }
  return out;
}

/**
 * Merge one update into the set, collapsing repeats on the same node.
 *
 * Collapsing matters: without it, renaming a node four times sends four
 * updates for the same id, and the server applies them in array order — so the
 * result depends on ordering that nothing guarantees. Last write wins, per
 * field.
 */
export function stageUpdate(edits: EditSet, update: NodeUpdate): EditSet {
  const existing = edits.updates.find((u) => u.id === update.id);
  if (!existing) return { ...edits, updates: [...edits.updates, update] };
  return {
    ...edits,
    updates: edits.updates.map((u) => (u.id === update.id ? { ...u, ...update } : u)),
  };
}

export function stageAddition(edits: EditSet, addition: NodeAddition): EditSet {
  return { ...edits, additions: [...edits.additions, addition] };
}

/**
 * Stage a delete.
 *
 * Any pending update for that node is dropped at the same time — sending an
 * update and a delete for one id is a contradiction, and which one wins would
 * depend on the server's iteration order rather than on the user's intent.
 */
export function stageDelete(edits: EditSet, nodeId: number): EditSet {
  if (edits.deletes.includes(nodeId)) return edits;
  return {
    ...edits,
    deletes: [...edits.deletes, nodeId],
    updates: edits.updates.filter((u) => u.id !== nodeId),
  };
}

export function unstageDelete(edits: EditSet, nodeId: number): EditSet {
  return { ...edits, deletes: edits.deletes.filter((id) => id !== nodeId) };
}

export type ReparentRefusal =
  | { ok: true }
  | { ok: false; reason: string };

/**
 * Whether a reparent is allowed, and why not when it isn't.
 *
 * Returns the reason rather than a bare boolean so the UI can say what is
 * wrong instead of silently disabling a control — a disabled control with no
 * explanation reads as a bug.
 */
export function canReparent(
  graph: ArenaGraphT,
  nodeId: number,
  newParentId: number | 0,
): ReparentRefusal {
  if (newParentId === 0) return { ok: true };
  if (nodeId === newParentId) return { ok: false, reason: "A skill cannot be its own parent." };

  const all = flatten(graph);
  const target = all.find((n) => n.id === newParentId);
  if (!target) return { ok: false, reason: "That group is not in this graph." };
  if (target.parent_id !== null) {
    return { ok: false, reason: "Graphs are two levels deep; that is already a child skill." };
  }

  const node = all.find((n) => n.id === nodeId);
  // Moving a PARENT under another parent would carry its children to depth 3.
  if (node && node.parent_id === null && (node.children?.length ?? 0) > 0) {
    return {
      ok: false,
      reason: "That group has skills under it. Move or promote them first.",
    };
  }

  const currentChildren = (target.children ?? []).filter((c) => c.id !== nodeId).length;
  if (currentChildren + 1 > MAX_CHILDREN_PER_PARENT) {
    return {
      ok: false,
      reason: `${target.canonical_name} already has ${MAX_CHILDREN_PER_PARENT} skills.`,
    };
  }
  return { ok: true };
}

/**
 * Apply a pending edit set to a graph for OPTIMISTIC display.
 *
 * The server remains authoritative — this exists so the screen responds to a
 * rename immediately instead of after a round trip. Deleting a parent
 * re-parents its children to top level here, mirroring what the server
 * actually does, because showing a cascade the server will not perform would
 * teach the user the wrong thing about a destructive action.
 */
export function applyEdits(graph: ArenaGraphT, edits: EditSet): ArenaGraphT {
  const updateFor = (id: number) => edits.updates.find((u) => u.id === id);
  const deleted = new Set(edits.deletes);

  const patched = (node: SkillNodeT): SkillNodeT => {
    const update = updateFor(node.id);
    if (!update) return node;
    return {
      ...node,
      canonical_name: update.canonical_name ?? node.canonical_name,
      jd_weight: update.jd_weight ?? node.jd_weight,
      target_tier: update.target_tier ?? node.target_tier,
      user_edited: true,
    };
  };

  const orphaned: SkillNodeT[] = [];
  const parents: SkillNodeT[] = [];

  for (const parent of graph.parents) {
    const children = (parent.children ?? []).filter((c) => !deleted.has(c.id)).map(patched);
    if (deleted.has(parent.id)) {
      // Re-parent, never cascade. These skills came from the JD.
      orphaned.push(...children.map((c) => ({ ...c, parent_id: null, children: [] })));
      continue;
    }
    parents.push({ ...patched(parent), children });
  }

  // Reparent-to-top-level updates, applied after deletion so a node can be
  // promoted and its old parent removed in one set.
  for (const update of edits.updates) {
    if (update.parent_id !== 0) continue;
    for (const parent of parents) {
      const found = (parent.children ?? []).find((c) => c.id === update.id);
      if (found) {
        parent.children = (parent.children ?? []).filter((c) => c.id !== update.id);
        orphaned.push({ ...found, parent_id: null, children: [] });
      }
    }
  }

  const added: SkillNodeT[] = edits.additions
    .filter((a) => !a.parent_id)
    .map((a, i) => ({
      id: -1 - i, // negative: not yet persisted, and never collides with a real id
      parent_id: null,
      canonical_name: a.canonical_name,
      jd_weight: a.jd_weight ?? 0.5,
      target_tier: a.target_tier ?? "working",
      surface_forms: [a.canonical_name],
      merge_evidence: [],
      source_spans: [],
      weight_signals: { derivation: "added by user" },
      weight_explanation: "added by you",
      extraction_source: "user_added",
      user_edited: true,
      children: [],
    }));

  return { ...graph, parents: [...parents, ...orphaned, ...added] };
}

/** Total skills after pending edits — what the confirm gate counts. */
export function nodeCount(graph: ArenaGraphT, edits: EditSet): number {
  return flatten(applyEdits(graph, edits)).length;
}

export interface StructureWarning {
  level: "warn" | "info";
  message: string;
}

/**
 * Structural observations, shown to the user as notes rather than errors.
 *
 * Deliberately NOT gates. A short JD honestly yielding three groups is a
 * correct result, not a problem to be corrected — pushing the user to add
 * groups the JD does not support is how a graph acquires invented skills. So
 * these inform and never block.
 */
export function structureWarnings(graph: ArenaGraphT, edits: EditSet): StructureWarning[] {
  const applied = applyEdits(graph, edits);
  const out: StructureWarning[] = [];

  for (const parent of applied.parents) {
    const n = parent.children?.length ?? 0;
    if (n > MAX_CHILDREN_PER_PARENT) {
      out.push({
        level: "warn",
        message: `"${parent.canonical_name}" has ${n} skills — the limit is ${MAX_CHILDREN_PER_PARENT}.`,
      });
    }
  }

  const total = flatten(applied).length;
  if (total === 0) {
    out.push({ level: "warn", message: "The graph is empty. Add at least one skill to continue." });
  }
  return out;
}
