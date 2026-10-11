/** What Steven's teaching sprite shows — pure, so it is tested without a DOM.
 *
 * Lecture segments carry no word timings, so moments in the speech are placed
 * by character position: a sentence that starts 40% of the way through the
 * text is assumed to start 40% of the way through the audio. Close enough for
 * a gesture; lip-sync uses the real audio (see nextMouth). */

export type Pose = "idle" | "explain" | "think" | "write" | "point";
export type Face = "neutral" | "smile" | "curious" | "serious" | "thinking";
export type Mouth = "closed" | "open" | "a" | "o";

export type CheckpointState = "none" | "waiting" | "correct" | "missed";

export interface LectureCues {
  /** start of each sentence, ms */
  sentences: number[];
  /** moments to point at the board, then write, ms */
  board: number[];
  /** [start, end) of key-point / warning sentences, ms */
  serious: [number, number][];
}

export const POINT_MS = 1600;
export const WRITE_MS = 2400;
const CURIOUS_MS = 4000;

const BOARD_WORDS =
  /\b(on the board|the board|written|i've written|i wrote|as you can see|look at|take a look|see here|here's|right here|this diagram|this table|this list)\b/i;
const SERIOUS_WORDS =
  /\b(key point|important|crucial|remember|don't forget|do not forget|careful|be careful|watch out|warning|common mistake|mistake|pitfall|never|must)\b/i;

/** Sentence-level cues for one segment's speech. */
export function lectureCues(spoken: string, hasBoard: boolean, durationMs: number): LectureCues {
  const text = spoken ?? "";
  const sentences: { start: number; end: number; text: string }[] = [];
  const re = /[^.!?]+[.!?]*\s*/g;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (!m[0].trim()) continue;
    sentences.push({ start: m.index, end: m.index + m[0].length, text: m[0] });
  }
  const len = Math.max(1, text.length);
  const at = (chars: number) => Math.round((chars / len) * Math.max(0, durationMs));
  const board: number[] = [];
  if (hasBoard) board.push(0);
  const serious: [number, number][] = [];
  for (const s of sentences) {
    if (hasBoard && BOARD_WORDS.test(s.text)) {
      const t = at(s.start);
      if (!board.some((b) => Math.abs(b - t) < POINT_MS + WRITE_MS)) board.push(t);
    }
    if (SERIOUS_WORDS.test(s.text)) serious.push([at(s.start), at(s.end)]);
  }
  return { sentences: sentences.map((s) => at(s.start)), board, serious };
}

export interface SpriteInput {
  playing: boolean;
  /** ms into the current segment's audio */
  tMs: number;
  cues: LectureCues | null;
  checkpoint: CheckpointState;
  /** ms since the checkpoint started waiting for an answer */
  waitingMs?: number;
}

export interface SpriteState {
  pose: Pose;
  face: Face;
}

/** The pose and face for the lecture's current moment. */
export function spriteStateFor(input: SpriteInput): SpriteState {
  const { playing, tMs, cues, checkpoint } = input;
  if (!playing) {
    if (checkpoint === "waiting")
      return { pose: "think", face: (input.waitingMs ?? 0) < CURIOUS_MS ? "curious" : "thinking" };
    if (checkpoint === "correct") return { pose: "idle", face: "smile" };
    return { pose: "idle", face: "neutral" };
  }
  if (!cues) return { pose: "explain", face: "neutral" };
  const face: Face = cues.serious.some(([a, b]) => tMs >= a && tMs < b) ? "serious" : "neutral";
  for (const b of cues.board) {
    if (tMs >= b && tMs < b + POINT_MS) return { pose: "point", face };
    if (tMs >= b + POINT_MS && tMs < b + POINT_MS + WRITE_MS) return { pose: "write", face };
  }
  // alternate by sentence so a gesture lasts a thought, not a fixed beat
  let k = 0;
  for (let i = 0; i < cues.sentences.length; i++) if (cues.sentences[i] <= tMs) k = i;
  return { pose: k % 2 === 0 ? "explain" : "idle", face };
}

// ── Lip-sync ──────────────────────────────────────────────────────────────

export const MOUTH_LOW = 0.16; // below: closed
export const MOUTH_HIGH = 0.48; // above: wide "a"
const HYSTERESIS = 0.05;
export const MOUTH_MIN_MS = 70; // ≤ ~14 changes per second
const LOUD_FOR_O_MS = 420; // a long loud stretch earns an occasional "o"

export interface MouthMachine {
  mouth: Mouth;
  changedAt: number;
  loudSince: number | null;
  smooth: number;
}

export const restMouth = (now = 0): MouthMachine => ({
  mouth: "closed",
  changedAt: now,
  loudSince: null,
  smooth: 0,
});

/** One frame of the mouth: smooth the level, map it with hysteresis, never
 * change faster than MOUTH_MIN_MS, and swap "a" for "o" now and then on long
 * loud stretches so it doesn't look mechanical. `rand` is injected for tests. */
export function nextMouth(
  prev: MouthMachine,
  level: number,
  now: number,
  rand: () => number = Math.random,
): MouthMachine {
  const smooth = prev.smooth + (level - prev.smooth) * (level > prev.smooth ? 0.6 : 0.35);
  const lowCut = prev.mouth === "closed" ? MOUTH_LOW + HYSTERESIS : MOUTH_LOW - HYSTERESIS;
  const highCut = prev.mouth === "a" || prev.mouth === "o" ? MOUTH_HIGH - HYSTERESIS : MOUTH_HIGH + HYSTERESIS;
  let want: Mouth = smooth < lowCut ? "closed" : smooth < highCut ? "open" : "a";
  const loudSince = want === "a" ? (prev.loudSince ?? now) : null;
  if (want === "a" && loudSince !== null && now - loudSince > LOUD_FOR_O_MS) {
    want = prev.mouth === "o" ? (rand() < 0.5 ? "a" : "o") : rand() < 0.35 ? "o" : "a";
  }
  if (want === prev.mouth || now - prev.changedAt < MOUTH_MIN_MS) {
    return { ...prev, smooth, loudSince };
  }
  return { mouth: want, changedAt: now, loudSince, smooth };
}
