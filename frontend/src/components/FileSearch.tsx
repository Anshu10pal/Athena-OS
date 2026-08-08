import { useEffect, useRef, useState } from "react";

interface SearchableFile {
  file_id: number;
  path: string;
}

const MAX_RESULTS = 12;

// Phase H5: substring match, exactly per the reference mockup -- fuzzy
// scoring or a command palette is explicitly out of scope ("the mockup
// version is enough"). "/" focuses the box (skipped while already typing
// in another field), Escape blurs and closes, arrow keys move a
// highlighted result, Enter selects it.
export function FileSearch({
  files, onSelectFile,
}: {
  files: SearchableFile[];
  onSelectFile: (fileId: number) => void;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const matches = query.trim().length >= 1
    ? files.filter((f) => f.path.toLowerCase().includes(query.trim().toLowerCase())).slice(0, MAX_RESULTS)
    : [];

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  useEffect(() => {
    function onGlobalKeyDown(e: KeyboardEvent) {
      if (e.key === "/" && document.activeElement !== inputRef.current) {
        const tag = (document.activeElement?.tagName ?? "").toLowerCase();
        if (tag === "input" || tag === "textarea") return; // don't steal "/" from another field
        e.preventDefault();
        inputRef.current?.focus();
      }
    }
    document.addEventListener("keydown", onGlobalKeyDown);
    return () => document.removeEventListener("keydown", onGlobalKeyDown);
  }, []);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, []);

  function select(fileId: number) {
    onSelectFile(fileId);
    setOpen(false);
    setQuery("");
    inputRef.current?.blur();
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      setOpen(false);
      inputRef.current?.blur();
      return;
    }
    if (!open || matches.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, matches.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      select(matches[activeIndex].file_id);
    }
  }

  return (
    <div ref={containerRef} className="relative w-72">
      <input
        ref={inputRef}
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        placeholder="Search files…   /"
        autoComplete="off"
        className="w-full bg-transparent border border-line rounded px-3 py-1.5 text-snow text-xs font-mono"
      />
      {open && matches.length > 0 && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-ink border border-line rounded z-30 max-h-64 overflow-y-auto">
          {matches.map((f, i) => (
            <button
              key={f.file_id}
              onMouseEnter={() => setActiveIndex(i)}
              onClick={() => select(f.file_id)}
              className={
                "block w-full text-left px-3 py-1.5 font-mono text-[11px] border-b border-line last:border-b-0 " +
                (i === activeIndex ? "bg-glass text-snow" : "text-fog")
              }
            >
              {f.path}
            </button>
          ))}
        </div>
      )}
      {open && query.trim().length >= 1 && matches.length === 0 && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-ink border border-line rounded z-30 px-3 py-1.5 font-mono text-[11px] text-fog">
          No match
        </div>
      )}
    </div>
  );
}
