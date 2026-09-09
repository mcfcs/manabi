import "@fontsource-variable/fraunces";
import "@fontsource-variable/jetbrains-mono";
import "@fontsource-variable/public-sans";
import "@fontsource-variable/source-serif-4";
import "./styles/global.css";

import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { registerSW } from "virtual:pwa-register";

import { router } from "./app/router";
import { ApiError } from "./lib/api";

// Update flow: never auto-reload (could interrupt note editing) — surface a
// toast; reload only on click.
const updateSW = registerSW({
  onNeedRefresh() {
    window.dispatchEvent(new CustomEvent("manabi-sw-update"));
  },
});
(window as unknown as { manabiUpdateSW?: () => void }).manabiUpdateSW = () =>
  updateSW(true);

/** A failed write used to be completely silent: 119 of the app's 141 mutations
 * have no onError, so saving a note or renaming a course could fail and look
 * exactly like success. Report centrally instead of touching every call site.
 *
 * Two deliberate exemptions:
 *  - a mutation that defines its own onError is already handling it;
 *  - a 409 carrying `requires_confirmation` is a prompt, not a failure (it is
 *    how delete asks "this has 12 documents, are you sure?").
 */
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 10_000 } },
  mutationCache: new MutationCache({
    onError: (error, _vars, _ctx, mutation) => {
      if (mutation.options.onError) return;
      const detail = (error as ApiError).detail as { requires_confirmation?: boolean } | undefined;
      if (detail?.requires_confirmation) return;
      window.dispatchEvent(
        new CustomEvent("manabi-error", { detail: error.message || "Something went wrong" }),
      );
    },
  }),
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
