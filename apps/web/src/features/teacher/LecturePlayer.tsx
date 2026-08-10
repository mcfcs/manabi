import { Loader2, Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { LectureOut } from "../../lib/api";

const SPEEDS = [0.9, 1, 1.25, 1.5];

/** Single-audio-element lecture player: auto-advance, checkpoint pauses
 * happen naturally (segments end), MediaSession lockscreen controls. Hidden
 * until at least one segment has audio. */
export function LecturePlayer({
  lecture,
  activeIndex,
  onSeek,
}: {
  lecture: LectureOut;
  activeIndex: number | null;
  onSeek: (i: number) => void;
}) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(0);
  const [speed, setSpeed] = useState(1);

  const ready = lecture.segments.filter((s) => s.audio_ready);
  const anyAudio = ready.length > 0;
  const seg = lecture.segments[current];

  useEffect(() => {
    if (activeIndex != null && activeIndex !== current) setCurrent(activeIndex);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeIndex]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.playbackRate = speed;
  }, [speed, current]);

  useEffect(() => {
    if (!("mediaSession" in navigator) || !seg) return;
    navigator.mediaSession.metadata = new MediaMetadata({
      title: seg.title,
      artist: "Steven A. Starphase",
      album: lecture.title,
    });
    navigator.mediaSession.setActionHandler("previoustrack", () => skip(-1));
    navigator.mediaSession.setActionHandler("nexttrack", () => skip(1));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, seg?.title]);

  function skip(delta: number) {
    const next = Math.min(Math.max(current + delta, 0), lecture.segments.length - 1);
    setCurrent(next);
    onSeek(next);
    if (playing) {
      requestAnimationFrame(() => audioRef.current?.play().catch(() => undefined));
    }
  }

  function toggle() {
    const audio = audioRef.current;
    if (!audio) return;
    if (playing) {
      audio.pause();
      setPlaying(false);
    } else {
      audio.play().then(() => setPlaying(true)).catch(() => undefined);
    }
  }

  function onEnded() {
    const currentSeg = lecture.segments[current];
    const next = current + 1;
    // checkpoints pause the lecture: the student answers, then presses play
    if (currentSeg?.checkpoint || next >= lecture.segments.length) {
      setPlaying(false);
      if (currentSeg?.checkpoint) onSeek(current);
      return;
    }
    setCurrent(next);
    onSeek(next);
    requestAnimationFrame(() => audioRef.current?.play().catch(() => undefined));
  }

  if (!anyAudio) {
    return lecture.audio_job_active ? (
      <p className="teacher-voice-note">
        <Loader2 size={13} className="spin" /> Steven is recording the lecture —
        segments become playable as they finish.
      </p>
    ) : null;
  }

  return (
    <div className="lecture-player">
      <audio
        ref={audioRef}
        src={`/api/artifacts/${lecture.artifact_id}/audio/${current}`}
        onEnded={onEnded}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        preload="auto"
      />
      <button className="icon-btn" onClick={() => skip(-1)} aria-label="Previous segment">
        <SkipBack size={16} strokeWidth={1.5} />
      </button>
      <button
        className="btn btn-primary lecture-play"
        onClick={toggle}
        disabled={!seg?.audio_ready}
        aria-label={playing ? "Pause" : "Play"}
      >
        {playing ? (
          <Pause size={16} strokeWidth={1.75} />
        ) : (
          <Play size={16} strokeWidth={1.75} />
        )}
      </button>
      <button className="icon-btn" onClick={() => skip(1)} aria-label="Next segment">
        <SkipForward size={16} strokeWidth={1.5} />
      </button>
      <span className="lecture-now">
        {String(current + 1).padStart(2, "0")} · {seg?.title}
        {!seg?.audio_ready && " (rendering…)"}
      </span>
      <button
        className="btn lecture-speed mono"
        onClick={() => setSpeed(SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length])}
        title="Playback speed"
      >
        {speed}×
      </button>
    </div>
  );
}
