import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ChevronDown,
  ChevronRight,
  GraduationCap,
  RotateCw,
  X,
} from "lucide-react";
import { useState } from "react";

import { Markdown } from "../../components/Markdown";
import { api, type LectureOut } from "../../lib/api";
import { CitationPill, JobProgress, StalenessBadge, useGenerationJob } from "../ai/common";
import { LecturePlayer } from "./LecturePlayer";
import "./teacher.css";

const MODES = [
  { key: "standard", label: "Standard", hint: "a full taught lesson" },
  { key: "cram", label: "Exam cram", hint: "essentials only, ~⅓ length" },
  { key: "deep_dive", label: "Deep dive", hint: "extra intuition and examples" },
];

function Checkpoint({
  artifactId,
  segmentIndex,
  checkpoint,
}: {
  artifactId: number;
  segmentIndex: number;
  checkpoint: { question: string; answer: string };
}) {
  const [revealed, setRevealed] = useState(false);
  const [answered, setAnswered] = useState<boolean | null>(null);
  const record = useMutation({
    mutationFn: (correct: boolean) =>
      api.post(`/api/artifacts/${artifactId}/checkpoints/${segmentIndex}`, {
        correct,
      }),
  });
  return (
    <div className="checkpoint">
      <span className="checkpoint-label">Checkpoint</span>
      <p className="checkpoint-q">{checkpoint.question}</p>
      {!revealed ? (
        <button className="btn" onClick={() => setRevealed(true)}>
          Reveal Steven's answer
        </button>
      ) : (
        <>
          <p className="checkpoint-a">{checkpoint.answer}</p>
          {answered === null ? (
            <div className="checkpoint-selfgrade">
              <span>Did you have it?</span>
              <button
                className="btn"
                onClick={() => {
                  setAnswered(true);
                  record.mutate(true);
                }}
              >
                <Check size={14} strokeWidth={2} /> Got it
              </button>
              <button
                className="btn"
                onClick={() => {
                  setAnswered(false);
                  record.mutate(false);
                }}
              >
                <X size={14} strokeWidth={2} /> Missed it
              </button>
            </div>
          ) : (
            <p className="checkpoint-recorded">
              {answered ? "Noted. Onward." : "Noted — Steven will circle back to this."}
            </p>
          )}
        </>
      )}
    </div>
  );
}

export function TeacherTab({ moduleId }: { moduleId: string }) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState("standard");
  const [openSeg, setOpenSeg] = useState<number | null>(0);

  const lecture = useQuery({
    queryKey: ["lecture", moduleId],
    queryFn: () => api.get<LectureOut | null>(`/api/modules/${moduleId}/lecture`),
    refetchInterval: (q) => (q.state.data?.audio_job_active ? 4000 : false),
  });

  const gen = useGenerationJob(moduleId, "teach_module", () => {
    queryClient.invalidateQueries({ queryKey: ["lecture", moduleId] });
  });

  const generate = useMutation({
    mutationFn: () =>
      api.post<{ job_id: number }>(`/api/modules/${moduleId}/lecture/generate`, {
        mode,
      }),
    onSuccess: (r) => gen.start(r.job_id),
  });
  const remediate = useMutation({
    mutationFn: () =>
      api.post<{ job_id: number }>(`/api/modules/${moduleId}/lecture/remediate`),
    onSuccess: (r) => gen.start(r.job_id),
  });
  const genAudio = useMutation({
    mutationFn: (artifactId: number) =>
      api.post(`/api/artifacts/${artifactId}/audio/generate`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["lecture", moduleId] }),
  });

  const l = lecture.data;

  if (!l && !gen.running) {
    return (
      <div className="teacher-tab">
        <div className="teacher-hero">
          <GraduationCap size={28} strokeWidth={1.25} />
          <h2>Have Steven teach this module</h2>
          <p>
            A structured lecture over your materials — explained, not read
            aloud, with checkpoint questions along the way.
          </p>
          <div className="teacher-modes">
            {MODES.map((m) => (
              <button
                key={m.key}
                className={`teacher-mode${mode === m.key ? " on" : ""}`}
                onClick={() => setMode(m.key)}
              >
                <b>{m.label}</b>
                <span>{m.hint}</span>
              </button>
            ))}
          </div>
          <button
            className="btn btn-primary"
            onClick={() => generate.mutate()}
            disabled={generate.isPending}
          >
            Start the lecture
          </button>
          {generate.isError && (
            <p className="error-text">{(generate.error as Error).message}</p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="teacher-tab">
      {l && (
        <>
          <header className="teacher-head">
            <div className="teacher-head-text">
              <h2>{l.title}</h2>
              <span className="teacher-meta">
                {MODES.find((m) => m.key === l.mode)?.label ?? l.mode} ·{" "}
                {l.model_name} <StalenessBadge staleness={l.staleness as never} />
              </span>
            </div>
            <button
              className="btn"
              onClick={() => remediate.mutate()}
              disabled={remediate.isPending}
              title="Re-teach the topics whose checkpoints you missed"
            >
              Review weak spots
            </button>
            <button
              className="icon-btn"
              onClick={() => generate.mutate()}
              aria-label="Regenerate lecture"
              title="Regenerate lecture"
            >
              <RotateCw size={15} strokeWidth={1.5} />
            </button>
          </header>
          {remediate.isError && (
            <p className="gen-hint">{(remediate.error as Error).message}</p>
          )}

          {!l.voice_available && (
            <p className="teacher-voice-note">
              Voice not set up yet — reading mode. Once the TTS service is
              configured on the AI node, lectures get Steven's voice.
            </p>
          )}
          {/* Configured but nothing rendered and no job running → synthesis
              likely failed (e.g. the TTS server is offline). Offer a retry. */}
          {l.voice_available &&
            !l.audio_job_active &&
            !l.segments.some((s) => s.audio_ready) && (
              <div className="teacher-voice-note teacher-voice-retry">
                <span>
                  Steven's voice isn't ready — the TTS server may be offline.
                </span>
                <button
                  className="btn"
                  onClick={() => genAudio.mutate(l.artifact_id)}
                  disabled={genAudio.isPending}
                >
                  {genAudio.isPending ? "Starting…" : "Generate voice"}
                </button>
              </div>
            )}

          <LecturePlayer lecture={l} activeIndex={openSeg} onSeek={setOpenSeg} />

          <div className="teacher-segments">
            {l.segments.map((seg) => {
              const open = openSeg === seg.index;
              return (
                <section
                  key={seg.index}
                  className={`teacher-seg${open ? " open" : ""}`}
                  id={`seg-${seg.index}`}
                >
                  <button
                    className="teacher-seg-head"
                    onClick={() => setOpenSeg(open ? null : seg.index)}
                    aria-expanded={open}
                  >
                    {open ? (
                      <ChevronDown size={15} strokeWidth={1.75} />
                    ) : (
                      <ChevronRight size={15} strokeWidth={1.75} />
                    )}
                    <span className="teacher-seg-no mono">
                      {String(seg.index + 1).padStart(2, "0")}
                    </span>
                    <span className="teacher-seg-title">{seg.title}</span>
                  </button>
                  {open && (
                    <div className="teacher-seg-body">
                      <p className="teacher-spoken">{seg.spoken_text}</p>
                      {seg.display_text && (
                        <div className="teacher-board">
                          <span className="teacher-board-label">On the board</span>
                          <Markdown className="teacher-board-md">
                            {seg.display_text}
                          </Markdown>
                        </div>
                      )}
                      {seg.citations.length > 0 && (
                        <div className="teacher-cites">
                          {seg.citations.map((c) => (
                            <CitationPill key={c.id} citation={c} />
                          ))}
                        </div>
                      )}
                      {seg.checkpoint && (
                        <Checkpoint
                          artifactId={l.artifact_id}
                          segmentIndex={seg.index}
                          checkpoint={seg.checkpoint as never}
                        />
                      )}
                    </div>
                  )}
                </section>
              );
            })}
          </div>
        </>
      )}
      {gen.running && <JobProgress job={gen.job} />}
    </div>
  );
}
