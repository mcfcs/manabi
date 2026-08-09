export interface RecentModule {
  moduleId: number;
  courseId: number;
  title: string;
}

const KEY = "manabi-recent-modules";
const MAX = 5;

export function getRecentModules(): RecentModule[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]");
  } catch {
    return [];
  }
}

export function trackRecentModule(entry: RecentModule): void {
  const rest = getRecentModules().filter((r) => r.moduleId !== entry.moduleId);
  localStorage.setItem(KEY, JSON.stringify([entry, ...rest].slice(0, MAX)));
}
