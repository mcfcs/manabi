import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "prompt",
      manifest: false, // hand-authored public/manifest.webmanifest
      workbox: {
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api/],
        maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
        runtimeCaching: [
          {
            // reads stay available offline; short-lived so fresh data wins
            urlPattern: ({ url, request }) =>
              request.method === "GET" &&
              /^\/api\/(courses|modules|documents\/\d+$|artifacts|quizzes|chat)/.test(
                url.pathname,
              ),
            handler: "NetworkFirst",
            options: {
              cacheName: "manabi-api",
              networkTimeoutSeconds: 4,
              expiration: { maxEntries: 200, maxAgeSeconds: 7 * 24 * 3600 },
            },
          },
          {
            urlPattern: ({ url, request }) =>
              request.method === "GET" &&
              /\/api\/documents\/\d+\/pages\/\d+\/(render|thumb)$/.test(url.pathname),
            handler: "CacheFirst",
            options: {
              cacheName: "manabi-renders",
              expiration: { maxEntries: 300, maxAgeSeconds: 30 * 24 * 3600 },
            },
          },
        ],
      },
    }),
  ],
  server: {
    proxy: {
      "/api": "http://localhost:56690",
    },
  },
});
