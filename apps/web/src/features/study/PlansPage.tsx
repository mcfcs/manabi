import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { ChevronLeft, ChevronRight, Plus, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";

import { api, type CourseOut, type PlanOut } from "../../lib/api";
import { PlanEditor, TYPE_LABELS } from "./PlanEditor";
import "./study.css";

function typesLabel(plan: PlanOut): string {
  if (!plan.types) return "Question types chosen from the material";
  return plan.types.map((t) => TYPE_LABELS[t] ?? t).join(", ");
}

/** A course's study plans: each a named path over chosen modules and
 * materials, with its own tests. */
export function PlansPage() {
  const { courseId } = useParams({ from: "/courses/$courseId/study" });
  const navigate = useNavigate();
  const qc = useQueryClient();
  const courses = useQuery({
    queryKey: ["courses"],
    queryFn: () => api.get<CourseOut[]>("/api/courses"),
  });
  const course = courses.data?.find((c) => String(c.id) === courseId);
  const plans = useQuery({
    queryKey: ["plans", courseId],
    queryFn: () => api.get<PlanOut[]>(`/api/courses/${courseId}/plans`),
  });
  const [creating, setCreating] = useState(false);
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/api/plans/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["plans", courseId] }),
  });

  return (
    <div className="study-page">
      <nav className="crumb">
        <Link to="/courses/$courseId" params={{ courseId }}>
          <ChevronLeft size={15} strokeWidth={1.5} /> {course?.code ?? "Course"}
        </Link>
      </nav>

      <header className="study-head">
        <div className="study-head-row">
          <h1>Study plans</h1>
          <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
            <Plus size={15} strokeWidth={2} /> New plan
          </button>
        </div>
        <p className="study-head-sub">
          Each plan is its own path: read the sections, check each one, pass the topic tests, then a
          final mock exam over everything the plan covers.
        </p>
      </header>

      {plans.isLoading && (
        <div className="study-skeleton" aria-hidden>
          {[0, 1].map((i) => (
            <div key={i} className="study-skel-row" />
          ))}
        </div>
      )}
      {plans.isError && <p className="error-text">Could not load the study plans.</p>}

      {plans.data && plans.data.length === 0 && (
        <div className="plans-empty">
          <Sparkles size={22} strokeWidth={1.5} />
          <h2>No study plans yet</h2>
          <p className="study-muted">
            Pick the modules (and, if you like, just some of their materials), choose the question
            types or let the AI choose from the material, and add a focus.
          </p>
          <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
            <Plus size={15} strokeWidth={2} /> Create the first plan
          </button>
        </div>
      )}

      {plans.data && plans.data.length > 0 && (
        <ul className="plans-list">
          {plans.data.map((p) => (
            <li key={p.id} className="plan-card">
              <Link
                className="plan-card-link"
                to="/courses/$courseId/study/$planId"
                params={{ courseId, planId: String(p.id) }}
              >
                <div className="plan-card-main">
                  <h2>{p.name}</h2>
                  <p className="study-muted plan-card-meta">
                    {p.module_ids.length} module{p.module_ids.length === 1 ? "" : "s"}
                    {p.document_ids ? `, ${p.document_ids.length} chosen materials` : ", all materials"}
                  </p>
                  <p className="plan-card-types">{typesLabel(p)}</p>
                  {p.focus && <p className="plan-card-focus">Focus: {p.focus}</p>}
                </div>
                <div className="plan-card-side">
                  <ol className="study-track plan-card-track" aria-label="Topic tests passed">
                    {Array.from({ length: Math.max(1, p.modules_total) }, (_, i) => (
                      <li key={i} className={i < p.modules_passed ? "ok" : ""} />
                    ))}
                  </ol>
                  <span className="study-muted study-small">
                    {p.modules_passed} of {p.modules_total} topic tests passed
                    {p.final_best != null && `, final best ${Math.round(p.final_best)}%`}
                  </span>
                </div>
                <ChevronRight size={18} className="plan-card-chev" />
              </Link>
              <button
                type="button"
                className="icon-btn plan-card-delete"
                aria-label={`Delete ${p.name}`}
                title="Delete this plan (its tests stay in each module's Quiz tab)"
                onClick={() => {
                  if (window.confirm(`Delete "${p.name}"? Its tests stay in each module's Quiz tab.`))
                    remove.mutate(p.id);
                }}
              >
                <Trash2 size={15} strokeWidth={1.5} />
              </button>
            </li>
          ))}
        </ul>
      )}

      {creating && (
        <PlanEditor
          courseId={courseId}
          onClose={() => setCreating(false)}
          onSaved={(p) => {
            setCreating(false);
            navigate({
              to: "/courses/$courseId/study/$planId",
              params: { courseId, planId: String(p.id) },
            });
          }}
        />
      )}
    </div>
  );
}
