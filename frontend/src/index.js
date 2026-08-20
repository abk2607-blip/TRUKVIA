import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { Toaster } from "sonner";
import "@/index.css";
import App from "@/App";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      // Iter71/77/96 — Backend hot-reload / brief restarts can hand out a
      // 404/502/503 for up to ~40 seconds when the reloader is compiling a
      // change plus running startup tasks (index-ensure, fixture-purge,
      // Iter49 null-coerce backfill, scheduler init).
      // Retry up to 10 times with exponential backoff:
      //   0.75s → 1.5s → 3s → 6s → 8s → 8s → 8s → 8s → 8s → 8s   (~65s total)
      // so users never see "DASHBOARD DATA COULDN'T LOAD" for a routine
      // hot-reload. Real client errors (400/401/403/422) are never retried.
      retry: (failureCount, error) => {
        if (failureCount >= 10) return false;
        const status = error?.response?.status;
        if (status && [400, 401, 403, 422].includes(status)) return false;
        return true;
      },
      retryDelay: (attempt) => Math.min(750 * 2 ** attempt, 8000),
    },
  },
});

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <QueryClientProvider client={queryClient}>
    <BrowserRouter>
      <App />
      <Toaster richColors position="top-right" />
    </BrowserRouter>
  </QueryClientProvider>
);
