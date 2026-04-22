import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";

import { TooltipProvider } from "@/components/ui/tooltip";
import App from "./App";
import "./styles.css";

document.documentElement.classList.add("dark");

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <App />
        <Toaster
          theme="dark"
          richColors
          position="top-right"
          toastOptions={{
            className: "border border-white/8 bg-[#09101b] text-slate-100",
          }}
        />
      </TooltipProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
