import { describe, expect, it } from "vitest";

import {
  lectureCues,
  MOUTH_MIN_MS,
  nextMouth,
  POINT_MS,
  restMouth,
  spriteStateFor,
  WRITE_MS,
} from "./spriteState";

const SPOKEN =
  "Let's begin with institutions. They are the rules of the game. " +
  "Remember, informal rules matter just as much. " +
  "As you can see on the board, money is a formal institution.";

describe("lectureCues", () => {
  it("places sentences, board mentions and key points by character position", () => {
    const c = lectureCues(SPOKEN, true, 10_000);
    expect(c.sentences.length).toBe(4);
    expect(c.sentences[0]).toBe(0);
    expect(c.board[0]).toBe(0); // board content arrives with the segment
    expect(c.board.length).toBe(2); // ...and the speech points at it later
    expect(c.board[1]).toBeGreaterThan(6000);
    expect(c.serious.length).toBe(1);
    const [a, b] = c.serious[0];
    expect(a).toBeGreaterThan(3000);
    expect(b).toBeLessThan(c.board[1] + 1);
  });

  it("never points without a board", () => {
    expect(lectureCues(SPOKEN, false, 10_000).board).toEqual([]);
  });
});

describe("spriteStateFor", () => {
  const cues = lectureCues(SPOKEN, true, 10_000);

  it("idles when nothing is playing", () => {
    expect(spriteStateFor({ playing: false, tMs: 0, cues, checkpoint: "none" })).toEqual({
      pose: "idle",
      face: "neutral",
    });
  });

  it("points at the board, then writes, when board content comes in", () => {
    expect(spriteStateFor({ playing: true, tMs: 100, cues, checkpoint: "none" }).pose).toBe("point");
    expect(
      spriteStateFor({ playing: true, tMs: POINT_MS + 100, cues, checkpoint: "none" }).pose,
    ).toBe("write");
    const after = POINT_MS + WRITE_MS + 100;
    expect(["explain", "idle"]).toContain(
      spriteStateFor({ playing: true, tMs: after, cues, checkpoint: "none" }).pose,
    );
  });

  it("alternates explain and idle by sentence while speaking", () => {
    const plain = lectureCues("One idea here. A second idea. A third idea.", false, 9000);
    const poses = plain.sentences.map(
      (t) => spriteStateFor({ playing: true, tMs: t + 10, cues: plain, checkpoint: "none" }).pose,
    );
    expect(poses).toEqual(["explain", "idle", "explain"]);
  });

  it("looks serious on a key-point line", () => {
    const [a] = cues.serious[0];
    expect(spriteStateFor({ playing: true, tMs: a + 50, cues, checkpoint: "none" }).face).toBe(
      "serious",
    );
  });

  it("thinks, curious then pondering, while a checkpoint waits", () => {
    const s = (waitingMs: number) =>
      spriteStateFor({ playing: false, tMs: 0, cues, checkpoint: "waiting", waitingMs });
    expect(s(500)).toEqual({ pose: "think", face: "curious" });
    expect(s(9000)).toEqual({ pose: "think", face: "thinking" });
  });

  it("smiles at a correct answer", () => {
    expect(spriteStateFor({ playing: false, tMs: 0, cues, checkpoint: "correct" }).face).toBe(
      "smile",
    );
  });
});

describe("nextMouth", () => {
  const run = (levels: number[], step = 80, rand = () => 0.9) => {
    let m = restMouth(0);
    const out: string[] = [];
    levels.forEach((lv, i) => {
      m = nextMouth(m, lv, (i + 1) * step, rand);
      out.push(m.mouth);
    });
    return out;
  };

  it("opens with the voice and closes in silence", () => {
    const out = run([0, 0.9, 0.9, 0.9, 0.3, 0.3, 0, 0, 0, 0]);
    expect(out[0]).toBe("closed");
    expect(out).toContain("a");
    expect(out.at(-1)).toBe("closed");
  });

  it("does not flicker on a level sitting at a threshold", () => {
    const out = run(Array.from({ length: 20 }, (_, i) => (i % 2 ? 0.17 : 0.15)));
    const changes = out.filter((v, i) => i > 0 && v !== out[i - 1]).length;
    expect(changes).toBeLessThanOrEqual(1);
  });

  it("never changes faster than the frame cap", () => {
    let m = restMouth(0);
    const times: number[] = [];
    for (let t = 16; t < 2000; t += 16) {
      const prev = m.mouth;
      m = nextMouth(m, t % 64 < 32 ? 0.95 : 0, t);
      if (m.mouth !== prev) times.push(t);
    }
    const gaps = times.slice(1).map((t, i) => t - times[i]);
    expect(Math.min(...gaps)).toBeGreaterThanOrEqual(MOUTH_MIN_MS);
  });

  it("rounds to an 'o' now and then on a long loud stretch", () => {
    const out = run(Array(30).fill(0.95), 80, () => 0.1);
    expect(out).toContain("o");
  });
});
