import { describe, expect, it } from "vitest";

import type { CalendarMonthOut, MeetingOut } from "../../lib/api";
import { loggableDates } from "./attendance";

const meeting = (date: string, courseId: number): MeetingOut => ({
  date,
  course_id: courseId,
  block_id: courseId * 10,
  schedule_id: 1,
  schedule_title: "Class schedule",
  code: `C${courseId}`,
  accent_color: null,
  start_minute: 600,
  end_minute: 690,
  location: null,
  meeting_url: null,
});

// SocSc (4) meets Tue/Thu; CSCI (2) meets Wed. Today is Saturday Oct 10.
const data = (over: Partial<CalendarMonthOut> = {}): CalendarMonthOut => ({
  ym: null,
  semester_start: "2026-08-10",
  semester_end: "2026-12-12",
  meetings: [
    meeting("2026-09-29", 4),
    meeting("2026-10-01", 4),
    meeting("2026-10-06", 4),
    meeting("2026-10-07", 2),
    meeting("2026-10-08", 4),
    meeting("2026-10-13", 4),
  ],
  events: [],
  gcal: [],
  marks: [],
  tasks: [],
  absences: [],
  roundups: [],
  gcal_configured: false,
  ...over,
});

describe("loggableDates", () => {
  it("defaults to the course's latest class day, not today", () => {
    expect(loggableDates(data(), 4, "2026-10-10")).toEqual([
      "2026-10-08",
      "2026-10-06",
      "2026-10-01",
      "2026-09-29",
    ]);
  });

  it("skips async days, per class or for all classes", () => {
    const marks = [
      {
        date: "2026-10-08",
        course_id: 4,
        block_id: null,
        mode: "async" as const,
        note: null,
      },
      {
        date: "2026-10-06",
        course_id: null,
        block_id: null,
        mode: "async" as const,
        note: null,
      },
    ];
    expect(loggableDates(data({ marks }), 4, "2026-10-10")[0]).toBe(
      "2026-10-01",
    );
  });

  it("an online (sync) class still counts", () => {
    const marks = [
      {
        date: "2026-10-08",
        course_id: 4,
        block_id: null,
        mode: "sync" as const,
        note: null,
      },
    ];
    expect(loggableDates(data({ marks }), 4, "2026-10-10")[0]).toBe(
      "2026-10-08",
    );
  });

  it("skips days already logged absent or late", () => {
    const absences = [
      {
        id: 1,
        date: "2026-10-08",
        course_id: 4,
        kind: "late" as const,
        reason: null,
      },
    ];
    expect(loggableDates(data({ absences }), 4, "2026-10-10")[0]).toBe(
      "2026-10-06",
    );
  });

  it("includes today when the class meets today", () => {
    expect(loggableDates(data(), 4, "2026-10-08")[0]).toBe("2026-10-08");
  });
});
