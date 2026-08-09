import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { AlertTriangle, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import {
  api,
  type ActiveJobOut,
  type CitationOut,
  type HealthOut,
  type JobOut,
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

/** Poll a generation job until it reaches a terminal state. */
export function useJob(jobId: number | null) {
  return useQuery({
    queryKey: ["job", jobId],
    enabled: jobId != null,
    queryFn: () => api.get<JobOut>(`/api/jobs/${jobId}`),
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === "queued" || s === "running" ? 2000 : false;
    },
  });
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
        ...(citation.chunk_id != null ? { highlight: citation.chunk_id } : {}),
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
  if (!job) return null;
  return (
    <div className="job-progress">
      <Loader2 size={16} className="spin" strokeWidth={1.5} />
      <span>{job.progress_note ?? "Queued…"}</span>
      {job.progress_pct != null && (
        <span className="mono job-pct">{job.progress_pct}%</span>
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
