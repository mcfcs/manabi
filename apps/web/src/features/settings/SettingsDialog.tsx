import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { Loader2 } from "lucide-react";

import { Modal } from "../../components/Modal";
import { api, ApiError, type SettingsOut } from "../../lib/api";
import {
  disablePush,
  enablePush,
  getPushState,
  pushBlocker,
  type PushState,
} from "../../lib/push";

const LAB_DEFAULT =
  "Good day. Settle in. Today we examine the zero-overhead principle, and why it matters rather more than you might think.";

/** A/B the zero-shot vs fine-tuned Steven voice on any line. Renders are
 * cached server-side per (variant, text). */
function VoiceLab() {
  const [text, setText] = useState(LAB_DEFAULT);
  const [busy, setBusy] = useState<string | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const [labError, setLabError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);

  async function render(variant: "base" | "tuned") {
    if (playing === variant) {
      audioRef.current?.pause();
      setPlaying(null);
      return;
    }
    setBusy(variant);
    setLabError(null);
    try {
      for (let i = 0; i < 60; i++) {
        const r = await api.post<{ ready: boolean; id?: number }>(
          "/api/voice/preview",
          { text: text.trim(), variant },
        );
        if (r.ready && r.id != null) {
          const audio = audioRef.current;
          if (audio) {
            audio.src = `/api/voice/previews/${r.id}`;
            setPlaying(variant);
            await audio.play().catch(() => setPlaying(null));
          }
          return;
        }
        await new Promise((res) => setTimeout(res, 2500));
      }
      setLabError("Timed out waiting for the render");
    } catch (e) {
      setLabError(e instanceof ApiError ? e.message : "Render failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <h3 className="settings-heading">Voice lab — compare Steven's voices</h3>
      <p className="settings-hint">
        Renders the same line with the original zero-shot clone and the
        fine-tuned model. First render of a new line takes ~10–40s (the
        zero-shot one swaps model weights, so it's slower).
      </p>
      <textarea
        className="input event-notes"
        rows={2}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="settings-push-row">
        <button
          className="btn"
          disabled={busy !== null || text.trim().length < 3}
          onClick={() => render("base")}
        >
          {busy === "base" ? (
            <Loader2 size={14} className="spin" />
          ) : playing === "base" ? (
            "◼"
          ) : (
            "▶"
          )}{" "}
          Zero-shot
        </button>
        <button
          className="btn"
          disabled={busy !== null || text.trim().length < 3}
          onClick={() => render("tuned")}
        >
          {busy === "tuned" ? (
            <Loader2 size={14} className="spin" />
          ) : playing === "tuned" ? (
            "◼"
          ) : (
            "▶"
          )}{" "}
          Fine-tuned
        </button>
      </div>
      {labError && <p className="error-text">{labError}</p>}
      <audio ref={audioRef} onEnded={() => setPlaying(null)} onPause={() => setPlaying(null)} />
    </>
  );
}

export function SettingsDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: () => api.get<SettingsOut>("/api/settings"),
  });

  const [semStart, setSemStart] = useState("");
  const [semEnd, setSemEnd] = useState("");
  const [gcalUrl, setGcalUrl] = useState("");
  const [pushState, setPushState] = useState<PushState | null>(null);
  const [pushNote, setPushNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPushState().then(setPushState);
  }, []);
  useEffect(() => {
    if (settings.data) {
      setSemStart(settings.data.semester_start);
      setSemEnd(settings.data.semester_end);
    }
  }, [settings.data]);

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.patch<SettingsOut>("/api/settings", body),
    onSuccess: (data) => {
      queryClient.setQueryData(["settings"], data);
      queryClient.invalidateQueries({ queryKey: ["calendar"] });
      setError(null);
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Save failed"),
  });

  const refreshGcal = useMutation({
    mutationFn: () =>
      api.post<{ count: number; error: string | null }>("/api/calendar/gcal/refresh"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      queryClient.invalidateQueries({ queryKey: ["calendar"] });
    },
  });

  const testPush = useMutation({
    mutationFn: () => api.post<{ delivered: number }>("/api/push/test"),
    onSuccess: (r) =>
      setPushNote(
        r.delivered > 0
          ? `Test sent to ${r.delivered} device${r.delivered > 1 ? "s" : ""}.`
          : "No subscribed devices.",
      ),
  });

  const s = settings.data;

  return (
    <Modal title="Settings" onClose={onClose}>
      <div className="modal-form settings-form">
        <h3 className="settings-heading">Semester</h3>
        <div className="event-form-row">
          <label className="field-label">
            Start
            <input
              type="date"
              className="input"
              value={semStart}
              onChange={(e) => setSemStart(e.target.value)}
              onBlur={() =>
                semStart &&
                semStart !== s?.semester_start &&
                save.mutate({ semester_start: semStart })
              }
            />
          </label>
          <label className="field-label">
            End
            <input
              type="date"
              className="input"
              value={semEnd}
              onChange={(e) => setSemEnd(e.target.value)}
              onBlur={() =>
                semEnd &&
                semEnd !== s?.semester_end &&
                save.mutate({ semester_end: semEnd })
              }
            />
          </label>
        </div>

        <h3 className="settings-heading">Google Calendar</h3>
        {s?.gcal_configured ? (
          <p className="settings-hint">
            {s.gcal_env_feeds > 0
              ? `${s.gcal_env_feeds} feed${s.gcal_env_feeds > 1 ? "s" : ""} configured in .env`
              : `Feed connected (${s.gcal_url_tail})`}
            {" · last sync "}
            {s.gcal_last_synced_at
              ? new Date(s.gcal_last_synced_at).toLocaleTimeString()
              : "never"}
            {s.gcal_last_error && (
              <span className="error-text"> — {s.gcal_last_error}</span>
            )}
          </p>
        ) : (
          <p className="settings-hint">
            Paste your calendar's <b>secret iCal address</b> (Google Calendar →
            Settings → your calendar → "Integrate calendar" → Secret address in
            iCal format). External meetings then show up in the Manabi calendar.
          </p>
        )}
        <div className="settings-gcal-row">
          <input
            type="password"
            className="input"
            placeholder="https://calendar.google.com/calendar/ical/…/basic.ics"
            value={gcalUrl}
            onChange={(e) => setGcalUrl(e.target.value)}
          />
          <button
            className="btn"
            disabled={!gcalUrl.trim() || save.isPending}
            onClick={() =>
              save.mutate(
                { gcal_ics_url: gcalUrl.trim() },
                { onSuccess: () => refreshGcal.mutate() },
              )
            }
          >
            Connect
          </button>
          {s?.gcal_configured && (
            <button
              className="btn"
              onClick={() => save.mutate({ gcal_ics_url: "" })}
            >
              Disconnect
            </button>
          )}
        </div>

        <h3 className="settings-heading">Canvas tasks</h3>
        <p className="settings-hint">
          Assignments auto-sync every 10 minutes.
          {" Last sync "}
          {s?.canvas_last_synced_at
            ? new Date(s.canvas_last_synced_at).toLocaleTimeString()
            : "never"}
          {s?.canvas_last_error && (
            <span className="error-text"> — {s.canvas_last_error}</span>
          )}
        </p>

        <h3 className="settings-heading">Notifications</h3>
        <p className="settings-hint">
          This device:{" "}
          <b>
            {pushState === "on" && "notifications on"}
            {pushState === "off" && "notifications off"}
            {pushState === "denied" && "blocked by the browser"}
            {pushState === "unsupported" && "not available yet"}
            {pushState === null && "checking…"}
          </b>
        </p>
        {pushState === "unsupported" && (
          <p className="settings-hint">
            {pushBlocker() === "insecure" && (
              <>
                Push needs a secure (HTTPS) address — you're on the plain-http
                one. Open{" "}
                <a href={`https://${window.location.hostname}${window.location.pathname}`}>
                  https://{window.location.hostname}
                </a>{" "}
                instead (no port number), then enable here.
              </>
            )}
            {pushBlocker() === "ios-install" && (
              <>
                On iPhone/iPad, notifications only work for installed web apps:
                open the Share menu → <b>Add to Home Screen</b>, then launch
                Manabi from that icon and enable notifications here.
              </>
            )}
            {pushBlocker() === "no-api" && (
              <>This browser doesn't support web push notifications.</>
            )}
          </p>
        )}
        {pushState === "denied" && (
          <p className="settings-hint">
            Re-allow notifications for this site in your browser settings
            (padlock icon → Permissions → Notifications), then press "Check
            again".
          </p>
        )}
        <div className="settings-push-row">
          {(pushState === "off" || pushState === "on") && (
            <button
              className="btn"
              onClick={() =>
                (pushState === "on" ? disablePush() : enablePush())
                  .then((s) => {
                    setPushState(s);
                    setPushNote(s === "on" ? "Notifications enabled on this device." : null);
                  })
                  .catch(() => {
                    setPushNote("Couldn't subscribe — check the connection and try again.");
                    getPushState().then(setPushState);
                  })
              }
            >
              {pushState === "on" ? "Disable on this device" : "Enable on this device"}
            </button>
          )}
          {pushState === "on" && (
            <button className="btn" onClick={() => testPush.mutate()}>
              Send test
            </button>
          )}
          {(pushState === "denied" || pushState === "unsupported") && (
            <button
              className="btn"
              onClick={() => getPushState().then(setPushState)}
            >
              Check again
            </button>
          )}
        </div>
        {s && !s.push_configured && pushState !== "unsupported" && (
          <p className="settings-hint">
            Server keys missing — set VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY in
            .env.
          </p>
        )}
        {pushNote && <p className="settings-hint">{pushNote}</p>}

        <label className="event-weekly settings-reminders">
          <input
            type="checkbox"
            checked={s?.class_reminders ?? false}
            onChange={(e) => save.mutate({ class_reminders: e.target.checked })}
          />
          Push a reminder ~15 minutes before each class
        </label>

        <VoiceLab />

        {error && <p className="error-text">{error}</p>}

        <div className="modal-actions">
          <button className="btn" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </Modal>
  );
}
