import { describe, expect, it } from "vitest";

import { ApiError } from "./api";
import { ContextEnvelopeT, fileIdFromParams, loadContext } from "./contextLoad";

// Injected async dep, the elkLayoutRun.test.ts pattern: the branching is the
// unit under test, so the network is replaced by a promise the test controls.
const ok = { file_id: 2256, path: "superset/models/core.py" } as unknown as ContextEnvelopeT;
const deps = (impl: () => Promise<ContextEnvelopeT>) => ({ fetchContext: impl });

describe("loadContext discriminates the states D10 requires", () => {
  it("no selection is `idle`, and does not call the network at all", async () => {
    let called = false;
    const s = await loadContext("6", null, deps(async () => { called = true; return ok; }));
    expect(s.status).toBe("idle");
    expect(called).toBe(false);
  });

  it("a successful load is `ready` and carries the envelope", async () => {
    const s = await loadContext("6", 2256, deps(async () => ok));
    expect(s).toEqual({ status: "ready", data: ok });
  });

  it("404 is `notFound` -- the id is wrong, re-ingesting will not help", async () => {
    const s = await loadContext("6", 999, deps(async () => {
      throw new ApiError("File not found in this repo", 404);
    }));
    expect(s.status).toBe("notFound");
  });

  it("409 is `notInSnapshot` -- the id is right and the graph is behind", async () => {
    const s = await loadContext("6", 2256, deps(async () => {
      throw new ApiError("'x' is not a file in repo 6", 409);
    }));
    expect(s.status).toBe("notInSnapshot");
  });

  it("LOADBEARING: 404 and 409 do NOT collapse into one state", async () => {
    // The single assertion this whole extraction exists for. The shape D10
    // rejects (`.catch(() => setNull)`) makes these two identical, and a user
    // told "re-ingest" when their link is stale is worse off than one told
    // nothing.
    const a = await loadContext("6", 1, deps(async () => { throw new ApiError("a", 404); }));
    const b = await loadContext("6", 1, deps(async () => { throw new ApiError("b", 409); }));
    expect(a.status).not.toBe(b.status);
  });

  it("a 500 is surfaced as `error`, not folded into a missing-file state", async () => {
    const s = await loadContext("6", 1, deps(async () => { throw new ApiError("boom", 500); }));
    expect(s.status).toBe("error");
  });

  it("a non-ApiError rejection (network down) is still `error`, never `ready`", async () => {
    const s = await loadContext("6", 1, deps(async () => { throw new TypeError("Failed to fetch"); }));
    expect(s.status).toBe("error");
    expect(s.status).not.toBe("notFound");
  });
});

describe("fileIdFromParams", () => {
  const f = (q: string) => fileIdFromParams(new URLSearchParams(q));
  it("reads an integer id", () => expect(f("fileId=2256")).toBe(2256));
  it("absent is null", () => expect(f("view=context")).toBeNull());
  it("empty is null", () => expect(f("fileId=")).toBeNull());
  it("REJECTS a non-integer rather than emitting NaN into a URL", () => {
    // A hand-edited `?fileId=abc` must not become `/files/NaN/context`.
    expect(f("fileId=abc")).toBeNull();
    expect(f("fileId=1.5")).toBeNull();
    expect(f("fileId=-3")).toBeNull();
  });
  it("rejects a path, which is what D9 decided the URL does NOT carry", () => {
    expect(f("fileId=superset/models/core.py")).toBeNull();
  });
});
