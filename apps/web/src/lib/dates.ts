/** Local-date helpers for form defaults. Dates are the device's local
 * calendar day as YYYY-MM-DD (the app is used in Manila; the server stores
 * naive Manila dates), never `toISOString()`, which is UTC and turns
 * "tomorrow 7 AM in Manila" into today. */

export const END_OF_DAY_MINUTE = 23 * 60 + 59;

export function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function todayISO(now: Date = new Date()): string {
  return isoDate(now);
}

export function addDaysISO(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  return isoDate(new Date(y, m - 1, d + days));
}

/** A new task's deadline: tomorrow, 11:59 PM — always after now. */
export function defaultDue(now: Date = new Date()): { date: string; minute: number } {
  return { date: addDaysISO(todayISO(now), 1), minute: END_OF_DAY_MINUTE };
}

/** A new event's times on `dateISO`: the next full hour when that's today
 * (so it starts after now), 9:00 on other days; one hour long. Clamped so
 * the end stays before midnight. */
export function defaultEventTimes(
  dateISO: string,
  now: Date = new Date(),
): { start: number; end: number } {
  let start = 9 * 60;
  if (dateISO === todayISO(now)) start = (now.getHours() + 1) * 60;
  start = Math.min(start, 22 * 60);
  return { start, end: Math.min(start + 60, END_OF_DAY_MINUTE) };
}

export function minuteToHHMM(minute: number | null | undefined): string {
  if (minute == null) return "";
  return `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
}

export function hhmmToMinute(value: string): number | null {
  if (!value) return null;
  const [h, m] = value.split(":").map(Number);
  return h * 60 + m;
}

/** The roundup for `dateISO` can be written now: past days any time, today
 * from 8 PM, never a future day (mirrors the server's rule). */
export const ROUNDUP_OPENS_HOUR = 20;

export function roundupOpen(dateISO: string, now: Date = new Date()): boolean {
  const today = todayISO(now);
  if (dateISO < today) return true;
  return dateISO === today && now.getHours() >= ROUNDUP_OPENS_HOUR;
}
