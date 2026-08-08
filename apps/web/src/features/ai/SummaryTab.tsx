import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PenLine } from "lucide-react";
import { useEffect, useState } from "react";

import { api, type JobRef, type SummaryOut } from "../../lib/api";
import {
  AiOfflineBanner,
  CitationPill,
  JobProgress,
  StalenessBadge,
  useAiOnline,
  useJob,
} from "./common";
import "./summary.css";

export function SummaryTab({ moduleId }: { moduleId: string }) {
  const queryClient = useQueryClient();
  const aiOnline = useAiOnline();
  const [jobId, setJobId] = useState<number | null>(null);

  const summary = useQuery({
    queryKey: ["summary", moduleId],
    queryFn: () => api.get<SummaryOut | null>(`/api/modules/${moduleId}/summary`),
  });

  const job = useJob(jobId);
  const running =
    jobId != null &&
    (job.data == null ||
      job.data.status === "queued" ||
      job.data.status === "running");

  useEffect(() => {
    if (job.data?.status === "succeeded" && jobId != null) {
      setJobId(null);
      queryClient.invalidateQueries({ queryKey: ["summary", moduleId] });
    }
  }, [job.data?.status, jobId, moduleId, queryClient]);

  const generate = useMutation({
    mutationFn: () =>
      api.post<JobRef>(`/api/modules/${moduleId}/summary/generate`),
    onSuccess: (ref) => setJobId(ref.job_id),
  });

  const s = summary.data;

  return (
    <div className="summary-tab">
      {s && (
        <header className="gen-head">
          <StalenessBadge staleness={s.staleness} />
          <span className="gen-head-meta">
            generated {new Date(s.generated_at).toLocaleString()} · {s.model_name}
          </span>
          <span className="gen-head-spacer" />
          <button
            className="btn btn-primary"
            onClick={() => generate.mutate()}
            disabled={running || generate.isPending}
          >
            <PenLine size={15} strokeWidth={1.75} /> Regenerate
          </button>
        </header>
      )}

      {!aiOnline && (running || !s) && <AiOfflineBanner />}
      {running && <JobProgress job={job.data} />}
      {job.data?.status === "failed" && (
        <p className="error-text">Generation failed: {job.data.error}</p>
      )}
      {generate.isError && (
        <p className="error-text">{(generate.error as Error).message}</p>
      )}

      {!s && !running && summary.isSuccess && (
        <div className="gen-empty">
          <p>
            No summary yet. Manabi will build structured study notes from this
            module's materials — every claim cited back to its source page.
          </p>
          <button
            className="btn btn-primary"
            onClick={() => generate.mutate()}
            disabled={generate.isPending}
          >
            <PenLine size={15} strokeWidth={1.75} /> Generate summary
          </button>
        </div>
      )}

      {s && (
        <article className="summary-body">
          {s.sections.map((section, si) => (
            <section key={si}>
              <h2>
                {si + 1}. {section.title}
              </h2>
              {section.blocks.map((block, bi) => (
                <div className="summary-block" key={bi}>
                  <p>{block.text}</p>
                  <span className="summary-cites">
                    {(s.citations[`s${si}:b${bi}`] ?? []).map((c) => (
                      <CitationPill key={c.id} citation={c} />
                    ))}
                  </span>
                </div>
              ))}
            </section>
          ))}
        </article>
      )}
    </div>
  );
}
