export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
  ) {
    super(message);
  }
}

interface RequestOpts {
  keepalive?: boolean;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  opts?: RequestOpts,
): Promise<T> {
  const isForm = body instanceof FormData;
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    keepalive: opts?.keepalive,
    headers: {
      // CSRF contract with the server: mutations require this header.
      "X-Requested-With": "fetch",
      ...(body !== undefined && !isForm
        ? { "Content-Type": "application/json" }
        : {}),
    },
    body: isForm ? body : body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let message = res.statusText;
    let detail: unknown;
    try {
      const data = await res.json();
      detail = data.detail;
      if (typeof data.detail === "string") message = data.detail;
      else if (data.detail?.message) message = data.detail.message;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, message, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  postForm: <T>(path: string, form: FormData) => request<T>("POST", path, form),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  put: <T>(path: string, body?: unknown, opts?: RequestOpts) =>
    request<T>("PUT", path, body, opts),
  delete: <T>(path: string) => request<T>("DELETE", path),
};

export interface UserOut {
  id: number;
  email: string;
}

export interface HealthOut {
  status: string;
  database: string;
  ai_node: { online: boolean; last_seen_at: string | null };
}

export interface JobOut {
  id: number;
  job_type: string;
  queue: "cpu" | "gpu";
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress_pct: number | null;
  progress_note: string | null;
  preview: string | null;
  result: Record<string, unknown> | null;
  error: string | null;
}

export interface CourseOut {
  id: number;
  code: string;
  name: string;
  description: string | null;
  instructor: string | null;
  term: string | null;
  accent_color: string | null;
  position: number;
  module_count: number;
  document_count: number;
  card_count: number;
  canvas_url: string | null;
  meeting_url: string | null;
}

// ── Increment 9: schedule / calendar / tasks / settings ─────────────────

export interface ScheduleEntryOut {
  id: number;
  schedule_id: number;
  course_id: number | null;
  code: string;
  name: string | null;
  instructor: string | null;
  accent_color: string | null;
  day_of_week: number | null;
  start_minute: number | null;
  end_minute: number | null;
  location: string | null;
  meeting_url: string | null;
  canvas_url: string | null;
}

export interface ScheduleGroupOut {
  id: number;
  title: string;
  position: number;
  entries: ScheduleEntryOut[];
}

export interface ScheduleOut {
  schedules: ScheduleGroupOut[];
}

export interface MeetingOut {
  date: string;
  course_id: number | null;
  code: string;
  accent_color: string | null;
  start_minute: number;
  end_minute: number;
  location: string | null;
  meeting_url: string | null;
}

export interface CalendarEventOut {
  id: number;
  title: string;
  notes: string | null;
  course_id: number | null;
  date: string;
  start_minute: number | null;
  end_minute: number | null;
  repeat_weekly: boolean;
  repeat_until: string | null;
}

export interface GcalAttendee {
  name: string | null;
  status: "accepted" | "declined" | "tentative" | "needs-action";
}

export interface GcalEventOut {
  date: string;
  title: string;
  calendar: string | null;
  start_minute: number | null;
  end_minute: number | null;
  location: string | null;
  organizer: string | null;
  attendees: GcalAttendee[] | null;
  my_status: string | null;
}

export interface AnnouncementOut {
  id: number;
  title: string;
  preview: string;
  message: string;
  posted_at: string | null;
  author: string | null;
  course_id: number | null;
  course_code: string | null;
  accent_color: string | null;
  html_url: string | null;
}

export interface DayMarkOut {
  date: string;
  course_id: number | null;
  mode: "sync" | "async";
  note: string | null;
}

export interface CalTaskOut {
  id: number;
  date: string;
  title: string;
  course_id: number | null;
  course_code: string | null;
  accent_color: string | null;
  due_minute: number | null;
  done: boolean;
}

export interface CalendarMonthOut {
  ym: string | null;
  semester_start: string;
  semester_end: string;
  meetings: MeetingOut[];
  events: CalendarEventOut[];
  gcal: GcalEventOut[];
  marks: DayMarkOut[];
  tasks: CalTaskOut[];
  gcal_configured: boolean;
}

export interface TaskOut {
  id: number;
  title: string;
  notes: string | null;
  course_id: number | null;
  course_code: string | null;
  course_accent_color: string | null;
  due_date: string | null;
  due_minute: number | null;
  done: boolean;
  source: "manual" | "canvas";
  created_at: string;
}

export interface SettingsOut {
  semester_start: string;
  semester_end: string;
  gcal_configured: boolean;
  gcal_env_feeds: number;
  gcal_url_tail: string | null;
  gcal_last_synced_at: string | null;
  gcal_last_error: string | null;
  class_reminders: boolean;
  push_configured: boolean;
}

export interface ModuleOut {
  id: number;
  course_id: number;
  title: string;
  position: number;
  content_version: number;
  document_count: number;
  has_note: boolean;
  summary_state: "none" | "current" | "outdated";
  card_count: number;
  quiz_count: number;
}

export interface ModuleDetail extends ModuleOut {
  course_code: string;
  course_name: string;
  course_accent_color: string | null;
  page_count: number;
  best_quiz_score: number | null;
  note_updated_at: string | null;
}

export type ExtractStatus = "pending" | "processing" | "ready" | "failed";

export interface DocumentOut {
  id: number;
  module_id: number;
  kind: "pdf" | "pptx";
  filename: string;
  byte_size: number;
  extract_status: ExtractStatus;
  error: string | null;
  page_count: number | null;
  ai_included: boolean;
  job_id: number | null;
  progress_pct: number | null;
  progress_note: string | null;
}

export interface PageOut {
  page_no: number;
  title: string | null;
  speaker_notes: string | null;
  has_render: boolean;
  width: number | null;
  height: number | null;
  text_html: string | null;
}

export interface DocumentDetail extends DocumentOut {
  pages: PageOut[];
}

export interface NoteOut {
  pm_json: Record<string, unknown>;
  updated_at: string | null;
}

export interface DeleteConsequences {
  requires_confirmation: boolean;
  modules?: number;
  documents: number;
  notes: number;
}

// ── Teacher lectures ──────────────────────────────────────────

export interface LectureSegmentOut {
  index: number;
  title: string;
  display_text: string;
  spoken_text: string;
  checkpoint: { question: string; answer: string } | null;
  audio_ready: boolean;
  audio_id: number | null;
  duration_ms: number | null;
  citations: CitationOut[];
}

export interface LectureOut {
  artifact_id: number;
  title: string;
  mode: string;
  model_name: string;
  generated_at: string;
  staleness: string;
  voice_available: boolean;
  audio_job_active: boolean;
  segments: LectureSegmentOut[];
}

// ── AI artifacts ──────────────────────────────────────────────

export type Staleness = "fresh" | "stale" | "incomplete";

export interface CitationOut {
  id: number;
  item_ref: string;
  chunk_id: number | null;
  document_id: number | null;
  document_title: string;
  page_start: number | null;
  page_end: number | null;
  support_score: number | null;
  status: "verified" | "weak" | "source_removed";
}

export interface JobRef {
  job_id: number;
}

export interface SummaryBlock {
  text: string;
  chunk_ids: number[];
}

export interface SummarySection {
  title: string;
  blocks: SummaryBlock[];
}

export interface KeyTerm {
  term: string;
  definition: string;
  user_added?: boolean;
  found_by_ai?: boolean;
}

export interface Acronym {
  acronym: string;
  meaning: string;
  user_added?: boolean;
}

export interface SummaryOut {
  artifact_id: number;
  title: string;
  model_name: string;
  generated_at: string;
  staleness: Staleness;
  sections: SummarySection[];
  key_terms: KeyTerm[];
  acronyms: Acronym[];
  coverage: { cited: number; total: number } | null;
  citations: Record<string, CitationOut[]>;
}

export interface ActiveJobOut {
  job_id: number;
  job_type: string;
  status: string;
  progress_pct: number | null;
  progress_note: string | null;
}

export interface ArtifactVersion {
  artifact_id: number;
  artifact_type: string;
  title: string;
  model_name: string;
  generated_at: string;
  item_count: number;
}

export interface AnnotationOut {
  id: number;
  page_no: number;
  quote: string;
  note: string | null;
  color: string;
}

export interface ChatThreadOut {
  id: number;
  title: string;
  teacher_mode: boolean;
  created_at: string;
}

export interface ChatCitation {
  chunk_id: number;
  document_id: number;
  document_title: string;
  page_start: number;
  page_end: number;
}

export interface ChatMessageOut {
  id: number;
  role: "user" | "assistant";
  content: string;
  grounded: boolean;
  general_knowledge: boolean;
  has_audio: boolean;
  audio_id: number | null;
  citations: ChatCitation[] | null;
  created_at: string;
}

export interface RegionOut {
  page_no: number;
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface CardOut {
  id: number;
  front: string;
  back: string;
  status: "active" | "suspended";
  edited: boolean;
  citations: CitationOut[];
}

export interface DeckOut {
  artifact_id: number;
  model_name: string;
  generated_at: string;
  staleness: Staleness;
  cards: CardOut[];
}

export interface QuestionOut {
  id: number;
  ord: number;
  qtype: "mcq" | "tf" | "short";
  prompt: string;
  options: string[] | null;
  answer:
    | { kind: "mcq"; correct_option: number }
    | { kind: "tf"; value: boolean }
    | { kind: "short"; text: string };
  explanation: string | null;
  citations: CitationOut[];
}

export interface QuizOut {
  artifact_id: number;
  title: string;
  model_name: string;
  generated_at: string;
  scope_module_ids: number[];
  questions: QuestionOut[];
}

export interface QuizListItem {
  artifact_id: number;
  title: string;
  generated_at: string;
  question_count: number;
  attempt_count: number;
  best_score: number | null;
}
