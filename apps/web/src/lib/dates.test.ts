import { describe, expect, it } from "vitest";

import { addDaysISO, defaultDue, defaultEventTimes, roundupOpen, todayISO } from "./dates";

// Local times: Oct 9 2026, mid-afternoon and late evening.
const afternoon = new Date(2026, 9, 9, 14, 20);
const evening = new Date(2026, 9, 9, 20, 5);

describe("form defaults", () => {
  it("a task is due tomorrow at 11:59 PM", () => {
    expect(defaultDue(afternoon)).toEqual({ date: "2026-10-10", minute: 23 * 60 + 59 });
  });

  it("today's event starts at the next full hour; other days at 9", () => {
    expect(defaultEventTimes("2026-10-09", afternoon)).toEqual({ start: 15 * 60, end: 16 * 60 });
    expect(defaultEventTimes("2026-10-12", afternoon)).toEqual({ start: 9 * 60, end: 10 * 60 });
  });

  it("dates are local calendar days across month ends", () => {
    expect(todayISO(afternoon)).toBe("2026-10-09");
    expect(addDaysISO("2026-10-31", 1)).toBe("2026-11-01");
  });
});

describe("roundup window", () => {
  it("opens at 8 PM today, any time for past days, never for future days", () => {
    expect(roundupOpen("2026-10-09", afternoon)).toBe(false);
    expect(roundupOpen("2026-10-09", evening)).toBe(true);
    expect(roundupOpen("2026-10-08", afternoon)).toBe(true);
    expect(roundupOpen("2026-10-10", evening)).toBe(false);
  });
});
