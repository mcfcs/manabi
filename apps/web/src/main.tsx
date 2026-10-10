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

// Update flow. A waiting version is applied by itself whenever a reload
// can't interrupt anything: right after the app opens (before the first tap
// or key) and when the app goes to the background. The toast is only for an
// update that lands mid-session. Before, an update waited for the toast's
// button, so reloading or reopening the app showed the same prompt again —
// on every device and window separately.
const OPEN_GRACE_MS = 6000;
const BACKGROUND_DELAY_MS = 1500; // lets notes flush their pending save first
let interacted = false;
let pending = false;
for (const evt of ["pointerdown", "keydown"]) {
  window.addEventListener(evt, () => (interacted = true), { once: true, capture: true });
}
const updateSW = registerSW({
  onNeedRefresh() {
    pending = true;
    if (!interacted && performance.now() < OPEN_GRACE_MS) {
      void updateSW(true); // just opened: nothing to lose
      return;
    }
    window.dispatchEvent(new CustomEvent("manabi-sw-update"));
  },
  onRegisteredSW(_url, registration) {
    // Notice new versions on a long-lived tab too, not only on load.
    if (registration) setInterval(() => void registration.update(), 60 * 60 * 1000);
  },
});
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "hidden" || !pending) return;
  window.setTimeout(() => {
    if (document.visibilityState === "hidden") void updateSW(true);
  }, BACKGROUND_DELAY_MS);
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
