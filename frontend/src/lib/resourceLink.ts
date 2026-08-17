export interface ResourceLinkInputT {
  kind: string;
  status: "intent" | "saved";
  title: string;
  url: string | null;
  search_query: string | null;
}

export type ResourceLinkT =
  | { action: "search"; href: string }
  | { action: "download" }
  | { action: "open"; href: string };

function searchHref(r: ResourceLinkInputT): string {
  const q = encodeURIComponent(r.search_query || "");
  return r.kind === "video"
    ? `https://www.youtube.com/results?search_query=${q}`
    : `https://www.google.com/search?q=${q}`;
}

// A resource's status decides whether it has content at all -- "intent" means
// nothing was ever chosen, so a search is the only thing to show. "saved"
// resources have real content and must never fall through to a search of
// their own title: that fallback is what let a click on an uploaded PDF
// silently become a web search for its filename, because an upload's `url`
// is null by construction (its bytes live behind an authenticated download
// endpoint instead, so it needs its own action, not the link fallback).
export function resourceLink(r: ResourceLinkInputT): ResourceLinkT {
  if (r.status !== "saved") return { action: "search", href: searchHref(r) };
  if (r.kind === "file") return { action: "download" };
  return { action: "open", href: r.url || "#" };
}
