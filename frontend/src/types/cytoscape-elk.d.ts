// cytoscape-elk ships no type declarations of its own (no `types` field,
// no bundled .d.ts -- verified in node_modules/cytoscape-elk/package.json),
// and there is no @types/cytoscape-elk on the registry. This is the
// minimal declaration for the only thing this project uses: the default
// export, which is a Cytoscape extension registration function.
//
// Deliberately NOT declared as `any` for the whole module -- that would
// silence real mistakes at the one call site that matters
// (cytoscape.use(elk)). Typing it as the extension shape cytoscape.use()
// already expects means a wrong import still fails to compile.
//
// cytoscape itself DOES ship its own types (cytoscape/index.d.ts), so
// @types/cytoscape is deliberately not installed -- it would be a
// redundant second, independently-versioned copy of the same definitions.
declare module "cytoscape-elk" {
  import type { Ext } from "cytoscape";
  const elk: Ext;
  export default elk;
}
