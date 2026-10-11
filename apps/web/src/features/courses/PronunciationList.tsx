import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  Loader2,
  Mic,
  Play,
  Plus,
  Trash2,
} from "lucide-react";
import { useRef, useState } from "react";

import { api, ApiError } from "../../lib/api";

interface Pronunciation {
  id: number;
  term: string;
  say: string;
  source: "auto" | "user";
  match: number | null;
}

/** Below this, the voice's real sounds strayed from the intended ones. */
const LISTEN_BELOW = 0.8;

const needsListen = (p: Pronunciation) =>
  p.source === "auto" &&
  p.say !== p.term &&
  p.match != null &&
  p.match < LISTEN_BELOW;

/** Play a line in Steven's voice through the voice lab's cached renders. */
async function speak(text: string, audio: HTMLAudioElement): Promise<void> {
  for (let i = 0; i < 60; i++) {
    const r = await api.post<{ ready: boolean; id?: number }>(
      "/api/voice/preview",
      {
        text,
        variant: "tuned",
      },
    );
    if (r.ready && r.id != null) {
      audio.src = `/api/voice/previews/${r.id}`;
      await audio.play();
      return;
    }
    await new Promise((res) => setTimeout(res, 2000));
  }
  throw new Error("Timed out waiting for Steven");
}

/** How Steven says this course's terms. Learned when a reading is recorded;
 * correct one here and only the paragraphs that use it are recorded again. */
export function PronunciationList({ courseId }: { courseId: number }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState("");
  const [say, setSay] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const list = useQuery({
    queryKey: ["pronunciations", courseId],
    queryFn: () =>
      api.get<Pronunciation[]>(`/api/courses/${courseId}/pronunciations`),
  });
  const refresh = () =>
    qc.invalidateQueries({ queryKey: ["pronunciations", courseId] });

  const add = useMutation({
    mutationFn: () =>
      api.post<Pronunciation>(`/api/courses/${courseId}/pronunciations`, {
        term,
        say,
      }),
    onSuccess: (p) => {
      setTerm("");
      setSay("");
      refresh();
      rerecord.mutate(p.id);
    },
  });
  const rerecord = useMutation({
    mutationFn: (id: number) =>
      api.post<{ segments: number; busy: string[] }>(
        `/api/pronunciations/${id}/rerecord`,
        {},
      ),
    onSuccess: (r) =>
      setNote(
        r.segments
          ? `Recording ${r.segments} paragraph${r.segments === 1 ? "" : "s"} again with it.`
          : r.busy.length
            ? "A recording is running; try again when it finishes."
            : null,
      ),
  });

  const rows = list.data ?? [];
  // Entries the voice already said right ("keep") are memory, not news.
  const shown = rows.filter((p) => p.say !== p.term);
  const toListen = shown.filter(needsListen).length;
  const sorted = [...shown].sort(
    (a, b) =>
      Number(needsListen(b)) - Number(needsListen(a)) ||
      a.term.localeCompare(b.term),
  );

  return (
    <section className="say-list">
      <button
        type="button"
        className="say-list-head"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        <Mic size={14} strokeWidth={1.75} /> How Steven says terms
        <span className="class-log-count">{shown.length}</span>
        {toListen > 0 && (
          <span className="say-list-flag">{toListen} worth a listen</span>
        )}
      </button>
      {open && (
        <div className="say-list-body">
          <p className="settings-hint">
            Learned when a reading is recorded. Write how a term should sound in
            plain syllables with spaces ("Keem Poe", not "keem-poh"); only the
            paragraphs that use it are recorded again.
          </p>
          {sorted.map((p) => (
            <SayRow
              key={p.id}
              p={p}
              audio={audio}
              onSaved={(id) => {
                refresh();
                rerecord.mutate(id);
              }}
              onRemoved={refresh}
            />
          ))}
          {list.isSuccess && shown.length === 0 && (
            <p className="glance-empty">
              No terms yet: they appear after a reading is recorded.
            </p>
          )}
          <form
            className="say-add"
            onSubmit={(e) => {
              e.preventDefault();
              if (term.trim() && say.trim()) add.mutate();
            }}
          >
            <input
              className="input"
              aria-label="Term"
              placeholder="Term (e.g. Quimpo)"
              value={term}
              onChange={(e) => setTerm(e.target.value)}
            />
            <input
              className="input"
              aria-label="Say it as"
              placeholder="Say it as (e.g. Keem Poe)"
              value={say}
              onChange={(e) => setSay(e.target.value)}
            />
            <button
              className="btn"
              disabled={add.isPending || !term.trim() || !say.trim()}
            >
              <Plus size={14} strokeWidth={2} /> Add
            </button>
          </form>
          {note && <p className="gen-hint">{note}</p>}
        </div>
      )}
      <audio ref={audio} hidden />
    </section>
  );
}

function SayRow({
  p,
  audio,
  onSaved,
  onRemoved,
}: {
  p: Pronunciation;
  audio: React.RefObject<HTMLAudioElement | null>;
  onSaved: (id: number) => void;
  onRemoved: () => void;
}) {
  const [value, setValue] = useState(p.say);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => api.patch(`/api/pronunciations/${p.id}`, { say: value }),
    onSuccess: () => onSaved(p.id),
    onError: (e) =>
      setError(e instanceof ApiError ? e.message : "Could not save"),
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/api/pronunciations/${p.id}`),
    onSuccess: onRemoved,
  });

  async function play() {
    if (!audio.current) return;
    setBusy(true);
    setError(null);
    try {
      // In a carrier sentence: this voice returns silence for a lone short line.
      await speak(
        `The next word is ${value.trim()}, as in this course.`,
        audio.current,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not play");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`say-row${needsListen(p) ? " listen" : ""}`}>
      <span className="say-term">{p.term}</span>
      <input
        className="input say-input"
        aria-label={`How Steven says ${p.term}`}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={() => value.trim() && value !== p.say && save.mutate()}
        onKeyDown={(e) =>
          e.key === "Enter" && (e.currentTarget as HTMLInputElement).blur()
        }
      />
      <span className="say-meta">
        {p.source === "user" ? "yours" : needsListen(p) ? "check" : "auto"}
      </span>
      <button
        type="button"
        className="icon-btn"
        onClick={play}
        disabled={busy || !value.trim()}
        aria-label={`Hear how Steven says ${p.term}`}
        title="Hear it"
      >
        {busy ? (
          <Loader2 size={14} className="spin" />
        ) : (
          <Play size={14} strokeWidth={1.75} />
        )}
      </button>
      <button
        type="button"
        className="icon-btn danger"
        onClick={() => remove.mutate()}
        aria-label={`Remove ${p.term}`}
        title="Remove (Steven reads it as written)"
      >
        <Trash2 size={13} strokeWidth={1.5} />
      </button>
      {error && <span className="error-text say-error">{error}</span>}
    </div>
  );
}
