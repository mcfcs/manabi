import { X } from "lucide-react";

import type { CalendarEventOut } from "../../lib/api";
import type { DayData } from "./CalendarPage";
import { DayDetails } from "./DayDetails";

export function DayPanel({
  date,
  data,
  onClose,
  onAddEvent,
  onEditEvent,
}: {
  date: string;
  data: DayData;
  onClose: () => void;
  onAddEvent: () => void;
  onEditEvent: (e: CalendarEventOut) => void;
}) {
  const label = new Date(date + "T00:00:00").toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });

  return (
    <aside className="day-panel">
      <header className="day-panel-head">
        <h2>{label}</h2>
        <button className="icon-btn" onClick={onClose} aria-label="Close">
          <X size={16} strokeWidth={1.5} />
        </button>
      </header>
      <DayDetails
        date={date}
        data={data}
        onAddEvent={onAddEvent}
        onEditEvent={onEditEvent}
      />
    </aside>
  );
}
