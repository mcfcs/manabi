import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History, PenLine } from "lucide-react";
import { useState } from "react";

import {
  api,
  type ArtifactVersion,
  type JobRef,
  type SummaryOut,
} from "../../lib/api";
import {
  AiOfflineBanner,
  CitationPill,
  JobProgress,
  StalenessBadge,
  useAiOnline,
  useGenerationJob,
} from "./common";
import "./summary.css";

function SummaryBody({ s }: { s: SummaryOut }) {
  return (
    <article className="summary-body">
      {s.key_terms.length > 0 && (
        <section>
          <h2>Key terms</h2>
          <dl className="key-terms">
            {s.key_terms.map((t, i) => (
              <div className="key-term" key={i}>
                <dt>{t.term}</dt>
                <dd>
                  {t.definition}
                  <span className="summary-cites">
                    {(s.citations[`kt:${i}`] ?? []).map((c) => (
                      <CitationPill key={c.id} citation={c} />
                    ))}
                  </span>
                </dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {s.acronyms.length > 0 && (
        <section>
          <h2>Acronyms</h2>
          <div className="acronym-grid">
            {s.acronyms.map((a, i) => (
              <div className="acronym" key={i}>
                <span className="acronym-short">{a.acronym}</span>
                <span className="acronym-long">
                  {a.meaning}
                  {(s.citations[`ac:${i}`] ?? []).slice(0, 1).map((c) => (
                    <CitationPill key={c.id} citation={c} />
                  ))}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

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
  );
}

export function SummaryTab({ moduleId }: { moduleId: string }) {
  const queryClient = useQueryClient();
  const aiOnline = useAiOnline();
  const [viewingVersion, setViewingVersion] = useState<number | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  const summary = useQuery({
    queryKey: ["summary", moduleId],
    queryFn: () => api.get<SummaryOut | null>(`/api/modules/${moduleId}/summary`),
  });

  const versions = useQuery({
    queryKey: ["summary-versions", moduleId],
    queryFn: () =>
      api.get<ArtifactVersion[]>(`/api/modules/${moduleId}/artifacts?type=summary`),
    enabled: showHistory,
  });

  const oldVersion = useQuery({
    queryKey: ["artifact", viewingVersion],
    queryFn: () => api.get<SummaryOut>(`/api/artifacts/${viewingVersion}`),
    enabled: viewingVersion != null,
  });

  const gen = useGenerationJob(moduleId, "generate_summary", () => {
    queryClient.invalidateQueries({ queryKey: ["summary", moduleId] });
    queryClient.invalidateQueries({ queryKey: ["summary-versions", moduleId] });
  });

  const generate = useMutation({
    mutationFn: () =>
      api.post<JobRef>(`/api/modules/${moduleId}/summary/generate`),
    onSuccess: (ref) => gen.start(ref.job_id),
  });

  const s = viewingVersion != null ? oldVersion.data : summary.data;
  const viewingOld = viewingVersion != null && s != null;

  return (
    <div className="summary-tab">
      {summary.data && (
        <header className="gen-head">
          <StalenessBadge staleness={summary.data.staleness} />
          <span className="gen-head-meta">
            generated {new Date(summary.data.generated_at).toLocaleString()} ·{" "}
            {summary.data.model_name}
          </span>
          <span className="gen-head-spacer" />
          <button
            className={`btn${showHistory ? " active" : ""}`}
            onClick={() => {
              setShowHistory((v) => !v);
              if (showHistory) setViewingVersion(null);
            }}
          >
            <History size={15} strokeWidth={1.75} /> History
          </button>
          <button
            className="btn btn-primary"
            onClick={() => generate.mutate()}
            disabled={gen.running || generate.isPending}
            title="Your notes guide emphasis — they are never treated as source material"
          >
            <PenLine size={15} strokeWidth={1.75} /> Regenerate
          </button>
        </header>
      )}

      {showHistory && versions.data && (
        <div className="version-list">
          {versions.data.map((v) => (
            <button
              key={v.artifact_id}
              className={`version-item${
                (viewingVersion ?? summary.data?.artifact_id) === v.artifact_id
                  ? " current"
                  : ""
              }`}
              onClick={() =>
                setViewingVersion(
                  v.artifact_id === summary.data?.artifact_id ? null : v.artifact_id,
                )
              }
            >
              {new Date(v.generated_at).toLocaleString()} · {v.item_count} blocks ·{" "}
              {v.model_name}
              {v.artifact_id === summary.data?.artifact_id && " (latest)"}
            </button>
          ))}
        </div>
      )}

      {viewingOld && (
        <p className="version-banner">
          Viewing version from {new Date(s!.generated_at).toLocaleString()} —{" "}
          <button className="link-btn" onClick={() => setViewingVersion(null)}>
            back to latest
          </button>
        </p>
      )}

      {!aiOnline && (gen.running || !summary.data) && <AiOfflineBanner />}
      {gen.running && <JobProgress job={gen.job} />}
      {gen.job?.status === "failed" && (
        <p className="error-text">Generation failed: {gen.job.error}</p>
      )}
      {generate.isError && (
        <p className="error-text">{(generate.error as Error).message}</p>
      )}

      {!summary.data && !gen.running && summary.isSuccess && (
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
          <p className="gen-hint">
            Your notes guide emphasis — they are never treated as source material.
          </p>
        </div>
      )}

      {s && <SummaryBody s={s} />}
    </div>
  );
}
