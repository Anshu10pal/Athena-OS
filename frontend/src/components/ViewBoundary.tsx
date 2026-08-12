import { Component, ErrorInfo, ReactNode } from "react";

// A React error boundary per view.
//
// The app had none anywhere. Any throw during render propagated to the root
// and unmounted the entire tree -- nav, tabs, everything -- leaving a white
// page with no information. That was a reported symptom on a 6,516-file repo
// and could not be reproduced in 256 automated tab switches, which is exactly
// the case a boundary exists for: the next occurrence produces a component
// name and a stack instead of another hunt.
//
// The justification was never "this fixes the reported bug". It is that the
// Reading list renders 701,507 characters of unvirtualised DOM for that repo,
// nothing in the app catches anything, and a white page is the worst available
// failure mode.
//
// Class component because React error boundaries have no hooks equivalent --
// getDerivedStateFromError and componentDidCatch exist only on classes.

type Props = {
  /** Shown to the reader and prefixed onto the console log so it is greppable. */
  name: string;
  /**
   * Escape hatch to render when this boundary replaces a whole page.
   *
   * The route-level boundary substitutes for RepoDetail entirely, and
   * RepoDetail is where "back to repos" lives -- so without this the reader
   * keeps the app nav but loses the only way back to the repo list from the
   * failing page. Verified: a canary throw in RepoDetail's `visible` memo left
   * the nav mounted and the back link gone.
   */
  backTo?: { href: string; label: string };
  children: ReactNode;
};

type State = {
  error: Error | null;
  info: ErrorInfo | null;
};

export class ViewBoundary extends Component<Props, State> {
  state: State = { error: null, info: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    this.setState({ info });
    // Prefixed with the view name so a user can paste one greppable line, and
    // logged as a group so the component stack is not lost in a wall of text.
    // eslint-disable-next-line no-console
    console.error(
      `[ViewBoundary:${this.props.name}] ${error.name}: ${error.message}`,
      "\ncomponent stack:", info.componentStack,
      "\nerror stack:", error.stack,
    );
  }

  private reset = () => this.setState({ error: null, info: null });

  render() {
    const { error, info } = this.state;
    if (!error) return this.props.children;

    // The first frame of the component stack is the component that threw --
    // more useful than the boundary's own name, which is only the view.
    const culprit = (info?.componentStack || "")
      .split("\n")
      .map((l) => l.trim())
      .find((l) => l.startsWith("at "))
      ?.replace(/^at\s+/, "")
      .split(" ")[0];

    return (
      <section className="card p-5 space-y-3 border-danger/40" role="alert">
        <div className="flex items-baseline justify-between gap-3 flex-wrap">
          <h3 className="font-display text-lg text-danger">
            {this.props.name} could not render
          </h3>
          <div className="flex items-baseline gap-4">
            {this.props.backTo && (
              <a
                href={this.props.backTo.href}
                className="font-mono text-[10px] uppercase tracking-widest text-fog hover:text-accent transition-colors"
              >
                ← {this.props.backTo.label}
              </a>
            )}
            <button
              onClick={this.reset}
              className="font-mono text-[10px] uppercase tracking-widest text-fog hover:text-accent transition-colors"
            >
              try again
            </button>
          </div>
        </div>

        <p className="font-mono text-[11px] text-snow/85 break-all">
          {error.name}: {error.message}
        </p>

        {culprit && (
          <p className="font-mono text-[10px] text-fog">
            thrown in <span className="text-snow/80">{culprit}</span>
          </p>
        )}

        <p className="font-mono text-[10px] text-fog/70 leading-relaxed">
          The rest of the page is unaffected — other tabs still work. The full
          stack is in the browser console, prefixed{" "}
          <span className="text-snow/80">[ViewBoundary:{this.props.name}]</span>.
        </p>
      </section>
    );
  }
}
