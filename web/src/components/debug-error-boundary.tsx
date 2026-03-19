import { Component, type ErrorInfo, type ReactNode } from "react";

export class DebugErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = {
    error: null as Error | null,
  };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("debug-error-boundary", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <main className="min-h-screen bg-[#050505] p-8 text-white">
          <div className="mx-auto max-w-5xl rounded-[18px] border border-rose-500/30 bg-rose-950/30 p-6">
            <div className="text-lg font-semibold">页面渲染失败</div>
            <pre className="mt-4 overflow-auto whitespace-pre-wrap text-sm text-rose-100">
              {this.state.error.stack || this.state.error.message}
            </pre>
          </div>
        </main>
      );
    }

    return this.props.children;
  }
}
