import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ChevronDown,
  ChevronRight,
  GraduationCap,
  RotateCw,
  X,
} from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Markdown } from "../../components/Markdown";
import { api, type LectureOut } from "../../lib/api";
import { CitationPill, JobProgress, StalenessBadge, useGenerationJob } from "../ai/common";
import { lectureAudioUrl, LecturePlayer, type PlayerStatus } from "./LecturePlayer";
import type { CheckpointState } from "./spriteState";
import { createFrameStore, StevenLive, useBlink, useStevenDriver } from "./StevenStage";
import { usePrefersReducedMotion, useSpritesAvailable } from "./StevenSprite";
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
  onResult,
}: {
  artifactId: number;
  segmentIndex: number;
  checkpoint: { question: string; answer: string };
  onResult: (correct: boolean) => void;
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
                  onResult(true);
                }}
              >
                <Check size={14} strokeWidth={2} /> Got it
              </button>
              <button
                className="btn"
                onClick={() => {
                  setAnswered(false);
                  record.mutate(false);
                  onResult(false);
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

  // Steven's sprite (only when public/steven/ is installed — it isn't in git)
  const sprites = useSpritesAvailable();
  const reduced = usePrefersReducedMotion();
  const [store] = useState(createFrameStore);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [status, setStatus] = useState<PlayerStatus>({
    playing: false,
    current: 0,
    endedOn: null,
  });
  const [answered, setAnswered] = useState<Record<number, boolean>>({});
  const [lastAnswer, setLastAnswer] = useState<boolean | null>(null);
  const [floating, setFloating] = useState(false);
  const onStatus = useCallback((s: PlayerStatus) => {
    setStatus(s);
    if (s.playing) setLastAnswer(null); // the smile lasts until he talks again
  }, []);

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

  const cur = l?.segments[status.current];
  const checkpoint: CheckpointState =
    lastAnswer != null
      ? lastAnswer
        ? "correct"
        : "missed"
      : cur?.checkpoint && status.endedOn === cur.index && answered[cur.index] == null
        ? "waiting"
        : "none";
  useBlink(store, !!sprites && !reduced);
  useStevenDriver(store, {
    enabled: !!sprites && !!l,
    audioRef,
    playing: status.playing,
    segment: cur,
    url: l ? lectureAudioUrl(l, status.current) : null,
    nextUrl: l ? lectureAudioUrl(l, status.current + 1) : null,
    checkpoint,
    reduced,
  });

  if (!l && !gen.running) {
    return (
      <div className="teacher-tab">
        <div className="teacher-hero">
          {sprites ? (
            <div className="teacher-hero-steven">
              <StevenLive store={store} />
            </div>
          ) : sprites === false ? (
            <GraduationCap size={28} strokeWidth={1.25} />
          ) : null}
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

  const steven = !!sprites && !!l;
  return (
    <div className={`teacher-tab${steven ? " has-steven" : ""}`}>
      <div className="teacher-main">
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

            <LecturePlayer
              lecture={l}
              activeIndex={openSeg}
              onSeek={setOpenSeg}
              audioRef={audioRef}
              onStatus={onStatus}
              trailing={
                steven && (
                  <button
                    className="lecture-steven"
                    onClick={() => setFloating((v) => !v)}
                    aria-label={floating ? "Hide Steven" : "Show Steven"}
                    aria-pressed={floating}
                  >
                    <StevenLive store={store} variant="crop" />
                  </button>
                )
              }
            />

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
                            onResult={(correct) => {
                              setAnswered((m) => ({ ...m, [seg.index]: correct }));
                              setLastAnswer(correct);
                            }}
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
      {steven && (
        <aside className="teacher-steven" aria-hidden>
          <StevenLive store={store} />
        </aside>
      )}
      {/* portalled: an ancestor's transform would pin position: fixed to it */}
      {steven &&
        floating &&
        createPortal(
          <button
            className="steven-float"
            onClick={() => setFloating(false)}
            aria-label="Hide Steven"
          >
            <StevenLive store={store} />
          </button>,
          document.body,
        )}
    </div>
  );
}
