import "@fontsource-variable/fraunces";
import "@fontsource-variable/jetbrains-mono";
import "@fontsource-variable/public-sans";
import "@fontsource-variable/source-serif-4";
import "./styles/global.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { registerSW } from "virtual:pwa-register";

import { router } from "./app/router";

// Update flow: never auto-reload (could interrupt note editing) — surface a
// toast; reload only on click.
const updateSW = registerSW({
  onNeedRefresh() {
    window.dispatchEvent(new CustomEvent("manabi-sw-update"));
  },
});
(window as unknown as { manabiUpdateSW?: () => void }).manabiUpdateSW = () =>
  updateSW(true);

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 10_000 } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
