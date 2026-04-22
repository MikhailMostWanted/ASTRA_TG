import { Component, Fragment, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, Eraser, LayoutDashboard, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";

interface ScreenErrorBoundaryProps {
  screenId: string;
  screenLabel: string;
  onRetry: () => void;
  onGoDashboard: () => void;
  onResetState: () => void;
  children: ReactNode;
}

interface ScreenErrorBoundaryState {
  error: Error | null;
  attempt: number;
}

export class ScreenErrorBoundary extends Component<
  ScreenErrorBoundaryProps,
  ScreenErrorBoundaryState
> {
  state: ScreenErrorBoundaryState = {
    error: null,
    attempt: 0,
  };

  static getDerivedStateFromError(error: Error): Partial<ScreenErrorBoundaryState> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("desktop.screen_render_failed", {
      screenId: this.props.screenId,
      screenLabel: this.props.screenLabel,
      message: error.message,
      stack: error.stack,
      componentStack: info.componentStack,
    });
  }

  private clearError = () => {
    this.setState((state) => ({
      error: null,
      attempt: state.attempt + 1,
    }));
  };

  private handleRetry = () => {
    this.clearError();
    this.props.onRetry();
  };

  private handleGoDashboard = () => {
    this.clearError();
    this.props.onGoDashboard();
  };

  private handleResetState = () => {
    this.clearError();
    this.props.onResetState();
  };

  render() {
    if (this.state.error) {
      return (
        <div className="flex h-full min-h-0 items-center justify-center px-2 py-2">
          <div className="w-full max-w-[860px] rounded-[28px] border border-rose-400/12 bg-rose-400/6 p-6 shadow-[0_24px_80px_rgba(2,6,17,0.35)]">
            <div className="flex items-start gap-4">
              <div className="flex size-14 shrink-0 items-center justify-center rounded-[18px] border border-rose-300/18 bg-rose-400/10 text-rose-100">
                <AlertTriangle className="size-6" />
              </div>

              <div className="min-w-0 flex-1">
                <div className="text-xs uppercase tracking-[0.24em] text-rose-200/70">Screen fallback</div>
                <div className="mt-1 text-2xl font-semibold tracking-tight text-white">
                  Экран «{this.props.screenLabel}» упал
                </div>
                <div className="mt-3 max-w-2xl text-sm leading-6 text-rose-50/80">
                  Во время рендера произошла ошибка. Shell и навигация остаются живыми, поэтому экран можно
                  перезапустить, вернуться на обзор или сбросить локальное desktop-состояние.
                </div>

                <div className="mt-5 rounded-[20px] border border-white/8 bg-[#070d17]/70 px-4 py-4">
                  <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Что произошло</div>
                  <div className="mt-2 text-sm leading-6 text-slate-100">
                    {this.state.error.message || "React screen render crash без дополнительного текста."}
                  </div>
                  <div className="mt-2 text-xs text-slate-500">screen id: {this.props.screenId}</div>
                </div>

                <div className="mt-5 flex flex-wrap gap-3">
                  <Button onClick={this.handleRetry}>
                    <RotateCcw data-icon="inline-start" />
                    Повторить
                  </Button>
                  <Button variant="outline" onClick={this.handleGoDashboard}>
                    <LayoutDashboard data-icon="inline-start" />
                    Вернуться на Обзор
                  </Button>
                  <Button variant="outline" onClick={this.handleResetState}>
                    <Eraser data-icon="inline-start" />
                    Сбросить локальное desktop-состояние
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      );
    }

    return <Fragment key={this.state.attempt}>{this.props.children}</Fragment>;
  }
}
