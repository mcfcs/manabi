import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronUp,
  Headphones,
  ListOrdered,
  Loader2,
  LocateFixed,
  Pause,
  Play,
  SkipBack,
  SkipForward,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, type NarrationOut, type NarrationSegmentOut } from "../../lib/api";
import "./narration.css";

const SPEEDS = [0.9, 1, 1.25, 1.5];
const GAP_MS = 450; // between paragraphs
const GAP_HEADING_MS = 900; // before a heading / the title

function fmt(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  const mm = h ? String(m % 60).padStart(2, "0") : String(m);
  return `${h ? `${h}:` : ""}${mm}:${String(s % 60).padStart(2, "0")}`;
}

function audioUrl(seg: NarrationSegmentOut): string {
  return `/api/narration/segments/${seg.id}/audio?v=${seg.audio_id ?? 0}`;
}

const KIND_LABEL: Record<string, string> = {
  title: "Title",
  abstract: "Abstract",
  heading: "Section",
  paragraph: "",
  caption: "Caption",
};

/** Steven reads the document: a pinned player with a teleprompter line,
 * paragraph-level prev/next, speed, page follow and a resume point. Audio
 * comes per segment as the GPU worker records it; playback waits at the
 * first segment that is not ready yet instead of skipping it. The teleprompter
 * expands to the whole paragraph, and a Script panel lists every paragraph
 * (tap one to jump there). */
export function NarrationBar({
  documentId,
  onGoToPage,
  onClose,
}: {
  documentId: string;
  onGoToPage: (page: number) => void;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const storageKey = `manabi-narration-${documentId}`;
  const narration = useQuery({
    queryKey: ["narration", documentId],
    queryFn: () => api.get<NarrationOut>(`/api/documents/${documentId}/narration`),
    refetchInterval: (q) => (q.state.data?.job_active ? 4000 : false),
  });
  const prepare = useMutation({
    mutationFn: (force: boolean) =>
      api.post<{ job_id: number | null; segment_count: number; status: string }>(
        `/api/documents/${documentId}/narration/prepare`,
        { force },
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["narration", documentId] }),
  });

  const segments = narration.data?.segments ?? [];
  const [current, setCurrent] = useState<number>(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      return raw ? Math.max(0, Number(raw) || 0) : 0;
    } catch {
      return 0;
    }
  });
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [follow, setFollow] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [scriptOpen, setScriptOpen] = useState(false);
  const [position, setPosition] = useState(0); // ms into the current segment
  const audioRef = useRef<HTMLAudioElement>(null);
  const gapTimer = useRef<number | null>(null);
  const prefetch = useRef<HTMLAudioElement | null>(null);
  const currentItemRef = useRef<HTMLButtonElement>(null);

  const index = Math.min(current, Math.max(0, segments.length - 1));
  const seg = segments[index];
  const next = segments[index + 1];
  const waiting = playing && seg && !seg.audio_ready;

  // The expanded paragraph and the full script are mutually exclusive so the
  // bar never stacks both and swallows the page.
  function toggleExpanded() {
    const on = !expanded;
    setExpanded(on);
    if (on) setScriptOpen(false);
  }
  function toggleScript() {
    const on = !scriptOpen;
    setScriptOpen(on);
    if (on) setExpanded(false);
  }

  // Elapsed = durations of everything before + position inside the current one.
  const elapsedBefore = useMemo(
    () => segments.slice(0, index).reduce((sum, s) => sum + (s.duration_ms ?? 0), 0),
    [segments, index],
  );
  const total = narration.data?.total_ms ?? 0;

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, String(index));
    } catch {
      /* private mode */
    }
  }, [index, storageKey]);

  // Page follow: jump the viewer to the segment's page as we advance.
  useEffect(() => {
    if (follow && seg) onGoToPage(seg.page_no);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seg?.id, follow]);

  // Keep the current paragraph in view inside the Script panel.
  useEffect(() => {
    if (scriptOpen) currentItemRef.current?.scrollIntoView({ block: "nearest" });
  }, [scriptOpen, index]);

  // Load + play the current segment when it has audio.
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !seg) return;
    if (!seg.audio_ready) {
      audio.removeAttribute("src");
      return;
    }
    const url = audioUrl(seg);
    if (audio.dataset.url !== url) {
      audio.src = url;
      audio.dataset.url = url;
      audio.load();
    }
    audio.playbackRate = speed;
    if (playing) void audio.play().catch(() => setPlaying(false));
    else audio.pause();
  }, [seg?.id, seg?.audio_ready, playing, speed]);

  // Prefetch the next clip so segment changes are seamless.
  useEffect(() => {
    if (next?.audio_ready) {
      const a = new Audio();
      a.preload = "auto";
      a.src = audioUrl(next);
      prefetch.current = a;
    }
    return () => {
      prefetch.current = null;
    };
  }, [next?.id, next?.audio_ready]);

  const go = useCallback(
    (i: number) => {
      if (gapTimer.current) window.clearTimeout(gapTimer.current);
      gapTimer.current = null;
      setPosition(0);
      setCurrent(Math.max(0, Math.min(i, Math.max(0, segments.length - 1))));
    },
    [segments.length],
  );

  const onEnded = () => {
    if (!next) {
      setPlaying(false);
      return;
    }
    const gap = next.kind === "heading" || next.kind === "title" ? GAP_HEADING_MS : GAP_MS;
    gapTimer.current = window.setTimeout(() => go(index + 1), gap / speed);
  };

  useEffect(
    () => () => {
      if (gapTimer.current) window.clearTimeout(gapTimer.current);
    },
    [],
  );

  // MediaSession: lock-screen / headset controls.
  useEffect(() => {
    if (!("mediaSession" in navigator) || !seg) return;
    navigator.mediaSession.metadata = new MediaMetadata({
      title: seg.kind === "heading" ? seg.text : `${index + 1} / ${segments.length}`,
      artist: "Steven A. Starphase",
      album: "Manabi · reading",
    });
    navigator.mediaSession.setActionHandler("previoustrack", () => go(index - 1));
    navigator.mediaSession.setActionHandler("nexttrack", () => go(index + 1));
    navigator.mediaSession.setActionHandler("play", () => setPlaying(true));
    navigator.mediaSession.setActionHandler("pause", () => setPlaying(false));
  }, [seg, index, segments.length, go]);

  const data = narration.data;
  if (!data) {
    return (
      <div className="narration-bar">
        <Loader2 size={14} className="spin" /> Loading narration…
      </div>
    );
  }

  const notPrepared = data.status == null || data.segment_count === 0;
  const recording = data.job_active;

  return (
    <div className="narration-bar" role="region" aria-label="Steven narrates">
      {scriptOpen && !notPrepared && (
        <div className="narration-script" role="list" aria-label="Full script">
          {segments.map((s, i) => (
            <button
              key={s.id}
              ref={i === index ? currentItemRef : undefined}
              role="listitem"
              className={
                "narration-script-item" +
                (i === index ? " current" : "") +
                (s.audio_ready ? "" : " pending") +
                (s.kind === "heading" || s.kind === "title" ? " is-heading" : "")
              }
              onClick={() => {
                go(i);
                setPlaying(true);
              }}
              title={s.audio_ready ? "Play from here" : "Not recorded yet"}
            >
              <span className="narration-script-meta mono">
                {i + 1} · p{s.page_no}
                {KIND_LABEL[s.kind] ? ` · ${KIND_LABEL[s.kind]}` : ""}
                {s.audio_ready ? "" : " · recording…"}
              </span>
              <span className="narration-script-text">{s.text}</span>
            </button>
          ))}
        </div>
      )}

      <div className="narration-row">
        <span className="narration-brand" title="Steven narrates this reading">
          <Headphones size={15} strokeWidth={1.75} />
        </span>

        {notPrepared ? (
          <div className="narration-prepare">
            {!data.voice_available ? (
              <span className="narration-hint">Steven's voice is offline right now.</span>
            ) : (
              <>
                <span className="narration-hint">
                  Steven can read this to you — headers, footnotes and the bibliography are
                  skipped.
                </span>
                <button
                  className="btn btn-primary"
                  onClick={() => prepare.mutate(false)}
                  disabled={prepare.isPending || recording}
                >
                  {prepare.isPending || recording ? (
                    <Loader2 size={14} className="spin" />
                  ) : (
                    <Play size={14} strokeWidth={2} />
                  )}{" "}
                  Listen
                </button>
              </>
            )}
          </div>
        ) : (
          <>
            <div className="narration-controls">
              <button
                className="icon-btn"
                onClick={() => go(index - 1)}
                disabled={index === 0}
                aria-label="Previous paragraph"
                title="Previous paragraph"
              >
                <SkipBack size={16} strokeWidth={1.75} />
              </button>
              <button
                className="icon-btn narration-play"
                onClick={() => setPlaying((p) => !p)}
                aria-label={playing ? "Pause" : "Play"}
                title={playing ? "Pause" : "Play"}
              >
                {waiting ? (
                  <Loader2 size={18} className="spin" />
                ) : playing ? (
                  <Pause size={18} strokeWidth={2} />
                ) : (
                  <Play size={18} strokeWidth={2} />
                )}
              </button>
              <button
                className="icon-btn"
                onClick={() => go(index + 1)}
                disabled={!next}
                aria-label="Next paragraph"
                title="Next paragraph"
              >
                <SkipForward size={16} strokeWidth={1.75} />
              </button>
              <button
                className="btn narration-speed mono"
                onClick={() => setSpeed(SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length])}
                title="Playback speed"
              >
                {speed}×
              </button>
              <button
                className={`icon-btn${follow ? " active" : ""}`}
                onClick={() => setFollow((f) => !f)}
                aria-pressed={follow}
                title={follow ? "Following the page (click to stop)" : "Follow the page"}
              >
                <LocateFixed size={16} strokeWidth={1.75} />
              </button>
              <button
                className={`icon-btn${scriptOpen ? " active" : ""}`}
                onClick={toggleScript}
                aria-pressed={scriptOpen}
                aria-label="Full script"
                title={scriptOpen ? "Hide the full script" : "Show the full script"}
              >
                <ListOrdered size={16} strokeWidth={1.75} />
              </button>
            </div>

            <div
              className={`narration-prompter${expanded ? " expanded" : ""}`}
              onClick={toggleExpanded}
              title={expanded ? "Collapse" : "Show the whole paragraph"}
            >
              <span className="narration-meta mono">
                {KIND_LABEL[seg?.kind ?? ""] ? `${KIND_LABEL[seg?.kind ?? ""]} · ` : ""}
                p{seg?.page_no} · {index + 1}/{segments.length} · {fmt(elapsedBefore + position)}
                {total ? ` / ${fmt(total)}` : ""}
                {recording
                  ? ` · Steven is recording ${data.ready_count}/${data.segment_count}`
                  : waiting
                    ? " · waiting for this paragraph…"
                    : ""}
              </span>
              <p className={`narration-text${seg?.kind === "heading" ? " is-heading" : ""}`}>
                {seg?.text}
              </p>
            </div>
            <button
              className="icon-btn narration-expand"
              onClick={toggleExpanded}
              aria-expanded={expanded}
              aria-label={expanded ? "Collapse paragraph" : "Expand paragraph"}
              title={expanded ? "Collapse" : "Show the whole paragraph"}
            >
              {expanded ? (
                <ChevronDown size={16} strokeWidth={1.75} />
              ) : (
                <ChevronUp size={16} strokeWidth={1.75} />
              )}
            </button>
          </>
        )}

        <button className="icon-btn narration-close" onClick={onClose} aria-label="Hide narration">
          ×
        </button>
      </div>

      {recording && data.segment_count > 0 && (
        <div className="narration-progress" aria-hidden>
          <span style={{ width: `${Math.round((100 * data.ready_count) / data.segment_count)}%` }} />
        </div>
      )}

      <audio
        ref={audioRef}
        preload="auto"
        onEnded={onEnded}
        onTimeUpdate={(e) => setPosition(Math.round(e.currentTarget.currentTime * 1000))}
        onPlay={() => setPlaying(true)}
        onPause={() => {
          if (!audioRef.current?.ended) setPlaying(false);
        }}
      />
    </div>
  );
}
