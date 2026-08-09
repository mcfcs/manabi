import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
} from "@tanstack/react-router";

import { CoursePage } from "../features/courses/CoursePage";
import { HomePage } from "../features/courses/HomePage";
import { ModuleWorkspace } from "../features/modules/ModuleWorkspace";
import { DocumentViewer } from "../features/viewer/DocumentViewer";
import { AppGate } from "./AppGate";

const rootRoute = createRootRoute({
  component: () => (
    <AppGate>
      <Outlet />
    </AppGate>
  ),
});

const homeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: HomePage,
});

const courseRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/courses/$courseId",
  component: CoursePage,
});

export type ModuleTab =
  | "overview"
  | "materials"
  | "summary"
  | "cards"
  | "quiz"
  | "notes";

const MODULE_TABS = ["overview", "materials", "summary", "cards", "quiz", "notes"];

const moduleRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/courses/$courseId/modules/$moduleId",
  component: ModuleWorkspace,
  validateSearch: (search: Record<string, unknown>): { tab: ModuleTab } => ({
    tab: (MODULE_TABS.includes(search.tab as string)
      ? search.tab
      : "overview") as ModuleTab,
  }),
});

const documentRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/documents/$documentId",
  component: DocumentViewer,
  validateSearch: (
    search: Record<string, unknown>,
  ): { page: number; highlight?: number } => ({
    page: Number(search.page) >= 1 ? Number(search.page) : 1,
    ...(Number(search.highlight) >= 1
      ? { highlight: Number(search.highlight) }
      : {}),
  }),
});

const routeTree = rootRoute.addChildren([
  homeRoute,
  courseRoute,
  moduleRoute,
  documentRoute,
]);

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
