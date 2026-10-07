import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Loader2, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";

import { Modal } from "../../components/Modal";
import { api, type DocumentOut, type ModuleOut, type PlanIn, type PlanOut } from "../../lib/api";

export const TYPE_LABELS: Record<string, string> = {
  output: "Predict the output",
  mcq: "Multiple choice",
  tf: "True or false",
  identification: "Identification",
  enumeration: "Enumeration",
  short: "Short answer",
  essay: "Essay",
  coding: "Coding",
};
const TYPE_ORDER = Object.keys(TYPE_LABELS);

/** Create or edit a study plan: name, modules, the materials inside them
 * (all by default), question types (or let the AI choose from the material)
 * with an emphasis per type, and a focus. */
export function PlanEditor({
  courseId,
  plan,
  onClose,
  onSaved,
}: {
  courseId: string;
  plan?: PlanOut | null;
  onClose: () => void;
  onSaved: (plan: PlanOut) => void;
}) {
  const qc = useQueryClient();
  const modules = useQuery({
    queryKey: ["modules", courseId],
    queryFn: () => api.get<ModuleOut[]>(`/api/courses/${courseId}/modules`),
  });
  // The modules endpoint already leaves out the hidden "Course files" module.
  const mods = useMemo(() => modules.data ?? [], [modules.data]);

  const [name, setName] = useState(plan?.name ?? "");
  const [moduleIds, setModuleIds] = useState<number[] | null>(plan?.module_ids ?? null);
  const [docIds, setDocIds] = useState<number[] | null>(plan?.document_ids ?? null);
  const [auto, setAuto] = useState(!plan?.types);
  const [weights, setWeights] = useState<Record<string, number>>(() => {
    if (plan?.types) {
      const out: Record<string, number> = {};
      for (const t of plan.types) out[t] = Math.round(plan.type_mix?.[t] ?? 1) || 1;
      return out;
    }
    return { output: 3, mcq: 3, tf: 1, identification: 1 };
  });
  const [focus, setFocus] = useState(plan?.focus ?? "");
  const [openMod, setOpenMod] = useState<number | null>(null);

  const chosen = moduleIds ?? mods.map((m) => m.id);
  const docs = useQueries({
    queries: mods.map((m) => ({
      queryKey: ["documents", String(m.id)],
      queryFn: () => api.get<DocumentOut[]>(`/api/modules/${m.id}/documents`),
      staleTime: 60_000,
    })),
  });
  const docsByModule = new Map(
    mods.map((m, i) => [m.id, (docs[i]?.data ?? []).filter((d) => d.ai_included)] as const),
  );
  const allDocIds = chosen.flatMap((mid) => (docsByModule.get(mid) ?? []).map((d) => d.id));
  const selectedDocs = new Set(docIds ?? allDocIds);

  function toggleModule(id: number) {
    const next = chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id];
    setModuleIds(next);
  }
  function toggleDoc(id: number) {
    const next = new Set(selectedDocs);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setDocIds([...next]);
  }
  function cycleWeight(t: string) {
    setWeights((w) => {
      const cur = w[t] ?? 0;
      const nextVal = cur >= 3 ? 0 : cur + 1;
      const out = { ...w };
      if (nextVal === 0) delete out[t];
      else out[t] = nextVal;
      return out;
    });
  }

  const effectiveDocs = docIds === null ? null : allDocIds.filter((d) => selectedDocs.has(d));
  const noDocs = effectiveDocs !== null && effectiveDocs.length === 0;
  const types = Object.keys(weights);
  const valid = name.trim() && chosen.length > 0 && !noDocs && (auto || types.length > 0);

  const save = useMutation({
    mutationFn: () => {
      const body: PlanIn = {
        name: name.trim(),
        module_ids: mods.map((m) => m.id).filter((id) => chosen.includes(id)),
        // "all" stays null so materials added later join the plan too
        document_ids:
          effectiveDocs && effectiveDocs.length === allDocIds.length ? null : effectiveDocs,
        types: auto ? null : types,
        type_mix: auto ? null : weights,
        focus: focus.trim() || null,
      };
      return plan
        ? api.patch<PlanOut>(`/api/plans/${plan.id}`, body)
        : api.post<PlanOut>(`/api/courses/${courseId}/plans`, body);
    },
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["plans", courseId] });
      qc.invalidateQueries({ queryKey: ["plan", String(p.id)] });
      onSaved(p);
    },
  });

  return (
    <Modal title={plan ? "Edit study plan" : "New study plan"} onClose={onClose} wide>
      <form
        className="plan-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) save.mutate();
        }}
      >
        <label className="plan-field">
          <span className="field-label">Name</span>
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Finals review, Pointers drill, Readings for the essay test"
            autoFocus
            maxLength={160}
          />
        </label>

        <div className="plan-field">
          <span className="field-label">Modules and materials</span>
          {modules.isLoading && (
            <p className="study-muted">
              <Loader2 size={13} className="spin" /> Loading modules
            </p>
          )}
          <ul className="plan-mods">
            {mods.map((m) => {
              const on = chosen.includes(m.id);
              const mdocs = docsByModule.get(m.id) ?? [];
              const picked = mdocs.filter((d) => selectedDocs.has(d.id)).length;
              return (
                <li key={m.id} className={on ? "on" : ""}>
                  <div className="plan-mod-row">
                    <label className="quiz-check">
                      <input type="checkbox" checked={on} onChange={() => toggleModule(m.id)} />
                      {m.title}
                    </label>
                    {on && mdocs.length > 0 && (
                      <button
                        type="button"
                        className="link-btn plan-mod-docs-btn"
                        onClick={() => setOpenMod((v) => (v === m.id ? null : m.id))}
                        aria-expanded={openMod === m.id}
                      >
                        {picked === mdocs.length ? "All materials" : `${picked} of ${mdocs.length}`}
                        <ChevronDown size={14} className={openMod === m.id ? "rot" : ""} />
                      </button>
                    )}
                    {on && mdocs.length === 0 && (
                      <span className="study-muted study-small">No materials yet</span>
                    )}
                  </div>
                  {on && openMod === m.id && (
                    <ul className="plan-docs">
                      {mdocs.map((d) => (
                        <li key={d.id}>
                          <label className="quiz-check">
                            <input
                              type="checkbox"
                              checked={selectedDocs.has(d.id)}
                              onChange={() => toggleDoc(d.id)}
                            />
                            <span className="plan-doc-name">{d.filename}</span>
                            <span className="study-muted study-small">{d.kind.toUpperCase()}</span>
                          </label>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
          {noDocs && <p className="error-text">Pick at least one material.</p>}
        </div>

        <div className="plan-field">
          <span className="field-label">Question types</span>
          <label className="plan-auto">
            <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
            <Sparkles size={14} strokeWidth={1.75} />
            <span>
              <strong>Let the AI choose</strong>
              <span className="study-muted study-small">
                {" "}
                from each module's material: code becomes predict-the-output and code-reading
                questions, readings become comprehension and identification.
              </span>
            </span>
          </label>
          {!auto && (
            <>
              <div className="plan-types">
                {TYPE_ORDER.map((t) => {
                  const w = weights[t] ?? 0;
                  return (
                    <button
                      key={t}
                      type="button"
                      className={`plan-type${w ? " on" : ""}`}
                      onClick={() => cycleWeight(t)}
                      aria-pressed={w > 0}
                      title="Click to add; click again for more emphasis"
                    >
                      {TYPE_LABELS[t]}
                      {w > 0 && (
                        <span className="plan-type-w" aria-label={`weight ${w}`}>
                          {"•".repeat(w)}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
              <p className="study-muted study-small">
                Click a type to include it; click again for more of it (up to three dots).
                Essays are graded by the AI against a rubric; coding answers are compiled and
                run.
              </p>
            </>
          )}
        </div>

        <label className="plan-field">
          <span className="field-label">Focus (optional)</span>
          <textarea
            className="input"
            rows={2}
            value={focus}
            onChange={(e) => setFocus(e.target.value)}
            placeholder="e.g. pointer arithmetic and string functions; or: the three forms of politics"
          />
        </label>

        {save.isError && <p className="error-text">{(save.error as Error).message}</p>}
        <div className="plan-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={!valid || save.isPending}>
            {save.isPending && <Loader2 size={14} className="spin" />}
            {plan ? "Save plan" : "Create plan"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
