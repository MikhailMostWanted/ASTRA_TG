import { lazy, Suspense, startTransition, useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Bot, RefreshCw } from "lucide-react";

import { AppShell } from "@/components/system/AppShell";
import { LoadingState } from "@/components/system/LoadingState";
import { Button } from "@/components/ui/button";
import { api, getApiUrl, setApiUrl } from "@/lib/api";
import { navigationItems } from "@/lib/navigation";
import { useAppStore } from "@/stores/app-store";

const DashboardScreen = lazy(() =>
  import("@/screens/DashboardScreen").then((module) => ({ default: module.DashboardScreen })),
);
const ChatsScreen = lazy(() =>
  import("@/screens/ChatsScreen").then((module) => ({ default: module.ChatsScreen })),
);
const SourcesScreen = lazy(() =>
  import("@/screens/SourcesScreen").then((module) => ({ default: module.SourcesScreen })),
);
const FullAccessScreen = lazy(() =>
  import("@/screens/FullAccessScreen").then((module) => ({ default: module.FullAccessScreen })),
);
const MemoryScreen = lazy(() =>
  import("@/screens/MemoryScreen").then((module) => ({ default: module.MemoryScreen })),
);
const DigestScreen = lazy(() =>
  import("@/screens/DigestScreen").then((module) => ({ default: module.DigestScreen })),
);
const RemindersScreen = lazy(() =>
  import("@/screens/RemindersScreen").then((module) => ({ default: module.RemindersScreen })),
);
const LogsScreen = lazy(() =>
  import("@/screens/LogsScreen").then((module) => ({ default: module.LogsScreen })),
);

type DesktopLaunchStatus = {
  apiUrl: string;
  repoRoot: string;
  configPath: string;
  logPath: string;
  status: string;
  detail: string;
  ownedBridge: boolean;
};

type BootstrapState =
  | { kind: "loading" }
  | { kind: "ready"; status: DesktopLaunchStatus }
  | { kind: "error"; message: string };

type TauriInvokeWindow = Window & {
  __TAURI_INTERNALS__?: {
    invoke: <T>(command: string, args?: Record<string, unknown>) => Promise<T>;
  };
};

async function prepareDesktopLaunch(): Promise<DesktopLaunchStatus> {
  if (typeof window !== "undefined") {
    const tauriWindow = window as TauriInvokeWindow;
    if (typeof tauriWindow.__TAURI_INTERNALS__?.invoke === "function") {
      return tauriWindow.__TAURI_INTERNALS__.invoke<DesktopLaunchStatus>("prepare_desktop_launch");
    }
  }

  return {
    apiUrl: getApiUrl(),
    repoRoot: "",
    configPath: "",
    logPath: "",
    status: "external",
    detail: "Desktop dev-режим использует уже заданный локальный API URL.",
    ownedBridge: false,
  };
}

function DesktopSplash({
  detail,
  apiUrl,
}: {
  detail: string;
  apiUrl: string;
}) {
  return (
    <div className="flex min-h-screen items-center justify-center px-6 py-10">
      <motion.div
        initial={{ opacity: 0, y: 18, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.28, ease: "easeOut" }}
        className="relative w-full max-w-[620px] overflow-hidden rounded-[32px] border border-white/10 bg-[#07111c]/90 p-8 shadow-[0_28px_90px_rgba(0,0,0,0.45)] backdrop-blur-xl"
      >
        <div className="absolute inset-x-10 top-0 h-px bg-gradient-to-r from-transparent via-cyan-300/50 to-transparent" />
        <div className="flex items-start gap-5">
          <div className="flex h-16 w-16 items-center justify-center rounded-[22px] border border-cyan-300/20 bg-cyan-300/10 shadow-[0_0_40px_rgba(76,201,255,0.18)]">
            <Bot className="h-8 w-8 text-cyan-100" />
          </div>
          <div className="space-y-2">
            <div className="inline-flex items-center rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-[11px] font-medium uppercase tracking-[0.26em] text-emerald-200/90">
              Astra Desktop
            </div>
            <h1 className="font-heading text-3xl font-semibold tracking-[-0.03em] text-white">
              Поднимаю локальный runtime
            </h1>
            <p className="max-w-[460px] text-sm leading-6 text-slate-300">
              {detail}
            </p>
          </div>
        </div>

        <div className="mt-8 space-y-4">
          <div className="h-2 overflow-hidden rounded-full bg-white/6">
            <motion.div
              className="h-full rounded-full bg-gradient-to-r from-cyan-300 via-sky-300 to-emerald-300"
              initial={{ x: "-40%", opacity: 0.5 }}
              animate={{ x: "160%", opacity: 1 }}
              transition={{ duration: 1.4, repeat: Number.POSITIVE_INFINITY, ease: "easeInOut" }}
              style={{ width: "42%" }}
            />
          </div>
          <div className="grid gap-3 rounded-[24px] border border-white/7 bg-white/[0.03] p-4 text-sm text-slate-300">
            <div className="flex items-center justify-between gap-4">
              <span className="text-slate-400">Bridge endpoint</span>
              <span className="font-mono text-xs text-slate-200">{apiUrl}</span>
            </div>
            <div className="flex items-center justify-between gap-4">
              <span className="text-slate-400">Состояние старта</span>
              <span className="rounded-full border border-cyan-300/20 bg-cyan-300/10 px-3 py-1 text-xs text-cyan-100">
                Проверяю и запускаю
              </span>
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

function DesktopLaunchError({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="flex min-h-screen items-center justify-center px-6 py-10">
      <motion.div
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.24, ease: "easeOut" }}
        className="w-full max-w-[720px] rounded-[32px] border border-rose-400/15 bg-[#0a111b]/95 p-8 shadow-[0_28px_90px_rgba(0,0,0,0.5)]"
      >
        <div className="flex items-start gap-5">
          <div className="flex h-16 w-16 items-center justify-center rounded-[22px] border border-rose-400/20 bg-rose-400/10">
            <AlertTriangle className="h-8 w-8 text-rose-200" />
          </div>
          <div className="space-y-2">
            <h1 className="font-heading text-3xl font-semibold tracking-[-0.03em] text-white">
              Desktop bridge не поднялся
            </h1>
            <p className="text-sm leading-6 text-slate-300">
              Приложение не смогло безопасно запустить локальный backend. Проверь путь к проекту,
              `.venv` и лог bridge, затем повтори запуск.
            </p>
          </div>
        </div>

        <div className="mt-6 rounded-[24px] border border-white/8 bg-white/[0.03] p-4">
          <p className="whitespace-pre-wrap font-mono text-xs leading-6 text-slate-200">{message}</p>
        </div>

        <div className="mt-6 flex flex-wrap gap-3">
          <Button onClick={onRetry} className="gap-2">
            <RefreshCw className="h-4 w-4" />
            Повторить запуск
          </Button>
        </div>
      </motion.div>
    </div>
  );
}

function AppContent() {
  const queryClient = useQueryClient();
  const activeScreen = useAppStore((state) => state.activeScreen);
  const setActiveScreen = useAppStore((state) => state.setActiveScreen);

  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 15_000,
  });

  const dashboardShellQuery = useQuery({
    queryKey: ["dashboard"],
    queryFn: api.dashboard,
    refetchInterval: 10_000,
  });

  const currentScreen = navigationItems.find((item) => item.id === activeScreen) || navigationItems[0];

  return (
    <AppShell
      activeScreen={activeScreen}
      onSelectScreen={(screen) => startTransition(() => setActiveScreen(screen))}
      title={currentScreen.label}
      description={currentScreen.description}
      health={healthQuery.data}
      repositoryRoot={dashboardShellQuery.data?.repositoryRoot}
      onRefreshAll={() => {
        queryClient.invalidateQueries();
      }}
    >
      <AnimatePresence mode="wait">
        <motion.div
          key={activeScreen}
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          transition={{ duration: 0.22, ease: "easeOut" }}
          className="h-full min-h-0"
        >
          <Suspense fallback={<LoadingState />}>
            {activeScreen === "dashboard" ? <DashboardScreen /> : null}
            {activeScreen === "chats" ? <ChatsScreen /> : null}
            {activeScreen === "sources" ? <SourcesScreen /> : null}
            {activeScreen === "fullaccess" ? <FullAccessScreen /> : null}
            {activeScreen === "memory" ? <MemoryScreen /> : null}
            {activeScreen === "digest" ? <DigestScreen /> : null}
            {activeScreen === "reminders" ? <RemindersScreen /> : null}
            {activeScreen === "logs" ? <LogsScreen /> : null}
          </Suspense>
        </motion.div>
      </AnimatePresence>
    </AppShell>
  );
}

function App() {
  const [bootstrapState, setBootstrapState] = useState<BootstrapState>({ kind: "loading" });

  useEffect(() => {
    let active = true;

    async function bootstrap() {
      setBootstrapState({ kind: "loading" });

      try {
        const status = await prepareDesktopLaunch();
        setApiUrl(status.apiUrl);
        if (!active) {
          return;
        }
        setBootstrapState({ kind: "ready", status });
      } catch (error) {
        if (!active) {
          return;
        }
        const message =
          error instanceof Error
            ? error.message
            : typeof error === "string"
              ? error
              : JSON.stringify(error, null, 2);
        setBootstrapState({ kind: "error", message });
      }
    }

    void bootstrap();

    return () => {
      active = false;
    };
  }, []);

  if (bootstrapState.kind === "loading") {
    return (
      <DesktopSplash
        detail="Проверяю bridge, launcher config и готовность локального API перед открытием интерфейса."
        apiUrl={getApiUrl()}
      />
    );
  }

  if (bootstrapState.kind === "error") {
    return <DesktopLaunchError message={bootstrapState.message} onRetry={() => window.location.reload()} />;
  }

  return <AppContent />;
}

export default App;
