import ELK from "elkjs/lib/elk-api.js";
import type { ElkNode } from "elkjs/lib/elk-api.js";
// Vite's `?url` suffix resolves to the built asset's path rather than
// importing the module -- the worker script is a self-executing GWT bundle
// (`self.onmessage = ...`), not something to evaluate on the main thread.
import elkWorkerUrl from "elkjs/lib/elk-worker.min.js?url";
import { NodeSingular, EdgeSingular } from "cytoscape";
import { resolvePositions } from "./elkPositions";

// One worker for the app's lifetime, not one per layout run: elkjs's ELK
// constructor spins up the worker and posts a `register` message before it
// is ready to layout anything, and doing that on every graph-scope change
// would serialize a startup cost into the interaction the worker exists to
// keep off the main thread.
let sharedElk: InstanceType<typeof ELK> | null = null;
function getElk(): InstanceType<typeof ELK> {
  if (!sharedElk) {
    sharedElk = new ELK({ workerFactory: () => new Worker(elkWorkerUrl) });
  }
  return sharedElk;
}

interface ElkInputNode {
  id: string;
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  children?: ElkInputNode[];
}

interface ElkInputGraph extends ElkInputNode {
  edges: { id: string; sources: string[]; targets: string[] }[];
}

// Mirrors cytoscape-elk's makeGraph/makeNode (src/layout.js) closely on
// purpose: this is the same input shape ELK has always been given for this
// view, just built without cytoscape-elk's own Layout class, whose position
// readback (`ele.scratch('elk')`, mutated in place) only works for a
// same-realm ELK and silently keeps every node at its old position with a
// worker-based one -- see elkPositions.ts's module comment.
function buildGraph(nodes: NodeSingular[], edges: EdgeSingular[]): ElkInputGraph {
  const byId = new Map<string, ElkInputNode>();
  const root: ElkInputNode = { id: "root", children: [] };

  for (const n of nodes) {
    const isParentNode = n.isParent();
    const k: ElkInputNode = { id: n.id() };
    if (!isParentNode) {
      // `layoutDimensions` and the `nodeDimensionsIncludeLabels` option are
      // core cytoscape internals with no public type declarations (also why
      // cytoscape-elk itself needs no types -- it's plain JS); this app has
      // one call site for them, here, replacing the one call site that used
      // to live inside cytoscape-elk's own layout.js.
      const dims = (n as unknown as { layoutDimensions: (opts: object) => { w: number; h: number } })
        .layoutDimensions({ nodeDimensionsIncludeLabels: true });
      const p = n.position();
      k.x = p.x - dims.w / 2;
      k.y = p.y - dims.h / 2;
      k.width = dims.w;
      k.height = dims.h;
    }
    byId.set(n.id(), k);
  }

  for (const n of nodes) {
    const k = byId.get(n.id())!;
    if (n.isChild()) {
      // parent() returns a NodeCollection, which the shipped cytoscape types
      // don't expose .id() on even though it is a single-node collection and
      // cytoscape proxies singular methods onto it at runtime -- the same
      // gap as layoutDimensions above.
      const parentId = (n.parent() as unknown as { id: () => string }).id();
      const parent = byId.get(parentId);
      (parent!.children = parent!.children ?? []).push(k);
    } else {
      root.children!.push(k);
    }
  }

  const elkEdges = edges.map((e) => ({
    id: e.id(),
    sources: [e.data("source") as string],
    targets: [e.data("target") as string],
  }));

  return { ...root, edges: elkEdges };
}

export interface ElkLayoutOptions {
  [key: string]: string;
}

// Runs the layered ELK algorithm off the main thread and returns the CENTRE
// position for every leaf (non-parent) node, keyed by cytoscape element id.
// Never touches `cy` or applies anything -- the caller decides whether the
// result is still wanted (a scope change during the await should discard it,
// not paint over the graph the user has already moved on from).
export async function computeElkLayout(
  nodes: NodeSingular[],
  edges: EdgeSingular[],
  elkOptions: ElkLayoutOptions,
): Promise<Map<string, { x: number; y: number }>> {
  const graph = buildGraph(nodes, edges);
  const result = await getElk().layout(graph as unknown as ElkNode, { layoutOptions: elkOptions });
  return resolvePositions(result);
}
