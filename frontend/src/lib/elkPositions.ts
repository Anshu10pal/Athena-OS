export interface ElkResultNode {
  id: string;
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  children?: ElkResultNode[];
}

interface Entry {
  x: number;
  y: number;
  width: number;
  height: number;
  parentId: string | null;
}

function collect(node: ElkResultNode, parentId: string | null, out: Map<string, Entry>) {
  for (const child of node.children ?? []) {
    out.set(child.id, {
      x: child.x ?? 0, y: child.y ?? 0,
      width: child.width ?? 0, height: child.height ?? 0,
      parentId,
    });
    collect(child, child.id, out);
  }
}

// cytoscape-elk's synchronous path reads positions back via `ele.scratch('elk')`,
// the SAME object it handed to ELK -- safe only because a synchronous, same-realm
// ELK mutates those objects in place. A worker-based ELK cannot do that: the
// graph crosses a postMessage boundary and comes back as a clone, so the only
// positions available are on the RESOLVED tree this function is given, and
// they have to be looked up by id and walked back up through THAT tree's
// nesting rather than cytoscape's live parent() chain.
//
// ELK gives each node an x/y that is a top-left corner relative to its own
// parent's origin (not absolute, not centred) -- so a nested node's canvas
// position is the sum of its own offset and every ancestor's offset, and
// cytoscape wants the centre of the node, not its corner.
export function resolvePositions(root: ElkResultNode): Map<string, { x: number; y: number }> {
  const entries = new Map<string, Entry>();
  collect(root, null, entries);

  const result = new Map<string, { x: number; y: number }>();
  for (const [id, entry] of entries) {
    let x = entry.x;
    let y = entry.y;
    let parentId = entry.parentId;
    while (parentId !== null) {
      const parent = entries.get(parentId);
      if (!parent) break;
      x += parent.x;
      y += parent.y;
      parentId = parent.parentId;
    }
    result.set(id, { x: x + entry.width / 2, y: y + entry.height / 2 });
  }
  return result;
}
