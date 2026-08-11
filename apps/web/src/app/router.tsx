import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
} from "@tanstack/react-router";

import { AssistantPage } from "../features/assistant/AssistantPage";
import { CalendarPage } from "../features/calendar/CalendarPage";
import { CoursePage } from "../features/courses/CoursePage";
import { HomePage } from "../features/courses/HomePage";
import { ModuleWorkspace } from "../features/modules/ModuleWorkspace";
import { SchedulePage } from "../features/schedule/SchedulePage";
import { ReviewPage } from "../features/review/ReviewPage";
import { TasksPage } from "../features/tasks/TasksPage";
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
  | "teacher"
  | "chat"
  | "notes";

const MODULE_TABS = [
  "overview",
  "materials",
  "summary",
  "cards",
  "quiz",
  "teacher",
  "chat",
  "notes",
];

const moduleRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/courses/$courseId/modules/$moduleId",
  component: ModuleWorkspace,
  validateSearch: (
    search: Record<string, unknown>,
  ): { tab: ModuleTab; ask?: string; note?: number } => ({
    tab: (MODULE_TABS.includes(search.tab as string)
      ? search.tab
      : "overview") as ModuleTab,
    ...(typeof search.ask === "string" && search.ask
      ? { ask: search.ask }
      : {}),
    ...(Number(search.note) >= 1 ? { note: Number(search.note) } : {}),
  }),
});

const documentRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/documents/$documentId",
  component: DocumentViewer,
  validateSearch: (
    search: Record<string, unknown>,
  ): { page: number; highlight?: number; citation?: number } => ({
    page: Number(search.page) >= 1 ? Number(search.page) : 1,
    ...(Number(search.highlight) >= 1
      ? { highlight: Number(search.highlight) }
      : {}),
    ...(Number(search.citation) >= 1
      ? { citation: Number(search.citation) }
      : {}),
  }),
});

const scheduleRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/schedule",
  component: SchedulePage,
});

export type CalendarView = "month" | "week" | "day";

const calendarRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/calendar",
  component: CalendarPage,
  validateSearch: (
    search: Record<string, unknown>,
  ): { view?: CalendarView; ym?: string; d?: string } => ({
    ...(["month", "week", "day"].includes(String(search.view))
      ? { view: String(search.view) as CalendarView }
      : {}),
    ...(/^\d{4}-\d{2}$/.test(String(search.ym)) ? { ym: String(search.ym) } : {}),
    ...(/^\d{4}-\d{2}-\d{2}$/.test(String(search.d)) ? { d: String(search.d) } : {}),
  }),
});

const tasksRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/tasks",
  component: TasksPage,
});

const reviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/review",
  component: ReviewPage,
});

const assistantRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/assistant",
  component: AssistantPage,
});

const routeTree = rootRoute.addChildren([
  homeRoute,
  courseRoute,
  moduleRoute,
  documentRoute,
  scheduleRoute,
  calendarRoute,
  tasksRoute,
  reviewRoute,
  assistantRoute,
]);

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
