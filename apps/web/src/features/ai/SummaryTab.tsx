import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History, ListPlus, PenLine, Search, Trash2 } from "lucide-react";
import { useState } from "react";

import {
  api,
  ApiError,
  type ArtifactVersion,
  type JobRef,
  type KeyTerm,
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
                    {t.user_added && <span className="badge stale">added by you</span>}
                    {t.found_by_ai && <span className="badge fresh">found on request</span>}
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

function TermsManager({
  summary,
  moduleId,
  onClose,
}: {
  summary: SummaryOut;
  moduleId: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [terms, setTerms] = useState<KeyTerm[]>(summary.key_terms);
  const [findInput, setFindInput] = useState("");
  const [findError, setFindError] = useState<string | null>(null);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["summary", moduleId] });
  };

  const save = useMutation({
    mutationFn: () =>
      api.patch(`/api/artifacts/${summary.artifact_id}/terms`, {
        key_terms: terms.map((t) => ({
          term: t.term,
          definition: t.definition,
          user_added: t.user_added ?? false,
        })),
      }),
    onSuccess: () => {
      invalidate();
      onClose();
    },
  });

  const find = useMutation({
    mutationFn: (term: string) =>
      api.post<JobRef>(`/api/artifacts/${summary.artifact_id}/terms/find`, { term }),
    onSuccess: () => {
      setFindError(null);
      setFindInput("");
      onClose(); // job progress surfaces via active-jobs; summary refreshes on done
    },
    onError: (err) =>
      setFindError(err instanceof ApiError ? err.message : "Request failed"),
  });

  function update(i: number, patch: Partial<KeyTerm>) {
    setTerms((prev) => prev.map((t, j) => (j === i ? { ...t, ...patch } : t)));
  }

  return (
    <div className="terms-manager">
      <h3>Manage key terms</h3>
      <div className="terms-rows">
        {terms.map((t, i) => (
          <div className="terms-row" key={i}>
            <input
              className="input terms-term"
              value={t.term}
              onChange={(e) => update(i, { term: e.target.value, user_added: true })}
            />
            <input
              className="input terms-def"
              value={t.definition}
              onChange={(e) =>
                update(i, { definition: e.target.value, user_added: true })
              }
            />
            <button
              className="icon-btn danger"
              onClick={() => setTerms((prev) => prev.filter((_, j) => j !== i))}
              aria-label="Remove term"
            >
              <Trash2 size={14} strokeWidth={1.5} />
            </button>
          </div>
        ))}
      </div>
      <button
        className="btn"
        onClick={() =>
          setTerms((prev) => [...prev, { term: "", definition: "", user_added: true }])
        }
      >
        <ListPlus size={15} strokeWidth={1.75} /> Add manually
      </button>

      <div className="terms-find">
        <input
          className="input"
          placeholder="Missing term? Let the AI find it in the materials…"
          value={findInput}
          onChange={(e) => setFindInput(e.target.value)}
        />
        <button
          className="btn"
          disabled={!findInput.trim() || find.isPending}
          onClick={() => find.mutate(findInput.trim())}
        >
          <Search size={15} strokeWidth={1.75} /> Find in material
        </button>
      </div>
      {findError && <p className="error-text">{findError}</p>}
      {save.isError && <p className="error-text">{(save.error as Error).message}</p>}

      <div className="modal-actions">
        <button className="btn" onClick={onClose}>
          Cancel
        </button>
        <button
          className="btn btn-primary"
          disabled={save.isPending}
          onClick={() => save.mutate()}
        >
          Save terms
        </button>
      </div>
    </div>
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
  const findJob = useGenerationJob(moduleId, "define_term", () => {
    queryClient.invalidateQueries({ queryKey: ["summary", moduleId] });
  });
  const [managingTerms, setManagingTerms] = useState(false);

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
          {summary.data.coverage && (
            <span
              className="badge fresh"
              title="How many source passages this summary cites"
            >
              cites {summary.data.coverage.cited}/{summary.data.coverage.total}{" "}
              passages
            </span>
          )}
          <span className="gen-head-meta">
            generated {new Date(summary.data.generated_at).toLocaleString()} ·{" "}
            {summary.data.model_name}
          </span>
          <span className="gen-head-spacer" />
          <button
            className={`btn${managingTerms ? " active" : ""}`}
            onClick={() => setManagingTerms((v) => !v)}
          >
            <ListPlus size={15} strokeWidth={1.75} /> Terms
          </button>
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

      {managingTerms && summary.data && (
        <TermsManager
          summary={summary.data}
          moduleId={moduleId}
          onClose={() => setManagingTerms(false)}
        />
      )}

      {!aiOnline && (gen.running || !summary.data) && <AiOfflineBanner />}
      {gen.running && <JobProgress job={gen.job} />}
      {findJob.running && <JobProgress job={findJob.job} />}
      {findJob.job?.status === "failed" && (
        <p className="error-text">{findJob.job.error}</p>
      )}
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
