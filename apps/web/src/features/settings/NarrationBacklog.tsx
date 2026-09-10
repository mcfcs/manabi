import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, type UnpreparedReading } from "../../lib/api";

/** Readings that predate the narration switch.
 *
 * Auto-prepare only fires for PDFs parsed *after* the switch was turned on, so
 * everything imported before it had to be opened and prepared one at a time.
 * Recording is GPU work, so this lists the backlog and queues only what is
 * confirmed — never on load. */
export function NarrationBacklog() {
  const [queued, setQueued] = useState<number>(0);
  const [failed, setFailed] = useState<string[]>([]);

  const list = useQuery({
    queryKey: ["narration-unprepared"],
    queryFn: () => api.get<UnpreparedReading[]>("/api/narration/unprepared"),
    staleTime: 60_000,
  });

  const prepare = useMutation({
    mutationFn: async (docs: UnpreparedReading[]) => {
      // Sequentially: each POST scripts a PDF server-side, and the GPU runs
      // them one at a time anyway. A failure on one must not lose the rest.
      const bad: string[] = [];
      let ok = 0;
      for (const d of docs) {
        try {
          await api.post(`/api/documents/${d.document_id}/narration/prepare`, {});
          ok += 1;
        } catch {
          bad.push(d.filename);
        }
      }
      return { ok, bad };
    },
    onSuccess: (r) => {
      setQueued(r.ok);
      setFailed(r.bad);
      list.refetch();
    },
  });

  const pending = list.data ?? [];
  if (pending.length === 0) {
    return (
      <p className="settings-hint">
        {queued > 0
          ? `Queued ${queued} reading${queued === 1 ? "" : "s"}. Watch progress under Activity.`
          : "Every reading has a narration."}
      </p>
    );
  }

  const pages = pending.reduce((n, d) => n + (d.page_count ?? 0), 0);

  return (
    <div className="narration-backlog">
      <p className="settings-hint">
        <b>{pending.length}</b> reading{pending.length === 1 ? "" : "s"}
        {pages > 0 ? ` (${pages} pages)` : ""} were imported before you turned this on, so they
        have no narration yet.
      </p>
      <ul className="narration-backlog-list">
        {pending.slice(0, 6).map((d) => (
          <li key={d.document_id}>
            <span className="narration-backlog-name">{d.filename}</span>
            <span className="narration-backlog-meta mono">
              {d.course_code ?? ""}
              {d.page_count ? ` · ${d.page_count}p` : ""}
            </span>
          </li>
        ))}
        {pending.length > 6 && (
          <li className="narration-backlog-more">…and {pending.length - 6} more</li>
        )}
      </ul>
      <button
        className="btn btn-sm"
        onClick={() => prepare.mutate(pending)}
        disabled={prepare.isPending}
        title="Scripts each reading and queues the recording on the GPU"
      >
        {prepare.isPending
          ? `Queueing… (${pending.length})`
          : `Prepare all ${pending.length}`}
      </button>
      {failed.length > 0 && (
        <p className="settings-hint">Could not prepare: {failed.join(", ")}.</p>
      )}
    </div>
  );
}
