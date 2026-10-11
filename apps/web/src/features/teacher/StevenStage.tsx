import { useEffect, useRef, useSyncExternalStore, type RefObject } from "react";

import type { LectureSegmentOut } from "../../lib/api";
import { levelAt, loadEnvelope } from "./envelope";
import {
  lectureCues,
  nextMouth,
  restMouth,
  spriteStateFor,
  type CheckpointState,
  type LectureCues,
  type MouthMachine,
} from "./spriteState";
import { StevenSprite, type SpriteFrame } from "./StevenSprite";

/** The sprite's current frame lives outside React state: the mouth changes up
 * to ~14 times a second, and only the sprites subscribed to the store should
 * re-render for it — not the whole lecture. */
export interface FrameStore {
  get: () => SpriteFrame;
  set: (patch: Partial<SpriteFrame>) => void;
  subscribe: (cb: () => void) => () => void;
}

export function createFrameStore(): FrameStore {
  let frame: SpriteFrame = {
    pose: "idle",
    face: "neutral",
    mouth: "closed",
    blink: false,
  };
  const subs = new Set<() => void>();
  return {
    get: () => frame,
    set(patch) {
      const keys = Object.keys(patch) as (keyof SpriteFrame)[];
      if (!keys.some((k) => patch[k] !== frame[k])) return;
      frame = { ...frame, ...patch };
      subs.forEach((cb) => cb());
    },
    subscribe(cb) {
      subs.add(cb);
      return () => subs.delete(cb);
    },
  };
}

export function StevenLive({ store, variant }: { store: FrameStore; variant?: "full" | "crop" }) {
  const frame = useSyncExternalStore(store.subscribe, store.get, store.get);
  return <StevenSprite frame={frame} variant={variant} />;
}

/** Eyes shut for ~120 ms every 2.5–6 s, at random. */
export function useBlink(store: FrameStore, enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;
    let t = 0;
    const schedule = () => {
      t = window.setTimeout(
        () => {
          store.set({ blink: true });
          t = window.setTimeout(() => {
            store.set({ blink: false });
            schedule();
          }, 120);
        },
        2500 + Math.random() * 3500,
      );
    };
    schedule();
    return () => {
      window.clearTimeout(t);
      store.set({ blink: false });
    };
  }, [store, enabled]);
}

export interface StageInput {
  enabled: boolean;
  audioRef: RefObject<HTMLAudioElement | null>;
  playing: boolean;
  segment: LectureSegmentOut | undefined;
  /** the playing segment's audio, and the next one's (decoded ahead) */
  url: string | null;
  nextUrl: string | null;
  checkpoint: CheckpointState;
  /** prefers-reduced-motion: poses only, no lip-sync */
  reduced: boolean;
}

/** Drives pose, face and mouth from the lecture's moment. While audio plays,
 * a rAF loop reads `audio.currentTime` (media time, so playbackRate is
 * already in it) for the pose cues and the loudness envelope. */
export function useStevenDriver(store: FrameStore, input: StageInput) {
  const { enabled, audioRef, playing, segment, url, nextUrl, checkpoint, reduced } = input;
  const env = useRef<Float32Array | null>(null);
  const waitingSince = useRef<number | null>(null);

  useEffect(() => {
    env.current = null;
    if (!enabled || reduced || !url) return;
    let live = true;
    void loadEnvelope(url).then((e) => {
      if (live) env.current = e;
    });
    if (nextUrl) void loadEnvelope(nextUrl);
    return () => {
      live = false;
    };
  }, [enabled, reduced, url, nextUrl]);

  // primitives, not the segment object: the lecture query refetches while
  // audio renders, and a new object must not restart the loop
  const index = segment?.index;
  const spoken = segment?.spoken_text ?? "";
  const hasBoard = !!segment?.display_text?.trim();
  const durationMs = segment?.duration_ms ?? 0;

  useEffect(() => {
    if (!enabled) return;
    if (checkpoint === "waiting") waitingSince.current ??= performance.now();
    else waitingSince.current = null;

    let cueKey = "";
    let cues: LectureCues | null = null;
    let mouth: MouthMachine = restMouth(performance.now());
    let raf = 0;

    const tick = () => {
      const now = performance.now();
      const audio = audioRef.current;
      const sec = audio?.currentTime ?? 0;
      const dur =
        audio && Number.isFinite(audio.duration) && audio.duration > 0
          ? audio.duration * 1000
          : durationMs;
      const key = `${index}:${Math.round(dur)}`;
      if (key !== cueKey) {
        cueKey = key;
        cues = index == null ? null : lectureCues(spoken, hasBoard, dur);
      }
      const { pose, face } = spriteStateFor({
        playing,
        tMs: sec * 1000,
        cues,
        checkpoint,
        waitingMs: waitingSince.current == null ? 0 : now - waitingSince.current,
      });
      mouth =
        playing && !reduced ? nextMouth(mouth, levelAt(env.current, sec), now) : restMouth(now);
      store.set({ pose, face, mouth: mouth.mouth });
      if (playing) raf = requestAnimationFrame(tick);
    };
    tick();
    // a waiting checkpoint turns from curious to pondering on its own
    const poll = !playing && checkpoint === "waiting" ? window.setInterval(tick, 500) : 0;
    return () => {
      cancelAnimationFrame(raf);
      window.clearInterval(poll);
      store.set({ mouth: "closed" });
    };
  }, [store, enabled, audioRef, playing, index, spoken, hasBoard, durationMs, checkpoint, reduced]);
}
