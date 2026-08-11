/// <reference lib="webworker" />
/* Hand-authored service worker (injectManifest strategy): precache + the two
 * runtime caching rules that generateSW used to emit, PLUS Web Push handlers
 * (the reason we switched strategies). */
declare let self: ServiceWorkerGlobalScope & {
  __WB_MANIFEST: Parameters<typeof precacheAndRoute>[0];
};

import { clientsClaim } from "workbox-core";
import { ExpirationPlugin } from "workbox-expiration";
import { cleanupOutdatedCaches, createHandlerBoundToURL, precacheAndRoute } from "workbox-precaching";
import { NavigationRoute, registerRoute } from "workbox-routing";
import { NetworkFirst } from "workbox-strategies";

precacheAndRoute(self.__WB_MANIFEST);
cleanupOutdatedCaches();
clientsClaim();

// registerType "prompt" contract: workbox-window sends SKIP_WAITING when the
// user clicks Reload in the UpdateToast — without this listener that button
// silently does nothing.
self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") self.skipWaiting();
});

// SPA navigation fallback — never intercept API calls
registerRoute(
  new NavigationRoute(createHandlerBoundToURL("/index.html"), {
    denylist: [/^\/api/],
  }),
);

// Reads stay available offline; short-lived so fresh data wins
registerRoute(
  ({ url, request }) =>
    request.method === "GET" &&
    /^\/api\/(courses|modules|documents\/\d+$|artifacts|quizzes|chat|schedule|calendar|tasks)/.test(
      url.pathname,
    ),
  new NetworkFirst({
    cacheName: "manabi-api",
    networkTimeoutSeconds: 4,
    plugins: [new ExpirationPlugin({ maxEntries: 200, maxAgeSeconds: 7 * 24 * 3600 })],
  }),
);

// Page renders/thumbs live at a STABLE url but their bytes change on
// re-extraction / re-split (e.g. the rotation fix). CacheFirst served the old
// image for 30 days — the "it still rotated" bug. NetworkFirst revalidates
// against the server (cheap 304 via the endpoint's ETag) so a re-extracted page
// is never stale, and still falls back to cache when offline.
registerRoute(
  ({ url, request }) =>
    request.method === "GET" &&
    /\/api\/documents\/\d+\/pages\/\d+\/(render|thumb)$/.test(url.pathname),
  new NetworkFirst({
    cacheName: "manabi-renders",
    networkTimeoutSeconds: 5,
    plugins: [new ExpirationPlugin({ maxEntries: 300, maxAgeSeconds: 30 * 24 * 3600 })],
  }),
);

// ── Web Push ──────────────────────────────────────────────────────────────

interface PushPayload {
  title?: string;
  body?: string;
  tag?: string;
  url?: string;
}

self.addEventListener("push", (event) => {
  let data: PushPayload = {};
  try {
    data = event.data?.json() ?? {};
  } catch {
    data = { body: event.data?.text() };
  }
  event.waitUntil(
    self.registration.showNotification(data.title ?? "Manabi", {
      body: data.body,
      tag: data.tag,
      icon: "/icon-192.png",
      badge: "/icon-192.png",
      data: { url: data.url ?? "/tasks" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url: string = event.notification.data?.url ?? "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(
      async (clients) => {
        const existing = clients[0];
        if (existing) {
          await existing.focus();
          if ("navigate" in existing) await existing.navigate(url);
        } else {
          await self.clients.openWindow(url);
        }
      },
    ),
  );
});
