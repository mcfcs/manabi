/** A segment's loudness over time, for lip-sync — decoded from the same mp3
 * the <audio> element plays, without touching that element.
 *
 * Routing the element through Web Audio (createMediaElementSource) is
 * permanent and, on iOS Safari, stops the lecture when the screen locks; it
 * also needs a user gesture and can only be wired once (StrictMode mounts
 * twice). Decoding a copy has none of those problems, and reading the
 * envelope at `audio.currentTime` follows playbackRate for free. */

export const ENVELOPE_RATE = 60; // values per second of audio

const cache = new Map<string, Promise<Float32Array | null>>();
const MAX_CACHED = 6;

async function decode(url: string): Promise<Float32Array | null> {
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    const bytes = await res.arrayBuffer();
    const Offline =
      window.OfflineAudioContext ??
      (
        window as unknown as {
          webkitOfflineAudioContext?: typeof OfflineAudioContext;
        }
      ).webkitOfflineAudioContext;
    if (!Offline) return null;
    const audio = await new Offline(1, 1, 22050).decodeAudioData(bytes);
    const samples = audio.getChannelData(0);
    const bin = Math.max(1, Math.round(audio.sampleRate / ENVELOPE_RATE));
    const env = new Float32Array(Math.ceil(samples.length / bin));
    for (let i = 0; i < env.length; i++) {
      let sum = 0;
      const end = Math.min(samples.length, (i + 1) * bin);
      for (let j = i * bin; j < end; j++) sum += samples[j] * samples[j];
      env[i] = Math.sqrt(sum / Math.max(1, end - i * bin));
    }
    // Normalise to the clip's own loud level (95th percentile), so the
    // thresholds mean the same for a quiet and a loud recording.
    const sorted = Float32Array.from(env).sort();
    const loud = sorted[Math.floor(sorted.length * 0.95)] || 1;
    for (let i = 0; i < env.length; i++) env[i] = Math.min(1, env[i] / loud);
    return env;
  } catch {
    return null; // no lip-sync for this clip; everything else still works
  }
}

export function loadEnvelope(url: string): Promise<Float32Array | null> {
  let p = cache.get(url);
  if (!p) {
    p = decode(url);
    cache.set(url, p);
    if (cache.size > MAX_CACHED) cache.delete(cache.keys().next().value as string);
  }
  return p;
}

export function levelAt(env: Float32Array | null, seconds: number): number {
  if (!env || !Number.isFinite(seconds)) return 0;
  return env[Math.floor(seconds * ENVELOPE_RATE)] ?? 0;
}
