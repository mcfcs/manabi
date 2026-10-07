import { useMutation } from "@tanstack/react-query";
import { Check, Loader2, Play, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api, type JobRef, type QuestionOut } from "../../lib/api";
import { useJob } from "./common";

type RunResult = {
  status: "passed" | "failed" | "error" | "unverifiable";
  message: string;
  expected_output?: string;
  student_output?: string;
};
type EssayGrade = {
  score: number;
  points: { point: string; met: boolean; comment: string }[];
  feedback: string;
};

/** Grades a coding answer by running it against the reference solution, or
 * an essay answer with the AI against its rubric. Reports a verdict through
 * `onGrade` (the caller keeps the override). `auto` starts it immediately. */
export function AutoGrade({
  q,
  response,
  onGrade,
  auto = false,
}: {
  q: QuestionOut;
  response: string;
  onGrade: (g: "right" | "wrong") => void;
  auto?: boolean;
}) {
  const [run, setRun] = useState<RunResult | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);
  const started = useRef(false);
  const job = useJob(jobId);
  const grade = (job.data?.status === "succeeded"
    ? (job.data.result?.grade as EssayGrade | undefined)
    : undefined) ?? null;

  const runCode = useMutation({
    mutationFn: () => api.post<RunResult>(`/api/quiz-questions/${q.id}/run`, { code: response }),
    onSuccess: (r) => {
      setRun(r);
      if (r.status === "passed") onGrade("right");
      else if (r.status === "failed" || r.status === "error") onGrade("wrong");
    },
  });
  const gradeEssay = useMutation({
    mutationFn: () => api.post<JobRef>(`/api/quiz-questions/${q.id}/grade`, { answer: response }),
    onSuccess: (r) => setJobId(r.job_id),
  });

  useEffect(() => {
    if (grade) onGrade(grade.score >= 60 ? "right" : "wrong");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [grade?.score]);

  const has = response.trim().length > 0;
  useEffect(() => {
    if (!auto || started.current || !has) return;
    started.current = true;
    if (q.qtype === "coding") runCode.mutate();
    else if (q.qtype === "essay") gradeEssay.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto, has]);

  if (!has || (q.qtype !== "coding" && q.qtype !== "essay")) return null;

  if (q.qtype === "coding") {
    return (
      <div className="autograde">
        {!run && (
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => runCode.mutate()}
            disabled={runCode.isPending}
          >
            {runCode.isPending ? <Loader2 size={13} className="spin" /> : <Play size={13} />} Run my
            code against the reference
          </button>
        )}
        {run && (
          <div className={`autograde-result ${run.status}`}>
            <strong>
              {run.status === "passed" ? <Check size={14} /> : run.status === "unverifiable" ? null : <X size={14} />}{" "}
              {run.message}
            </strong>
            {run.status !== "passed" && run.expected_output != null && (
              <div className="autograde-outputs">
                <div>
                  <span className="field-label">Expected</span>
                  <pre className="quiz-output-block">{run.expected_output}</pre>
                </div>
                <div>
                  <span className="field-label">Yours</span>
                  <pre className="quiz-output-block">{run.student_output || "(nothing printed)"}</pre>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  const pending =
    gradeEssay.isPending || (jobId != null && !grade && job.data?.status !== "failed");
  return (
    <div className="autograde">
      {!jobId && !gradeEssay.isPending && (
        <button type="button" className="btn btn-sm" onClick={() => gradeEssay.mutate()}>
          <Sparkles size={13} /> Grade my answer with AI
        </button>
      )}
      {pending && (
        <p className="study-muted autograde-pending">
          <Loader2 size={13} className="spin" /> {job.data?.progress_note || "Grading against the rubric"}
        </p>
      )}
      {job.data?.status === "failed" && <p className="error-text">Grading failed: {job.data.error}</p>}
      {grade && (
        <div className={`autograde-result ${grade.score >= 60 ? "passed" : "failed"}`}>
          <strong>
            {grade.score}/100. {grade.feedback}
          </strong>
          <ul className="autograde-points">
            {grade.points.map((p, i) => (
              <li key={i} className={p.met ? "met" : "missed"}>
                {p.met ? <Check size={13} /> : <X size={13} />} <span>{p.point}</span>
                <span className="study-muted"> {p.comment}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
