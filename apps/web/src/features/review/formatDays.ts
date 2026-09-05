/** "today", "4d", "3w", "2mo", "1y" — compact next-interval label for the
 * rating buttons. Mirrors the server's preview_intervals() day counts. */
export function formatDays(days: number | undefined): string {
  if (days === undefined) return "";
  if (days <= 0) return "today";
  if (days < 14) return `${days}d`;
  if (days < 60) return `${Math.round(days / 7)}w`;
  if (days < 365) return `${Math.round(days / 30)}mo`;
  return `${Math.round(days / 365)}y`;
}
