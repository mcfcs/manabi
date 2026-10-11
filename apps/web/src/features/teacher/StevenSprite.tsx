import { useEffect, useRef, useState } from "react";

import type { Face, Mouth, Pose } from "./spriteState";

/** Steven's layered teaching sprite.
 *
 * Every layer is mounted once and only its visibility changes, so a pose or
 * mouth swap never waits on a decode and never flashes. Poses are full cut-out
 * frames; face, mouth and eye patches stack on the head, which is the same
 * pixels on every pose — `pose-point` is the idle frame slid 220 px right, so
 * the head layers slide with it.
 *
 * The PNGs live in public/steven/ but are NOT in git (a real show's
 * character): `useSpritesAvailable` probes for them, and the Teacher tab falls
 * back to its plain UI when they are missing. */

export const POSES: Pose[] = ["idle", "explain", "think", "write", "point"];
export const FACES: Face[] = ["neutral", "smile", "curious", "serious", "thinking"];
const MOUTH_LAYERS: Exclude<Mouth, "closed">[] = ["open", "a", "o"];

const FRAME_W = 896;
const POINT_SHIFT = 220; // px, in frame pixels
const POINT_SHIFT_PCT = `${(POINT_SHIFT / FRAME_W) * 100}%`;

// Ask with the smallest layer (17 KB, needed anyway), not a 600 KB pose. The
// server answers a missing file with index.html and a 200, so only an image
// counts; it refuses HEAD, hence a GET.
let probe: Promise<boolean> | null = null;
function probeSprites(): Promise<boolean> {
  const url = "/steven/layers/eyes-closed.png";
  probe ??= fetch(url)
    .then((r) => r.ok && (r.headers.get("content-type") ?? "").startsWith("image/"))
    .catch(async () => {
      try {
        return !!(await caches.match(url));
      } catch {
        return false;
      }
    });
  return probe;
}

/** null while checking, then whether /steven/ is installed. */
export function useSpritesAvailable(): boolean | null {
  const [ok, setOk] = useState<boolean | null>(null);
  useEffect(() => {
    let live = true;
    void probeSprites().then((v) => live && setOk(v));
    return () => {
      live = false;
    };
  }, []);
  return ok;
}

const MODE_KEY = "manabi-steven";

/** Steven mode, per device: on unless switched off on this browser (a phone
 * can skip the sprites while the laptop keeps him). */
export function useStevenMode(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(() => {
    try {
      return localStorage.getItem(MODE_KEY) !== "0";
    } catch {
      return true;
    }
  });
  const set = (v: boolean) => {
    try {
      localStorage.setItem(MODE_KEY, v ? "1" : "0");
    } catch {
      // private mode: still applies for this visit
    }
    setOn(v);
  };
  return [on, set];
}

export function usePrefersReducedMotion(): boolean {
  const query = "(prefers-reduced-motion: reduce)";
  const [reduced, setReduced] = useState(
    () => typeof window !== "undefined" && window.matchMedia(query).matches,
  );
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setReduced(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return reduced;
}

export interface SpriteFrame {
  pose: Pose;
  face: Face;
  mouth: Mouth;
  blink: boolean;
}

export function StevenSprite({
  frame,
  variant = "full",
}: {
  frame: SpriteFrame;
  /** "crop": head and shoulders only, for the phone player bar */
  variant?: "full" | "crop";
}) {
  const { pose, face, mouth, blink } = frame;
  const pointing = pose === "point";
  const show = (on: boolean) => (on ? "steven-layer on" : "steven-layer");

  // hidden until every layer has decoded: the small face patches arrive
  // before the 600 KB poses, and a floating head is worse than a beat of nothing
  const root = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const imgs = [...(root.current?.querySelectorAll("img") ?? [])];
    const check = () => {
      if (imgs.every((i) => i.complete && i.naturalWidth > 0)) setReady(true);
    };
    imgs.forEach((i) => i.addEventListener("load", check));
    check();
    return () => imgs.forEach((i) => i.removeEventListener("load", check));
  }, []);

  const body = (
    <div
      ref={root}
      className={`steven-sprite${pointing ? " pointing" : ""}${ready ? " ready" : ""}`}
      aria-hidden
    >
      {POSES.map((p) => (
        <img
          key={p}
          className={`${show(p === pose)} steven-pose steven-pose-${p}`}
          src={`/steven/pose-${p}.png`}
          alt=""
          draggable={false}
          decoding="async"
        />
      ))}
      <div
        className="steven-head"
        style={{
          transform: pointing ? `translateX(${POINT_SHIFT_PCT})` : undefined,
        }}
      >
        {FACES.map((f) => (
          <img
            key={f}
            className={show(f === face)}
            src={`/steven/layers/face-${f}.png`}
            alt=""
            draggable={false}
          />
        ))}
        {/* closed = the face's own mouth (a smile stays a smile) */}
        {MOUTH_LAYERS.map((m) => (
          <img
            key={m}
            className={show(m === mouth)}
            src={`/steven/layers/mouth-${m}.png`}
            alt=""
            draggable={false}
          />
        ))}
        <img
          className={show(blink)}
          src="/steven/layers/eyes-closed.png"
          alt=""
          draggable={false}
        />
      </div>
    </div>
  );
  if (variant === "full") return body;
  return (
    <div className={`steven-crop${pointing ? " pointing" : ""}`} aria-hidden>
      {body}
    </div>
  );
}
