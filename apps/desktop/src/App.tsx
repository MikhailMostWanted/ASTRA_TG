import { lazy, Suspense, startTransition } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { AppShell } from "@/components/system/AppShell";
import { LoadingState } from "@/components/system/LoadingState";
import { navigationItems } from "@/lib/navigation";
import { api } from "@/lib/api";
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

function App() {
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

export default App;
