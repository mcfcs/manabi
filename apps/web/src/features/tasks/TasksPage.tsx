import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  ChevronDown,
  ChevronRight,
  Loader2,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";

import {
  api,
  ApiError,
  type CourseOut,
  type SettingsOut,
  type TaskOut,
} from "../../lib/api";
import { enablePush, getPushState, type PushState } from "../../lib/push";
import "./tasks.css";

type GroupKey = "overdue" | "today" | "week" | "later" | "done";

const GROUP_LABELS: Record<GroupKey, string> = {
  overdue: "Overdue",
  today: "Today",
  week: "This week",
  later: "Later",
  done: "Done",
};

function localToday(): string {
  return new Date().toLocaleDateString("sv");
}

function groupOf(task: TaskOut, today: string, weekEnd: string): GroupKey {
  if (task.done) return "done";
  if (!task.due_date) return "later";
  if (task.due_date < today) return "overdue";
  if (task.due_date === today) return "today";
  if (task.due_date <= weekEnd) return "week";
  return "later";
}

export function agoLabel(iso: string | null): string {
  if (!iso) return "never";
  const mins = Math.max(0, Math.floor((Date.now() - Date.parse(iso)) / 60_000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

function dueLabel(task: TaskOut): string {
  if (!task.due_date) return "";
  const d = new Date(task.due_date + "T00:00:00");
  let label = d.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
  if (task.due_minute != null) {
    const h = Math.floor(task.due_minute / 60);
    const m = String(task.due_minute % 60).padStart(2, "0");
    label += ` · ${h}:${m}`;
  }
  return label;
}

function TaskRow({ task }: { task: TaskOut }) {
  const queryClient = useQueryClient();
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["tasks"] });
  };
  const toggle = useMutation({
    mutationFn: () => api.patch(`/api/tasks/${task.id}`, { done: !task.done }),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/api/tasks/${task.id}`),
    onSuccess: invalidate,
  });
  return (
    <div className={`task-row${task.done ? " done" : ""}`}>
      <input
        type="checkbox"
        checked={task.done}
        onChange={() => toggle.mutate()}
        aria-label={task.done ? "Mark not done" : "Mark done"}
      />
      <span className="task-title">{task.title}</span>
      {task.course_code && (
        <span
          className="task-course"
          style={{
            color: task.course_accent_color ?? "var(--accent-blue)",
            background: `color-mix(in srgb, ${task.course_accent_color ?? "var(--accent-blue)"} 13%, transparent)`,
          }}
        >
          {task.course_code}
        </span>
      )}
      {task.source === "canvas" && <span className="task-canvas">canvas</span>}
      <span className="task-due mono">{dueLabel(task)}</span>
      <button
        className="icon-btn danger task-delete"
        onClick={() => remove.mutate()}
        aria-label="Delete task"
      >
        <Trash2 size={14} strokeWidth={1.5} />
      </button>
    </div>
  );
}

export function TasksPage() {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [courseId, setCourseId] = useState<number | "">("");
  const [dueDate, setDueDate] = useState("");
  const [doneOpen, setDoneOpen] = useState(false);
  const [pushState, setPushState] = useState<PushState | null>(null);
  const [syncNote, setSyncNote] = useState<string | null>(null);

  useEffect(() => {
    getPushState().then(setPushState);
  }, []);

  const tasks = useQuery({
    queryKey: ["tasks"],
    queryFn: () => api.get<TaskOut[]>("/api/tasks"),
  });
  const courses = useQuery({
    queryKey: ["courses"],
    queryFn: () => api.get<CourseOut[]>("/api/courses"),
    staleTime: 60_000,
  });
  // 60s refetch doubles as the "N min ago" label refresher.
  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: () => api.get<SettingsOut>("/api/settings"),
    refetchInterval: 60_000,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["tasks"] });
  };

  const add = useMutation({
    mutationFn: () =>
      api.post("/api/tasks", {
        title: title.trim(),
        course_id: courseId === "" ? null : courseId,
        due_date: dueDate || null,
      }),
    onSuccess: () => {
      setTitle("");
      setDueDate("");
      invalidate();
    },
  });

  const canvasSync = useMutation({
    mutationFn: () =>
      api.post<{ created: number; updated: number; courses_checked: number }>(
        "/api/tasks/canvas-sync",
      ),
    onSuccess: (r) => {
      setSyncNote(`${r.created} new, ${r.updated} updated from Canvas`);
      invalidate();
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (e) => {
      setSyncNote(e instanceof ApiError ? e.message : "Canvas sync failed");
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  const today = localToday();
  const weekEnd = new Date(Date.now() + 6 * 86400_000).toLocaleDateString("sv");
  const groups = new Map<GroupKey, TaskOut[]>();
  for (const t of tasks.data ?? []) {
    const g = groupOf(t, today, weekEnd);
    groups.set(g, [...(groups.get(g) ?? []), t]);
  }

  return (
    <div className="tasks-page">
      <header className="tasks-head">
        <h1>Tasks</h1>
        {settings.data && (
          <span
            className={`tasks-synced mono${settings.data.canvas_last_error ? " error-text" : ""}`}
            title={settings.data.canvas_last_error ?? "Auto-syncs every 10 minutes"}
          >
            {settings.data.canvas_last_error
              ? "sync failing"
              : `synced ${agoLabel(settings.data.canvas_last_synced_at)}`}
          </span>
        )}
        <button
          className="btn"
          onClick={() => canvasSync.mutate()}
          disabled={canvasSync.isPending}
        >
          {canvasSync.isPending ? (
            <Loader2 size={15} className="spin" />
          ) : (
            <RefreshCw size={15} strokeWidth={1.75} />
          )}{" "}
          Sync Canvas
        </button>
      </header>
      {syncNote && <p className="tasks-sync-note">{syncNote}</p>}

      {pushState === "off" && (
        <div className="tasks-push-banner">
          <Bell size={15} strokeWidth={1.75} />
          <span>Get a push notification when tasks are due.</span>
          <button
            className="btn"
            onClick={() => enablePush().then(setPushState)}
          >
            Enable
          </button>
        </div>
      )}

      <form
        className="task-quickadd"
        onSubmit={(e) => {
          e.preventDefault();
          if (title.trim()) add.mutate();
        }}
      >
        <input
          className="input"
          placeholder="Add a task…"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <select
          className="input task-quickadd-course"
          value={courseId}
          onChange={(e) => setCourseId(e.target.value ? Number(e.target.value) : "")}
        >
          <option value="">Course</option>
          {(courses.data ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.code}
            </option>
          ))}
        </select>
        <input
          type="date"
          className="input task-quickadd-date"
          value={dueDate}
          onChange={(e) => setDueDate(e.target.value)}
        />
        <button className="btn btn-primary" disabled={!title.trim() || add.isPending}>
          Add
        </button>
      </form>

      {(["overdue", "today", "week", "later"] as GroupKey[]).map((key) => {
        const list = groups.get(key) ?? [];
        if (!list.length) return null;
        return (
          <section key={key} className={`task-group ${key}`}>
            <h2>
              {GROUP_LABELS[key]} <span className="task-count">{list.length}</span>
            </h2>
            {list.map((t) => (
              <TaskRow key={t.id} task={t} />
            ))}
          </section>
        );
      })}

      {(groups.get("done") ?? []).length > 0 && (
        <section className="task-group done-group">
          <button className="task-done-toggle" onClick={() => setDoneOpen(!doneOpen)}>
            {doneOpen ? (
              <ChevronDown size={14} strokeWidth={1.5} />
            ) : (
              <ChevronRight size={14} strokeWidth={1.5} />
            )}
            Done <span className="task-count">{groups.get("done")!.length}</span>
          </button>
          {doneOpen &&
            groups.get("done")!.map((t) => <TaskRow key={t.id} task={t} />)}
        </section>
      )}

      {tasks.data && tasks.data.length === 0 && (
        <div className="home-empty">
          <p>No tasks yet. Add one above or sync your Canvas assignments.</p>
        </div>
      )}
    </div>
  );
}
