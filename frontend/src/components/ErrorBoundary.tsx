import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * A render error anywhere below here unmounts React's whole tree, and what the
 * user sees is an empty page with nothing to act on — the worst failure mode
 * during a live demo, and the hardest one to diagnose after the fact.
 *
 * This turns that into a legible panel that names the failing component and
 * carries the stack, so the next crash is reported rather than guessed at. It
 * deliberately does not swallow the error: it is re-thrown to the console for
 * DevTools, and the panel stays until the reader reloads.
 */

interface State {
  error: Error | null;
  componentStack: string | null;
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null, componentStack: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    this.setState({ componentStack: info.componentStack ?? null });
    // Keep the original in the console, with its stack intact.
    console.error("Unhandled render error", error, info.componentStack);
  }

  render() {
    const { error, componentStack } = this.state;
    if (!error) return this.props.children;

    return (
      <section
        role="alert"
        className="border border-alert/35 bg-alert-wash p-4"
        aria-label="Application error"
      >
        <div className="text-[10px] font-semibold tracking-[0.12em] text-alert">
          RENDER FAILED
        </div>
        <p className="mt-1 font-sans text-[14px] text-ink">{error.message}</p>
        <p className="mt-1 font-sans text-[12px] leading-relaxed text-ink-mid">
          This screen stopped rendering. The details below identify the
          component that failed.
        </p>

        <details className="group mt-3 border-t border-rule pt-2">
          <summary className="inline-flex items-center gap-1.5 text-[11px] text-ink-mid hover:text-ink">
            <span className="transition-transform group-open:rotate-90">▸</span>
            Error detail
          </summary>
          <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-[11px] leading-relaxed text-ink-mid">
            {error.stack ?? String(error)}
            {componentStack}
          </pre>
        </details>

        <button
          type="button"
          onClick={() => window.location.reload()}
          className="mt-3 border border-ink bg-ink px-3 py-1.5 text-[12px] font-medium text-paper hover:bg-ink/90"
        >
          Reload
        </button>
      </section>
    );
  }
}
