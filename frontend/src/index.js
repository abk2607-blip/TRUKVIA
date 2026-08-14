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
      // Iter71 — Backend hot-reload / brief restarts can hand out a 404/502/503
      // for a couple of seconds. Retry up to 3 times with exponential backoff
      // (0.5s → 1s → 2s) so the UI recovers automatically instead of showing
      // "DASHBOARD DATA COULDN'T LOAD".
      retry: (failureCount, error) => {
        if (failureCount >= 3) return false;
        const status = error?.response?.status;
        // Never retry on real client errors (auth, validation, forbidden)
        if (status && [400, 401, 403, 422].includes(status)) return false;
        return true;
      },
      retryDelay: (attempt) => Math.min(500 * 2 ** attempt, 4000),
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
