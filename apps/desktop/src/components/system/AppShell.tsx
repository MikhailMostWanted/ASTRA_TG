import { useState, type ReactNode } from "react";
import { Menu } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { navigationItems } from "@/lib/navigation";
import type { HealthPayload, ScreenId } from "@/lib/types";
import { useIsMobile } from "@/hooks/use-mobile";

import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

interface AppShellProps {
  activeScreen: ScreenId;
  onSelectScreen: (screen: ScreenId) => void;
  title: string;
  description: string;
  health?: HealthPayload;
  repositoryRoot?: string;
  onRefreshAll: () => void;
  children: ReactNode;
}

export function AppShell({
  activeScreen,
  onSelectScreen,
  title,
  description,
  health,
  repositoryRoot,
  onRefreshAll,
  children,
}: AppShellProps) {
  const isMobile = useIsMobile();
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="relative h-dvh overflow-hidden px-3 py-3 sm:px-4 sm:py-4">
      <div className="pointer-events-none absolute inset-x-16 top-0 h-52 rounded-full bg-cyan-300/8 blur-3xl" />
      <div className="pointer-events-none absolute right-0 top-1/3 h-64 w-64 rounded-full bg-amber-200/6 blur-3xl" />

      <div className="relative mx-auto grid h-full max-w-[1760px] grid-cols-1 gap-4 xl:grid-cols-[292px_minmax(0,1fr)]">
        {!isMobile ? (
          <Sidebar
            items={navigationItems}
            activeScreen={activeScreen}
            onSelectScreen={onSelectScreen}
            health={health}
            repositoryRoot={repositoryRoot}
          />
        ) : null}

        <div className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden rounded-[32px] border border-white/8 bg-[rgba(5,10,19,0.78)] shadow-[0_35px_120px_rgba(2,6,17,0.65)] backdrop-blur-2xl">
          <TopBar
            title={title}
            description={description}
            health={health}
            repositoryRoot={repositoryRoot}
            onRefreshAll={onRefreshAll}
            menuTrigger={
              isMobile ? (
                <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
                  <SheetTrigger asChild>
                    <Button variant="outline" size="icon">
                      <Menu />
                    </Button>
                  </SheetTrigger>
                  <SheetContent side="left" className="border-r border-white/8 bg-[rgba(6,10,20,0.96)] p-0 text-white">
                    <SheetHeader className="sr-only">
                      <SheetTitle>Навигация Astra</SheetTitle>
                      <SheetDescription>Основные разделы desktop-приложения.</SheetDescription>
                    </SheetHeader>
                    <div className="h-full p-3">
                      <Sidebar
                        items={navigationItems}
                        activeScreen={activeScreen}
                        onSelectScreen={onSelectScreen}
                        health={health}
                        repositoryRoot={repositoryRoot}
                        onClose={() => setMobileOpen(false)}
                      />
                    </div>
                  </SheetContent>
                </Sheet>
              ) : null
            }
          />
          <main className="min-h-0 overflow-hidden px-4 pb-4 sm:px-5 sm:pb-5">{children}</main>
        </div>
      </div>
    </div>
  );
}
