import { useState } from "react";

import { api, ApiError, type JobOut } from "../../lib/api";
import "./home.css";

function SpineTest() {
  const [job, setJob] = useState<JobOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setError(null);
    setJob(null);
    try {
      let j = await api.post<JobOut>("/api/jobs/echo");
      setJob(j);
      while (j.status === "queued" || j.status === "running") {
        await new Promise((r) => setTimeout(r, 1500));
        j = await api.get<JobOut>(`/api/jobs/${j.id}`);
        setJob(j);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="spine-test">
      <div>
        <h3>AI spine test</h3>
        <p className="spine-desc">
          Queues a trivial job for the GPU worker on phillmyeol and waits for
          the round trip. If the AI node is asleep, the job waits in the queue.
        </p>
      </div>
      <button className="btn" onClick={run} disabled={busy}>
        {busy ? "Waiting…" : "Run test"}
      </button>
      {job && (
        <pre className="mono spine-result">
          job #{job.id} · {job.status}
          {job.progress_note ? ` · ${job.progress_note}` : ""}
          {job.result ? `\n${JSON.stringify(job.result, null, 2)}` : ""}
          {job.error ? `\n${job.error}` : ""}
        </pre>
      )}
      {error && <p className="error-text">{error}</p>}
    </section>
  );
}

export function HomePage() {
  return (
    <div className="home">
      <header className="home-head">
        <h1>Your Courses</h1>
        <button className="btn btn-primary" type="button" disabled>
          + New course
        </button>
      </header>

      <div className="home-empty">
        <p>
          No courses yet. Course creation arrives in Phase 1 — this shell
          proves auth, the design frame, and the AI spine.
        </p>
      </div>

      <hr className="hairline" />
      <SpineTest />
    </div>
  );
}
