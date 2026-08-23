import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { AlertTriangle, Cpu, Loader2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Markdown } from "../../components/Markdown";
import {
  api,
  type ActiveJobOut,
  type AiModelsOut,
  type CitationOut,
  type HealthOut,
  type JobOut,
  type SettingsOut,
  type Staleness,
} from "../../lib/api";
import "./ai.css";

/** Queued/running generation jobs for a module — polled so progress
 * survives tab switches and page reloads. */
export function useActiveJobs(moduleId: string) {
  return useQuery({
    queryKey: ["active-jobs", moduleId],
    queryFn: () => api.get<ActiveJobOut[]>(`/api/modules/${moduleId}/active-jobs`),
    refetchInterval: (query) =>
      (query.state.data?.length ?? 0) > 0 ? 2000 : 15_000,
  });
}

/** Poll a generation job until it reaches a terminal state. Fast while running
 * so the streamed answer preview updates feel like live typing. */
export function useJob(jobId: number | null) {
  return useQuery({
    queryKey: ["job", jobId],
    enabled: jobId != null,
    queryFn: () => api.get<JobOut>(`/api/jobs/${jobId}`),
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === "queued" || s === "running" ? 800 : false;
    },
  });
}

/** Pull the (possibly partial) `answer` string out of the model's streaming
 * JSON preview, so the chat can type the answer out live instead of showing
 * raw JSON. Returns "" until the answer field starts streaming. */
export function extractStreamingAnswer(preview: string | null | undefined): string {
  if (!preview) return "";
  const m = preview.match(/"answer"\s*:\s*"((?:\\.|[^"\\])*)/);
  if (!m) return "";
  try {
    return JSON.parse(`"${m[1]}"`); // unescape \n, \", \uXXXX, …
  } catch {
    // Stream cut mid-escape — drop a trailing backslash and any bad escape.
    return m[1].replace(/\\$/, "").replace(/\\(?!["\\/bfnrtu])/g, "");
  }
}

/** Reveal `target` progressively (typewriter). Within one answer bubble the
 * streamed text only grows, so the shown length just catches up to it; the
 * bubble unmounts between messages, resetting state for the next answer. */
export function useTypewriter(target: string): string {
  const [len, setLen] = useState(0);
  useEffect(() => {
    if (len >= target.length) return;
    // Reveal a fraction of the remaining gap each tick — fast when far behind
    // (keeps up with generation), easing to a natural stop as it catches up.
    const step = Math.max(2, Math.ceil((target.length - len) / 12));
    const id = setTimeout(() => setLen((l) => Math.min(target.length, l + step)), 45);
    return () => clearTimeout(id);
  }, [len, target]);
  return target.slice(0, Math.min(len, target.length));
}

/** Compact per-chat model switcher (gpt-oss ⇄ qwen3.5 ⇄ …). "Auto" = the
 * server default. Works for module AND general threads (a thread's
 * model_override rides the answer job). Hidden when the node reports no models. */
export function ModelPicker({
  threadId,
  value,
  invalidateKeys,
}: {
  threadId: number;
  value: string | null;
  invalidateKeys: unknown[][];
}) {
  const qc = useQueryClient();
  const models = useQuery({
    queryKey: ["ai-models"],
    queryFn: () => api.get<AiModelsOut>("/api/ai/models"),
    staleTime: 60_000,
  });
  const patch = useMutation({
    mutationFn: (m: string | null) =>
      api.patch(`/api/chat/threads/${threadId}`, { model_override: m }),
    onSuccess: () =>
      invalidateKeys.forEach((k) => qc.invalidateQueries({ queryKey: k })),
  });
  const list = models.data?.models ?? [];
  if (list.length === 0) return null;
  return (
    <label className="chat-model-pick" title="Model for this chat (Auto = default)">
      <Cpu size={13} strokeWidth={1.75} />
      <select
        className="chat-model-select"
        value={value ?? ""}
        onChange={(e) => patch.mutate(e.target.value || null)}
      >
        <option value="">Auto</option>
        {list.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
    </label>
  );
}

/** The live assistant bubble content while a reply generates: types the answer
 * out (markdown + cursor) once the model starts streaming it, else shows the
 * thinking dots. Shared by the module chat, the assistant, and the ask panel. */
export function StreamingAnswer({
  job,
  thinkingLabel = "reading your materials",
}: {
  job: JobOut | undefined;
  thinkingLabel?: string;
}) {
  const typed = useTypewriter(extractStreamingAnswer(job?.preview));
  if (typed) {
    return (
      <div className="chat-typeout">
        <Markdown>{typed}</Markdown>
        <span className="type-cursor" aria-hidden />
      </div>
    );
  }
  return (
    <p className="chat-thinking">
      {job?.status === "queued" ? "waiting for the AI node" : thinkingLabel}
      <span className="typing-dots" aria-hidden>
        <span />
        <span />
        <span />
      </span>
    </p>
  );
}

/** Track a generation job from defer to completion; fires onDone once.
 * Resumes automatically from the server's active-jobs list, so progress
 * survives navigating away and full page reloads. */
export function useGenerationJob(
  moduleId: string,
  jobType: string,
  onDone: () => void,
) {
  const [jobId, setJobId] = useState<number | null>(null);
  const active = useActiveJobs(moduleId);

  // adopt a server-side in-flight job of this type (resume after nav/reload)
  const serverJob = active.data?.find((j) => j.job_type === jobType);
  useEffect(() => {
    if (jobId == null && serverJob != null) setJobId(serverJob.job_id);
  }, [jobId, serverJob]);

  const job = useJob(jobId);
  const running =
    (jobId != null &&
      (job.data == null ||
        job.data.status === "queued" ||
        job.data.status === "running")) ||
    serverJob != null;

  useEffect(() => {
    if (jobId != null && job.data?.status === "succeeded") {
      setJobId(null);
      onDone();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.data?.status, jobId]);

  return { start: setJobId, job: job.data, running };
}

/** Cancel a running/queued generation job. Invalidates the active-jobs and
 * job caches so the spinner clears (works even for orphaned jobs). */
export function useCancelJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: number) => api.post(`/api/jobs/${jobId}/cancel`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["active-jobs"] });
      qc.invalidateQueries({ queryKey: ["job"] });
    },
  });
}

/** Chat voice preference: the Settings `chat_autovoice` toggle is the default;
 * the per-conversation toggle overrides it for the session (localStorage). */
export function useChatVoice(): [boolean, (v: boolean) => void] {
  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: () => api.get<SettingsOut>("/api/settings"),
    staleTime: 60_000,
  });
  const [override, setOverride] = useState<boolean | null>(() => {
    const v = localStorage.getItem("manabi-chat-voice");
    return v === null ? null : v === "1";
  });
  const on = override ?? settings.data?.chat_autovoice ?? false;
  const set = (v: boolean) => {
    localStorage.setItem("manabi-chat-voice", v ? "1" : "0");
    setOverride(v);
  };
  return [on, set];
}

export function useAiOnline(): boolean {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => api.get<HealthOut>("/api/health"),
    refetchInterval: 30_000,
  });
  return health.data?.ai_node.online === true;
}

export function CitationPill({ citation }: { citation: CitationOut }) {
  const pages =
    citation.page_start == null
      ? ""
      : citation.page_end && citation.page_end !== citation.page_start
        ? ` · p. ${citation.page_start}–${citation.page_end}`
        : ` · p. ${citation.page_start}`;
  const label = `${citation.document_title}${pages}`;
  const weak = citation.status === "weak";

  if (citation.status === "source_removed" || citation.document_id == null) {
    return <span className="citation-pill removed">source removed</span>;
  }
  return (
    <Link
      to="/documents/$documentId"
      params={{ documentId: String(citation.document_id) }}
      search={{
        page: citation.page_start ?? 1,
        citation: citation.id,
      }}
      className={`citation-pill${weak ? " weak" : ""}`}
      title={
        weak
          ? "Weak support — the source only loosely backs this statement"
          : "Open source"
      }
    >
      {weak && <AlertTriangle size={11} strokeWidth={1.75} />}
      {label}
    </Link>
  );
}

export function StalenessBadge({ staleness }: { staleness: Staleness }) {
  if (staleness === "fresh") return <span className="badge fresh">current</span>;
  if (staleness === "incomplete")
    return (
      <span className="badge stale" title="New material was added since generation">
        new material available
      </span>
    );
  return (
    <span className="badge stale" title="Source material changed since generation">
      materials changed
    </span>
  );
}

export function JobProgress({ job }: { job: JobOut | undefined }) {
  const [watching, setWatching] = useState(false);
  const tailRef = useRef<HTMLPreElement>(null);
  const cancel = useCancelJob();

  useEffect(() => {
    if (watching && tailRef.current) {
      tailRef.current.scrollTop = tailRef.current.scrollHeight;
    }
  }, [watching, job?.preview]);

  if (!job) return null;
  const active = job.status === "queued" || job.status === "running";
  return (
    <div className="job-progress-box">
      <div className="job-progress">
        <Loader2 size={16} className="spin" strokeWidth={1.5} />
        <span>{job.progress_note ?? "Queued…"}</span>
        {job.progress_pct != null && (
          <span className="mono job-pct">{job.progress_pct}%</span>
        )}
        <button className="link-btn watch-toggle" onClick={() => setWatching((v) => !v)}>
          {watching ? "hide generation" : "watch generation"}
        </button>
        {active && (
          <button
            className="link-btn job-cancel"
            onClick={() => cancel.mutate(job.id)}
            disabled={cancel.isPending}
            title="Cancel this generation"
          >
            <X size={13} strokeWidth={2} /> cancel
          </button>
        )}
      </div>
      {watching && (
        <pre ref={tailRef} className="job-preview">
          {job.preview ?? "…waiting for the model to start writing…"}
        </pre>
      )}
    </div>
  );
}

export function AiOfflineBanner() {
  return (
    <p className="ai-offline-banner">
      AI node is offline — your request is queued and will run when it wakes.
    </p>
  );
}
