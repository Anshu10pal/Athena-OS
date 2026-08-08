import { NeighborsResponseT } from "./api";
import { groupNeighborsByDirectory, shortDirLabel } from "./neighborGrouping";

// Phase H4: neighbours are grouped by directory and collapsed to a count
// -- the same aggregation principle as the architecture map, applied per
// file. Before this, security.py's 14 real importers under backend/app/api
// rendered as 14 separate nodes, all labelled "backend/app/api/...py":
// the repeated path prefix was drawn fourteen times, which is exactly why
// the diagram was unreadable at panel width. Grouped, that's one node:
// "api/ ×14". Cap is now on GROUPS per direction, not files -- 8, not the
// old 15 -- since collapsing same-directory neighbours already does most
// of the crowding-reduction work G4's per-file cap existed for.
export const MERMAID_GROUP_CAP_PER_DIRECTION = 8;

// Mermaid node IDs can't contain "/", ".", or "-" -- exactly what file
// paths are made of. Generated IDs (c0 for the center file, i0.. for
// importer groups, o0.. for import groups -- kept from G4 unchanged) side
// step this entirely rather than trying to sanitize a path into a valid
// identifier; the real path/label only ever appears escaped, never as an ID.
function sanitizeLabel(text: string): string {
  return text.replace(/"/g, "&quot;");
}

export interface MermaidGroup {
  dir: string;
  label: string; // e.g. "api/ ×14"
  count: number;
}

function groupByDirectory(neighbors: Parameters<typeof groupNeighborsByDirectory>[0]): MermaidGroup[] {
  return groupNeighborsByDirectory(neighbors).map((g) => ({
    dir: g.dir,
    count: g.count,
    label: `${shortDirLabel(g.dir)}/ ×${g.count}`,
  }));
}

export interface MermaidBuildResult {
  text: string;
  importerGroupsShown: MermaidGroup[];
  importerGroupsTotal: number; // distinct directories, before the 8-group cap
  importerFilesTotal: number; // data.importers_total_before_cap -- the backend's own (separate) cap
  importGroupsShown: MermaidGroup[];
  importGroupsTotal: number;
  importFilesTotal: number;
}

export function buildMermaidNeighborhood(data: NeighborsResponseT): MermaidBuildResult {
  const importerGroups = groupByDirectory(data.importers);
  const importGroups = groupByDirectory(data.imports);
  const shownImporterGroups = importerGroups.slice(0, MERMAID_GROUP_CAP_PER_DIRECTION);
  const shownImportGroups = importGroups.slice(0, MERMAID_GROUP_CAP_PER_DIRECTION);

  const lines = ["graph LR", `  c0["${sanitizeLabel(data.path)}"]`];

  shownImporterGroups.forEach((g, i) => {
    const id = `i${i}`;
    lines.push(`  ${id}["${sanitizeLabel(g.label)}"]`);
    lines.push(`  ${id} --> c0`);
  });

  shownImportGroups.forEach((g, i) => {
    const id = `o${i}`;
    lines.push(`  ${id}["${sanitizeLabel(g.label)}"]`);
    lines.push(`  c0 --> ${id}`);
  });

  return {
    text: lines.join("\n"),
    importerGroupsShown: shownImporterGroups,
    importerGroupsTotal: importerGroups.length,
    importerFilesTotal: data.importers_total_before_cap,
    importGroupsShown: shownImportGroups,
    importGroupsTotal: importGroups.length,
    importFilesTotal: data.imports_total_before_cap,
  };
}

// null when nothing was truncated -- callers render no note at all rather
// than a redundant "showing 3 of 3".
export function truncationNote(shown: number, total: number, label: string): string | null {
  if (shown >= total) return null;
  return `Showing ${shown} of ${total} ${label}`;
}
