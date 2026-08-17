// This project has no other `?url` import and does not otherwise reference
// vite/client's ambient types, so TypeScript has no declaration for the
// suffix at all. Scoped to exactly the one file this project loads this way
// (elkjs's worker script, which must be a URL Vite serves/bundles, not a
// module to evaluate on the main thread -- see elkWorkerLayout.ts) rather
// than declaring `*?url` generally, which would silence a typo in any future
// import the same way `declare module "*"` would.
declare module "elkjs/lib/elk-worker.min.js?url" {
  const url: string;
  export default url;
}
