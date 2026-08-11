import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowRight, X } from "lucide-react";
import { useState } from "react";

import { api, type BriefingOut } from "../../lib/api";

const DISMISS_KEY = "steven-letter-dismissed";

/** A "letter from Steven" at the top of the home page: his once-a-day briefing,
 * surfaced outside the chat. Reuses the idempotent briefing endpoint (so opening
 * the home page also ensures today's briefing exists). Dismissible for the day. */
export function StevenLetter() {
  const todayKey = new Date().toDateString();
  const [dismissed, setDismissed] = useState(
    () => localStorage.getItem(DISMISS_KEY) === todayKey,
  );

  const briefing = useQuery({
    queryKey: ["briefing-today"],
    queryFn: () => api.post<BriefingOut>("/api/assistant/briefing"),
    refetchInterval: (q) =>
      q.state.data && q.state.data.generating && !q.state.data.body ? 2500 : false,
    staleTime: 5 * 60_000,
  });

  if (dismissed) return null;

  const b = briefing.data;
  const composing = !b || (b.generating && !b.body);
  const dateLabel = new Date().toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });

  function dismiss() {
    localStorage.setItem(DISMISS_KEY, todayKey);
    setDismissed(true);
  }

  return (
    <section className="steven-letter" aria-label="A letter from Steven">
      <div className="steven-letter-head">
        <img className="steven-letter-avatar" src="/steven.jpg" alt="Steven" />
        <div className="steven-letter-from">
          <span className="steven-letter-label">A letter from Steven</span>
          <span className="steven-letter-date">{dateLabel}</span>
        </div>
        <button
          className="steven-letter-x"
          onClick={dismiss}
          aria-label="Dismiss for today"
          title="Dismiss for today"
        >
          <X size={15} strokeWidth={1.75} />
        </button>
      </div>
      <div className="steven-letter-body">
        {composing ? (
          <p className="steven-letter-composing">Steven is composing your letter…</p>
        ) : (
          <p>{b?.body}</p>
        )}
      </div>
      {!composing && (
        <Link to="/assistant" className="steven-letter-open">
          Open chat <ArrowRight size={14} strokeWidth={1.75} />
        </Link>
      )}
    </section>
  );
}
