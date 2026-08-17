import { describe, expect, it } from "vitest";
import { resourceLink, ResourceLinkInputT } from "./resourceLink";

function resource(over: Partial<ResourceLinkInputT> = {}): ResourceLinkInputT {
  return {
    kind: "article",
    status: "saved",
    title: "Some Title",
    url: "https://example.com/a",
    search_query: "some title",
    ...over,
  };
}

describe("resourceLink", () => {
  it("LOADBEARING: an uploaded file downloads rather than opening a url", () => {
    // A file's `url` is null by construction -- its bytes are behind an
    // authenticated endpoint, not a link. Before this fix, null `url` here
    // fell through to a search-of-the-filename instead.
    const r = resourceLink(resource({ kind: "file", url: null }));
    expect(r.action).toBe("download");
  });

  it("LOADBEARING: an intent resource always searches, regardless of kind", () => {
    const r = resourceLink(resource({ status: "intent", kind: "file", url: null }));
    expect(r).toEqual({ action: "search", href: expect.stringContaining("google.com") });
  });

  it("an intent video resource searches YouTube", () => {
    const r = resourceLink(resource({ status: "intent", kind: "video" }));
    expect(r.action).toBe("search");
    if (r.action === "search") expect(r.href).toContain("youtube.com");
  });

  it("a saved link resource opens its own url", () => {
    const r = resourceLink(resource({ kind: "article", url: "https://example.com/x" }));
    expect(r).toEqual({ action: "open", href: "https://example.com/x" });
  });

  it("never returns a search action for a saved resource", () => {
    for (const kind of ["article", "video", "doc", "file"]) {
      expect(resourceLink(resource({ kind, url: "https://example.com" })).action).not.toBe("search");
    }
  });
});
