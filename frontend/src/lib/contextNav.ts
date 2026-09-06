/** Phase 8 checkpoint 3b-3 -- the D14 path fingerprint, and navigation.
 *
 *  WHY A FINGERPRINT EXISTS AT ALL (D14, and D9's corrected open item).
 *  The URL carries an integer `fileId`, and `code_files.id` is NOT stable
 *  across re-ingest. A reassigned id does not 404 -- ck2 proved the 409 branch
 *  is unreachable, because every code_files row is a graph node. It renders a
 *  DIFFERENT file's neighbourhood: correctly computed, plausible, and with no
 *  error anywhere. That is §17.25 exactly, and it is the failure this file
 *  exists to make impossible.
 *
 *  The fingerprint is NOT security and NOT collision-proof. It is a tripwire
 *  against silent substitution, and its only job is to be wrong when the id
 *  points somewhere else.
 */

/** A short, stable, non-cryptographic hash of a repo-relative path.
 *
 *  FNV-1a, 32-bit, base36. Chosen because it must produce the SAME string in a
 *  browser and in a node test with no dependency and no async API --
 *  `crypto.subtle.digest` is async and Promise-returning, which would push the
 *  comparison into an effect and make the mismatch state race the render.
 *
 *  Six chars. A collision means a stale link renders the wrong file silently,
 *  which is what this prevents -- so the tradeoff is stated rather than
 *  implied: ~2^30 space, and the population is the files of one repo (6,584 for
 *  Superset). Birthday collision probability at that size is ~1 in 50,000. Not
 *  zero, and not the right tool if it ever needs to be.
 */
export function fingerprintPath(path: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < path.length; i++) {
    h ^= path.charCodeAt(i);
    // 16777619, via shifts: Math.imul keeps this in int32 in every engine.
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return (h >>> 0).toString(36).padStart(6, "0").slice(-6);
}

export type FingerprintVerdictT =
  /** No `fp` in the URL. Old links and hand-typed ones still work -- absence is
   *  not evidence of a mismatch, and refusing to render would break every link
   *  made before this checkpoint. */
  | { status: "unverified" }
  | { status: "match" }
  | { status: "mismatch"; expected: string; actual: string; actualPath: string };

export function verifyFingerprint(
  urlFp: string | null, returnedPath: string,
): FingerprintVerdictT {
  if (urlFp === null || urlFp === "") return { status: "unverified" };
  const actual = fingerprintPath(returnedPath);
  if (actual === urlFp) return { status: "match" };
  return { status: "mismatch", expected: urlFp, actual, actualPath: returnedPath };
}

/** The canonical query string for a file. One builder, so a link made by a node
 *  click and one made by the empty state cannot disagree about the format. */
export function contextParams(fileId: number, path: string): URLSearchParams {
  const p = new URLSearchParams();
  p.set("view", "context");
  p.set("fileId", String(fileId));
  p.set("fp", fingerprintPath(path));
  return p;
}

/** What a click on a graph node means.
 *
 *  DECISION (3b-3): a SINGLE-FILE node navigates. A COLLAPSED GROUP does NOT
 *  navigate -- it has no single target -- and it does NOT silently do nothing
 *  either. It DRILLS IN: the group's files are listed below the graph as
 *  navigable links.
 *
 *  Expanding the group inside the graph was the alternative and was rejected:
 *  `unit_tests` holds 76 files, and re-laying-out 76 nodes into a container
 *  sized for ~20 reintroduces exactly the legibility defect §17.37 was promoted
 *  for. A list is readable at any count.
 */
export type NodeActionT =
  | { kind: "navigate"; fileId: number; path: string }
  | { kind: "drill"; groupKey: string; fileIds: number[] }
  | { kind: "none"; reason: string };

export interface ClickTargetT {
  kind: string;
  fileIds: number[];
  groupKey: string;
  paths: string[];
}

export function actionForNode(target: ClickTargetT): NodeActionT {
  if (target.kind === "centre") {
    // Already here. Saying so beats a no-op that reads as a broken click.
    return { kind: "none", reason: "This is the file you are looking at." };
  }
  if (target.fileIds.length === 1 && target.paths.length === 1) {
    return { kind: "navigate", fileId: target.fileIds[0], path: target.paths[0] };
  }
  return { kind: "drill", groupKey: target.groupKey, fileIds: target.fileIds };
}
