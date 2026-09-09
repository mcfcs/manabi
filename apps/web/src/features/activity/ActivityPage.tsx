import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { AlertTriangle, Ban, Check, Loader2 } from "lucide-react";
import { useState } from "react";

import { api, type JobListItem } from "../../lib/api";
import "./activity.css";

const LIVE = new Set(["queued", "running"]);

/** Human names for job_type. An unknown type falls back to its raw value
 * rather than being hidden, so a new job kind still shows up here. */
const LABEL: Record<string, string> = {
  process_document: "Reading a document",
  generate_summary: "Writing a summary",
  generate_flashcards: "Making flashcards",
  generate_quiz: "Making a quiz",
  regenerate_question: "Rewriting a question",
  verify_question: "Checking an answer",
  define_term: "Defining a term",
  chat_answer: "Answering",
  daily_briefing: "Morning briefing",
  teach_module: "Writing a lecture",
  synthesize_lecture: "Recording a lecture",
  narrate_document: "Narrating a reading",
  speak_text: "Speaking",
  voice_preview: "Voice preview",
  echo: "Echo test",
};

const FILTERS = [
  { key: "all", label: "All", status: [] as string[] },
  { key: "failed", label: "Failed", status: ["failed"] },
  { key: "live", label: "Running", status: ["queued", "running"] },
] as const;

function when(iso: string): string {
  const d = new Date(iso);
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} h ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function took(job: JobListItem): string | null {
  if (!job.started_at || !job.finished_at) return null;
  const s = Math.round(
    (new Date(job.finished_at).getTime() - new Date(job.started_at).getTime()) / 1000,
  );
  if (s < 1) return null;
  return s < 90 ? `${s}s` : `${Math.round(s / 60)}m`;
}

export function ActivityPage() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");
  const qc = useQueryClient();
  const active = FILTERS.find((f) => f.key === filter) ?? FILTERS[0];

  const jobs = useQuery({
    queryKey: ["jobs", filter],
    queryFn: () => {
      const qs = active.status.map((s) => `status=${s}`).join("&");
      return api.get<JobListItem[]>(`/api/jobs${qs ? `?${qs}` : ""}`);
    },
    refetchInterval: (q) =>
      (q.state.data ?? []).some((j) => LIVE.has(j.status)) ? 4000 : 30_000,
  });

  const cancel = useMutation({
    mutationFn: (id: number) => api.post(`/api/jobs/${id}/cancel`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });

  const rows = jobs.data ?? [];

  return (
    <div className="activity-page">
      <header className="activity-head">
        <h1>Activity</h1>
        <div className="activity-filters">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              className={`btn btn-sm${f.key === filter ? " active" : ""}`}
              onClick={() => setFilter(f.key)}
              aria-pressed={f.key === filter}
            >
              {f.label}
            </button>
          ))}
        </div>
      </header>

      <p className="activity-hint">
        Everything Manabi has run for you recently — including the runs that failed while you were
        somewhere else.
      </p>

      {jobs.isLoading && <p className="gen-hint">Loading…</p>}
      {!jobs.isLoading && rows.length === 0 && (
        <p className="gen-hint">
          {filter === "failed" ? "Nothing has failed. " : "Nothing to show yet. "}
        </p>
      )}

      <ol className="activity-list">
        {rows.map((j) => (
          <li key={j.id} className={`activity-row is-${j.status}`}>
            <span className="activity-icon" aria-hidden>
              {j.status === "failed" ? (
                <AlertTriangle size={14} strokeWidth={1.75} />
              ) : j.status === "cancelled" ? (
                <Ban size={14} strokeWidth={1.75} />
              ) : LIVE.has(j.status) ? (
                <Loader2 size={14} strokeWidth={1.75} className="spin" />
              ) : (
                <Check size={14} strokeWidth={1.75} />
              )}
            </span>

            <span className="activity-text">
              <span className="activity-title">
                {LABEL[j.job_type] ?? j.job_type}
                {j.module_title || j.document_title ? (
                  <span className="activity-where">
                    {" · "}
                    {j.module_id && j.course_id ? (
                      <Link
                        to="/courses/$courseId/modules/$moduleId"
                        params={{
                          courseId: String(j.course_id),
                          moduleId: String(j.module_id),
                        }}
                        search={{ tab: "overview" }}
                      >
                        {j.module_title}
                      </Link>
                    ) : j.document_id ? (
                      <Link
                        to="/documents/$documentId"
                        params={{ documentId: String(j.document_id) }}
                        search={{ page: 1 }}
                      >
                        {j.document_title}
                      </Link>
                    ) : (
                      j.module_title || j.document_title
                    )}
                  </span>
                ) : null}
              </span>
              {/* A succeeded run can still carry an error string from an
                  attempt that was retried — only report one that actually
                  ended badly. */}
              {j.error && (j.status === "failed" || j.status === "cancelled") && (
                <span className="activity-error">{j.error.split(/\r?\n/)[0]}</span>
              )}
              {!j.error && j.progress_note && LIVE.has(j.status) && (
                <span className="activity-note">{j.progress_note}</span>
              )}
            </span>

            <span className="activity-meta mono">
              {took(j) && (
                <>
                  <span className="activity-took">{took(j)}</span>
                  <span aria-hidden>·</span>
                </>
              )}
              {when(j.created_at)}
            </span>

            {LIVE.has(j.status) && (
              <button
                className="btn btn-sm"
                onClick={() => cancel.mutate(j.id)}
                disabled={cancel.isPending}
              >
                Cancel
              </button>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
