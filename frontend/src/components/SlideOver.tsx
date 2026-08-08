import { ReactNode, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { NAV_H } from "../lib/layout";

// Phase G3/G4: extracted once a second panel (Mermaid export, G4) needed
// the exact same open/close mechanics the glossary panel already had --
// three exit paths (Escape, outside click, close button) that must all do
// the same two things (close, return focus) is a shape that wants one
// function, not two copies that can drift.
//
// Closes on Escape, on a click outside the panel, and on the explicit
// close button; focus moves to the close button on open and back to
// whatever triggered it on every close path alike.
//
// Rendered via createPortal directly into document.body, not inline in
// the caller's tree -- found necessary live: RepoDetail's root container
// uses `space-y-6`, which sets `margin-top: 24px` on any later sibling.
// For a `position: fixed` box with BOTH `top` and `bottom` set (this
// panel's `inset-0`), CSS does NOT discard a non-auto margin in that
// over-constrained case -- it adds to the offset, so the panel rendered
// 24px below the true top of the viewport with its header clipped. A
// portal escapes the parent's layout context entirely, which is also
// just the right architecture for a fixed overlay regardless of which
// specific ancestor style would have collided with it next.
export function SlideOver({
  open, onClose, triggerRef, title, children,
}: {
  open: boolean;
  onClose: () => void;
  // HTMLElement, not HTMLButtonElement -- the Glossary and Mermaid panels
  // are triggered by real buttons, but the interactive graph's node-detail
  // panel (G4 sub-checkpoint 2) is triggered by a canvas click above the
  // 200-node threshold, which has no per-node DOM element to focus. That
  // caller passes a ref to the graph's own (focusable) container instead.
  triggerRef: React.RefObject<HTMLElement>;
  title: string;
  children: ReactNode;
}) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  const close = () => {
    onClose();
    triggerRef.current?.focus();
  };

  useEffect(() => {
    if (!open) return;
    closeButtonRef.current?.focus();
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      // stopPropagation is load-bearing, not defensive: App.tsx has a
      // global EscToHub handler on `window` that navigates to "/" on
      // Escape whenever focus isn't in an input/textarea -- found live,
      // by pressing Escape in a real browser, not by code review. Without
      // this, closing a panel via Escape also navigated away from the
      // whole page. Capture phase + stopPropagation here wins regardless
      // of what else is listening, rather than relying on DOM-depth
      // ordering between a document listener and a window listener.
      e.stopPropagation();
      close();
    };
    document.addEventListener("keydown", onKeyDown, { capture: true });
    return () => document.removeEventListener("keydown", onKeyDown, { capture: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (!open) return null;

  return createPortal(
    // The backdrop still covers the full viewport (dimming the top nav
    // too is fine, expected even) -- only the panel itself is clipped to
    // start below it. `.chrome` (the fixed top nav, index.css) is
    // z-index 60, above this panel's z-40 on purpose: this is a side
    // panel meant to keep the rest of the app usable, not a full modal,
    // so the nav stays visible and interactive while it's open. NAV_H is
    // the same constant Layout.tsx itself uses to reserve this space --
    // not a second, independently-hardcoded copy of "58".
    <div className="fixed inset-0 z-40">
      <div className="absolute inset-0 bg-ink/70" onClick={close} aria-hidden="true" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        style={{ top: NAV_H }}
        className="absolute right-0 bottom-0 w-full max-w-sm bg-ink border-l border-line p-6 overflow-y-auto shadow-2xl"
      >
        <div className="flex items-start justify-between gap-3 mb-5">
          <h3 className="font-display text-lg font-semibold text-snow break-all min-w-0">{title}</h3>
          <button
            ref={closeButtonRef}
            onClick={close}
            aria-label={`Close ${title}`}
            className="font-mono text-xs text-fog hover:text-snow border border-line rounded px-2 py-1 shrink-0"
          >
            ✕ close
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
