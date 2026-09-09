import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, type SettingsOut } from "../../lib/api";

/** True while the global "hide grades" switch is on. */
export function useGradesHidden(): boolean {
  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: () => api.get<SettingsOut>("/api/settings"),
    staleTime: 60_000,
  });
  return settings.data?.grades_hidden ?? false;
}

/**
 * Wraps one grade figure. When grades are hidden the value is blurred rather
 * than removed, so the layout never shifts; a click reveals just that figure
 * for the rest of the visit (never persisted).
 */
export function GradeValue({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const hidden = useGradesHidden();
  const [revealed, setRevealed] = useState(false);
  const blurred = hidden && !revealed;
  return (
    <span
      className={`grade-value${blurred ? " blurred" : ""}${className ? ` ${className}` : ""}`}
      onClick={
        blurred
          ? (e) => {
              e.preventDefault();
              e.stopPropagation();
              setRevealed(true);
            }
          : undefined
      }
      role={blurred ? "button" : undefined}
      tabIndex={blurred ? 0 : undefined}
      onKeyDown={
        blurred
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setRevealed(true);
              }
            }
          : undefined
      }
      title={blurred ? "Click to reveal" : undefined}
      aria-label={blurred ? "Hidden grade — click to reveal" : undefined}
    >
      {children}
    </span>
  );
}
