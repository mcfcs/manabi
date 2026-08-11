import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  CalendarClock,
  CalendarDays,
  Home,
  Layers,
  ListTodo,
  Loader2,
  Menu,
  Search,
  Settings2,
  Sparkles,
} from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import { SearchPalette } from "../features/search/SearchPalette";
import { SettingsDialog } from "../features/settings/SettingsDialog";
import { api, type CourseOut, type HealthOut, type UserOut } from "../lib/api";
import { getRecentModules } from "../lib/recents";
import "./shell.css";

function useReviewDueCount(): number {
  const due = useQuery({
    queryKey: ["review-due-count"],
    queryFn: () => api.get<{ count: number }>("/api/review/due-count"),
    refetchInterval: 5 * 60_000,
  });
  return due.data?.count ?? 0;
}

function useDueCount(): number {
  const due = useQuery({
    queryKey: ["tasks", "due-count"],
    queryFn: () => api.get<{ count: number }>("/api/tasks/due-count"),
    refetchInterval: 60_000,
  });
  return due.data?.count ?? 0;
}

function DueBadge({ count }: { count: number }) {
  if (count === 0) return null;
  return <span className="due-badge">{count}</span>;
}

function AiStatus() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => api.get<HealthOut>("/api/health"),
    refetchInterval: 30_000,
  });
  const online = health.data?.ai_node.online === true;
  return (
    <div className="ai-status" title={online ? "AI node online" : "AI node offline"}>
      <span className={online ? "status-dot online" : "status-dot"} />
      <span className="ai-status-label">AI</span>
    </div>
  );
}

interface GlobalJob {
  job_id: number;
  job_type: string;
  module_id: number | null;
  module_title: string | null;
  course_id: number | null;
  progress_note: string | null;
}

function Activity() {
  const jobs = useQuery({
    queryKey: ["global-active-jobs"],
    queryFn: () => api.get<GlobalJob[]>("/api/jobs/active"),
    refetchInterval: (q) => ((q.state.data?.length ?? 0) > 0 ? 4000 : 30_000),
  });
  const active = jobs.data ?? [];
  if (active.length === 0) return null;
  const first = active[0];
  return (
    <Link
      to="/courses/$courseId/modules/$moduleId"
      params={{
        courseId: String(first.course_id ?? ""),
        moduleId: String(first.module_id ?? ""),
      }}
      search={{ tab: "overview" }}
      className="rail-activity"
      title={active.map((j) => `${j.job_type} — ${j.module_title}`).join("\n")}
    >
      <Loader2 size={13} strokeWidth={1.75} className="spin" />
      <span>
        generating{active.length > 1 ? ` ×${active.length}` : ""}
        {first.module_title ? ` · ${first.module_title.slice(0, 16)}` : ""}
      </span>
    </Link>
  );
}

function UpdateToast() {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const show = () => setVisible(true);
    window.addEventListener("manabi-sw-update", show);
    return () => window.removeEventListener("manabi-sw-update", show);
  }, []);
  if (!visible) return null;
  return (
    <div className="update-toast">
      <span>A new version of Manabi is ready.</span>
      <button
        className="btn btn-primary"
        onClick={() =>
          (window as unknown as { manabiUpdateSW?: () => void }).manabiUpdateSW?.()
        }
      >
        Reload
      </button>
    </div>
  );
}

export function AppShell({
  user,
  children,
}: {
  user: UserOut;
  children: ReactNode;
}) {
  const courses = useQuery({
    queryKey: ["courses"],
    queryFn: () => api.get<CourseOut[]>("/api/courses"),
    staleTime: 30_000,
  });
  const recents = getRecentModules();
  const dueCount = useDueCount();
  const reviewDue = useReviewDueCount();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="shell">
      <nav className="rail" aria-label="Main">
        <Link to="/" className="rail-mark">
          <span className="rail-kanji" aria-hidden>
            学び
          </span>
          <span className="rail-name">MANABI</span>
        </Link>

        <div className="rail-links">
          <Link
            to="/assistant"
            className="rail-link"
            activeProps={{ className: "rail-link active" }}
          >
            <Sparkles size={16} strokeWidth={1.5} />
            <span>Steven</span>
          </Link>
          <Link
            to="/schedule"
            className="rail-link"
            activeProps={{ className: "rail-link active" }}
          >
            <CalendarClock size={16} strokeWidth={1.5} />
            <span>Schedule</span>
          </Link>
          <Link
            to="/calendar"
            className="rail-link"
            activeProps={{ className: "rail-link active" }}
          >
            <CalendarDays size={16} strokeWidth={1.5} />
            <span>Calendar</span>
          </Link>
          <Link
            to="/tasks"
            className="rail-link"
            activeProps={{ className: "rail-link active" }}
          >
            <ListTodo size={16} strokeWidth={1.5} />
            <span>Tasks</span>
            <DueBadge count={dueCount} />
          </Link>
          <Link
            to="/review"
            className="rail-link"
            activeProps={{ className: "rail-link active" }}
          >
            <Layers size={16} strokeWidth={1.5} />
            <span>Review</span>
            <DueBadge count={reviewDue} />
          </Link>
          <button className="rail-link rail-search" onClick={() => setSearchOpen(true)}>
            <Search size={16} strokeWidth={1.5} />
            <span>Search</span>
            <kbd className="rail-kbd">⌘K</kbd>
          </button>

          <span className="rail-heading rail-heading-gap">Courses</span>
          {(courses.data ?? []).map((c) => (
            <Link
              key={c.id}
              to="/courses/$courseId"
              params={{ courseId: String(c.id) }}
              className="rail-link rail-course"
              activeProps={{ className: "rail-link rail-course active" }}
            >
              <span
                className="rail-course-dot"
                style={{ background: c.accent_color ?? "var(--accent-blue)" }}
              />
              <span className="rail-course-code">{c.code}</span>
            </Link>
          ))}
          {courses.data?.length === 0 && (
            <span className="rail-empty">no courses yet</span>
          )}

          {recents.length > 0 && (
            <>
              <span className="rail-heading rail-heading-gap">Recent</span>
              {recents.map((r) => (
                <Link
                  key={r.moduleId}
                  to="/courses/$courseId/modules/$moduleId"
                  params={{
                    courseId: String(r.courseId),
                    moduleId: String(r.moduleId),
                  }}
                  search={{ tab: "overview" }}
                  className="rail-link rail-recent"
                >
                  <span className="rail-recent-title">{r.title}</span>
                </Link>
              ))}
            </>
          )}
        </div>

        <div className="rail-foot">
          <Activity />
          <AiStatus />
          <div className="rail-foot-row">
            <div className="rail-user mono" title={user.email}>
              {user.email}
            </div>
            <button
              className="icon-btn"
              onClick={() => setSettingsOpen(true)}
              aria-label="Settings"
            >
              <Settings2 size={15} strokeWidth={1.5} />
            </button>
          </div>
        </div>
      </nav>

      <main className="content">{children}</main>
      <UpdateToast />
      {settingsOpen && <SettingsDialog onClose={() => setSettingsOpen(false)} />}
      {searchOpen && <SearchPalette onClose={() => setSearchOpen(false)} />}

      <nav className="bottom-bar" aria-label="Main">
        <Link to="/" className="bottom-link" activeProps={{ className: "bottom-link active" }}>
          <Home size={20} strokeWidth={1.5} />
          <span>Home</span>
        </Link>
        <Link
          to="/assistant"
          className="bottom-link"
          activeProps={{ className: "bottom-link active" }}
        >
          <Sparkles size={20} strokeWidth={1.5} />
          <span>Steven</span>
        </Link>
        <Link
          to="/calendar"
          className="bottom-link"
          activeProps={{ className: "bottom-link active" }}
        >
          <CalendarDays size={20} strokeWidth={1.5} />
          <span>Calendar</span>
        </Link>
        <Link
          to="/tasks"
          className="bottom-link"
          activeProps={{ className: "bottom-link active" }}
        >
          <span className="bottom-link-icon">
            <ListTodo size={20} strokeWidth={1.5} />
            <DueBadge count={dueCount} />
          </span>
          <span>Tasks</span>
        </Link>
        <Link
          to="/review"
          className="bottom-link"
          activeProps={{ className: "bottom-link active" }}
        >
          <span className="bottom-link-icon">
            <Layers size={20} strokeWidth={1.5} />
            <DueBadge count={reviewDue} />
          </span>
          <span>Review</span>
        </Link>
        <button
          className={`bottom-link${moreOpen ? " active" : ""}`}
          onClick={() => setMoreOpen((v) => !v)}
          aria-label="More"
        >
          <Menu size={20} strokeWidth={1.5} />
          <span>More</span>
        </button>
      </nav>

      {moreOpen && (
        <>
          <div className="more-backdrop" onClick={() => setMoreOpen(false)} />
          <div className="more-sheet" role="menu" aria-label="More">
            <Link
              to="/schedule"
              className="more-sheet-item"
              onClick={() => setMoreOpen(false)}
            >
              <CalendarClock size={17} strokeWidth={1.5} />
              Schedule
            </Link>
            <button
              className="more-sheet-item"
              onClick={() => {
                setMoreOpen(false);
                setSearchOpen(true);
              }}
            >
              <Search size={17} strokeWidth={1.5} />
              Search
            </button>
            <button
              className="more-sheet-item"
              onClick={() => {
                setMoreOpen(false);
                setSettingsOpen(true);
              }}
            >
              <Settings2 size={17} strokeWidth={1.5} />
              Settings
            </button>
          </div>
        </>
      )}
    </div>
  );
}
